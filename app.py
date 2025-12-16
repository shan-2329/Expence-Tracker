from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, g, session, jsonify, Response
)
import psycopg2
import psycopg2.extras
import os
import threading
import requests
import csv
import io
import base64
from datetime import date
from io import BytesIO
import urllib.parse
import qrcode
from qrcode.constants import ERROR_CORRECT_L

# ================= CONFIG =================
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")
ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP", "919659796217")
SITE_URL = os.getenv("SITE_URL", "https://jagadha-a-to-z-event-management.onrender.com")

# ================= APP =================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change_me")

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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()

with app.app_context():
    create_tables()

# ================= PDF =================
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

def generate_pdf_receipt(row):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    y = 800

    p.setFont("Helvetica-Bold", 18)
    p.drawString(50, y, "JAGADHA A to Z Event Management")
    y -= 40

    p.setFont("Helvetica", 12)
    for k in ["id","name","phone","customer_email","event_date","service","extras","notes"]:
        p.drawString(50, y, f"{k.capitalize()}: {row.get(k,'')}")
        y -= 18

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer.read()

# ================= WHATSAPP =================
def send_whatsapp_message(row):
    msg = (
        f"❤️ JAGADHA A to Z ❤️\n"
        f"Booking #{row['id']}\n"
        f"Name: {row['name']}\n"
        f"Date: {row['event_date']}\n"
        f"Service: {row['service']}"
    )
    encoded = urllib.parse.quote(msg)
    return f"https://wa.me/91{row['phone']}?text={encoded}"

# ================= ROUTES =================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/book", methods=["GET","POST"])
def book():
    if request.method == "POST":
        data = (
            request.form["name"].strip(),
            request.form["location"].strip(),
            request.form["phone"].strip(),
            request.form.get("customer_email"),
            request.form["event_date"],
            request.form["service"],
            ", ".join(request.form.getlist("extras")),
            request.form.get("notes","")
        )

        db = get_db()
        cur = db.cursor()
        cur.execute("""
            INSERT INTO bookings
            (name,location,phone,customer_email,event_date,service,extras,notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, data)

        booking_id = cur.fetchone()["id"]
        db.commit()

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
        whatsapp_link=send_whatsapp_message(row)
    )

# ================= ADMIN =================
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == ADMIN_USER and request.form["password"] == ADMIN_PASS:
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Invalid credentials","danger")
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

@app.route("/api/bookings")
def api_bookings():
    if not session.get("admin"):
        return jsonify([])

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM bookings ORDER BY created_at DESC")
    rows = cur.fetchall()

    return jsonify({
        "total": len(rows),
        "pending": sum(1 for r in rows if r["status"]=="Pending"),
        "confirmed": sum(1 for r in rows if r["status"]=="Confirmed"),
        "rejected": sum(1 for r in rows if r["status"]=="Rejected"),
        "bookings": rows
    })

@app.route("/confirm/<int:booking_id>")
def confirm_booking(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor()
    cur.execute(
        "UPDATE bookings SET status='Confirmed' WHERE id=%s",
        (booking_id,)
    )
    db.commit()
    flash("Booking confirmed","success")
    return redirect(url_for("admin_dashboard"))

@app.route("/reject/<int:booking_id>")
def reject_booking(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor()
    cur.execute(
        "UPDATE bookings SET status='Rejected' WHERE id=%s",
        (booking_id,)
    )
    db.commit()
    flash("Booking rejected","warning")
    return redirect(url_for("admin_dashboard"))

@app.route("/delete/<int:booking_id>")
def delete_booking(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM bookings WHERE id=%s",(booking_id,))
    db.commit()
    flash("Booking deleted","success")
    return redirect(url_for("admin_dashboard"))

@app.route("/export_csv")
def export_csv():
    if not session.get("admin"):
        return redirect(url_for("login"))

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM bookings ORDER BY created_at DESC")
    rows = cur.fetchall()

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(rows[0].keys() if rows else [])
    for r in rows:
        cw.writerow(r.values())

    return Response(
        si.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition":"attachment;filename=bookings.csv"}
    )

@app.route("/ping")
def ping():
    return "pong"

# ================= RUN =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",5000)))
