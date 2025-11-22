from flask import Flask, render_template, request, redirect, url_for, flash, g, session
import sqlite3
from pathlib import Path
import os
import threading
import requests

# Brevo
from sib_api_v3_sdk import Configuration, TransactionalEmailsApi, ApiClient, SendSmtpEmail


# ---------------- App + DB ----------------
BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "instance" / "bookings.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
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
        print("SMS Disabled — FAST2SMS_API_KEY missing.")
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
        res = requests.post(url, data=payload, headers=headers)
        print("SMS SENT ✓", res.text)
    except Exception as e:
        print("SMS ERROR:", e)


# ---------------- EMAIL (BREVO API) ----------------
def send_email_via_brevo(name, location, phone, event_date, service,
                         extras, notes, customer_email, whatsapp_link=None):

    api_key = os.getenv("BREVO_API_KEY")
    admin_email = os.getenv("ADMIN_EMAIL")

    if not api_key or not admin_email:
        print("Brevo Missing API or Admin email.")
        return

    configuration = Configuration()
    configuration.api_key["api-key"] = api_key
    api_instance = TransactionalEmailsApi(ApiClient(configuration))

    to_list = [{"email": admin_email}]
    if customer_email:
        to_list.append({"email": customer_email})

    html_content = f"""
    <h2>🎉 Booking Confirmation</h2>
    <p><b>Name:</b> {name}</p>
    <p><b>Phone:</b> {phone}</p>
    <p><b>Email:</b> {customer_email}</p>
    <p><b>Event Date:</b> {event_date}</p>
    <p><b>Service:</b> {service}</p>
    <p><b>Extras:</b> {extras}</p>
    <p><b>Location:</b> {location}</p>
    <p><b>Notes:</b> {notes}</p>
    <p><a href="{whatsapp_link}">Chat on WhatsApp</a></p>
    """

    email_obj = SendSmtpEmail(
        to=to_list,
        sender={"email": admin_email},
        subject=f"Booking Confirmation - {name}",
        html_content=html_content,
    )

    try:
        api_instance.send_transac_email(email_obj)
        print("BREVO EMAIL SENT ✓")
    except Exception as e:
        print("BREVO ERROR:", e)


# ---------------- WHATSAPP (UltraMSG or Free Link) ----------------
def send_whatsapp_message(name, phone, event_date, service,
                          extras, location, customer_email, notes):

    instance = os.getenv("W_INSTANCE")
    token = os.getenv("W_TOKEN")

    if not instance or not token:
        print("WHATSAPP API DISABLED")
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
        r = requests.post(url, data=payload)
        print("WHATSAPP SENT ✓", r.text)
    except Exception as e:
        print("WHATSAPP ERROR:", e)


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

        whatsapp_link = (
            f"https://wa.me/91{phone}?text=Hello%20JAGADHA,%20I%20want%20to%20discuss%20my%20booking."
        )

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
            return render_with_values("⚠ Please select Service!")
        if len(extras_list) == 0:
            return render_with_values("⚠ Select Additional Services!")

        # Save
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


# ---------------- ADMIN ----------------
@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect(url_for("login"))

    rows = get_db().execute(
        "SELECT * FROM bookings ORDER BY created_at DESC"
    ).fetchall()

    return render_template("admin.html", bookings=rows)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if (
            request.form.get("username") == ADMIN_USER
            and request.form.get("password") == ADMIN_PASS
        ):
            session["admin"] = True
            return redirect(url_for("admin"))

        flash("❌ Invalid Credentials", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------- DELETE BOOKING ----------------
@app.route("/delete/<int:booking_id>")
def delete_booking(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    db = get_db()
    db.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
    db.commit()

    flash("🗑️ Booking deleted successfully!", "success")
    return redirect(url_for("admin"))


# ---------------- CONFIRM BOOKING ----------------
@app.route("/confirm/<int:booking_id>")
def confirm_booking(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    db = get_db()
    row = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()

    if not row:
        flash("Booking not found!", "danger")
        return redirect(url_for("admin"))

    db.execute("UPDATE bookings SET status='Confirmed' WHERE id=?", (booking_id,))
    db.commit()

    msg = f"🎉 Your booking for {row['event_date']} is CONFIRMED!"
    send_sms_fast2sms(row["phone"], msg)

    send_whatsapp_message(
        row["name"], row["phone"], row["event_date"],
        row["service"], row["extras"], row["location"],
        row["customer_email"], row["notes"]
    )

    flash("Booking Confirmed ✓", "success")
    return redirect(url_for("admin"))


# ---------------- REJECT BOOKING ----------------
@app.route("/reject/<int:booking_id>")
def reject_booking(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    db = get_db()
    row = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()

    if not row:
        flash("Booking not found!", "danger")
        return redirect(url_for("admin"))

    db.execute("UPDATE bookings SET status='Rejected' WHERE id=?", (booking_id,))
    db.commit()

    msg = f"❌ Sorry, your booking on {row['event_date']} was rejected."
    send_sms_fast2sms(row["phone"], msg)

    flash("Booking Rejected ❌", "warning")
    return redirect(url_for("admin"))

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
