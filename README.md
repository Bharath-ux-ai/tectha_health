# TEC THA Follow-Up Engine — Version 1

Appointment booking and WhatsApp follow-up reminders for hospitals and clinics, built to the
*TEC THA Follow-Up Engine – Version 1 Brief*. Five modules, nothing else: booking, day-before
WhatsApp reminders, 7- and 3-day follow-up reminders, a reception dashboard, and a monthly report
("We brought back X patients this month").

Not in Version 1 (by design): AI assistant, public patient app, billing, health records.

---

## 1. Project structure

```
tectha-followup/
├── backend/                     FastAPI · SQLAlchemy 2 · PostgreSQL · Alembic
│   ├── app/
│   │   ├── main.py              app, error handlers, security headers
│   │   ├── config.py            settings from environment
│   │   ├── worker.py            reminder worker (python -m app.worker)
│   │   ├── cli.py               create-system-admin · create-hospital · seed-demo
│   │   ├── core/                auth deps, RBAC, clock, phone, security, rate limits
│   │   ├── models/              tenancy.py · clinical.py · messaging.py (23 tables)
│   │   ├── services/            booking, slots, reminders, follow-ups, engine, dashboard,
│   │   │   │                    reports, templates, patients, hospitals, demo, audit
│   │   │   └── whatsapp/        client.py (Cloud API) · sender.py · webhook.py
│   │   └── api/                 11 routers, 70 endpoints
│   ├── alembic/versions/        0001 schema · 0002 roles & permissions seed
│   ├── tests/                   66 pytest tests against real PostgreSQL
│   ├── Dockerfile · requirements.txt
├── frontend/                    Next.js 16 · React 19 · TypeScript · Tailwind CSS 4
│   ├── src/app/                 22 routes (see §5)
│   ├── src/components/          shell, UI kit, reminder rail, slot picker, …
│   ├── src/lib/                 API client, types, formatting
│   ├── e2e/smoke.mjs            browser end-to-end test (Mr. Ravi scenario)
│   └── Dockerfile
├── deploy/                      Caddyfile (HTTPS) · backup.sh
├── docs/screenshots/            screens captured by the browser end-to-end run
├── docker-compose.yml
└── .env.example
```

## 2. What is implemented

| Module | Highlights |
|---|---|
| **Booking** | Public page per hospital at `/book/<slug>` (English/Tamil), doctor → day → time → name & mobile → WhatsApp consent. Slots come from each doctor's weekly sessions. Double booking is blocked by the database itself (partial unique index on doctor + start time for active bookings) and by a one-booking-per-patient-per-doctor-per-day rule. References like `TT-7KQ9X2`. Honeypot + rate limit. Public endpoints never return patient data. |
| **Day-before reminder** | Due the evening before at the hospital's chosen time (default 18:00 IST). Late bookings are reminded immediately; same-day bookings get none; a reminder never goes out on the visit day itself ("tomorrow" would be wrong). Template with **Confirm** and **Reschedule** quick-reply buttons. |
| **Patient replies** | Signed webhook (`X-Hub-Signature-256`). Confirm → appointment confirmed + thank-you reply. Reschedule → flagged for staff + reply with the booking link; rebooking online closes the old one. Replies are accepted only from the number that was messaged. Redelivered webhooks are ignored (dedupe keys). `STOP` opts the patient out. |
| **Follow-ups** | Staff set the next visit date from the appointment (quick picks: 1 week, 2 weeks, 1 month, 3 months). Reminders 7 and 3 days before at the follow-up time (default 10:00). Windows already passed are recorded as skipped, never sent late; if the worker was down, only the 3-day reminder goes. Moving the date replaces reminders; moving it back never duplicates. Confirm on a follow-up reminder books the first free slot that day ("books again with one tap"). Completing a visit closes the matching follow-up. |
| **Dashboard** | Today's appointments with one-click outcomes, day summary, **"Call these patients"** — red when the follow-up date passed or there's no reply two days before (also when a reminder failed), amber when the patient asked for another date. Upcoming follow-ups with the reminder rail, earlier visits needing an outcome, search, date and status filters on the appointments list, patient lookup. Hospital admins also see the month's headline and WhatsApp status. |
| **Monthly report** | Totals, completed, cancelled, did-not-come, follow-ups scheduled/completed, return rate, new vs returning patients, WhatsApp delivery numbers, and the headline. "Brought back" counts a patient only if the follow-up visit was **recorded** and WhatsApp **confirmed** a reminder was delivered/read or the patient tapped a button, before the visit. Returns without that evidence are shown separately. CSV export, print-to-PDF, saved snapshots. |
| **Roles** | System admin (hospitals, platform switch, status — no patient data), hospital admin (everything in the hospital), reception staff (appointments, follow-ups, patients, messages). Roles/permissions live in the database. Every hospital query is scoped to the user's hospital; other hospitals' records answer 404. |
| **WhatsApp engine** | Official Cloud API adapter. Modes per hospital: *test* (nothing leaves the server; stored as "simulated" and labelled everywhere), *live*, *off*. Worker claims due reminders with `FOR UPDATE SKIP LOCKED`, so several workers are safe. Retries 5/30/120 min for temporary errors only; permanent errors fail at once; timeouts with unknown outcome are **not** retried automatically. Staff retry from the UI; a reminder that already reached WhatsApp is never sent twice. Platform-wide kill switch. |
| **Safety** | Consent recorded with source and text version before any message. Demo/fictional patients can only receive real messages if their number is on the hospital's test-phone list. Templates must be approved before live use. |
| **Demo** | Demo clinic with its own adjustable clock (real hospitals always use real time). One-click steps for the Mr. Ravi story; history for the report is played through the real engine. |

## 3. Database

PostgreSQL 16, migrations in `backend/alembic/versions`:

- `0001_initial_schema` — 23 tables: `hospitals`, `users`, `roles`, `permissions`, `role_permissions`,
  `password_reset_tokens`, `system_settings`, `audit_logs`, `doctors`, `doctor_availability`, `patients`,
  `patient_consents`, `appointments`, `follow_ups`, `contact_logs`, `message_templates`, `reminder_schedules`,
  `whatsapp_messages`, `message_events` (delivery log), `webhook_events` (inbound log), `whatsapp_configs`,
  `monthly_reports`, plus `alembic_version`.
- `0002_seed_roles_permissions` — 3 roles, 21 permissions.

Key constraints: UUID keys, `created_at/updated_at` everywhere, soft delete on hospitals/users/doctors/patients,
`uq_appointments_active_slot` (no double booking), `uq_patients_identity` (hospital + phone + normalised name, so
family members sharing a phone stay separate), unique reminder `idempotency_key`, unique WhatsApp message id,
unique webhook `dedupe_key`, check constraints on every status column. No medical data is stored.

## 4. API (70 endpoints)

Interactive docs at `/api/docs` outside production.

```
Auth        POST /api/auth/login · logout · logout-all · forgot-password · reset-password · change-password   GET /api/auth/me
Public      GET  /api/public/hospitals/{slug} · /dates · /slots      POST /api/public/hospitals/{slug}/appointments
Appts       GET/POST /api/appointments   GET /api/appointments/slots   GET /api/appointments/{id}
            POST /api/appointments/{id}/status · /reschedule
Follow-ups  GET/POST /api/followups   GET /api/followups/{id}   POST /{id}/reschedule · /status · /contacts
Patients    GET /api/patients   GET/PATCH /api/patients/{id}
Dashboard   GET /api/dashboard
Reports     GET /api/reports/monthly   POST /api/reports/monthly/{month}/save   GET …/{month}/export.csv
Hospital    GET/PATCH /api/hospital   GET /api/audit-logs
Doctors     GET/POST /api/doctors   PATCH/DELETE /api/doctors/{id}   PUT /api/doctors/{id}/availability
Staff       GET/POST /api/staff   PATCH /api/staff/{id}   POST /api/staff/{id}/password
WhatsApp    GET/PUT /api/whatsapp/config   POST /api/whatsapp/config/verify   POST /api/whatsapp/test-message
            GET /api/whatsapp/templates   PUT /api/whatsapp/templates/{id}   POST …/{id}/submit · /sync
            GET /api/whatsapp/messages · /reminders   POST /api/whatsapp/reminders/{id}/retry
Webhook     GET/POST /api/webhooks/whatsapp
System      GET/POST /api/system/hospitals   PATCH /api/system/hospitals/{id}   GET …/{id}/admins
            GET /api/system/status   GET/PUT /api/system/settings
Demo        GET /api/demo   POST /api/demo/clock · /clock/real · /run-engine · /step · /reset · /simulate-reply
Health      GET /api/health
```

Sessions use an httpOnly, SameSite=Lax cookie. State-changing requests with a cookie must send
`X-Requested-With: tectha` (CSRF guard); API clients may use `Authorization: Bearer`.

## 5. Screens (frontend routes)

| Screen | Route | Who |
|---|---|---|
| Login · Forgot password · Reset password | `/login` `/forgot-password` `/reset-password` | everyone |
| System admin dashboard | `/system` | system admin |
| Hospital admin dashboard / Staff dashboard | `/dashboard` (admin sees the month headline + WhatsApp status) | hospital |
| Appointment management | `/appointments`, `/appointments/[id]` | hospital |
| Public booking page | `/book/[slug]` | patients |
| Patient details | `/patients`, `/patients/[id]` | hospital |
| Follow-up management | `/follow-ups` | hospital |
| Monthly reports | `/reports` | admin |
| Hospital settings (profile, doctors & schedules, activity log) | `/settings` | admin |
| Staff management | `/staff` | admin |
| WhatsApp configuration | `/whatsapp` | admin |
| Message template management | `/templates` | admin |
| WhatsApp message log & reminder queue | `/messages` | hospital |
| Demo controls | `/demo` | admin of a demo clinic |
| Account (change password, sign out everywhere) | `/account` | everyone |

## 6. Run locally

Requirements: Python 3.12+, Node 22, PostgreSQL 16.

```bash
# database
createuser -P tectha            # password e.g. tectha_dev_pw
createdb -O tectha tectha && createdb -O tectha tectha_test

# backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://tectha:tectha_dev_pw@localhost:5432/tectha
export PUBLIC_BASE_URL=http://localhost:3000
alembic upgrade head
python -m app.cli create-system-admin --email you@tectha.in --name "Your Name"   # prints a password
DEMO_PASSWORD='ChooseAPassw0rd' python -m app.cli seed-demo                     # demo clinic + 2 users
uvicorn app.main:app --reload --port 8000        # terminal 1
python -m app.worker                             # terminal 2 (sends due reminders every 60 s)

# frontend
cd ../frontend
npm install
API_ORIGIN=http://localhost:8000 npm run dev     # http://localhost:3000
```

Demo logins after `seed-demo`: `admin@demo.tectha.in` and `staff@demo.tectha.in`.

### Tests

```bash
cd backend && pytest                    # uses TEST_DATABASE_URL (default: …/tectha_test); drops and re-migrates it
cd frontend && npm run typecheck && npm run build
# browser end-to-end (needs API + `npm start` running, the demo seeded and Chrome installed)
DEMO_PASSWORD='ChooseAPassw0rd' CHROME_PATH=/usr/bin/google-chrome npm run e2e
```

## 7. Deploy

One VM (2 vCPU / 4 GB is plenty for the pilot), Docker and a domain pointing at it.

```bash
git clone … /opt/tectha && cd /opt/tectha
cp .env.example .env            # fill every secret: POSTGRES_PASSWORD, JWT_SECRET, ENCRYPTION_KEY,
                                # PUBLIC_BASE_URL, DOMAIN, WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN
docker compose --profile proxy up -d --build      # db, api (runs migrations), worker, web, Caddy with HTTPS
docker compose exec api python -m app.cli create-system-admin --email you@tectha.in --name "Your Name"
docker compose logs -f worker                      # should log a pass every minute
```

- **HTTPS**: Caddy obtains certificates for `DOMAIN` automatically. Keep `COOKIE_SECURE=true`.
- **Backups**: `deploy/backup.sh` (pg_dump, gzip, 14-day retention) from cron; copy `backups/` off the
  server. Restore instructions are in the script. Test a restore before the pilot starts.
- **Upgrades**: `git pull && docker compose up -d --build` (migrations run on API start).
- **Scaling**: more `worker` replicas are safe (row-level claiming). The in-process rate limiter is per
  API process — add proxy/CDN rate limiting if you run several API replicas.

## 8. Turning on real WhatsApp messages

What exists today: the Cloud API client, template submission and status sync, signed webhook,
delivery tracking, retries, and test mode. What's needed from outside:

1. **Meta Business account** for Tec Tha (business verification in Meta Business Manager).
2. **Meta app** (type *Business*) with the WhatsApp product. Put its **App secret** in `WHATSAPP_APP_SECRET`.
3. **Webhook**: in the app's WhatsApp → Configuration, callback URL `https://<DOMAIN>/api/webhooks/whatsapp`,
   verify token = `WHATSAPP_VERIFY_TOKEN`, subscribe to the **messages** field.
4. **Per hospital**: a WhatsApp Business Account and a phone number not used in the WhatsApp app
   (hospital's own number via Embedded Signup, or one added under Tec Tha's WABA), a display name approved by Meta,
   and a **permanent System User access token** with `whatsapp_business_messaging` and
   `whatsapp_business_management`. Enter phone number ID, WABA ID and token on **WhatsApp setup**, press
   **Check connection**.
5. **Templates**: on **Message templates**, review the English and Tamil wording (marketing team), then
   **Submit for approval**. They're category *Utility* with two quick-reply buttons. Approval usually takes
   minutes to a day; **Check approval status** syncs it.
6. Add a test phone, **Send test message**, then switch the hospital to **Live**.
7. Payment method on the WABA for per-message charges (utility templates are billed per delivered message;
   replies inside the 24-hour window after a patient taps a button are free-form and not templated).

Until then, every hospital runs in **test mode**: reminders are generated on schedule and shown as
"Test mode — not sent", never as delivered.

## 9. Demo script (from the brief)

Sign in as the demo admin → **Demo controls**. The demo week starts Monday 16 Nov 2026 (change it there).

1. Ask: *"Out of 10 follow-up patients, how many come back?"*
2. **Step 1** sets the clock to Monday 10:00 and opens the booking page — book live as **Mr. Ravi**
   (use the owner's own number if you'll show a real message).
3. **Step 2** (Tuesday 18:05) sends the reminder; **Step 3** taps Confirm (or, in live mode, the owner taps it).
4. **Step 4** (Wednesday): open Ravi's appointment, mark **Visited**, choose **2 weeks** → 2 December.
   Reminders appear for 25 and 29 November.
5. **Steps 5–6** send them. **Step 7** (30 Nov): Ravi is **red** on the dashboard under "Call these patients".
6. Open **Monthly report**: "We brought back 3 patients this month" from the replayed history.
7. Offer the free 2-week pilot. **Reset demo** before the next visit.

For a real message to the owner's phone: add it under WhatsApp setup → Test phones, set the demo clinic to
Live (needs approved templates), and book Ravi with that number. Other demo patients are fictional and are
never messaged.

## 10. Status

| | |
|---|---|
| **Implemented and tested** | All five modules, roles and tenant isolation, auth (lockout, reset, sessions), consent, audit log, test-mode messaging, Cloud API request/response handling, webhooks, retries, idempotency, monthly report attribution, demo scenario. 66 backend tests + 20-check browser E2E pass. |
| **Requires external credentials** | Real WhatsApp sending/receiving (Meta app, WABA, approved templates — §8). Password-reset email (SMTP). |
| **Not verified in the build environment** | Docker image builds (Docker Hub rate-limited the sandbox; `docker compose config` validates), HTTPS via Caddy, a live call to graph.facebook.com (tested against recorded API response shapes). |

### Known limitations

- Doctor schedules are weekly; there is no holiday/leave calendar yet (pause a doctor's bookings instead).
- One WhatsApp number per hospital; one Meta app for the platform.
- Session replies (thank-you, booking link) are only sent right after a button tap, inside WhatsApp's 24-hour window.
- Rate limiting is per API process.
- The report's "brought back" needs delivery receipts (webhook) or a button tap; if webhooks are misconfigured,
  live reminders stay at "Accepted by WhatsApp" and are, correctly, not counted.
- Tamil message wording is a first draft for the marketing team to review before submitting to Meta.
#   t e c t h a _ h e a l t h  
 