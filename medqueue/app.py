"""
MedQueue - Online Appointment & Queue Management System
Flask + SQLite backend, server-rendered HTML/CSS/JS frontend.
"""
from datetime import datetime, timedelta, date as date_cls
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, g
)
from werkzeug.security import generate_password_hash, check_password_hash

import database as db

app = Flask(__name__)
app.secret_key = "medqueue-dev-secret-change-in-production"

# ---------------------------------------------------------------- helpers --

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def current_user():
    if "user_id" not in session:
        return None
    return db.query("SELECT * FROM users WHERE id=?", (session["user_id"],), one=True)


@app.before_request
def load_user():
    g.user = current_user()


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not g.user:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*a, **kw)
    return wrapped


def role_required(role):
    def decorator(view):
        @wraps(view)
        def wrapped(*a, **kw):
            if not g.user:
                flash("Please log in to continue.", "error")
                return redirect(url_for("login"))
            if g.user["role"] != role:
                flash("You don't have access to that page.", "error")
                return redirect(url_for("dashboard"))
            return view(*a, **kw)
        return wrapped
    return decorator


def notify(user_id, message, ntype="info"):
    db.execute(
        "INSERT INTO notifications (user_id, message, type) VALUES (?,?,?)",
        (user_id, message, ntype),
    )


def get_doctor_by_user(user_id):
    return db.query("SELECT * FROM doctors WHERE user_id=?", (user_id,), one=True)


def slot_list(doctor):
    """Generate HH:MM slot strings between work_start and work_end."""
    slots = []
    start = datetime.strptime(doctor["work_start"], "%H:%M")
    end = datetime.strptime(doctor["work_end"], "%H:%M")
    step = timedelta(minutes=doctor["slot_minutes"])
    t = start
    while t < end:
        slots.append(t.strftime("%H:%M"))
        t += step
    return slots


def queue_for(doctor_id, appt_date):
    """Return today's appointments for a doctor/date, in serving order."""
    return db.query(
        """SELECT a.*, u.name AS patient_name, u.phone AS patient_phone
           FROM appointments a JOIN users u ON u.id = a.patient_id
           WHERE a.doctor_id=? AND a.appt_date=?
             AND a.status NOT IN ('cancelled')
           ORDER BY a.time_slot ASC, a.queue_number ASC""",
        (doctor_id, appt_date),
    )


def position_and_wait(appt, queue_rows, avg_minutes):
    """Compute this appointment's position (1-based, among not-yet-done) and estimated wait minutes."""
    ahead = 0
    found_self = False
    for row in queue_rows:
        if row["id"] == appt["id"]:
            found_self = True
            break
        if row["status"] in ("booked", "checked_in", "in_progress"):
            ahead += 1
    if not found_self:
        return None, None
    wait_minutes = ahead * avg_minutes
    return ahead + 1, wait_minutes


# ------------------------------------------------------------------ auth --

@app.route("/")
def index():
    if g.user:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        if not name or not email or not password:
            flash("Name, email and password are required.", "error")
            return render_template("register.html")
        existing = db.query("SELECT id FROM users WHERE email=?", (email,), one=True)
        if existing:
            flash("An account with that email already exists.", "error")
            return render_template("register.html")
        uid = db.execute(
            "INSERT INTO users (name, email, password_hash, role, phone) VALUES (?,?,?,?,?)",
            (name, email, generate_password_hash(password), "patient", phone),
        )
        session["user_id"] = uid
        notify(uid, f"Welcome to MedQueue, {name.split()[0]}! You can now book appointments.", "success")
        flash("Account created. Welcome to MedQueue!", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.query("SELECT * FROM users WHERE email=?", (email,), one=True)
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Incorrect email or password.", "error")
            return render_template("login.html")
        if not user["is_active"]:
            flash("This account has been deactivated. Contact the clinic admin.", "error")
            return render_template("login.html")
        session["user_id"] = user["id"]
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    if g.user["role"] == "patient":
        return redirect(url_for("patient_dashboard"))
    if g.user["role"] == "doctor":
        return redirect(url_for("doctor_dashboard"))
    return redirect(url_for("admin_dashboard"))


# ------------------------------------------------------------ notifications --

@app.route("/notifications")
@login_required
def notifications():
    rows = db.query(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
        (g.user["id"],),
    )
    db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (g.user["id"],))
    return render_template("notifications.html", notifications=rows)


@app.route("/api/notifications/unread_count")
@login_required
def api_unread_count():
    row = db.query(
        "SELECT COUNT(*) c FROM notifications WHERE user_id=? AND is_read=0",
        (g.user["id"],), one=True,
    )
    return jsonify({"count": row["c"]})


# ------------------------------------------------------------------ patient --

@app.route("/patient/dashboard")
@role_required("patient")
def patient_dashboard():
    upcoming = db.query(
        """SELECT a.*, d.specialization, u.name AS doctor_name
           FROM appointments a
           JOIN doctors d ON d.id = a.doctor_id
           JOIN users u ON u.id = d.user_id
           WHERE a.patient_id=? AND a.status IN ('booked','checked_in','in_progress')
           ORDER BY a.appt_date ASC, a.time_slot ASC""",
        (g.user["id"],),
    )
    return render_template("patient_dashboard.html", upcoming=upcoming)


@app.route("/patient/book")
@role_required("patient")
def book_select_doctor():
    doctors = db.query(
        """SELECT d.*, u.name AS doctor_name FROM doctors d
           JOIN users u ON u.id = d.user_id
           WHERE d.is_active=1 ORDER BY u.name""",
    )
    return render_template("book_select_doctor.html", doctors=doctors)


@app.route("/patient/book/<int:doctor_id>", methods=["GET", "POST"])
@role_required("patient")
def book_appointment(doctor_id):
    doctor = db.query(
        """SELECT d.*, u.name AS doctor_name FROM doctors d
           JOIN users u ON u.id = d.user_id WHERE d.id=? AND d.is_active=1""",
        (doctor_id,), one=True,
    )
    if not doctor:
        flash("That doctor is not available.", "error")
        return redirect(url_for("book_select_doctor"))

    if request.method == "POST":
        appt_date = request.form.get("appt_date")
        time_slot = request.form.get("time_slot")
        reason = request.form.get("reason", "").strip()

        if not appt_date or not time_slot:
            flash("Please choose a date and time slot.", "error")
            return redirect(url_for("book_appointment", doctor_id=doctor_id))

        taken = db.query(
            "SELECT id FROM appointments WHERE doctor_id=? AND appt_date=? AND time_slot=? AND status NOT IN ('cancelled','no_show')",
            (doctor_id, appt_date, time_slot), one=True,
        )
        if taken:
            flash("That slot was just taken. Please pick another.", "error")
            return redirect(url_for("book_appointment", doctor_id=doctor_id))

        count_row = db.query(
            "SELECT COUNT(*) c FROM appointments WHERE doctor_id=? AND appt_date=? AND status != 'cancelled'",
            (doctor_id, appt_date), one=True,
        )
        queue_number = count_row["c"] + 1

        appt_id = db.execute(
            """INSERT INTO appointments (patient_id, doctor_id, appt_date, time_slot, queue_number, reason)
               VALUES (?,?,?,?,?,?)""",
            (g.user["id"], doctor_id, appt_date, time_slot, queue_number, reason),
        )
        notify(
            g.user["id"],
            f"Appointment confirmed with Dr. {doctor['doctor_name']} on {appt_date} at {time_slot}. Your token is #{queue_number}.",
            "success",
        )
        flash("Appointment booked!", "success")
        return redirect(url_for("queue_status", appt_id=appt_id))

    today = date_cls.today().isoformat()
    max_date = (date_cls.today() + timedelta(days=30)).isoformat()
    return render_template("book_appointment.html", doctor=doctor, today=today, max_date=max_date)


@app.route("/api/slots")
@role_required("patient")
def api_slots():
    doctor_id = request.args.get("doctor_id", type=int)
    appt_date = request.args.get("date", "")
    doctor = db.query("SELECT * FROM doctors WHERE id=?", (doctor_id,), one=True)
    if not doctor or not appt_date:
        return jsonify({"slots": []})

    try:
        d = datetime.strptime(appt_date, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"slots": []})

    days_off = {int(x) for x in doctor["days_off"].split(",") if x.strip().isdigit()}
    if d.isoweekday() in days_off:
        return jsonify({"slots": [], "closed": True})

    all_slots = slot_list(doctor)
    booked = db.query(
        "SELECT time_slot FROM appointments WHERE doctor_id=? AND appt_date=? AND status NOT IN ('cancelled','no_show')",
        (doctor_id, appt_date),
    )
    booked_set = {r["time_slot"] for r in booked}

    now = datetime.now()
    available = []
    for s in all_slots:
        if s in booked_set:
            continue
        if d == now.date():
            slot_dt = datetime.strptime(f"{appt_date} {s}", "%Y-%m-%d %H:%M")
            if slot_dt <= now:
                continue
        available.append(s)

    return jsonify({"slots": available})


@app.route("/patient/appointments")
@role_required("patient")
def my_appointments():
    rows = db.query(
        """SELECT a.*, u.name AS doctor_name, d.specialization
           FROM appointments a
           JOIN doctors d ON d.id = a.doctor_id
           JOIN users u ON u.id = d.user_id
           WHERE a.patient_id=?
           ORDER BY a.appt_date DESC, a.time_slot DESC""",
        (g.user["id"],),
    )
    return render_template("my_appointments.html", appointments=rows)


@app.route("/patient/appointment/<int:appt_id>/cancel", methods=["POST"])
@role_required("patient")
def cancel_appointment(appt_id):
    appt = db.query(
        "SELECT * FROM appointments WHERE id=? AND patient_id=?",
        (appt_id, g.user["id"]), one=True,
    )
    if not appt:
        flash("Appointment not found.", "error")
        return redirect(url_for("my_appointments"))
    if appt["status"] not in ("booked", "checked_in"):
        flash("This appointment can no longer be cancelled.", "error")
        return redirect(url_for("my_appointments"))
    db.execute("UPDATE appointments SET status='cancelled' WHERE id=?", (appt_id,))
    flash("Appointment cancelled.", "success")
    return redirect(url_for("my_appointments"))


@app.route("/patient/queue/<int:appt_id>")
@role_required("patient")
def queue_status(appt_id):
    appt = db.query(
        """SELECT a.*, u.name AS doctor_name, d.avg_consult_minutes, d.id AS doc_id
           FROM appointments a
           JOIN doctors d ON d.id = a.doctor_id
           JOIN users u ON u.id = d.user_id
           WHERE a.id=? AND a.patient_id=?""",
        (appt_id, g.user["id"]), one=True,
    )
    if not appt:
        flash("Appointment not found.", "error")
        return redirect(url_for("my_appointments"))
    return render_template("queue_status.html", appt=appt)


@app.route("/api/patient/queue/<int:appt_id>")
@role_required("patient")
def api_patient_queue(appt_id):
    appt = db.query(
        "SELECT * FROM appointments WHERE id=? AND patient_id=?",
        (appt_id, g.user["id"]), one=True,
    )
    if not appt:
        return jsonify({"error": "not found"}), 404
    doctor = db.query("SELECT * FROM doctors WHERE id=?", (appt["doctor_id"],), one=True)
    rows = queue_for(appt["doctor_id"], appt["appt_date"])
    position, wait = position_and_wait(appt, rows, doctor["avg_consult_minutes"])
    now_serving = next((r for r in rows if r["status"] == "in_progress"), None)
    return jsonify({
        "status": appt["status"],
        "position": position,
        "estimated_wait_minutes": wait,
        "now_serving_token": now_serving["queue_number"] if now_serving else None,
        "your_token": appt["queue_number"],
    })


# ------------------------------------------------------------------- doctor --

@app.route("/doctor/dashboard")
@role_required("doctor")
def doctor_dashboard():
    doctor = get_doctor_by_user(g.user["id"])
    if not doctor:
        flash("No doctor profile is linked to this account. Contact admin.", "error")
        return render_template("doctor_dashboard.html", doctor=None, queue=[])
    today = date_cls.today().isoformat()
    queue = queue_for(doctor["id"], today)
    return render_template("doctor_dashboard.html", doctor=doctor, queue=queue, today=today)


@app.route("/api/doctor/queue")
@role_required("doctor")
def api_doctor_queue():
    doctor = get_doctor_by_user(g.user["id"])
    if not doctor:
        return jsonify({"queue": []})
    today = date_cls.today().isoformat()
    rows = queue_for(doctor["id"], today)
    queue = [{
        "id": r["id"], "token": r["queue_number"], "time_slot": r["time_slot"],
        "patient_name": r["patient_name"], "status": r["status"], "reason": r["reason"] or "",
    } for r in rows]
    return jsonify({"queue": queue})


def _doctor_owns_appt(appt_id):
    doctor = get_doctor_by_user(g.user["id"])
    appt = db.query("SELECT * FROM appointments WHERE id=?", (appt_id,), one=True)
    if not doctor or not appt or appt["doctor_id"] != doctor["id"]:
        return None, None
    return doctor, appt


@app.route("/doctor/appointment/<int:appt_id>/start", methods=["POST"])
@role_required("doctor")
def start_appointment(appt_id):
    doctor, appt = _doctor_owns_appt(appt_id)
    if not appt:
        flash("Appointment not found.", "error")
        return redirect(url_for("doctor_dashboard"))
    db.execute(
        "UPDATE appointments SET status='in_progress', started_at=? WHERE id=?",
        (datetime.now().isoformat(timespec="seconds"), appt_id),
    )
    notify(appt["patient_id"], f"It's your turn now (token #{appt['queue_number']}). Please head to the room.", "alert")

    rows = queue_for(doctor["id"], appt["appt_date"])
    upcoming = [r for r in rows if r["status"] == "booked" and r["id"] != appt_id]
    if upcoming:
        nxt = upcoming[0]
        notify(nxt["patient_id"], f"You're next in line (token #{nxt['queue_number']}). Please be ready.", "info")

    flash(f"Started appointment #{appt['queue_number']}.", "success")
    return redirect(url_for("doctor_dashboard"))


@app.route("/doctor/appointment/<int:appt_id>/complete", methods=["POST"])
@role_required("doctor")
def complete_appointment(appt_id):
    doctor, appt = _doctor_owns_appt(appt_id)
    if not appt:
        flash("Appointment not found.", "error")
        return redirect(url_for("doctor_dashboard"))
    db.execute(
        "UPDATE appointments SET status='completed', completed_at=? WHERE id=?",
        (datetime.now().isoformat(timespec="seconds"), appt_id),
    )
    notify(appt["patient_id"], "Your consultation is complete. Thank you for visiting.", "success")
    flash(f"Completed appointment #{appt['queue_number']}.", "success")
    return redirect(url_for("doctor_dashboard"))


@app.route("/doctor/appointment/<int:appt_id>/no_show", methods=["POST"])
@role_required("doctor")
def no_show_appointment(appt_id):
    doctor, appt = _doctor_owns_appt(appt_id)
    if not appt:
        flash("Appointment not found.", "error")
        return redirect(url_for("doctor_dashboard"))
    db.execute("UPDATE appointments SET status='no_show' WHERE id=?", (appt_id,))
    notify(appt["patient_id"], "You were marked as a no-show for your appointment. Please rebook if this is a mistake.", "error")
    flash(f"Marked appointment #{appt['queue_number']} as no-show.", "success")
    return redirect(url_for("doctor_dashboard"))


@app.route("/doctor/schedule", methods=["GET", "POST"])
@role_required("doctor")
def doctor_schedule():
    doctor = get_doctor_by_user(g.user["id"])
    if not doctor:
        flash("No doctor profile is linked to this account.", "error")
        return redirect(url_for("doctor_dashboard"))

    if request.method == "POST":
        work_start = request.form.get("work_start", "09:00")
        work_end = request.form.get("work_end", "17:00")
        slot_minutes = request.form.get("slot_minutes", type=int) or 15
        avg_consult = request.form.get("avg_consult_minutes", type=int) or 15
        days_off = request.form.getlist("days_off")
        bio = request.form.get("bio", "").strip()

        db.execute(
            """UPDATE doctors SET work_start=?, work_end=?, slot_minutes=?,
               avg_consult_minutes=?, days_off=?, bio=? WHERE id=?""",
            (work_start, work_end, slot_minutes, avg_consult,
             ",".join(days_off) if days_off else "0", bio, doctor["id"]),
        )
        flash("Schedule updated.", "success")
        return redirect(url_for("doctor_schedule"))

    return render_template("doctor_schedule.html", doctor=doctor, weekdays=WEEKDAY_NAMES)


# -------------------------------------------------------------------- admin --

@app.route("/admin/dashboard")
@role_required("admin")
def admin_dashboard():
    stats = {}
    stats["total_users"] = db.query("SELECT COUNT(*) c FROM users WHERE role='patient'", one=True)["c"]
    stats["total_doctors"] = db.query("SELECT COUNT(*) c FROM doctors WHERE is_active=1", one=True)["c"]
    stats["total_appts"] = db.query("SELECT COUNT(*) c FROM appointments", one=True)["c"]
    today = date_cls.today().isoformat()
    stats["today_appts"] = db.query(
        "SELECT COUNT(*) c FROM appointments WHERE appt_date=? AND status!='cancelled'", (today,), one=True
    )["c"]
    recent = db.query(
        """SELECT a.*, up.name AS patient_name, ud.name AS doctor_name
           FROM appointments a
           JOIN users up ON up.id = a.patient_id
           JOIN doctors d ON d.id = a.doctor_id
           JOIN users ud ON ud.id = d.user_id
           ORDER BY a.created_at DESC LIMIT 8"""
    )
    return render_template("admin_dashboard.html", stats=stats, recent=recent)


@app.route("/admin/doctors", methods=["GET", "POST"])
@role_required("admin")
def admin_doctors():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        specialization = request.form.get("specialization", "").strip()
        if not (name and email and password and specialization):
            flash("All fields are required to add a doctor.", "error")
            return redirect(url_for("admin_doctors"))
        existing = db.query("SELECT id FROM users WHERE email=?", (email,), one=True)
        if existing:
            flash("A user with that email already exists.", "error")
            return redirect(url_for("admin_doctors"))
        uid = db.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?,?,?,?)",
            (name, email, generate_password_hash(password), "doctor"),
        )
        db.execute(
            "INSERT INTO doctors (user_id, specialization) VALUES (?,?)",
            (uid, specialization),
        )
        notify(uid, f"Welcome to MedQueue, Dr. {name.split()[-1]}! Set your schedule to start accepting patients.", "success")
        flash(f"Dr. {name} added.", "success")
        return redirect(url_for("admin_doctors"))

    doctors = db.query(
        """SELECT d.*, u.name, u.email, u.is_active AS user_active
           FROM doctors d JOIN users u ON u.id = d.user_id ORDER BY u.name"""
    )
    return render_template("admin_doctors.html", doctors=doctors)


@app.route("/admin/doctors/<int:doctor_id>/toggle", methods=["POST"])
@role_required("admin")
def admin_toggle_doctor(doctor_id):
    doctor = db.query("SELECT * FROM doctors WHERE id=?", (doctor_id,), one=True)
    if doctor:
        db.execute("UPDATE doctors SET is_active=? WHERE id=?", (0 if doctor["is_active"] else 1, doctor_id))
        flash("Doctor status updated.", "success")
    return redirect(url_for("admin_doctors"))


@app.route("/admin/users")
@role_required("admin")
def admin_users():
    patients = db.query("SELECT * FROM users WHERE role='patient' ORDER BY created_at DESC")
    return render_template("admin_users.html", patients=patients)


@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@role_required("admin")
def admin_toggle_user(user_id):
    user = db.query("SELECT * FROM users WHERE id=?", (user_id,), one=True)
    if user and user["role"] == "patient":
        db.execute("UPDATE users SET is_active=? WHERE id=?", (0 if user["is_active"] else 1, user_id))
        flash("User status updated.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/analytics")
@role_required("admin")
def admin_analytics():
    return render_template("admin_analytics.html")


@app.route("/api/admin/analytics")
@role_required("admin")
def api_admin_analytics():
    status_counts = db.query(
        "SELECT status, COUNT(*) c FROM appointments GROUP BY status"
    )
    status_map = {r["status"]: r["c"] for r in status_counts}

    # Average delay: minutes between scheduled time_slot and actual started_at, for started appointments
    started = db.query(
        "SELECT appt_date, time_slot, started_at FROM appointments WHERE started_at IS NOT NULL"
    )
    delays = []
    for r in started:
        try:
            scheduled = datetime.strptime(f"{r['appt_date']} {r['time_slot']}", "%Y-%m-%d %H:%M")
            actual = datetime.fromisoformat(r["started_at"])
            delta = (actual - scheduled).total_seconds() / 60.0
            delays.append(delta)
        except Exception:
            continue
    avg_delay = round(sum(delays) / len(delays), 1) if delays else 0

    # Per-doctor stats
    per_doctor = db.query(
        """SELECT u.name AS doctor_name, d.id AS doctor_id,
                  COUNT(a.id) AS total,
                  SUM(CASE WHEN a.status='completed' THEN 1 ELSE 0 END) AS completed,
                  SUM(CASE WHEN a.status='no_show' THEN 1 ELSE 0 END) AS no_show,
                  SUM(CASE WHEN a.status='cancelled' THEN 1 ELSE 0 END) AS cancelled
           FROM doctors d
           JOIN users u ON u.id = d.user_id
           LEFT JOIN appointments a ON a.doctor_id = d.id
           GROUP BY d.id ORDER BY total DESC"""
    )
    per_doctor_delay = {}
    for r in started:
        pass
    doctor_delay_rows = db.query(
        """SELECT a.doctor_id, a.appt_date, a.time_slot, a.started_at
           FROM appointments a WHERE a.started_at IS NOT NULL"""
    )
    doc_delay_acc = {}
    for r in doctor_delay_rows:
        try:
            scheduled = datetime.strptime(f"{r['appt_date']} {r['time_slot']}", "%Y-%m-%d %H:%M")
            actual = datetime.fromisoformat(r["started_at"])
            delta = (actual - scheduled).total_seconds() / 60.0
        except Exception:
            continue
        doc_delay_acc.setdefault(r["doctor_id"], []).append(delta)

    per_doctor_out = []
    for r in per_doctor:
        ds = doc_delay_acc.get(r["doctor_id"], [])
        per_doctor_out.append({
            "doctor_name": r["doctor_name"],
            "total": r["total"] or 0,
            "completed": r["completed"] or 0,
            "no_show": r["no_show"] or 0,
            "cancelled": r["cancelled"] or 0,
            "avg_delay": round(sum(ds) / len(ds), 1) if ds else 0,
        })

    # Last 14 days appointment volume
    last_14 = []
    for i in range(13, -1, -1):
        d = (date_cls.today() - timedelta(days=i)).isoformat()
        c = db.query(
            "SELECT COUNT(*) c FROM appointments WHERE appt_date=? AND status!='cancelled'",
            (d,), one=True,
        )["c"]
        last_14.append({"date": d, "count": c})

    total_appts = sum(status_map.values())
    completed = status_map.get("completed", 0)
    no_show = status_map.get("no_show", 0)
    cancelled = status_map.get("cancelled", 0)
    no_show_rate = round(100 * no_show / total_appts, 1) if total_appts else 0

    return jsonify({
        "status_counts": status_map,
        "total_appts": total_appts,
        "no_show_rate": no_show_rate,
        "avg_delay_minutes": avg_delay,
        "per_doctor": per_doctor_out,
        "last_14_days": last_14,
        "completed": completed,
        "cancelled": cancelled,
        "no_show": no_show,
    })


if __name__ == "__main__":
    import os
    if not os.path.exists(db.DB_PATH):
        db.init_db()
        print("Database initialized. Run seed.py to add demo data.")
    app.run(debug=True, host="0.0.0.0", port=5000)
