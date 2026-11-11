"""Patients, public booking, double-booking prevention, status changes and rescheduling."""
from datetime import date, datetime, time

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Appointment, Patient, PatientConsent, ReminderSchedule
from app.services import patients
from tests.conftest import IST, at

WED = date(2026, 11, 18)


def book(c, slug, doc, when, name="Ravi Kumar", phone="9876543210", consent=True, lang="en"):
    return c.post(f"/api/public/hospitals/{slug}/appointments", json={
        "doctor_id": str(doc.id), "start_at": when, "full_name": name, "phone": phone,
        "language": lang, "whatsapp_consent": consent})


def test_patient_dedupe_and_phone_normalisation(hosp, db):
    h = hosp[0]
    p1 = patients.find_or_create_patient(db, h, full_name="Mr. Ravi Kumar", phone="98765 43210")
    p2 = patients.find_or_create_patient(db, h, full_name="ravi  kumar", phone="+91-9876543210")
    p3 = patients.find_or_create_patient(db, h, full_name="Meena Kumar", phone="9876543210")  # family, same phone
    db.commit()
    assert p1.id == p2.id
    assert p3.id != p1.id
    assert p1.phone_e164 == "+919876543210"
    assert db.query(Patient).count() == 2


def test_invalid_phone_rejected(hosp, api, frozen):
    h, _, _, docs = hosp
    r = book(api(), "alpha", docs[0], at(WED, 10), phone="123456")
    assert r.status_code == 400 and "valid mobile" in r.json()["detail"]


def test_public_profile_and_slots_expose_no_patient_data(hosp, api, frozen):
    h, _, _, docs = hosp
    c = api()
    assert book(c, "alpha", docs[0], at(WED, 10)).status_code == 201
    prof = c.get("/api/public/hospitals/alpha").json()
    assert prof["today"] == "2026-11-16" and len(prof["doctors"]) == 1
    slots = c.get("/api/public/hospitals/alpha/slots", params={"doctor_id": str(docs[0].id), "date": WED.isoformat()}).json()
    taken = [s for s in slots["slots"] if not s["available"]]
    assert [s["time"] for s in taken] == ["10:00"]
    assert set(slots["slots"][0]) == {"start_at", "time", "available"}
    assert "Ravi" not in str(slots) and "98765" not in str(slots)
    assert c.get("/api/public/hospitals/does-not-exist").status_code == 404


def test_public_booking_creates_appointment_and_consent(hosp, api, db, frozen):
    h, _, _, docs = hosp
    r = book(api(), "alpha", docs[0], at(WED, 10, 30))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["reference"].startswith("TT-") and len(body["reference"]) == 9
    assert (body["date"], body["time"], body["whatsapp_reminder"]) == ("2026-11-18", "10:30", True)
    appt = db.query(Appointment).one()
    assert appt.status == "booked" and appt.source == "online"
    consent = db.query(PatientConsent).one()
    assert consent.granted and consent.source == "booking_form" and consent.consent_text_version


def test_slot_must_belong_to_schedule_and_be_in_future(hosp, api, frozen):
    h, _, _, docs = hosp
    c = api()
    assert book(c, "alpha", docs[0], at(WED, 15)).status_code == 400  # afternoon not in schedule
    assert book(c, "alpha", docs[0], at(WED, 10, 7)).status_code == 400  # not on a slot boundary
    assert book(c, "alpha", docs[0], at(date(2026, 11, 22), 10)).status_code == 400  # Sunday: no schedule
    assert book(c, "alpha", docs[0], at(date(2026, 11, 13), 10)).status_code == 400  # past
    assert book(c, "alpha", docs[0], at(date(2026, 11, 16), 9, 15)).status_code == 409  # within 30 min lead time
    assert book(c, "alpha", docs[0], at(date(2027, 1, 20), 10)).status_code == 400  # beyond horizon


def test_double_booking_prevented(hosp, api, frozen):
    h, _, _, docs = hosp
    c = api()
    assert book(c, "alpha", docs[0], at(WED, 11)).status_code == 201
    r = book(c, "alpha", docs[0], at(WED, 11), name="Someone Else", phone="9876500000")
    assert r.status_code == 409 and r.json()["code"] == "slot_taken"
    # Same patient, same doctor, same day, different time: also blocked
    r = book(c, "alpha", docs[0], at(WED, 12))
    assert r.status_code == 409 and r.json()["code"] == "duplicate_booking"


def test_database_unique_index_blocks_race(hosp, db, frozen):
    """Even if two requests pass the availability check at the same moment, the partial unique index wins."""
    h, _, _, docs = hosp
    p1 = patients.find_or_create_patient(db, h, full_name="A One", phone="9876500001")
    p2 = patients.find_or_create_patient(db, h, full_name="B Two", phone="9876500002")
    start = datetime.combine(WED, time(9, 0), tzinfo=IST)
    end = datetime.combine(WED, time(9, 15), tzinfo=IST)
    db.add(Appointment(hospital_id=h.id, reference="TT-AAAAAA", patient_id=p1.id, doctor_id=docs[0].id,
                       start_at=start, end_at=end))
    db.commit()
    db.add(Appointment(hospital_id=h.id, reference="TT-BBBBBB", patient_id=p2.id, doctor_id=docs[0].id,
                       start_at=start, end_at=end))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    # A cancelled booking frees the slot
    first = db.query(Appointment).filter_by(reference="TT-AAAAAA").one()
    first.status = "cancelled"
    db.add(Appointment(hospital_id=h.id, reference="TT-CCCCCC", patient_id=p2.id, doctor_id=docs[0].id,
                       start_at=start, end_at=end))
    db.commit()


def test_honeypot_and_rate_limit(hosp, api, frozen):
    h, _, _, docs = hosp
    c = api()
    r = c.post("/api/public/hospitals/alpha/appointments", json={
        "doctor_id": str(docs[0].id), "start_at": at(WED, 9), "full_name": "Bot", "phone": "9876543210",
        "website": "http://spam"})
    assert r.status_code == 400
    codes = [book(c, "alpha", docs[0], at(WED, 9 + i // 4, (i % 4) * 15), name=f"P{i} Name",
                  phone=f"98765000{i:02d}").status_code for i in range(11)]
    assert codes[-1] == 429


def test_staff_status_changes_and_rules(hosp, api, db, frozen):
    h, _, _, docs = hosp
    c = api().login("staff@alpha.clinic.in")
    appt = c.post("/api/appointments", json={"doctor_id": str(docs[0].id), "start_at": at(WED, 10),
                                            "full_name": "Ravi Kumar", "phone": "9876543210",
                                            "whatsapp_consent": True}).json()
    assert c.post(f"/api/appointments/{appt['id']}/status", json={"status": "completed"}).status_code == 400  # future
    r = c.post(f"/api/appointments/{appt['id']}/status", json={"status": "confirmed"})
    assert r.json()["status"] == "confirmed" and r.json()["confirmed_via"] == "staff"
    frozen.set(datetime(2026, 11, 18, 11, 0))
    assert c.post(f"/api/appointments/{appt['id']}/status", json={"status": "completed"}).json()["status"] == "completed"
    r = c.post(f"/api/appointments/{appt['id']}/status", json={"status": "cancelled"})
    assert r.status_code == 400  # completed is final
    reminder = db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one()
    assert reminder.status in ("cancelled", "pending", "simulated")


def test_cancel_cancels_reminder(hosp, api, db, frozen):
    h, _, _, docs = hosp
    c = api().login("staff@alpha.clinic.in")
    appt = c.post("/api/appointments", json={"doctor_id": str(docs[0].id), "start_at": at(WED, 10),
                                            "full_name": "Ravi Kumar", "phone": "9876543210"}).json()
    assert db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one().status == "pending"
    c.post(f"/api/appointments/{appt['id']}/status", json={"status": "cancelled", "reason": "Patient called"})
    db.expire_all()
    assert db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one().status == "cancelled"


def test_staff_reschedule_moves_reminder_and_frees_slot(hosp, api, db, frozen):
    h, _, _, docs = hosp
    c = api().login("staff@alpha.clinic.in")
    appt = c.post("/api/appointments", json={"doctor_id": str(docs[0].id), "start_at": at(WED, 10),
                                            "full_name": "Ravi Kumar", "phone": "9876543210"}).json()
    c.post(f"/api/appointments/{appt['id']}/status", json={"status": "confirmed"})
    r = c.post(f"/api/appointments/{appt['id']}/reschedule",
               json={"doctor_id": str(docs[0].id), "start_at": at(date(2026, 11, 20), 11)})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "booked" and r.json()["reschedule_count"] == 1
    rems = db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).order_by(ReminderSchedule.created_at).all()
    assert [x.status for x in rems] == ["cancelled", "pending"]
    assert rems[1].due_at == datetime(2026, 11, 19, 18, 0, tzinfo=IST)
    other = book(api(), "alpha", docs[0], at(WED, 10), name="New Person", phone="9876500009")
    assert other.status_code == 201  # old slot is free again
    clash = c.post(f"/api/appointments/{appt['id']}/reschedule",
                   json={"doctor_id": str(docs[0].id), "start_at": at(WED, 10)})
    assert clash.status_code == 409


def test_online_rebooking_supersedes_reschedule_request(hosp, api, db, frozen):
    h, _, _, docs = hosp
    c = api()
    assert book(c, "alpha", docs[0], at(WED, 10)).status_code == 201
    old = db.query(Appointment).one()
    old.status = "reschedule_requested"
    db.commit()
    assert book(c, "alpha", docs[0], at(date(2026, 11, 19), 10)).status_code == 201
    db.expire_all()
    old = db.get(Appointment, old.id)
    assert old.status == "rescheduled" and old.rescheduled_to_id is not None
