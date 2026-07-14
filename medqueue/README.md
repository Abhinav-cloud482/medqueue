# MedQueue &mdash; Online Appointment & Queue Management System

A full-stack web app that tackles medical appointment delays: patients book online and
track a live queue position instead of waiting blind in a waiting room; doctors run
their day from a simple queue console; admins see exactly where delays happen.

**Stack:** Python (Flask) backend, SQLite database, server-rendered HTML/CSS/JS
frontend (no build step, no frameworks required).

## Features

- **Patients** &mdash; register/login, browse doctors, book an open time slot, see a
  live "now serving" queue board with position and estimated wait, get in-app
  notifications, cancel appointments, view history.
- **Doctors** &mdash; a queue console for today's patients (Start / Complete /
  No-show), and a schedule page to set working hours, slot length, days off, and
  average consultation time.
- **Admins** &mdash; add/deactivate doctors, manage patient accounts, and an
  analytics dashboard with appointment volume, status breakdown, no-show rate, and
  **average start delay per doctor** &mdash; the key metric for reducing appointment
  delays.
- **Notifications** &mdash; in-app (bell icon + notifications page). Booking
  confirmations, "you're next", "it's your turn", cancellations, and no-shows all
  generate a notification for the patient.

## Project structure

```
medqueue/
  app.py              Flask application (routes, auth, business logic)
  database.py          SQLite connection helpers
  schema.sql            Database schema
  seed.py                 Demo data: admin, 3 doctors, 4 patients, sample appointments
  requirements.txt
  static/
    css/style.css        Design system (colors, type, components)
    js/main.js            Shared notification-badge polling
  templates/               Jinja2 HTML templates (one per page)
```

## Setup

Requires Python 3.9+.

```bash
cd medqueue
pip install -r requirements.txt

# Create the database and load demo data (doctors, patients, sample appointments)
python3 seed.py

# Run the app
python3 app.py
```

Visit **http://127.0.0.1:5000**.

## Demo logins

| Role    | Email                          | Password    |
|---------|---------------------------------|-------------|
| Admin   | admin@medqueue.local            | admin123    |
| Doctor  | asha.rao@medqueue.local         | doctor123   |
| Doctor  | neel.kapoor@medqueue.local      | doctor123   |
| Doctor  | priya.menon@medqueue.local      | doctor123   |
| Patient | rahul.sharma@example.com        | patient123  |
| Patient | sneha.verma@example.com         | patient123  |

New patients can also self-register from the landing page.

## How the queue works

- When a patient books, they get a **token number** for that doctor/day.
- The serving order is each doctor's appointments for the day, sorted by time slot.
- A doctor's console shows **Start** (marks a patient "in progress" and notifies
  the next patient in line to get ready) and **Complete**.
- A patient's "Track queue" page polls `/api/patient/queue/<id>` every 10 seconds
  to show their live position and an estimated wait (people ahead &times; the
  doctor's average consultation time).
- Every appointment records its **scheduled time** and the **actual time the
  doctor started it**. The admin analytics page turns that gap into an
  average delay per doctor &mdash; the core "why are we running late" signal.

## Notes for extending this

- Swap SQLite for Postgres/MySQL by changing `database.py`; the SQL is
  intentionally plain (no ORM) to make that straightforward.
- Notifications are in-app only. To add real email/SMS, call an email/SMS
  provider's API inside the `notify()` helper in `app.py` alongside the existing
  database insert.
- `app.secret_key` in `app.py` is a placeholder &mdash; set a real secret via an
  environment variable before deploying.
- The dev server (`app.run(debug=True)`) is for local use only; use a
  production WSGI server (gunicorn, waitress) for real deployments.
