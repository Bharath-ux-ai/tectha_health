"""Monthly report calculations and the full demo scenario (Mr. Ravi)."""
from datetime import date, datetime

from app.models import Hospital, Patient
from app.services import demo, engine
from app.services.hospitals import create_hospital, create_user
from tests.conftest import PASSWORD, at, go_live, signed, wh_envelope

WED = date(2026, 11, 18)


def run(db, h):
    db.expire_all()
    return engine.run_hospital(db, db.merge(h))


def visit_and_complete(c, frozen, doc, day, hh, name, phone):
    frozen.set(datetime(day.year, day.month, day.day, 8, 0))
    a = c.post("/api/appointments", json={"doctor_id": str(doc.id), "start_at": at(day, hh), "full_name": name,
                                         "phone": phone, "whatsapp_consent": True}).json()
    frozen.set(datetime(day.year, day.month, day.day, hh, 30))
    assert c.post(f"/api/appointments/{a['id']}/status", json={"status": "completed"}).status_code == 200
    return a


def test_monthly_report_counts_only_verifiable_returns(hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h)
    c = api().login("admin@alpha.clinic.in")
    patients = [("Anand A", "9876500001"), ("Bala B", "9876500002"), ("Chitra C", "9876500003"),
                ("Divya D", "9876500004")]
    fus = {}
    frozen.set(datetime(2026, 11, 2, 9, 0))
    for i, (name, phone) in enumerate(patients):
        a = c.post("/api/appointments", json={"doctor_id": str(docs[0].id), "start_at": at(date(2026, 11, 2), 10, i * 15),
                                             "full_name": name, "phone": phone, "whatsapp_consent": i != 3}).json()
        fus[name] = c.post("/api/followups", json={"patient_id": a["patient"]["id"], "due_date": "2026-11-20"}).json()
    frozen.set(datetime(2026, 11, 13, 10, 5))
    run(db, h)  # 7-day reminders: 3 accepted by the API, Divya has no consent
    # Only Anand's reminder gets a delivery receipt; Bala's stays "accepted" (no receipt) — not proof of delivery.
    raw, headers = signed(wh_envelope("1111", statuses=[{"id": "wamid.TEST1", "status": "delivered", "timestamp": "1"}]))
    api().post("/api/webhooks/whatsapp", content=raw, headers=headers)
    # Chitra taps a button (proof she received it) even without a delivery receipt
    from app.models import WhatsAppMessage
    chitra_msg = db.query(WhatsAppMessage).filter(WhatsAppMessage.wa_message_id == "wamid.TEST3").one()
    raw, headers = signed(wh_envelope("1111", messages=[{
        "from": chitra_msg.phone_e164.lstrip("+"), "id": "wamid.IN9", "timestamp": "1", "type": "button",
        "button": {"payload": f"TT1:R:{chitra_msg.payload_ref}", "text": "Reschedule"}}]))
    api().post("/api/webhooks/whatsapp", content=raw, headers=headers)
    # Everyone comes back on 20 Nov
    for i, (name, phone) in enumerate(patients):
        visit_and_complete(c, frozen, docs[0], date(2026, 11, 20), 9 + i, name, phone)
    rep = c.get("/api/reports/monthly", params={"month": "2026-11"}).json()
    assert rep["brought_back"] == 2  # Anand (delivered) + Chitra (replied); Bala unproven, Divya no reminder
    assert rep["summary"] == "We brought back 2 patients this month."
    assert rep["follow_ups"]["completed"] == 4
    assert rep["follow_ups"]["returned_after_reminder"] == 2
    assert rep["follow_ups"]["returned_without_delivered_reminder"] == 2
    assert rep["follow_ups"]["due_this_month"] == 4 and rep["follow_ups"]["retention_rate"] == 100.0
    assert rep["appointments"]["completed"] == 4 and rep["appointments"]["total"] == 8
    assert rep["patients"] == {"seen": 4, "returning": 0, "new": 4}
    assert rep["includes_simulated_messages"] is False
    assert {r["patient"] for r in rep["brought_back_list"]} == {"Anand A", "Chitra C"}
    csv = c.get("/api/reports/monthly/2026-11/export.csv")
    assert csv.status_code == 200 and "We brought back 2 patients this month." in csv.text
    assert "attachment" in csv.headers["content-disposition"]
    saved = c.post("/api/reports/monthly/2026-11/save")
    assert saved.status_code == 200
    assert c.get("/api/reports/monthly", params={"month": "2026-11"}).json()["saved_at"]


def test_report_month_boundaries_use_hospital_timezone(hosp, api, frozen):
    h, _, _, docs = hosp
    c = api().login("admin@alpha.clinic.in")
    frozen.set(datetime(2026, 11, 30, 8, 0))
    # 1 Dec 09:00 IST is still 30 Nov in UTC for much of the world, but belongs to December here.
    c.post("/api/appointments", json={"doctor_id": str(docs[0].id), "start_at": at(date(2026, 12, 1), 9),
                                      "full_name": "Early Bird", "phone": "9876500020"})
    c.post("/api/appointments", json={"doctor_id": str(docs[0].id), "start_at": at(date(2026, 11, 30), 12, 45),
                                      "full_name": "Last Slot", "phone": "9876500021"})
    nov = c.get("/api/reports/monthly", params={"month": "2026-11"}).json()
    dec = c.get("/api/reports/monthly", params={"month": "2026-12"}).json()
    assert nov["appointments"]["total"] == 1 and dec["appointments"]["total"] == 1
    assert c.get("/api/reports/monthly", params={"month": "nonsense"}).status_code == 400


def test_full_demo_scenario_mr_ravi(api, db):
    h, _ = create_hospital(db, name="TEC THA Demo Clinic", slug=demo.DEMO_SLUG, address=None, phone="+914224000000",
                           is_demo=True, admin_email="admin@demo.clinic.in", admin_name="Demo", admin_password=PASSWORD)
    create_user(db, email="staff@demo.clinic.in", full_name="Desk", password=PASSWORD, role_code="staff", hospital_id=h.id)
    db.commit()
    c = api().login("admin@demo.clinic.in")
    st = c.post("/api/demo/reset", json={"start_monday": "2026-11-16"}).json()
    assert st["local_now"].startswith("Mon 16 Nov 2026, 09:30")
    assert st["scenario"]["follow_up"] == "2026-12-02"
    assert (st["scenario"]["reminder_7d"], st["scenario"]["reminder_3d"]) == ("2026-11-25", "2026-11-29")

    # 1. Monday: Ravi books on the public page
    c.post("/api/demo/step", json={"key": "book"})
    pub = c.get(f"/api/public/hospitals/{demo.DEMO_SLUG}").json()
    doc = pub["doctors"][0]["id"]
    slots = c.get(f"/api/public/hospitals/{demo.DEMO_SLUG}/slots", params={"doctor_id": doc, "date": "2026-11-18"}).json()
    slot = next(s for s in slots["slots"] if s["available"] and s["time"] == "10:30")
    r = c.post(f"/api/public/hospitals/{demo.DEMO_SLUG}/appointments", json={
        "doctor_id": doc, "start_at": slot["start_at"], "full_name": "Mr. Ravi", "phone": "9876543210",
        "language": "en", "whatsapp_consent": True})
    assert r.status_code == 201
    assert db.query(Patient).filter_by(name_normalized="ravi").one().is_test  # demo patients are always test patients

    # 2. Tuesday evening reminder; 3. Ravi taps Confirm
    c.post("/api/demo/step", json={"key": "reminder"})
    out = c.post("/api/demo/step", json={"key": "confirm"}).json()
    assert out["result"]["outcome"] == "appointment_confirmed"
    # 4. Wednesday visit; follow-up for 2 December
    out = c.post("/api/demo/step", json={"key": "visit"}).json()
    assert out["result"]["follow_up_date"] == "2026-12-02"
    fu_id = out["result"]["follow_up_id"]
    # 5–6. Reminders on 25 and 29 November
    c.post("/api/demo/step", json={"key": "reminder_7d"})
    c.post("/api/demo/step", json={"key": "reminder_3d"})
    fu = c.get(f"/api/followups/{fu_id}").json()
    assert {r["kind"]: r["status"] for r in fu["reminders"]} == {"followup_7d": "simulated", "followup_3d": "simulated"}
    # 7. No reply: red on the dashboard, visible to the reception staff account
    final = c.post("/api/demo/step", json={"key": "red"}).json()
    assert final["state"]["local_now"].startswith("Mon 30 Nov 2026")
    staff = api().login("staff@demo.clinic.in")
    dash = staff.get("/api/dashboard").json()
    ravi = next(a for a in dash["attention"] if a["patient"]["name"] == "Mr. Ravi")
    assert (ravi["attention"], ravi["attention_reason"]) == ("red", "no_response")
    msgs = final["state"]["ravi_messages"]
    assert [m["direction"] for m in msgs] == ["outbound", "inbound", "outbound", "outbound", "outbound"]
    assert all(m["is_simulated"] for m in msgs)
    # The report reflects the history played through the engine, labelled as including simulated messages
    rep = c.get("/api/reports/monthly", params={"month": "2026-11"}).json()
    assert rep["brought_back"] == 3 and rep["includes_simulated_messages"] is True
    assert rep["follow_ups"]["returned_without_delivered_reminder"] == 1
    # Staff can't drive the demo clock; real hospitals can't use demo controls at all
    assert staff.post("/api/demo/step", json={"key": "book"}).status_code == 403


def test_demo_controls_refused_for_real_hospitals(hosp, api):
    c = api().login("admin@alpha.clinic.in")
    r = c.post("/api/demo/clock", json={"local_datetime": "2026-12-01T10:00:00"})
    assert r.status_code == 403
    assert Hospital  # imported for clarity of the assertion's subject


def test_demo_live_mode_only_reaches_allowlisted_phone(api, db, meta):
    h, _ = create_hospital(db, name="Demo", slug="demo-live", address=None, phone=None, is_demo=True,
                           admin_email="a@demo-live.clinic.in", admin_name="A", admin_password=PASSWORD)
    db.commit()
    c = api().login("a@demo-live.clinic.in")
    c.post("/api/demo/reset", json={"start_monday": "2026-11-16"})
    go_live(db, h, allowlist=["+919876543210"])
    c.post("/api/demo/step", json={"key": "book"})
    pub = c.get("/api/public/hospitals/demo-live").json()
    doc = pub["doctors"][0]["id"]
    slots = c.get("/api/public/hospitals/demo-live/slots", params={"doctor_id": doc, "date": "2026-11-18"}).json()
    slot = next(s for s in slots["slots"] if s["available"])
    c.post("/api/public/hospitals/demo-live/appointments", json={
        "doctor_id": doc, "start_at": slot["start_at"], "full_name": "Ravi", "phone": "9876543210",
        "whatsapp_consent": True})
    c.post("/api/demo/step", json={"key": "reminder"})
    # Only the owner's allowlisted phone received a real message; fictional background patients were skipped
    assert [s["json"]["to"] for s in meta.sends] == ["919876543210"]
