# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, g, session, jsonify, Response, send_file
import sqlite3
from pathlib import Path
import os
import threading
import requests
import csv
import io
import base64
from datetime import datetime, date, timedelta
from io import BytesIO
import urllib.parse
import qrcode

ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP", "919659796217")

# Email (Brevo)
from sib_api_v3_sdk import Configuration, TransactionalEmailsApi, ApiClient, SendSmtpEmail

# PDF generation
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# scheduler for daily report
from apscheduler.schedulers.background import BackgroundScheduler

# ---------------- App + DB ----------------
BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "instance" / "bookings.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, template_folder=str(BASE / "templates"), static_folder=str(BASE / "static"))
app.secret_key = os.getenv("SECRET_KEY", "change_this_secret_key")
app.config["DATABASE"] = str(DB_PATH)

# Optional: provide SITE_URL env var (e.g. https://your-domain.com) to build absolute links in emails
SITE_URL = os.getenv("SITE_URL")

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")

# ---------------- Database Helpers ----------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db:
        db.close()

def create_tables():
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            customer_email TEXT,
            phone TEXT NOT NULL,
            event_date TEXT NOT NULL,
            service TEXT,
            extras TEXT,
            notes TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.commit()

with app.app_context():
    create_tables()

# ---------------- Utilities: PDF receipt ----------------
def generate_pdf_receipt(booking_row):
    """
    Return bytes of a simple PDF receipt using reportlab
    """
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    x = 40
    y = height - 60

    p.setFont("Helvetica-Bold", 18)
    p.drawString(x, y, "JAGADHA A to Z Event Management")
    y -= 30
    p.setFont("Helvetica", 12)
    p.drawString(x, y, f"Booking ID: {booking_row['id']}")
    y -= 18
    p.drawString(x, y, f"Name: {booking_row['name']}")
    y -= 16
    p.drawString(x, y, f"Phone: {booking_row['phone']}")
    y -= 16
    p.drawString(x, y, f"Email: {booking_row['customer_email'] or '-'}")
    y -= 16
    p.drawString(x, y, f"Event Date: {booking_row['event_date']}")
    y -= 16
    p.drawString(x, y, f"Service: {booking_row['service']}")
    y -= 16
    p.drawString(x, y, "Extras:")
    y -= 14
    p.setFont("Helvetica", 10)
    p.drawString(x+12, y, booking_row['extras'] or "-")
    y -= 20
    p.setFont("Helvetica", 12)
    p.drawString(x, y, "Notes:")
    y -= 14
    p.setFont("Helvetica", 10)
    text = p.beginText(x, y)
    notes = booking_row['notes'] or ""
    for line in notes.splitlines():
        text.textLine(line)
    p.drawText(text)
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer.read()

# ---------------- SMS (Fast2SMS) ----------------
def send_sms_fast2sms(phone, message):
    api_key = os.getenv("FAST2SMS_API_KEY")
    if not api_key:
        app.logger.info("SMS Disabled — FAST2SMS_API_KEY missing.")
        return
    url = "https://www.fast2sms.com/dev/bulkV2"
    payload = {
        "sender_id": "TXTIND",
        "message": message,
        "language": "english",
        "route": "v3",
        "numbers": phone
    }
    headers = {"authorization": api_key}
    try:
        res = requests.post(url, data=payload, headers=headers, timeout=15)
        app.logger.info("SMS SENT ✓ %s", res.text)
    except Exception as e:
        app.logger.exception("SMS ERROR: %s", e)

# ---------------- EMAIL (BREVO API) with PDF attachment & Tamil ----------------
def send_email_via_brevo(
        name, location, phone, event_date, service,
        extras, notes, customer_email=None,
        status="Pending", booking_id=None
    ):
    """
    Send booking email using BREVO to both ADMIN and Customer (if available).
    Includes Tamil translation + PDF receipt (when booking_id is provided).
    Safe URL building: uses SITE_URL env if provided; otherwise tries url_for inside app context; falls back to localhost.
    """
    # website link resolution (safe outside request)
    website_link = SITE_URL
    if not website_link:
        try:
            with app.app_context():
                # url_for will require SERVER_NAME if no request; wrap in try/except
                from flask import url_for as _url_for
                website_link = _url_for('index', _external=True)
        except Exception:
            website_link = os.getenv("SITE_URL", "http://localhost:5000")

    api_key = os.getenv("BREVO_API_KEY")
    admin_email = os.getenv("ADMIN_EMAIL")

    if not api_key or not admin_email:
        app.logger.info("Brevo Missing API or Admin email.")
        return

    configuration = Configuration()
    configuration.api_key["api-key"] = api_key
    api_instance = TransactionalEmailsApi(ApiClient(configuration))

    # Send to admin + customer
    to_list = [{"email": admin_email}]
    if customer_email and customer_email.strip():
        to_list.append({"email": customer_email.strip()})

    # Status text
    status_text = {
        "Pending": "🎉 Booking Received",
        "Confirmed": "✅ Booking Confirmed",
        "Rejected": "❌ Booking Rejected"
    }.get(status, "🎉 Booking Update")

    # Tamil translation
    tamil_status = {
        "Pending": "உங்கள் முன்பதிவு பெறப்பட்டது",
        "Confirmed": "உங்கள் முன்பதிவு உறுதிசெய்யப்பட்டது",
        "Rejected": "மன்னிக்கவும் — உங்கள் முன்பதிவு நிராகரிக்கப்பட்டது"
    }.get(status, "நிலையை புதுப்பித்தல்")

    # EMAIL HTML TEMPLATE
    html_content = f"""
    <!DOCTYPE html><html><body style="font-family: Arial, sans-serif; background:#f7f7f7; margin:0; padding:0;">
    <div style="max-width:600px; margin:18px auto; background:#fff; border-radius:10px; overflow:hidden; box-shadow:0 4px 20px rgba(0,0,0,0.08);">
      <div style="background:#f9c5d5; padding:18px; text-align:center;">
        <h2 style="margin:0; color:#b01357;">❤️ JAGADHA A to Z Event Management ❤️</h2>
      </div>
      <div style="padding:18px; color:#333;">
        <h3>{status_text}</h3>
        <p>Dear <b>{name}</b>,</p>
        <p>Your booking details:</p>
        <table style="width:100%; font-size:14px;">
          <tr><td><b>📛 Name:</b></td><td>{name}</td></tr>
          <tr><td><b>📞 Phone:</b></td><td>{phone}</td></tr>
          <tr><td><b>📧 Email:</b></td><td>{customer_email}</td></tr>
          <tr><td><b>📅 Event Date:</b></td><td>{event_date}</td></tr>
          <tr><td><b>🎈 Service:</b></td><td>{service}</td></tr>
          <tr><td><b>✨ Extras:</b></td><td>{extras}</td></tr>
          <tr><td><b>📍 Location:</b></td><td>{location}</td></tr>
        </table>

        <p style="margin-top:12px;"><b>Notes:</b> {notes or '-'}</p>

        <hr>
        <p><b>தமிழில்: </b>{tamil_status}</p>
        <p style="font-size:13px; color:#666;">(மேலும் உதவிக்கு எங்களைத் தொடர்பு கொள்ளவும். Mob: 96597 96217)</p>

        <div style="text-align:center; margin:16px 0;">
          <a href="{website_link}" style="background:#b01357; color:white; padding:10px 18px; text-decoration:none; border-radius:6px;">Visit Our Website</a>
        </div>
      </div>
      <div style="background:#fafafa; padding:12px; text-align:center; font-size:12px;">
        © 2025 JAGADHA A to Z Event Management — Automated message
      </div>
    </div>
    </body></html>
    """

    # PDF ATTACHMENT HANDLING
    attachments = None
    if booking_id:
        try:
            db = get_db()
            row = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
            if row:
                pdf_bytes = generate_pdf_receipt(row)
                b64 = base64.b64encode(pdf_bytes).decode("utf-8")
                attachments = [{
                    "content": b64,
                    "name": f"booking_{booking_id}.pdf"
                }]
        except Exception as e:
            app.logger.exception("PDF generation failed: %s", e)

    # SEND EMAIL
    send_smtp_email = SendSmtpEmail(
        to=to_list,
        sender={"email": admin_email},
        subject=f"{status_text} - {name}",
        html_content=html_content,
        attachment=attachments
    )

    try:
        api_instance.send_transac_email(send_smtp_email)
        app.logger.info("BREVO EMAIL SENT ✓ to Admin + Customer")
    except Exception as e:
        app.logger.exception("BREVO ERROR: %s", e)

# ---------------- WHATSAPP (UltraMSG) with Template fallback ----------------
def send_whatsapp_message(name, phone, event_date, service,
                          extras, location, customer_email, notes):
    """
    FREE WhatsApp handling using wa.me (Click-to-Chat)
    - Generates customer + admin WhatsApp links
    - Generates QR code
    - No API / No payment
    """

    message = (
        f"🌸 JAGADHA A to Z Event Management 🌸\n\n"
        f"Booking Update\n"
        f"Name: {name}\n"
        f"Phone: {phone}\n"
        f"Date: {event_date}\n"
        f"Service: {service}\n"
        f"Location: {location}\n\n"
        f"Thank you!"
    )

    encoded = urllib.parse.quote(message)

    customer_link = f"https://wa.me/91{phone}?text={encoded}"
    admin_link = f"https://wa.me/{ADMIN_WHATSAPP}?text={encoded}"

    # Generate QR (customer)
    try:
        qr = qrcode.make(customer_link)
        qr_path = os.path.join(app.static_folder, "whatsapp_qr.png")
        qr.save(qr_path)
    except Exception as e:
        app.logger.exception("QR generation failed: %s", e)
        qr_path = None

    # Log only (cannot auto-send WhatsApp)
    app.logger.info("WHATSAPP LINK (Customer): %s", customer_link)
    app.logger.info("WHATSAPP LINK (Admin): %s", admin_link)

    return {
        "message": message,
        "customer_link": customer_link,
        "admin_link": admin_link,
        "qr_path": qr_path
    }


# ---------------- TELEGRAM ADMIN PUSH (for new bookings & daily report) ----------------
def telegram_push(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        app.logger.info("Telegram disabled — missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message}
        r = requests.post(url, data=payload, timeout=10)
        app.logger.info("TELEGRAM PUSH %s", r.text)
    except Exception as e:
        app.logger.exception("Telegram push error: %s", e)

# ---------------- Admin daily summary (08:00) ----------------
def daily_admin_report():
    try:
        db = get_db()
        today = date.today()
        rows = db.execute("SELECT status, COUNT(*) as cnt FROM bookings WHERE date(created_at)=? GROUP BY status", (today.isoformat(),)).fetchall()
        summary = {r["status"]: r["cnt"] for r in rows}
        total = sum(summary.values())
        msg = f"Daily Bookings Report ({today.isoformat()})\nTotal: {total}\n"
        for k, v in summary.items():
            msg += f"{k}: {v}\n"
        # send to telegram and email admin
        telegram_push(msg)
        # email admin (use send_email_via_brevo)
        send_email_via_brevo("Admin", "-", "-", today.isoformat(), "-", "-", msg, customer_email=None, status="Daily Report")
    except Exception as e:
        app.logger.exception("daily_admin_report error: %s", e)

# start scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(daily_admin_report, 'cron', hour=8, minute=0)  # 08:00 server time
scheduler.start()

# ---------------- Utility ----------------
def render_with_values(message, category="danger", **kwargs):
    flash(message, category)
    return render_template("book.html", **kwargs)

# ---------------- ROUTES ----------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/book", methods=["GET", "POST"])
def book():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        location = request.form.get("location", "").strip()
        phone = request.form.get("phone", "").strip()
        event_date = request.form.get("event_date", "").strip()
        service = request.form.get("service", "").strip()
        notes = request.form.get("notes", "").strip()
        customer_email = request.form.get("customer_email", "").strip() or None

        extras_list = request.form.getlist("extras")
        extras = ", ".join(extras_list)

        # whatsapp_link = f"https://wa.me/91{phone}?text=Hello%20JAGADHA,%20I%20want%20to%20discuss%20my%20booking."
        whatsapp_link = f"https://wa.me/91{phone}?text=" \
                        f"Hello%20JAGADHA,%20I%20want%20to%20discuss%20my%20booking."

        # Validations
        if not name:
            return render_with_values("⚠ Please fill Name!", name=name)
        if not location:
            return render_with_values("⚠ Please fill Location!", name=name, location=location)
        if not phone:
            return render_with_values("⚠ Please fill Phone!", name=name)
        if not event_date:
            return render_with_values("⚠ Please fill Date!", name=name)
        if not service:
            return render_with_values("⚠ Please select Service!", name=name)
        if len(extras_list) == 0:
            return render_with_values("⚠ Select Additional Services!", name=name)

        db = get_db()
        cur = db.execute(
            """
            INSERT INTO bookings (name, location, phone, event_date, service, extras, notes, customer_email)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, location, phone, event_date, service, extras, notes, customer_email),
        )
        db.commit()
        booking_id = cur.lastrowid

        # Background notifications
        def notify():
            """
            Background async notifier:
            - Sends Brevo email (Admin + Customer)
            - Sends WhatsApp confirmation
            - Sends Telegram alert to admin
            """
            with app.app_context():
                try:
                    # 1) Always send ADMIN + CUSTOMER email (Pending)
                    send_email_via_brevo(
                        name, location, phone, event_date,
                        service, extras, notes, customer_email,
                        status="Pending",
                        booking_id=booking_id
                    )
                except Exception:
                    app.logger.exception("Error sending pending email")

                # 2) WhatsApp message (best-effort)
                try:
                    wa_data = send_whatsapp_message(
                        name, phone, event_date, service,
                        extras, location, customer_email, notes
                    )
                except Exception:
                    app.logger.exception("WhatsApp send failed")

                # 3) Admin Telegram alert
                try:
                    telegram_push(
                        f"📩 New Booking #{booking_id}\n"
                        f"👤 {name}\n"
                        f"🎈 {service}\n"
                        f"📅 {event_date}"
                    )
                except Exception:
                    app.logger.exception("Telegram push failed")

        threading.Thread(target=notify, daemon=True).start()

        return redirect(url_for("booking_success", booking_id=booking_id))

    return render_template("book.html")

@app.route("/booking/<int:booking_id>")
def booking_success(booking_id):
    db = get_db()
    row = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not row:
        flash("Booking not found", "danger")
        return redirect(url_for("index"))

    wa = send_whatsapp_message(
        row["name"], row["phone"], row["event_date"],
        row["service"], row["extras"], row["location"],
        row["customer_email"], row["notes"]
    )

    return render_template(
        "booking_success.html",
        booking=row,
        wa=wa
    )


# ---------------- ADMIN & DASHBOARD ----------------
@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect(url_for("login"))
    rows = get_db().execute("SELECT * FROM bookings ORDER BY created_at DESC").fetchall()
    return render_template("admin.html", bookings=rows)

@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("login"))
    return render_template("admin_dashboard.html")

# JSON endpoint used by dashboard
@app.route("/api/bookings")
def api_bookings():
    if not session.get("admin"):
        return jsonify({"bookings":[]})

    rows = get_db().execute("SELECT * FROM bookings ORDER BY created_at DESC").fetchall()

    bookings = []
    for r in rows:
        # safe access to status (backwards compatible)
        status = r["status"] if "status" in r.keys() else "Pending"
        bookings.append({
            "id": r["id"],
            "name": r["name"],
            "phone": r["phone"],
            "location": r["location"],
            "event_date": r["event_date"],
            "service": r["service"],
            "extras": r["extras"],
            "notes": r["notes"],
            "customer_email": r["customer_email"],
            "status": status,
            "created_at": r["created_at"],
        })

    return jsonify({"bookings": bookings})

# CSV export
@app.route("/export_csv")
def export_csv():
    if not session.get("admin"):
        return redirect(url_for("login"))
    rows = get_db().execute("SELECT * FROM bookings ORDER BY created_at DESC").fetchall()
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(["id","name","phone","email","location","event_date","service","extras","notes","status","created_at"])
    for r in rows:
        cw.writerow([r["id"], r["name"], r["phone"], r["customer_email"], r["location"], r["event_date"], r["service"], r["extras"], r["notes"], r["status"], r["created_at"]])
    output = si.getvalue()
    return Response(output, mimetype="text/csv", headers={"Content-Disposition":"attachment;filename=bookings.csv"})

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == ADMIN_USER and request.form.get("password") == ADMIN_PASS:
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("❌ Invalid Credentials", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------- DELETE / CONFIRM / REJECT ----------------
@app.route("/delete/<int:booking_id>")
def delete_booking(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))
    db = get_db()
    db.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
    db.commit()
    flash("🗑️ Booking deleted successfully!", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/confirm/<int:booking_id>")
def confirm_booking(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    db = get_db()
    row = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()

    if not row:
        flash("Booking not found!", "danger")
        return redirect(url_for("admin_dashboard"))

    try:
        db.execute("UPDATE bookings SET status='Confirmed' WHERE id=?", (booking_id,))
        db.commit()
    except sqlite3.OperationalError:
        flash("Database missing 'status' column. Visit /fixdb to add it.", "danger")
        return redirect(url_for("admin_dashboard"))

    # ✔ EMAIL
    send_email_via_brevo(
        row["name"], row["location"], row["phone"], row["event_date"],
        row["service"], row["extras"], row["notes"], row["customer_email"],
        status="Confirmed",
        booking_id=booking_id
    )

    # ✔ WHATSAPP
    try:
        send_whatsapp_message(
            row["name"], row["phone"], row["event_date"],
            row["service"], row["extras"], row["location"],
            row["customer_email"], row["notes"]
        )
    except:
        app.logger.exception("WhatsApp send failed")

    # ✔ SMS
    send_sms_fast2sms(row["phone"], f"🎉 Your booking for {row['event_date']} is CONFIRMED!")

    flash("Booking Confirmed!", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/reject/<int:booking_id>")
def reject_booking(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    db = get_db()
    row = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()

    if not row:
        flash("Booking not found!", "danger")
        return redirect(url_for("admin_dashboard"))

    db.execute("UPDATE bookings SET status='Rejected' WHERE id=?", (booking_id,))
    db.commit()

    # EMAIL
    send_email_via_brevo(
        row["name"], row["location"], row["phone"], row["event_date"],
        row["service"], row["extras"], row["notes"], row["customer_email"],
        status="Rejected",
        booking_id=booking_id
    )

    # WHATSAPP
    try:
        send_whatsapp_message(
            row["name"], row["phone"], row["event_date"],
            row["service"], row["extras"], row["location"],
            row["customer_email"], row["notes"]
        )
    except:
        app.logger.exception("WhatsApp send failed")

    # SMS Reject
    send_sms_fast2sms(row["phone"], f"❌ Your booking for {row['event_date']} was rejected.")

    flash("Booking Rejected!", "warning")
    return redirect(url_for("admin_dashboard"))

# ---------------- AUTO FIX DB ON STARTUP ----------------
def auto_fix_db():
    db = get_db()
    try:
        db.execute("ALTER TABLE bookings ADD COLUMN status TEXT DEFAULT 'Pending'")
        db.commit()
        print("AUTO-FIX ✔: 'status' column added")
    except Exception as e:
        print("AUTO-FIX ℹ: status column already exists / skipped:", e)


@app.route("/ping")
def ping():
    return "pong"

# ---------------- MAIN ----------------
if __name__ == "__main__":
    # Ensure DB fix runs before app starts
    with app.app_context():
        auto_fix_db()

    try:
        app.run(
            debug=True,
            host="0.0.0.0",                 # Use 0.0.0.0 for Render compatibility
            port=int(os.getenv("PORT", 5000))
        )
    finally:
        try:
            scheduler.shutdown()
        except Exception:
            pass