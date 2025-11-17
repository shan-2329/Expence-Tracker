from flask import Flask, render_template, request, redirect, url_for, flash, g, session
import sqlite3
from pathlib import Path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ---------------- App + DB ----------------
BASE = Path(__file__).parent
DB_PATH = BASE / "instance" / "bookings.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["DATABASE"] = str(DB_PATH)
app.secret_key = "change_this_secret_key"  # change in production

ADMIN_USER = "admin"
ADMIN_PASS = "admin123"

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
            customer_email TEXT,
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

# ---------------- Email helper ----------------
def send_email_notification(name, location, phone, event_date, service, extras, notes, customer_email=None):
    """
    Sends email to admin list and optionally to customer_email (if provided).
    Uses SMTP SSL (Gmail). Replace credentials below.
    If SMTP fails on your host (e.g. Render), use a transactional email API (Brevo/SendGrid).
    """
    SMTP_USER = "smtshan007@gmail.com"
    SMTP_PASSWORD = "bijt rril icdh hsqp"  # <<--- Replace with App Password

    admin_recipients = ["Jagadhaeventplanner@gmail.com", "smtshan007@gmail.com"]
    recipients = admin_recipients.copy()
    if customer_email:
        recipients.append(customer_email)

    subject = f"Booking Confirmation / New Booking – {name}"

    html_message = f"""
    <html>
    <body style="font-family: Arial; line-height: 1.6;">
      <h2>🎉 New Booking / Confirmation</h2>
      <table style="width:100%; border-collapse: collapse;">
        <tr><td><b>Name</b></td><td>{name}</td></tr>
        <tr><td><b>Location</b></td><td>{location}</td></tr>
        <tr><td><b>Phone</b></td><td>{phone}</td></tr>
        <tr><td><b>Event Date</b></td><td>{event_date}</td></tr>
        <tr><td><b>Service</b></td><td>{service}</td></tr>
        <tr><td><b>Extras</b></td><td>{extras}</td></tr>
        <tr><td><b>Notes</b></td><td>{notes}</td></tr>
      </table>
      <p>❤️ Thank you for choosing JAGADHA A to Z Event Management!</p>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    # we will set To header per-recipient when sending

    msg.attach(MIMEText(html_message, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            for r in recipients:
                msg["To"] = r
                server.sendmail(SMTP_USER, r, msg.as_string())
        app.logger.info("Email(s) sent to: %s", ", ".join(recipients))
    except Exception as ex:
        # log error but don't crash the request flow
        app.logger.error("Email sending failed: %s", ex)

# ---------------- Routes ----------------
@app.route("/")
def index():
    return render_template("index.html")

def render_with_values(message, category="danger", **kwargs):
    flash(message, category)
    return render_template("book.html", **kwargs)


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

        # Required validation
        if not name:
            return render_with_values("⚠ Please fill Name!")

        if not location:
            return render_with_values("⚠ Please fill Location!")

        if not phone:
            return render_with_values("⚠ Please fill Phone!")

        if not event_date:
            return render_with_values("⚠ Please fill Date of Event!")

        if not service:
            return render_with_values("⚠ Please select Service!")

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

        # SAVE TO DB (EMAIL REMOVED)
        db = get_db()
        db.execute("""
            INSERT INTO bookings (name, location, phone, event_date, service, extras, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, location, phone, event_date, service, extras, notes))
        db.commit()

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
        if request.form.get("username") == ADMIN_USER and request.form.get("password") == ADMIN_PASS:
            session["admin"] = True
            return redirect(url_for("admin"))
        flash("❌ Invalid Credentials", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)
