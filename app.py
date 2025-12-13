# app.py
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, g, session
)
import sqlite3
from pathlib import Path
import os
import threading
import urllib.parse
from datetime import datetime, date, timedelta
from io import BytesIO
import base64
import qrcode
from qrcode.constants import ERROR_CORRECT_L

# PDF
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# Brevo Email
from sib_api_v3_sdk import Configuration, TransactionalEmailsApi, ApiClient, SendSmtpEmail

# Scheduler
from apscheduler.schedulers.background import BackgroundScheduler

# ---------------- CONFIG ----------------
BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "instance" / "bookings.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP", "919659796217")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")

# ---------------- APP ----------------
app = Flask(__name__, template_folder=str(BASE / "templates"), static_folder=str(BASE / "static"))
app.secret_key = os.getenv("SECRET_KEY", "change_this_key")
app.config["DATABASE"] = str(DB_PATH)

# ---------------- DB ----------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            location TEXT,
            customer_email TEXT,
            phone TEXT,
            event_date TEXT,
            service TEXT,
            extras TEXT,
            notes TEXT,
            status TEXT DEFAULT 'Pending',
            whatsapp_sent INTEGER DEFAULT 0,
            reminder_sent INTEGER DEFAULT 0,
            email_sent INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()

with app.app_context():
    init_db()

# ---------------- PDF ----------------
def generate_pdf_receipt(row):
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    y = 800
    p.setFont("Helvetica-Bold", 16)
    p.drawString(40, y, "JAGADHA A to Z Event Management")
    y -= 40
    p.setFont("Helvetica", 11)

    for k in ["id","name","phone","customer_email","event_date","service","extras","notes","status"]:
        p.drawString(40, y, f"{k.replace('_',' ').title()}: {row[k] or '-'}")
        y -= 18

    p.showPage()
    p.save()
    buf.seek(0)
    return buf.read()

# ---------------- EMAIL ----------------
def send_email_with_pdf(row):
    if not BREVO_API_KEY:
        app.logger.warning("BREVO API KEY missing")
        return

    try:
        config = Configuration()
        config.api_key["api-key"] = BREVO_API_KEY
        api = TransactionalEmailsApi(ApiClient(config))

        pdf_bytes = generate_pdf_receipt(row)
        pdf_b64 = base64.b64encode(pdf_bytes).decode()

        subject = f"Booking Confirmation – #{row['id']}"

        html = f"""
        <h2>❤️ JAGADHA A to Z Event Management ❤️</h2>
        <p>Dear <b>{row['name']}</b>,</p>
        <p>Your booking details are below.</p>

        <ul>
          <li>📅 Event Date: {row['event_date']}</li>
          <li>🎈 Service: {row['service']}</li>
          <li>📍 Location: {row['location']}</li>
        </ul>

        <hr>
        <p><b>தமிழில்:</b></p>
        <p>உங்கள் முன்பதிவு பெறப்பட்டுள்ளது. எங்களை தொடர்பு கொண்டதற்கு நன்றி.</p>

        <p>🙏 Thank you</p>
        """

        email = SendSmtpEmail(
            to=[{"email": row["customer_email"]}] if row["customer_email"] else [],
            bcc=[{"email": ADMIN_EMAIL}],
            subject=subject,
            html_content=html,
            sender={"name": "JAGADHA Events", "email": ADMIN_EMAIL},
            attachment=[{
                "content": pdf_b64,
                "name": f"Booking_{row['id']}.pdf"
            }]
        )

        api.send_transac_email(email)

        db = get_db()
        db.execute("UPDATE bookings SET email_sent=1 WHERE id=?", (row["id"],))
        db.commit()

    except Exception as e:
        app.logger.exception("EMAIL ERROR: %s", e)

# ---------------- WHATSAPP ----------------
def send_whatsapp_message(row):
    msg = (
        "❤️ *JAGADHA A to Z Event Management* ❤️\n\n"
        "🎉 Booking Update\n\n"
        f"📛 Name: {row['name']}\n"
        f"📞 Phone: {row['phone']}\n"
        f"📅 Date: {row['event_date']}\n"
        f"🎈 Service: {row['service']}\n"
        f"📍 Location: {row['location']}\n\n"
        "🙏 Thank you\n"
        "தமிழில்: உங்கள் முன்பதிவு பெறப்பட்டது"
    )

    link = f"https://wa.me/91{row['phone']}?text={urllib.parse.quote(msg)}"

    try:
        qr = qrcode.QRCode(version=1, error_correction=ERROR_CORRECT_L, box_size=8, border=3)
        qr.add_data(link)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(os.path.join(app.static_folder, "whatsapp_qr.png"))
    except Exception:
        pass

    db = get_db()
    db.execute("UPDATE bookings SET whatsapp_sent=1 WHERE id=?", (row["id"],))
    db.commit()

    return link

# ---------------- REMINDER ----------------
def whatsapp_reminder_job():
    db = get_db()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    rows = db.execute("""
        SELECT * FROM bookings
        WHERE event_date=? AND status='Confirmed' AND reminder_sent=0
    """, (tomorrow,)).fetchall()

    for r in rows:
        link = f"https://wa.me/91{r['phone']}?text={urllib.parse.quote('⏰ Event Reminder – Tomorrow')}"
        app.logger.info("REMINDER: %s", link)
        db.execute("UPDATE bookings SET reminder_sent=1 WHERE id=?", (r["id"],))
        db.commit()

# ---------------- SCHEDULER ----------------
scheduler = BackgroundScheduler()
scheduler.add_job(whatsapp_reminder_job, "cron", hour=8, minute=30)
scheduler.start()

# ---------------- ROUTES ----------------
@app.route("/book", methods=["GET","POST"])
def book():
    if request.method == "POST":
        f = request.form
        db = get_db()
        cur = db.execute("""
            INSERT INTO bookings (name, location, phone, event_date, service, extras, notes, customer_email)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            f["name"], f["location"], f["phone"], f["event_date"],
            f["service"], ", ".join(f.getlist("extras")),
            f.get("notes"), f.get("customer_email")
        ))
        db.commit()
        bid = cur.lastrowid

        row = db.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()

        threading.Thread(target=lambda: send_whatsapp_message(row), daemon=True).start()
        threading.Thread(target=lambda: send_email_with_pdf(row), daemon=True).start()

        return redirect(url_for("booking_success", booking_id=bid))

    return render_template("book.html")

@app.route("/booking/<int:booking_id>")
def booking_success(booking_id):
    row = get_db().execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    return render_template("booking_success.html", booking=row)

# ---------------- MAIN ----------------
if __name__ == "__main__":
    app.run(debug=True)
