from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, g, session, jsonify, Response
)
import psycopg2
import psycopg2.extras
import os
import csv
import io
import urllib.parse
import requests
from datetime import timedelta

# ================= CONFIG =================
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")
ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP", "919659796217")
SITE_URL = os.getenv(
    "SITE_URL",
    "https://jagadha-a-to-z-event-management.onrender.com"
)

# ================= APP =================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change_me")
app.permanent_session_lifetime = timedelta(days=7)

# ================= DB =================
def get_db():
    if "db" not in g:
        g.db = psycopg2.connect(
            os.environ["DATABASE_URL"],
            cursor_factory=psycopg2.extras.RealDictCursor,
            sslmode="require"
        )
    return g.db

@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()

def create_tables():
    db = get_db()
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
            whatsapp_sent BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()

with app.app_context():
    create_tables()

# ================= WHATSAPP =================
def whatsapp_customer(row):
    msg = f"""
❤️ JAGADHA A to Z Event Management ❤️

Booking ID: {row['id']}
Name: {row['name']}
Event Date: {row['event_date']}
Service: {row['service']}

Thank you for choosing us 🙏
"""
    return f"https://wa.me/91{row['phone']}?text={urllib.parse.quote(msg)}"

def whatsapp_admin(row):
    msg = f"""
📢 NEW BOOKING ALERT

Booking ID: {row['id']}
Name: {row['name']}
Phone: {row['phone']}
Event Date: {row['event_date']}
Service: {row['service']}
"""
    return f"https://wa.me/{ADMIN_WHATSAPP}?text={urllib.parse.quote(msg)}"

app.jinja_env.globals.update(whatsapp_admin=whatsapp_admin)

# ================= BREVO EMAIL =================
def send_brevo_email(to_email, subject, html_content):
    api_key = os.environ.get("BREVO_API_KEY")
    if not api_key:
        print("⚠ BREVO API KEY missing")
        return

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json"
    }

    payload = {
        "sender": {"name": "JAGADHA A to Z", "email": "noreply@jagadha.com"},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content
    }

    r = requests.post(url, json=payload, headers=headers)
    if r.status_code not in (200, 201):
        print("BREVO ERROR:", r.text)

def whatsapp_message(booking):
    msg = f"""
🎉 Booking Confirmed 🎉

👤 Name: {booking['name']}
🆔 Booking ID: #{booking['id']}
🎈 Service: {booking['service']}
📅 Event Date: {booking['event_date']}
📍 Location: {booking['location']}

🙏 Thank you for choosing JAGADHA A to Z
"""
    return urllib.parse.quote(msg)

# ================= ROUTES =================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/book", methods=["GET", "POST"])
def book():
    if request.method == "POST":
        name = request.form["name"].strip()
        location = request.form["location"].strip()
        phone = request.form["phone"].strip()
        customer_email = request.form.get("customer_email")
        event_date = request.form["event_date"]
        service = request.form["service"]
        extras = ", ".join(request.form.getlist("extras"))
        notes = request.form.get("notes", "")

        db = get_db()
        cur = db.cursor()
        cur.execute("""
            INSERT INTO bookings
            (name, location, phone, customer_email, event_date, service, extras, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (name, location, phone, customer_email, event_date, service, extras, notes))

        booking_id = cur.fetchone()["id"]
        db.commit()

        # 📧 ADMIN EMAIL
        send_brevo_email(
            "admin@jagadha.com",
            "📩 New Booking Received",
            f"""
            <h3>New Booking Received</h3>
            <p><b>Name:</b> {name}</p>
            <p><b>Service:</b> {service}</p>
            <p><b>Phone:</b> {phone}</p>
            """
        )

        # 📧 CUSTOMER EMAIL
        if customer_email:
            send_brevo_email(
                customer_email,
                "🎉 Booking Received — JAGADHA",
                f"""
                <h3>Thank you for your booking!</h3>
                <p>Your Booking ID: <b>#{booking_id}</b></p>
                """
            )

        return redirect(url_for("booking_success", booking_id=booking_id))

    return render_template("book.html")

@app.route("/booking/<int:booking_id>")
def booking_success(booking_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM bookings WHERE id=%s", (booking_id,))
    row = cur.fetchone()

    if not row:
        flash("Booking not found", "danger")
        return redirect(url_for("index"))

    return render_template(
        "booking_success.html",
        booking=row,
        wa={
            "message": "",
            "customer_link": whatsapp_customer(row),
            "admin_link": whatsapp_admin(row),
            "qr_path": True
        }
    )

# ================= ADMIN =================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == ADMIN_USER and request.form["password"] == ADMIN_PASS:
            session.permanent = True
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("login"))
    return render_template("admin_dashboard.html")

# ================= API =================
@app.route("/api/bookings")
def api_bookings():
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 401

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM bookings ORDER BY created_at DESC")
    rows = cur.fetchall()

    return jsonify({
        "total": len(rows),
        "pending": sum(1 for r in rows if r["status"] == "Pending"),
        "confirmed": sum(1 for r in rows if r["status"] == "Confirmed"),
        "rejected": sum(1 for r in rows if r["status"] == "Rejected"),
        "bookings": rows
    })

# ================= ACTIONS =================
@app.route("/confirm/<int:booking_id>")
def confirm_booking(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM bookings WHERE id=%s", (booking_id,))
    booking = cur.fetchone()

    if not booking:
        flash("Booking not found", "danger")
        return redirect(url_for("admin_dashboard"))

    cur.execute("UPDATE bookings SET status='Confirmed' WHERE id=%s", (booking_id,))
    db.commit()

    if booking["customer_email"]:
        send_brevo_email(
            booking["customer_email"],
            "✅ Booking Confirmed — JAGADHA",
            f"<p>Your booking <b>#{booking_id}</b> is confirmed 🎉</p>"
        )

    wa = f"https://wa.me/91{booking['phone']}?text={whatsapp_message(booking)}"
    return redirect(wa)

# ================= CSV =================
@app.route("/export_csv")
def export_csv():
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 401

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM bookings ORDER BY created_at DESC")
    rows = cur.fetchall()

    si = io.StringIO()
    cw = csv.writer(si)
    if rows:
        cw.writerow(rows[0].keys())
        for r in rows:
            cw.writerow(r.values())

    return Response(
        si.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=bookings.csv"}
    )

@app.route("/ping")
def ping():
    return "pong"

# ================= RENDER COOKIE FIX =================
if os.getenv("RENDER"):
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_SAMESITE="None"
    )

# ================= RUN =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
