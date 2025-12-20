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
import requests
import random

# ===== BREVO SDK =====
from sib_api_v3_sdk import ApiClient, Configuration
from sib_api_v3_sdk.api.transactional_emails_api import TransactionalEmailsApi

# ================= CONFIG =================
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")
ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP", "919659796217")
ADMIN_MOBILE = os.getenv("ADMIN_MOBILE", "919659796217")

SITE_URL = os.getenv(
    "SITE_URL",
    "https://jagadha-a-to-z-event-management.onrender.com"
)

ADMIN_EMAIL = os.getenv(
    "ADMIN_EMAIL",
    "Jagadhaeventplanner@gmail.com"
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

# ================= EMAIL (BREVO) =================
def send_email_via_brevo(
    name, location, phone, event_date, service,
    extras, notes, customer_email=None,
    status="Pending", booking_id=None
):
    """Send email to ADMIN + CUSTOMER with Tamil"""

    api_key = os.getenv("BREVO_API_KEY")
    if not api_key:
        app.logger.warning("⚠ BREVO API KEY missing")
        return

    configuration = Configuration()
    configuration.api_key["api-key"] = api_key
    api_instance = TransactionalEmailsApi(ApiClient(configuration))

    to_list = [{"email": ADMIN_EMAIL}]
    if customer_email:
        to_list.append({"email": customer_email})

    status_text = {
        "Pending": "🎉 Booking Received",
        "Confirmed": "✅ Booking Confirmed",
        "Rejected": "❌ Booking Rejected"
    }.get(status, "🎉 Booking Update")

    tamil_status = {
        "Pending": "உங்கள் முன்பதிவு பெறப்பட்டது",
        "Confirmed": "உங்கள் முன்பதிவு உறுதிசெய்யப்பட்டது",
        "Rejected": "மன்னிக்கவும் — உங்கள் முன்பதிவு நிராகரிக்கப்பட்டது"
    }.get(status, "நிலையை புதுப்பித்தல்")

    subject = f"{status_text} — JAGADHA A to Z"

    html_content = f"""
    <html><body style="font-family:Arial;background:#f7f7f7;padding:20px">
      <div style="max-width:600px;margin:auto;background:#fff;border-radius:10px">
        <div style="background:#f9c5d5;padding:16px;text-align:center">
          <h2 style="color:#b01357">❤️ JAGADHA A to Z Event Management ❤️</h2>
        </div>

        <div style="padding:18px">
          <h3>{status_text}</h3>
          <p>Dear <b>{name}</b>,</p>

          <table style="width:100%;font-size:14px">
            <tr><td><b>Booking ID</b></td><td>#{booking_id}</td></tr>
            <tr><td><b>📅 Event Date</b></td><td>{event_date}</td></tr>
            <tr><td><b>🎈 Service</b></td><td>{service}</td></tr>
            <tr><td><b>✨ Extras</b></td><td>{extras or '-'}</td></tr>
            <tr><td><b>📍 Location</b></td><td>{location}</td></tr>
            <tr><td><b>📞 Phone</b></td><td>{phone}</td></tr>
          </table>

          <p><b>Notes:</b> {notes or '-'}</p>

          <hr>
          <p><b>தமிழில்:</b> {tamil_status}</p>

          <div style="text-align:center;margin-top:16px">
            <a href="{SITE_URL}"
               style="background:#b01357;color:white;padding:10px 18px;
               border-radius:6px;text-decoration:none">
               Visit Our Website
            </a>
          </div>
        </div>

        <div style="background:#fafafa;padding:10px;text-align:center;font-size:12px">
          Automated message – JAGADHA A to Z
        </div>
      </div>
    </body></html>
    """

    email = {
        "sender": {"name": "JAGADHA A to Z", "email": ADMIN_EMAIL},
        "to": to_list,
        "subject": subject,
        "htmlContent": html_content
    }

    try:
        api_instance.send_transac_email(email)
    except Exception as e:
        app.logger.error(f"BREVO ERROR: {e}")

# ================= WHATSAPP =================
def whatsapp_customer(row):
    msg = f"""
❤️ JAGADHA A to Z Event Management ❤️

Booking ID: {row['id']}
Name: {row['name']}
Event Date: {row['event_date']}
Service: {row['service']}
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
        """, (
            name, location, phone, customer_email,
            event_date, service, extras, notes
        ))
        booking_id = cur.fetchone()["id"]
        db.commit()

        send_email_via_brevo(
            name, location, phone, event_date,
            service, extras, notes,
            customer_email, "Pending", booking_id
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
            "customer_link": whatsapp_customer(row),
            "admin_link": whatsapp_admin(row)
        }
    )

# ================= ADMIN =================
# @app.route("/login", methods=["GET", "POST"])
# def login():
#     if request.method == "POST":
#         if (
#             request.form["username"] == ADMIN_USER
#             and request.form["password"] == ADMIN_PASS
#         ):
#             session.permanent = True
#             session["admin"] = True
#             return redirect(url_for("admin_dashboard"))
#         flash("Invalid credentials", "danger")
#     return render_template("login.html")

@app.route("/login", methods=["GET", "POST"])
def login(username=None):
    if request.method == "POST":
        if username == ADMIN_USER and password == ADMIN_PASS:
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

# ================= ACTIONS =================
@app.route("/confirm/<int:booking_id>")
def confirm_booking(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT * FROM bookings WHERE id=%s", (booking_id,))
    booking = cur.fetchone()

    if not booking:
        flash("Booking not found", "danger")
        return redirect(url_for("admin_dashboard"))

    cur.execute("""
        UPDATE bookings
        SET status='Confirmed', whatsapp_sent=TRUE
        WHERE id=%s
    """, (booking_id,))
    db.commit()

    send_email_via_brevo(
        booking["name"], booking["location"], booking["phone"],
        booking["event_date"], booking["service"],
        booking["extras"], booking["notes"],
        booking["customer_email"], "Confirmed", booking_id
    )

    flash("✅ Booking confirmed", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/reject/<int:booking_id>")
def reject_booking(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM bookings WHERE id=%s", (booking_id,))
    booking = cur.fetchone()

    if not booking:
        flash("Booking not found!", "danger")
        return redirect(url_for("admin_dashboard"))

    cur.execute(
        "UPDATE bookings SET status='Rejected' WHERE id=%s",
        (booking_id,)
    )
    db.commit()

    send_email_via_brevo(
        booking["name"], booking["location"], booking["phone"],
        booking["event_date"], booking["service"],
        booking["extras"], booking["notes"],
        booking["customer_email"], "Rejected", booking_id
    )

    flash("❌ Booking rejected!", "warning")
    return redirect(url_for("admin_dashboard"))

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

@app.route("/resend_email/<int:booking_id>")
def resend_email(booking_id):
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 401

    db = get_db()
    cur = db.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM bookings WHERE id=%s", (booking_id,))
    b = cur.fetchone()

    if not b:
        return jsonify({"error": "Not found"}), 404

    send_email_via_brevo(
        b["name"], b["location"], b["phone"],
        b["event_date"], b["service"],
        b["extras"], b["notes"],
        b["customer_email"], b["status"], b["id"]
    )

    return jsonify({"success": True})

# ================= RUN =================
if os.getenv("RENDER"):
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_SAMESITE="None"
    )

@app.route("/login-otp", methods=["GET", "POST"])
def login_otp():
    if request.method == "POST":
        step = request.form.get("step")

        if step == "send":
            mobile = request.form.get("mobile")
            if mobile != ADMIN_MOBILE:
                flash("Unauthorized mobile number", "danger")
                return redirect(url_for("login_otp"))

            otp = random.randint(100000, 999999)
            session["otp"] = str(otp)
            session["otp_sent"] = True

            print("ADMIN OTP:", otp)  # 🔐 replace with SMS API later
            flash("OTP sent successfully", "success")
            return redirect(url_for("login_otp"))

        if step == "verify":
            if request.form.get("otp") == session.get("otp"):
                session.clear()
                session["admin_logged_in"] = True
                flash("Login successful", "success")
                return redirect(url_for("admin_dashboard"))
            else:
                flash("Invalid OTP", "danger")

    return render_template("login_otp.html")

@app.route("/api/bookings")
def api_bookings(bookings=None, total=None, confirmed=None, pending=None, rejected=None):
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 401

    # fetch bookings
    return jsonify({
        "bookings": bookings,
        "total": total,
        "confirmed": confirmed,
        "pending": pending,
        "rejected": rejected
    })
print("SESSION:", dict(session))

# @app.route("/logout")
# def logout():
#     session.clear()
#     flash("You have been logged out successfully.", "info")
#     return redirect(url_for("login"))

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    flash("Admin logged out successfully.", "info")
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
