"""Reminder scheduling (day-before, 7-day, 3-day), the engine, follow-up lifecycle and red flags."""
from datetime import date, datetime

from app.models import FollowUp, ReminderSchedule, WhatsAppMessage
from app.services import engine
from tests.conftest import IST, at

WED = date(2026, 11, 18)


def register(c, doc, when, name="Ravi Kumar", phone="9876543210", consent=True, lang="en"):
    r = c.post("/api/appointments", json={"doctor_id": str(doc.id), "start_at": when, "full_name": name,
                                         "phone": phone, "whatsapp_consent": consent, "language": lang})
    assert r.status_code == 201, r.text
    return r.json()


def run(db, h):
    db.expire_all()
    return engine.run_hospital(db, db.merge(h))


def test_day_before_reminder_due_at_configured_evening_time(hosp, api, db, frozen):
    h, _, _, docs = hosp
    appt = register(api().login("staff@alpha.clinic.in"), docs[0], at(WED, 10))
    r = db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one()
    assert r.kind == "appointment_day_before" and r.status == "pending"
    assert r.due_at == datetime(2026, 11, 17, 18, 0, tzinfo=IST)


def test_engine_sends_only_when_due_and_only_once(hosp, api, db, frozen):
    h, _, _, docs = hosp
    appt = register(api().login("staff@alpha.clinic.in"), docs[0], at(WED, 10))
    frozen.set(datetime(2026, 11, 17, 17, 59))
    assert run(db, h)["processed"] == 0
    frozen.set(datetime(2026, 11, 17, 18, 1))
    stats = run(db, h)
    assert stats["simulated"] == 1  # new hospitals start in test mode: nothing leaves the server
    for _ in range(3):
        assert run(db, h)["processed"] == 0
    msgs = db.query(WhatsAppMessage).all()
    assert len(msgs) == 1 and msgs[0].status == "simulated" and msgs[0].is_simulated
    assert "tomorrow" in msgs[0].body_preview and "10:00 AM" in msgs[0].body_preview
    r = db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one()
    assert r.status == "simulated"  # never reported as "sent" in test mode


def test_late_booking_reminds_immediately_and_same_day_is_skipped(hosp, api, db, frozen):
    h, _, _, docs = hosp
    c = api().login("staff@alpha.clinic.in")
    frozen.set(datetime(2026, 11, 17, 20, 0))  # after Tuesday's 18:00 reminder time
    appt = register(c, docs[0], at(WED, 10))
    r = db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one()
    assert r.status == "pending" and r.due_at == frozen.current
    frozen.set(datetime(2026, 11, 18, 9, 0))
    same_day = register(c, docs[0], at(WED, 12), name="Walk In", phone="9876500011")
    r2 = db.query(ReminderSchedule).filter_by(appointment_id=same_day["id"]).one()
    assert r2.status == "skipped" and r2.skip_reason == "same_day_booking"


def test_overdue_day_before_reminder_is_not_sent_on_the_day(hosp, api, db, frozen):
    h, _, _, docs = hosp
    appt = register(api().login("staff@alpha.clinic.in"), docs[0], at(WED, 12))
    frozen.set(datetime(2026, 11, 18, 8, 0))  # worker was down all evening
    run(db, h)
    r = db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one()
    assert r.status == "skipped" and r.skip_reason == "too_late_for_day_before"
    assert db.query(WhatsAppMessage).count() == 0


def test_no_consent_means_no_message(hosp, api, db, frozen):
    h, _, _, docs = hosp
    appt = register(api().login("staff@alpha.clinic.in"), docs[0], at(WED, 10), consent=False)
    frozen.set(datetime(2026, 11, 17, 18, 5))
    run(db, h)
    r = db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one()
    assert r.status == "skipped" and r.skip_reason == "no_whatsapp_consent"
    assert db.query(WhatsAppMessage).count() == 0


def test_tamil_patient_gets_tamil_template(hosp, api, db, frozen):
    h, _, _, docs = hosp
    register(api().login("staff@alpha.clinic.in"), docs[0], at(WED, 10), lang="ta")
    frozen.set(datetime(2026, 11, 17, 18, 5))
    run(db, h)
    m = db.query(WhatsAppMessage).one()
    assert m.language == "ta" and "நாளை" in m.body_preview and "புதன்" in m.body_preview


def test_followup_reminders_seven_and_three_days_before_across_month_boundary(hosp, api, db, frozen):
    h, _, _, docs = hosp
    c = api().login("staff@alpha.clinic.in")
    appt = register(c, docs[0], at(WED, 10))
    r = c.post("/api/followups", json={"patient_id": appt["patient"]["id"], "due_date": "2026-12-02",
                                      "source_appointment_id": appt["id"]})
    assert r.status_code == 201, r.text
    rems = {x["kind"]: x for x in r.json()["reminders"]}
    assert datetime.fromisoformat(rems["followup_7d"]["due_at"]) == datetime(2026, 11, 25, 10, 0, tzinfo=IST)
    assert datetime.fromisoformat(rems["followup_3d"]["due_at"]) == datetime(2026, 11, 29, 10, 0, tzinfo=IST)
    assert {x["status"] for x in rems.values()} == {"pending"}
    assert r.json()["doctor"]["id"] == str(docs[0].id)  # defaults to the visit's doctor


def test_followup_validation_and_duplicate_guard(hosp, api, frozen):
    h, _, _, docs = hosp
    c = api().login("staff@alpha.clinic.in")
    appt = register(c, docs[0], at(WED, 10))
    pid = appt["patient"]["id"]
    assert c.post("/api/followups", json={"patient_id": pid, "due_date": "2026-11-16"}).status_code == 400
    assert c.post("/api/followups", json={"patient_id": pid, "due_date": "2028-01-01"}).status_code == 400
    ok = c.post("/api/followups", json={"patient_id": pid, "due_date": "2026-12-02", "source_appointment_id": appt["id"]})
    assert ok.status_code == 201
    dup = c.post("/api/followups", json={"patient_id": pid, "due_date": "2026-12-09", "source_appointment_id": appt["id"]})
    assert dup.status_code == 400


def test_close_followup_skips_past_windows(hosp, api, db, frozen):
    h, _, _, docs = hosp
    c = api().login("staff@alpha.clinic.in")
    appt = register(c, docs[0], at(WED, 10))
    r = c.post("/api/followups", json={"patient_id": appt["patient"]["id"], "due_date": "2026-11-21"}).json()
    rems = {x["kind"]: x for x in r["reminders"]}
    assert rems["followup_7d"]["status"] == "skipped" and rems["followup_7d"]["skip_reason"] == "window_passed"
    assert rems["followup_3d"]["status"] == "pending"  # 18 Nov 10:00 is still ahead


def test_seven_and_three_day_reminders_sent_once_each(hosp, api, db, frozen):
    h, _, _, docs = hosp
    c = api().login("staff@alpha.clinic.in")
    appt = register(c, docs[0], at(WED, 10))
    fu = c.post("/api/followups", json={"patient_id": appt["patient"]["id"], "due_date": "2026-12-02"}).json()
    frozen.set(datetime(2026, 11, 25, 9, 59))
    run(db, h)
    assert db.query(WhatsAppMessage).join(ReminderSchedule).filter(ReminderSchedule.follow_up_id == fu["id"]).count() == 0
    frozen.set(datetime(2026, 11, 25, 10, 1))
    run(db, h)
    run(db, h)
    frozen.set(datetime(2026, 11, 29, 10, 1))
    run(db, h)
    run(db, h)
    msgs = db.query(WhatsAppMessage).join(ReminderSchedule).filter(ReminderSchedule.follow_up_id == fu["id"]).all()
    assert sorted(m.reminder_id for m in msgs) == sorted({m.reminder_id for m in msgs}) and len(msgs) == 2
    assert all("2 Dec" in m.body_preview for m in msgs)


def test_late_engine_sends_only_the_three_day_reminder(hosp, api, db, frozen):
    h, _, _, docs = hosp
    c = api().login("staff@alpha.clinic.in")
    appt = register(c, docs[0], at(WED, 10))
    fu = c.post("/api/followups", json={"patient_id": appt["patient"]["id"], "due_date": "2026-12-02"}).json()
    frozen.set(datetime(2026, 11, 29, 11, 0))  # worker was down from 25 Nov to 29 Nov
    run(db, h)
    rems = {r.kind: r for r in db.query(ReminderSchedule).filter_by(follow_up_id=fu["id"])}
    assert rems["followup_7d"].status == "skipped" and rems["followup_7d"].skip_reason == "superseded_by_3_day"
    assert rems["followup_3d"].status == "simulated"


def test_reschedule_followup_replaces_reminders_without_duplicates(hosp, api, db, frozen):
    h, _, _, docs = hosp
    c = api().login("staff@alpha.clinic.in")
    appt = register(c, docs[0], at(WED, 10))
    fu = c.post("/api/followups", json={"patient_id": appt["patient"]["id"], "due_date": "2026-12-02"}).json()
    c.post(f"/api/followups/{fu['id']}/reschedule", json={"due_date": "2026-12-09"})
    back = c.post(f"/api/followups/{fu['id']}/reschedule", json={"due_date": "2026-12-02"}).json()
    rows = db.query(ReminderSchedule).filter_by(follow_up_id=fu["id"]).all()
    assert len(rows) == 4  # two per distinct date, re-activated rather than duplicated
    active = [r for r in back["reminders"] if r["status"] == "pending"]
    assert len(active) == 2 and back["reschedule_count"] == 2


def test_confirmed_followup_gets_no_further_reminders(hosp, api, db, frozen):
    h, _, _, docs = hosp
    c = api().login("staff@alpha.clinic.in")
    appt = register(c, docs[0], at(WED, 10))
    fu = c.post("/api/followups", json={"patient_id": appt["patient"]["id"], "due_date": "2026-12-02"}).json()
    c.post(f"/api/followups/{fu['id']}/status", json={"status": "confirmed"})
    frozen.set(datetime(2026, 11, 29, 10, 5))
    run(db, h)
    assert db.query(WhatsAppMessage).join(ReminderSchedule).filter(ReminderSchedule.follow_up_id == fu["id"]).count() == 0


def test_unanswered_followup_turns_red_then_missed(hosp, api, db, frozen):
    h, _, _, docs = hosp
    c = api().login("staff@alpha.clinic.in")
    appt = register(c, docs[0], at(WED, 10))
    fu = c.post("/api/followups", json={"patient_id": appt["patient"]["id"], "due_date": "2026-12-02"}).json()
    frozen.set(datetime(2026, 11, 29, 12, 0))
    run(db, h)
    item = c.get(f"/api/followups/{fu['id']}").json()
    assert item["attention"] is None  # 3-day reminder just went out; give him a day
    frozen.set(datetime(2026, 11, 30, 9, 0))
    d = c.get("/api/dashboard").json()
    red = [a for a in d["attention"] if a["id"] == fu["id"]][0]
    assert (red["attention"], red["attention_reason"]) == ("red", "no_response")
    c.post(f"/api/followups/{fu['id']}/contacts", json={"method": "phone", "outcome": "no_answer"})
    frozen.set(datetime(2026, 12, 3, 8, 0))
    run(db, h)
    db.expire_all()
    assert db.get(FollowUp, fu["id"]).status == "missed"
    d = c.get("/api/followups", params={"view": "attention"}).json()["items"]
    assert d[0]["attention_reason"] == "missed" and d[0]["last_contact"]["outcome"] == "no_answer"


def test_completing_a_visit_closes_the_followup(hosp, api, db, frozen):
    h, _, _, docs = hosp
    c = api().login("staff@alpha.clinic.in")
    first = register(c, docs[0], at(WED, 10))
    fu = c.post("/api/followups", json={"patient_id": first["patient"]["id"], "due_date": "2026-12-02",
                                       "source_appointment_id": first["id"]}).json()
    frozen.set(datetime(2026, 12, 1, 9, 0))
    second = register(c, docs[0], at(date(2026, 12, 2), 9, 30))
    frozen.set(datetime(2026, 12, 2, 10, 0))
    c.post(f"/api/appointments/{second['id']}/status", json={"status": "completed"})
    detail = c.get(f"/api/followups/{fu['id']}").json()
    assert detail["status"] == "completed" and detail["completed_appointment_id"] == second["id"]
