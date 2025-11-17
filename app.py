from flask import Flask, render_template, request, redirect, url_for, flash, g, session
import sqlite3
from pathlib import Path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import json

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/book")
def book():
    return render_template("book.html")

if __name__ == "__main__":
    app.run()

def send_whatsapp_cloud(to_number, name, event_date, service, extras):

    url = f"https://graph.facebook.com/v20.0/{15558968536}/messages"
# /1163757498610413
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    message_body = f"""
🌸 *JAGADHA A to Z - Booking Confirmation* 🌸

Hello *{name}*,
Your event booking has been received.

📅 *Event Date:* {event_date}
🎈 *Service:* {service}
✨ *Additional Services:* {extras}

❤️ Thank you for booking with us!
"""

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": f"91{to_number}",
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message_body
        }
    }

    response = requests.post(url, headers=headers, data=json.dumps(payload))
    print("WhatsApp Response:", response.json())

BASE = Path(__file__).parent
DB_PATH = BASE / "instance" / "bookings.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)  # ensure instance folder exists

app = Flask(__name__)
app.config["DATABASE"] = str(DB_PATH)
app.secret_key = "change_this_secret_key"   # Change before production

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
    if db is not None:
        db.close()

def create_tables():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            event_date TEXT NOT NULL,
            service TEXT,
            extras TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()

# ✅ Runs once at app start
with app.app_context():
    create_tables()

# ---------------------- EMAIL ----------------------
def send_email_notification(name, email, phone, event_date, service, extras, notes):

    sender_email = "smtshan007@gmail.com"
    sender_password = "gqtd suke rmcd rpmp"   # Must replace

    receiver_emails = [
        "Jagadhaeventplanner@gmail.com",
        "smtshan007@gmail.com"
        "{email}"
    ]

    subject = f"Booking Confirmation – {name}"

    html_message = f"""
    <html>
    <body style="font-family: Arial; line-height: 1.7;">

        <h2 style="color:#0A74DA;">🎉 Booking Confirmation</h2>

        <p>Dear <strong>{name}</strong>,</p>
        <p>Your event booking has been received successfully. Below are the details:</p>

        <table style="width:100%; border-collapse: collapse;">
            <tr><td>📛 Name</td><td>{name}</td></tr>
            <tr><td>📧 Email</td><td>{email}</td></tr>
            <tr><td>📞 Phone</td><td>{phone}</td></tr>
            <tr><td>📅 Event Date</td><td>{event_date}</td></tr>
            <tr><td>🎈 Service Required</td><td>{service}</td></tr>
            <tr><td>✨ Additional Services</td><td>{extras}</td></tr>
            <tr><td>📝 Notes</td><td>{notes}</td></tr>
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

        print("Email sent successfully.")

    except Exception as e:
        print("Email sending error:", e)

# ---------------------- ROUTES ----------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/book", methods=["GET", "POST"])
def book():
    if request.method == "POST":

        # ---- Read Form Data ----
        name = request.form["name"].strip()
        email = request.form["email"].strip()
        phone = request.form["phone"].strip()
        event_date = request.form["event_date"].strip()
        service = request.form["service"].strip()
        notes = request.form.get("notes", "").strip()

        extras_list = request.form.getlist("extras")
        extras = ", ".join(extras_list)

        # ---- Mapping for error messages ----
        field_labels = {
            "name": "Name",
            "email": "Email",
            "phone": "Phone",
            "event_date": "Date of Event",
            "service": "Service Required"
        }

        # ---- Backend Required Field Checks (same as JS) ----
        if not name:
            flash(f'⚠ Please fill "{field_labels["name"]}" field.', "danger")
            return render_template("book.html",
                                   name=name, email=email, phone=phone,
                                   event_date=event_date, service=service,
                                   notes=notes, selected_extras=extras_list)

        if not email:
            flash(f'⚠ Please fill "{field_labels["email"]}" field.', "danger")
            return render_template("book.html",
                                   name=name, email=email, phone=phone,
                                   event_date=event_date, service=service,
                                   notes=notes, selected_extras=extras_list)

        if not phone:
            flash(f'⚠ Please fill "{field_labels["phone"]}" field.', "danger")
            return render_template("book.html",
                                   name=name, email=email, phone=phone,
                                   event_date=event_date, service=service,
                                   notes=notes, selected_extras=extras_list)

        if not event_date:
            flash(f'⚠ Please fill "{field_labels["event_date"]}" field.', "danger")
            return render_template("book.html",
                                   name=name, email=email, phone=phone,
                                   event_date=event_date, service=service,
                                   notes=notes, selected_extras=extras_list)

        # Special dropdown validation
        if service == "----Select----" or not service:
            flash(f'⚠ Please fill "{field_labels["service"]}" field.', "danger")
            return render_template("book.html",
                                   name=name, email=email, phone=phone,
                                   event_date=event_date, service=service,
                                   notes=notes, selected_extras=extras_list)

        # Checkbox validation
        if len(extras_list) == 0:
            flash("⚠ Additional Services Not Selected. Kindly check it!", "danger")
            return render_template("book.html",
                                   name=name, email=email, phone=phone,
                                   event_date=event_date, service=service,
                                   notes=notes, selected_extras=extras_list)

        # ---- Save to DB ----
        db = get_db()
        db.execute("""
            INSERT INTO bookings (name, email, phone, event_date, service, extras, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, email, phone, event_date, service, extras, notes))
        db.commit()

        # ---- Send Notifications ----
        send_email_notification(name, email, phone, event_date, service, extras, notes)

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
        username = request.form["username"]
        password = request.form["password"]

        if username == ADMIN_USER and password == ADMIN_PASS:
            session["admin"] = True
            return redirect(url_for("admin"))
        else:
            flash("❌ Invalid credentials")

    return render_template("login.html")

@app.route("/admin/login", methods=["POST"])
def admin_login_submit():
    username = request.form["username"]
    password = request.form["password"]

    if username == "admin" and password == "1234":
        return redirect("/admin")
    else:
        flash("Invalid login!", "danger")
        return redirect("/login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------------- RUN APP ----------------------
if __name__ == "__main__":
    with app.app_context():
        create_tables()
    app.run(debug=True)
