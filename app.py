# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, g, session
import sqlite3
from pathlib import Path
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

# ---------------- App + DB ----------------
BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "instance" / "bookings.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
# Use environment SECRET_KEY in production
app.secret_key = os.getenv("SECRET_KEY", "change_this_secret_key")

# App DB config
app.config["DATABASE"] = str(DB_PATH)

# Admin credentials (override via environment in production)
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")


# ---------------- Database helpers ----------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.commit()


# Ensure tables exist on startup
with app.app_context():
    create_tables()


# ---------------- Notifications ----------------
def send_notifications(name, location, phone, event_date, service, extras, notes, customer_email=None):
    SMTP_USER = os.getenv("SMTP_USER")
    SMTP_PASS = os.getenv("SMTP_PASS")

    # ---------------- EMAIL ----------------
    try:
        if not SMTP_USER or not SMTP_PASS:
            app.logger.error("SMTP credentials missing!")
            return

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"New Booking - {name}"
        msg["From"] = SMTP_USER

        recipients = [SMTP_USER]
        if customer_email:
            recipients.append(customer_email)
        msg["To"] = ", ".join(recipients)

        html = f"""
        <html><body>
            <h2>New Booking Received</h2>
            <p><b>Name:</b> {name}</p>
            <p><b>Phone:</b> {phone}</p>
            <p><b>Event Date:</b> {event_date}</p>
            <p><b>Service:</b> {service}</p>
            <p><b>Extras:</b> {extras}</p>
            <p><b>Location:</b> {location}</p>
            <p><b>Notes:</b> {notes}</p>
        </body></html>
        """
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, recipients, msg.as_string())

        app.logger.info("EMAIL SENT ✓")

    except Exception as e:
        app.logger.exception("EMAIL ERROR: %s", e)

    # ---------------- WHATSAPP ----------------
    try:
        api_token = os.getenv("W_TOKEN")         # correct
        instance_id = os.getenv("W_INSTANCE")    # correct

        if not api_token or not instance_id:
            app.logger.info("WHATSAPP SKIPPED: Missing W_TOKEN/W_INSTANCE")
            return

        url = f"https://api.ultramsg.com/{instance_id}/messages/chat"

        payload = {
            "token": api_token,
            "to": phone,
            "body": (
                f"Hello {name} 🌸\n\n"
                f"Your booking is confirmed!\n"
                f"📅 Event Date: {event_date}\n"
                f"🎯 Service: {service}\n"
                f"📍 Location: {location}\n"
                f"✨ Extras: {extras}\n"
            )
        }

        r = requests.post(url, data=payload, timeout=15)
        app.logger.info("WHATSAPP RESPONSE: %s", r.text)

    except Exception as e:
        app.logger.exception("WHATSAPP ERROR: %s", e)


# ---------------- Utility render helper ----------------
def render_with_values(message, category="danger", **kwargs):
    flash(message, category)
    return render_template("book.html", **kwargs)


# ---------------- Routes ----------------
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

        # Required validation
        if not name:
            return render_with_values("⚠ Please fill Name!", name=name, location=location, phone=phone,
                                      event_date=event_date, service=service, notes=notes, selected_extras=extras_list)

        if not location:
            return render_with_values("⚠ Please fill Location!", name=name, location=location, phone=phone,
                                      event_date=event_date, service=service, notes=notes, selected_extras=extras_list)

        if not phone:
            return render_with_values("⚠ Please fill Phone!", name=name, location=location, phone=phone,
                                      event_date=event_date, service=service, notes=notes, selected_extras=extras_list)

        if not event_date:
            return render_with_values("⚠ Please fill Date of Event!", name=name, location=location, phone=phone,
                                      event_date=event_date, service=service, notes=notes, selected_extras=extras_list)

        if not service:
            return render_with_values("⚠ Please select Service!", name=name, location=location, phone=phone,
                                      event_date=event_date, service=service, notes=notes, selected_extras=extras_list)

        if len(extras_list) == 0:
            return render_with_values(
                "⚠ Additional Services not selected!",
                name=name,
                location=location,
                phone=phone,
                event_date=event_date,
                service=service,
                notes=notes,
                selected_extras=extras_list
            )

        # SAVE TO DB
        db = get_db()
        db.execute(
            """
            INSERT INTO bookings (name, location, phone, event_date, service, extras, notes, customer_email)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, location, phone, event_date, service, extras, notes, customer_email)
        )
        db.commit()

        # 🔔 Send email + WhatsApp notifications (non-blocking approach would be to queue; here we call directly)
        send_notifications(name, location, phone, event_date, service, extras, notes, customer_email)

        flash("✅ Booking submitted successfully!", "success")
        return redirect(url_for("book"))

    # GET
    return render_template("book.html")


@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect(url_for("login"))
    db = get_db()
    rows = db.execute("SELECT * FROM bookings ORDER BY created_at DESC").fetchall()
    return render_template("admin.html", bookings=rows)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == ADMIN_USER and password == ADMIN_PASS:
            session["admin"] = True
            return redirect(url_for("admin"))
        flash("❌ Invalid Credentials", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    # Use 0.0.0.0 in production container if you want external access; debug should be False in production.
    app.run(debug=True, host="127.0.0.1", port=int(os.getenv("PORT", 5000)))
