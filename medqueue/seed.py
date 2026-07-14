"""Seed MedQueue with demo data: an admin, a few doctors, patients, and sample appointments."""
from datetime import datetime, timedelta, date as date_cls
from werkzeug.security import generate_password_hash
import database as db

def run():
    db.init_db(reset=True)

    # --- Admin ---
    admin_id = db.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (?,?,?,?)",
        ("Clinic Admin", "admin@medqueue.local", generate_password_hash("admin123"), "admin"),
    )

    # --- Doctors ---
    doctors_data = [
        ("Dr. Asha Rao", "asha.rao@medqueue.local", "General Physician", 15, "09:00", "17:00"),
        ("Dr. Neel Kapoor", "neel.kapoor@medqueue.local", "Cardiology", 20, "10:00", "16:00"),
        ("Dr. Priya Menon", "priya.menon@medqueue.local", "Pediatrics", 12, "09:30", "15:30"),
    ]
    doctor_ids = []
    for name, email, spec, avg_min, start, end in doctors_data:
        uid = db.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?,?,?,?)",
            (name, email, generate_password_hash("doctor123"), "doctor"),
        )
        did = db.execute(
            """INSERT INTO doctors (user_id, specialization, avg_consult_minutes, work_start, work_end, slot_minutes, days_off, bio)
               VALUES (?,?,?,?,?,?,?,?)""",
            (uid, spec, avg_min, start, end, avg_min, "7",
             f"{spec} specialist with a focus on timely, attentive care."),
        )
        doctor_ids.append(did)

    # --- Patients ---
    patients_data = [
        ("Rahul Sharma", "rahul.sharma@example.com", "9990001111"),
        ("Sneha Verma", "sneha.verma@example.com", "9990002222"),
        ("Arjun Iyer", "arjun.iyer@example.com", "9990003333"),
        ("Kavya Nair", "kavya.nair@example.com", "9990004444"),
    ]
    patient_ids = []
    for name, email, phone in patients_data:
        uid = db.execute(
            "INSERT INTO users (name, email, password_hash, role, phone) VALUES (?,?,?,?,?)",
            (name, email, generate_password_hash("patient123"), "patient", phone),
        )
        patient_ids.append(uid)

    # --- Sample appointments for today ---
    today = date_cls.today().isoformat()
    doc0 = db.query("SELECT * FROM doctors WHERE id=?", (doctor_ids[0],), one=True)
    slots_today = ["09:00", "09:15", "09:30", "09:45"]
    now = datetime.now()

    for i, slot in enumerate(slots_today):
        pid = patient_ids[i % len(patient_ids)]
        qn = i + 1
        appt_id = db.execute(
            """INSERT INTO appointments (patient_id, doctor_id, appt_date, time_slot, queue_number, status, reason)
               VALUES (?,?,?,?,?,?,?)""",
            (pid, doctor_ids[0], today, slot, qn, "booked", "Routine check-up"),
        )
        db.execute(
            "INSERT INTO notifications (user_id, message, type) VALUES (?,?,?)",
            (pid, f"Appointment confirmed with Dr. Asha Rao on {today} at {slot}. Your token is #{qn}.", "success"),
        )

    # Mark the first as completed (with a realistic delay) and second as in_progress, to show a live queue
    rows = db.query(
        "SELECT * FROM appointments WHERE doctor_id=? AND appt_date=? ORDER BY time_slot",
        (doctor_ids[0], today),
    )
    if len(rows) >= 2:
        first = rows[0]
        started = datetime.strptime(f"{today} {first['time_slot']}", "%Y-%m-%d %H:%M") + timedelta(minutes=8)
        completed = started + timedelta(minutes=doc0["avg_consult_minutes"])
        db.execute(
            "UPDATE appointments SET status='completed', started_at=?, completed_at=? WHERE id=?",
            (started.isoformat(timespec="seconds"), completed.isoformat(timespec="seconds"), first["id"]),
        )
        second = rows[1]
        started2 = completed + timedelta(minutes=2)
        db.execute(
            "UPDATE appointments SET status='in_progress', started_at=? WHERE id=?",
            (started2.isoformat(timespec="seconds"), second["id"]),
        )

    # --- Some historical appointments (past 13 days) across doctors for analytics ---
    import random
    random.seed(42)
    for i in range(1, 14):
        d = (date_cls.today() - timedelta(days=i)).isoformat()
        num_appts = random.randint(2, 6)
        for j in range(num_appts):
            doc_id = random.choice(doctor_ids)
            doc = db.query("SELECT * FROM doctors WHERE id=?", (doc_id,), one=True)
            pid = random.choice(patient_ids)
            hour = 9 + j
            slot = f"{hour:02d}:00"
            status = random.choices(
                ["completed", "no_show", "cancelled"], weights=[75, 15, 10]
            )[0]
            qn = j + 1
            scheduled = datetime.strptime(f"{d} {slot}", "%Y-%m-%d %H:%M")
            started_at = None
            completed_at = None
            if status == "completed":
                delay = random.randint(-5, 35)
                started_dt = scheduled + timedelta(minutes=delay)
                started_at = started_dt.isoformat(timespec="seconds")
                completed_at = (started_dt + timedelta(minutes=doc["avg_consult_minutes"])).isoformat(timespec="seconds")
            db.execute(
                """INSERT INTO appointments
                   (patient_id, doctor_id, appt_date, time_slot, queue_number, status, reason, started_at, completed_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (pid, doc_id, d, slot, qn, status, "Consultation", started_at, completed_at),
            )

    print("Seed complete.")
    print("Admin login:   admin@medqueue.local / admin123")
    print("Doctor login:  asha.rao@medqueue.local / doctor123  (also neel.kapoor@, priya.menon@)")
    print("Patient login: rahul.sharma@example.com / patient123 (also sneha.verma@, arjun.iyer@, kavya.nair@)")


if __name__ == "__main__":
    run()
