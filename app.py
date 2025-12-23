from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, g, session, jsonify, Response
)
import psycopg2
import psycopg2.extras
from psycopg2.extras import RealDictCursor
import os
import csv
import io
import urllib.parse
from datetime import timedelta
import random

# ===== BREVO SDK =====
from sib_api_v3_sdk import ApiClient, Configuration
from sib_api_v3_sdk.api.transactional_emails_api import TransactionalEmailsApi

# ================= CONFIG =================
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")
ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP", "919659796217")
ADMIN_MOBILE = os.getenv("ADMIN_MOBILE", "919659796217")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "Jagadhaeventplanner@gmail.com")

SITE_URL = os.getenv(
    "SITE_URL",
    "https://jagadha-a-to-z-event-management.onrender.com"
)

# ================= APP =================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change_me")
app.permanent_session_lifetime = timedelta(days=7)

# ================= DATABASE =================
def get_db():
    if "db" not in g:
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            return None
        try:
            g.db = psycopg2.connect(
                db_url,
                cursor_factory=psycopg2.extras.RealDictCursor,
                sslmode="require"
            )
        except Exception as e:
            app.logger.error(f"DB connection failed: {e}")
            return None
    return g.db

@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()

def create_tables():
    db = get_db()
    if not db:
        return
    cur = db.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            phone TEXT NOT NULL,
            customer_email TEXT,
            event_date DATE NOT NULL,
            service TEXT,
            extras TEXT,
            notes TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()

def ensure_whatsapp_column():
    db = get_db()
    if not db:
        return
    cur = db.cursor()
    cur.execute("""
        ALTER TABLE bookings
        ADD COLUMN IF NOT EXISTS whatsapp_sent BOOLEAN DEFAULT FALSE;
    """)
    db.commit()

# ---- SAFE DB INIT (Flask 3 compatible) ----
def init_db():
    with app.app_context():
        create_tables()
        ensure_whatsapp_column()

init_db()

# ================= EMAIL (BREVO) =================
def send_email_via_brevo(
    name, location, phone, event_date, service,
    extras, notes, customer_email=None,
    status="Pending", booking_id=None
):
    api_key = os.getenv("BREVO_API_KEY")
    if not api_key:
        return

    config = Configuration()
    config.api_key["api-key"] = api_key
    api = TransactionalEmailsApi(ApiClient(config))

    to_list = [{"email": ADMIN_EMAIL}]
    if customer_email:
        to_list.append({"email": customer_email})

    subject_map = {
        "Pending": "🎉 Booking Received",
        "Confirmed": "✅ Booking Confirmed",
        "Rejected": "❌ Booking Rejected"
    }

    subject = f"{subject_map.get(status, 'Booking Update')} — JAGADHA"

    html = f"""
    <h3>{subject}</h3>
    <p>Name: {name}</p>
    <p>Event Date: {event_date}</p>
    <p>Service: {service}</p>
    <p>Location: {location}</p>
    <p>Phone: {phone}</p>
    <p>Extras: {extras or '-'}</p>
    <p>Notes: {notes or '-'}</p>
    <p><a href="{SITE_URL}">Visit Website</a></p>
    """

    email = {
        "sender": {"name": "JAGADHA A to Z", "email": ADMIN_EMAIL},
        "to": to_list,
        "subject": subject,
        "htmlContent": html
    }

    try:
        api.send_transac_email(email)
    except Exception as e:
        app.logger.error(f"BREVO ERROR: {e}")

# ================= WHATSAPP =================
def whatsapp_customer(row):
    msg = f"""
Booking ID: {row['id']}
Name: {row['name']}
Event Date: {row['event_date']}
Service: {row['service']}
"""
    return f"https://wa.me/91{row['phone']}?text={urllib.parse.quote(msg)}"

def whatsapp_admin(row):
    msg = f"""
NEW BOOKING
ID: {row['id']}
Name: {row['name']}
Phone: {row['phone']}
"""
    return f"https://wa.me/{ADMIN_WHATSAPP}?text={urllib.parse.quote(msg)}"

app.jinja_env.globals.update(whatsapp_admin=whatsapp_admin)

# ================= ROUTES =================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/book", methods=["GET", "POST"])
def book():
    if request.method == "POST":
        db = get_db()
        if not db:
            return "Database unavailable", 503

        cur = db.cursor()
        cur.execute("""
            INSERT INTO bookings
            (name, location, phone, customer_email, event_date, service, extras, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            request.form["name"].strip(),
            request.form["location"].strip(),
            request.form["phone"].strip(),
            request.form.get("customer_email"),
            request.form["event_date"],
            request.form["service"],
            ", ".join(request.form.getlist("extras")),
            request.form.get("notes", "")
        ))
        booking_id = cur.fetchone()["id"]
        db.commit()

        send_email_via_brevo(
            request.form["name"],
            request.form["location"],
            request.form["phone"],
            request.form["event_date"],
            request.form["service"],
            ", ".join(request.form.getlist("extras")),
            request.form.get("notes"),
            request.form.get("customer_email"),
            "Pending",
            booking_id
        )

        return redirect(url_for("booking_success", booking_id=booking_id))

    return render_template("book.html")

@app.route("/booking/<int:booking_id>")
def booking_success(booking_id):
    db = get_db()
    if not db:
        return "Database unavailable", 503

    cur = db.cursor()
    cur.execute("SELECT * FROM bookings WHERE id=%s", (booking_id,))
    row = cur.fetchone()

    if not row:
        return redirect(url_for("index"))

    return render_template(
        "booking_success.html",
        booking=row,
        wa={
            "customer_link": whatsapp_customer(row),
            "admin_link": whatsapp_admin(row)
        }
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == ADMIN_USER and request.form["password"] == ADMIN_PASS:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")

@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin_logged_in"):
        return redirect(url_for("login"))
    return render_template("admin_dashboard.html")

@app.route("/api/bookings")
def api_bookings():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    db = get_db()
    if not db:
        return jsonify({"error": "DB unavailable"}), 503

    cur = db.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM bookings ORDER BY created_at DESC")
    rows = cur.fetchall()

    return jsonify(rows)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/health")
def health():
    return {"status": "ok"}, 200

# ================= RUN =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
