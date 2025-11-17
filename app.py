from flask import Flask, render_template, request, redirect, url_for, flash, g, session
import sqlite3
from pathlib import Path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import json

# ======================================================
# APP + DATABASE SETUP
# ======================================================

BASE = Path(__file__).parent
DB_PATH = BASE / "instance" / "bookings.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["DATABASE"] = str(DB_PATH)
app.secret_key = "change_this_secret_key"

ADMIN_USER = "admin"
ADMIN_PASS = "admin123"


# ---------------------- DATABASE ----------------------
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
    db.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            phone TEXT NOT NULL,
            event_date TEXT NOT NULL,
            service TEXT,
            extras TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()


with app.app_context():
    create_tables()


# ======================================================
# EMAIL FUNCTION
# ======================================================

def send_email_notification(name, location, phone, event_date, service, extras, notes):

    sender_email = "smtshan007@gmail.com"
    sender_password = "bijt rril icdh hsqp"  # IMPORTANT

    receiver_emails = [
        "Jagadhaeventplanner@gmail.com",
        "smtshan007@gmail.com"
    ]

    subject = f"New Event Booking – {name}"

    html_message = f"""
    <html>
    <body style="font-family: Arial; line-height: 1.7;">

        <h2 style="color:#0A74DA;">🎉 New Event Booking Received</h2>

        <table style="width:100%; border-collapse: collapse;">
            <tr><td><b>Name</b></td><td>{name}</td></tr>
            <tr><td><b>Location</b></td><td>{location}</td></tr>
            <tr><td><b>Phone</b></td><td>{phone}</td></tr>
            <tr><td><b>Event Date</b></td><td>{event_date}</td></tr>
            <tr><td><b>Service</b></td><td>{service}</td></tr>
            <tr><td><b>Extras</b></td><td>{extras}</td></tr>
            <tr><td><b>Notes</b></td><td>{notes}</td></tr>
        </table>

        <p style="margin-top:20px;">
            ❤️ Thank you for choosing JAGADHA A to Z Event Management!
        </p>

    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg.attach(MIMEText(html_message, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            for r in receiver_emails:
                msg["To"] = r
                server.sendmail(sender_email, r, msg.as_string())
        print("Email sent successfully!")

    except Exception as e:
        print("Email sending error:", e)

# ======================================================
# ROUTES
# ======================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/book", methods=["GET", "POST"])
def book():
    if request.method == "POST":

        name = request.form["name"].strip()
        location = request.form["location"].strip()
        phone = request.form["phone"].strip()
        event_date = request.form["event_date"].strip()
        service = request.form["service"].strip()
        notes = request.form.get("notes", "").strip()

        extras_list = request.form.getlist("extras")
        extras = ", ".join(extras_list)

        # Required field validation
        if not name:
            flash("⚠ Please fill Name!", "danger")
            return render_template("book.html")

        if not location:
            flash("⚠ Please fill Location!", "danger")
            return render_template("book.html")

        if not phone:
            flash("⚠ Please fill Phone!", "danger")
            return render_template("book.html")

        if not event_date:
            flash("⚠ Please fill Date of Event!", "danger")
            return render_template("book.html")

        if not service:
            flash("⚠ Please select Service!", "danger")
            return render_template("book.html")

        if len(extras_list) == 0:
            flash("⚠ Additional Services not selected!", "danger")
            return render_template(
                "book.html",
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
        db.execute("""
            INSERT INTO bookings (name, location, phone, event_date, service, extras, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, location, phone, event_date, service, extras, notes))
        db.commit()

        # ✅ SEND EMAIL HERE
        send_email_notification(name, location, phone, event_date, service, extras, notes)

        flash("✅ Booking submitted successfully!", "success")
        return redirect(url_for("book"))

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
        if request.form["username"] == ADMIN_USER and request.form["password"] == ADMIN_PASS:
            session["admin"] = True
            return redirect(url_for("admin"))
        flash("❌ Invalid Credentials", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ======================================================
# RUN APP
# ======================================================

if __name__ == "__main__":
    app.run(debug=True)
