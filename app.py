# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, g, session, jsonify, send_file, Response
import sqlite3
from pathlib import Path
import os
import threading
import requests
import csv
import io

# Brevo
from sib_api_v3_sdk import Configuration, TransactionalEmailsApi, ApiClient, SendSmtpEmail

# ---------------- App + DB ----------------
BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "instance" / "bookings.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, template_folder=str(BASE / "templates"), static_folder=str(BASE / "static"))
app.secret_key = os.getenv("SECRET_KEY", "change_this_secret_key")
app.config["DATABASE"] = str(DB_PATH)

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

# ---------------- EMAIL (BREVO API) ----------------
def send_email_via_brevo(name, location, phone, event_date, service,
                         extras, notes, customer_email, whatsapp_link=None):
    api_key = os.getenv("BREVO_API_KEY")
    admin_email = os.getenv("ADMIN_EMAIL")

    if not api_key or not admin_email:
        app.logger.info("Brevo Missing API or Admin email.")
        return

    configuration = Configuration()
    configuration.api_key["api-key"] = api_key
    api_instance = TransactionalEmailsApi(ApiClient(configuration))

    to_list = [{"email": admin_email}]
    if customer_email:
        to_list.append({"email": customer_email})

    html_content = f"""<!DOCTYPE html><html><body style="font-family: Arial; background:#f7f7f7; margin:0; padding:0;">
    <div style="max-width:600px; margin:20px auto; background:white; border-radius:10px;
                box-shadow:0 4px 20px rgba(0,0,0,0.08); overflow:hidden;">
      <div style="background:#f9c5d5; padding:20px; text-align:center;">
        <h2 style="margin:0; color:#b01357;">❤️ JAGADHA A to Z Event Management ❤️</h2>
      </div>
      <div style="padding:25px;">
        <h3>🎉 Booking Confirmation</h3>
        <p>Dear <b>{name}</b>,</p>
        <p>Your booking has been received. Below are your details:</p>
        <table style="width:100%; font-size:15px;">
          <tr><td><b>📛 Name:</b></td><td>{name}</td></tr>
          <tr><td><b>📞 Phone:</b></td><td>{phone}</td></tr>
          <tr><td><b>📅 Event Date:</b></td><td>{event_date}</td></tr>
          <tr><td><b>🎈 Service:</b></td><td>{service}</td></tr>
          <tr><td><b>✨ Extras:</b></td><td>{extras}</td></tr>
          <tr><td><b>📍 Location:</b></td><td>{location}</td></tr>
          <tr><td><b>📝 Notes:</b></td><td>{notes}</td></tr>
        </table>
        <p style="margin-top:20px;">❤️ Thank you for choosing <b>JAGADHA A to Z Event Management</b>!</p>
        <div style="text-align:center; margin:25px 0;">
          <a href="https://jagadha-a-to-z-event-management.onrender.com" style="background:#b01357; color:white; padding:12px 25px; text-decoration:none; border-radius:6px;">Visit Our Website</a>
        </div>
      </div>
      <div style="background:#fafafa; padding:15px; text-align:center; font-size:13px;">
        © 2025 JAGADHA A to Z Event Management<br>This is an automated message.
      </div>
    </div></body></html>
    """

    send_smtp_email = SendSmtpEmail(
        to=to_list,
        sender={"email": admin_email},
        subject=f"🎉 Booking Confirmation - {name}",
        html_content=html_content,
    )

    try:
        api_instance.send_transac_email(send_smtp_email)
        app.logger.info("BREVO EMAIL SENT ✓")
    except Exception as e:
        app.logger.exception("BREVO ERROR: %s", e)

# ---------------- WHATSAPP (UltraMSG) ----------------
def send_whatsapp_message(name, phone, event_date, service,
                          extras, location, customer_email, notes):
    instance = os.getenv("W_INSTANCE")
    token = os.getenv("W_TOKEN")
    if not instance or not token:
        app.logger.info("WHATSAPP API DISABLED")
        return
    url = f"https://api.ultramsg.com/{instance}/messages/chat"
    message = f"""
🎉 *Booking Confirmation* 🎉
📛 *Name:* {name}
📞 *Phone:* {phone}
📅 *Event Date:* {event_date}
🎈 *Service:* {service}
✨ *Extras:* {extras}
📍 *Location:* {location}
📝 *Notes:* {notes}
"""
    payload = {"token": token, "to": f"91{phone}", "body": message}
    try:
        r = requests.post(url, data=payload, timeout=15)
        app.logger.info("WHATSAPP SENT ✓ %s", r.text)
    except Exception as e:
        app.logger.exception("WHATSAPP ERROR: %s", e)

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

        whatsapp_link = f"https://wa.me/91{phone}?text=Hello%20JAGADHA,%20I%20want%20to%20discuss%20my%20booking."

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
        db.execute(
            """
            INSERT INTO bookings (name, location, phone, event_date, service, extras, notes, customer_email)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, location, phone, event_date, service, extras, notes, customer_email),
        )
        db.commit()

        # Notifications (Thread)
        threading.Thread(
            target=lambda: (
                send_email_via_brevo(name, location, phone, event_date,
                                     service, extras, notes, customer_email, whatsapp_link),
                send_whatsapp_message(name, phone, event_date, service,
                                      extras, location, customer_email, notes)
            ),
            daemon=True,
        ).start()

        flash("✅ Booking submitted successfully!", "success")
        return redirect(url_for("book"))

    return render_template("book.html")

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
        # keep data private; allow only admin (you can relax this if needed)
        return jsonify({"bookings":[]})
    rows = get_db().execute("SELECT * FROM bookings ORDER BY created_at DESC").fetchall()
    bookings = []
    for r in rows:
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
            "status": r["status"],
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
    db.execute("UPDATE bookings SET status='Confirmed' WHERE id=?", (booking_id,))
    db.commit()
    # notifications
    try:
        msg = f"🎉 Your booking for {row['event_date']} is CONFIRMED!"
        send_sms_fast2sms(row["phone"], msg)
        send_whatsapp_message(row["name"], row["phone"], row["event_date"], row["service"], row["extras"], row["location"], row["customer_email"], row["notes"])
        send_email_via_brevo(row["name"], row["location"], row["phone"], row["event_date"], row["service"], row["extras"], row["notes"], row["customer_email"])
    except Exception as e:
        app.logger.exception("Error sending confirmation notifications: %s", e)
    flash("Booking Confirmed ✓", "success")
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
    try:
        msg = f"❌ Sorry, your booking on {row['event_date']} was rejected."
        send_sms_fast2sms(row["phone"], msg)
        send_email_via_brevo(row["name"], row["location"], row["phone"], row["event_date"], row["service"], row["extras"], f"Your booking was rejected.", row["customer_email"])
    except Exception as e:
        app.logger.exception("Error sending rejection notifications: %s", e)
    flash("Booking Rejected ❌", "warning")
    return redirect(url_for("admin_dashboard"))

# DB fix endpoint (keep for convenience)
@app.route("/fixdb")
def fixdb():
    db = get_db()
    try:
        db.execute("ALTER TABLE bookings ADD COLUMN status TEXT DEFAULT 'Pending'")
        db.commit()
        return "DB FIXED ✓"
    except Exception as e:
        return f"Already exists or error: {e}"

# ---------------- MAIN ----------------
if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=int(os.getenv("PORT", 5000)))
