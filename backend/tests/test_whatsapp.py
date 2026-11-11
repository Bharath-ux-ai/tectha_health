"""Live-mode WhatsApp: Cloud API calls, failures and retries, webhooks (signature, statuses, button replies)."""
from datetime import date, datetime

import httpx

from app.models import Appointment, FollowUp, Patient, ReminderSchedule, WebhookEvent, WhatsAppConfig, WhatsAppMessage
from app.services import engine
from app.services.whatsapp.client import parse_send_response
from tests.conftest import IST, at, go_live, signed, wh_envelope

WED = date(2026, 11, 18)


def setup_reminder(api, docs, lang="en", phone="9876543210"):
    c = api().login("staff@alpha.clinic.in")
    r = c.post("/api/appointments", json={"doctor_id": str(docs[0].id), "start_at": at(WED, 10),
                                         "full_name": "Ravi Kumar", "phone": phone, "whatsapp_consent": True,
                                         "language": lang})
    assert r.status_code == 201, r.text
    return c, r.json()


def run(db, h):
    db.expire_all()
    return engine.run_hospital(db, db.merge(h))


def tap(api, msg: WhatsAppMessage, action: str, *, from_phone=None, wamid="wamid.IN1"):
    payload = wh_envelope("1111", messages=[{
        "from": (from_phone or msg.phone_e164).lstrip("+"), "id": wamid, "timestamp": "1763390000",
        "type": "button", "context": {"from": "914224000000", "id": msg.wa_message_id},
        "button": {"payload": f"TT1:{action}:{msg.payload_ref}", "text": "Confirm" if action == "C" else "Reschedule"}}])
    raw, headers = signed(payload)
    return api().post("/api/webhooks/whatsapp", content=raw, headers=headers)


def test_live_send_builds_official_template_request(hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h)
    setup_reminder(api, docs)
    frozen.set(datetime(2026, 11, 17, 18, 1))
    assert run(db, h)["sent"] == 1
    req = meta.sends[0]
    assert req["url"] == "https://graph.facebook.com/v23.0/1111/messages"
    body = req["json"]
    assert body["messaging_product"] == "whatsapp" and body["to"] == "919876543210" and body["type"] == "template"
    assert body["template"]["name"] == "tt_appointment_reminder" and body["template"]["language"]["code"] == "en"
    comps = body["template"]["components"]
    assert [p["text"] for p in comps[0]["parameters"]] == ["Ravi Kumar", "Hospital alpha", "Dr. Test 1", "Wed, 18 Nov",
                                                          "10:00 AM"]
    assert [c["sub_type"] for c in comps[1:]] == ["quick_reply", "quick_reply"]
    msg = db.query(WhatsAppMessage).one()
    assert msg.status == "accepted" and msg.wa_message_id == "wamid.TEST1" and not msg.is_simulated
    assert comps[1]["parameters"][0]["payload"] == f"TT1:C:{msg.payload_ref}"


def test_transient_error_retries_with_backoff_then_succeeds(hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h)
    _, appt = setup_reminder(api, docs)
    meta.responses = [(500, {"error": {"message": "Something went wrong", "code": 131000}})]
    frozen.set(datetime(2026, 11, 17, 18, 1))
    assert run(db, h)["retrying"] == 1
    r = db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one()
    assert r.status == "pending" and r.attempts == 1
    assert r.next_attempt_at == datetime(2026, 11, 17, 18, 6, tzinfo=IST)
    frozen.set(datetime(2026, 11, 17, 18, 4))
    assert run(db, h)["processed"] == 0  # not before the backoff
    frozen.set(datetime(2026, 11, 17, 18, 7))
    assert run(db, h)["sent"] == 1
    msgs = db.query(WhatsAppMessage).order_by(WhatsAppMessage.attempt_no).all()
    assert [(m.attempt_no, m.status) for m in msgs] == [(1, "failed"), (2, "accepted")]


def test_retries_stop_after_max_attempts(hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h)
    _, appt = setup_reminder(api, docs)
    meta.responses = [(503, {"error": {"message": "unavailable", "code": 131016}})] * 3
    frozen.set(datetime(2026, 11, 17, 18, 1))
    for minutes in (0, 6, 40):
        frozen.set(datetime(2026, 11, 17, 18, 1 + minutes))
        run(db, h)
    r = db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one()
    assert r.status == "failed" and r.attempts == 3 and len(meta.sends) == 3


def test_permanent_error_fails_without_retry(hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h)
    _, appt = setup_reminder(api, docs)
    meta.responses = [(400, {"error": {"message": "Message undeliverable", "code": 131026,
                                       "error_data": {"details": "Receiver is incapable of receiving this message"}}})]
    frozen.set(datetime(2026, 11, 17, 18, 1))
    assert run(db, h)["failed"] == 1
    r = db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one()
    assert r.status == "failed" and "131026" in r.last_error
    frozen.set(datetime(2026, 11, 17, 19, 0))
    run(db, h)
    assert len(meta.sends) == 1


def test_ambiguous_timeout_is_not_retried_automatically(hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h)
    _, appt = setup_reminder(api, docs)
    meta.responses = [httpx.ReadTimeout("read timed out")]
    frozen.set(datetime(2026, 11, 17, 18, 1))
    run(db, h)
    r = db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one()
    assert r.status == "failed" and "can't tell" in r.last_error
    assert db.query(WhatsAppMessage).one().status == "unknown"
    # Connection refused before the request left: safe to retry automatically
    assert parse_send_response(200, {"messages": []}).ambiguous


def test_manual_retry_of_failed_reminder(hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h)
    c, appt = setup_reminder(api, docs)
    meta.responses = [(400, {"error": {"message": "Invalid parameter", "code": 100}})]
    frozen.set(datetime(2026, 11, 17, 18, 1))
    run(db, h)
    rid = db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one().id
    r = c.post(f"/api/whatsapp/reminders/{rid}/retry")
    assert r.status_code == 200 and r.json()["result"] == "sent"
    again = c.post(f"/api/whatsapp/reminders/{rid}/retry")
    assert again.status_code == 400  # already sent: no duplicate
    assert len(meta.sends) == 2


def test_auth_error_flags_configuration(hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h)
    setup_reminder(api, docs)
    meta.responses = [(401, {"error": {"message": "Error validating access token", "code": 190}})]
    frozen.set(datetime(2026, 11, 17, 18, 1))
    run(db, h)
    db.expire_all()
    assert "credentials" in db.get(WhatsAppConfig, h.id).last_error


def test_unapproved_template_and_test_patients_never_hit_the_api(hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h, approve=False)
    _, appt = setup_reminder(api, docs)
    frozen.set(datetime(2026, 11, 17, 18, 1))
    run(db, h)
    r = db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one()
    assert r.status == "failed" and "not approved" in r.last_error
    assert meta.sends == []

    go_live(db, h, approve=True)
    p = db.query(Patient).one()
    p.is_test = True  # fictional patient
    r.status, r.attempts = "pending", 0
    db.commit()
    run(db, h)
    db.expire_all()
    r = db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one()
    assert r.status == "skipped" and r.skip_reason == "test_patient_not_allowlisted"
    assert meta.sends == []


def test_global_kill_switch_pauses_live_sending(hosp, api, db, frozen, meta):
    from app.models import SystemSetting
    h, _, _, docs = hosp
    go_live(db, h)
    _, appt = setup_reminder(api, docs)
    db.add(SystemSetting(key="live_messaging_enabled", value={"enabled": False}))
    db.commit()
    frozen.set(datetime(2026, 11, 17, 18, 1))
    run(db, h)
    r = db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one()
    assert r.status == "pending" and r.attempts == 0 and meta.sends == []


def test_webhook_verification_handshake(api):
    c = api()
    ok = c.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "test-verify-token",
                                                 "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"
    bad = c.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "nope",
                                                  "hub.challenge": "12345"})
    assert bad.status_code == 403


def test_webhook_rejects_bad_signature(hosp, api):
    raw, headers = signed(wh_envelope("1111", statuses=[]))
    headers["X-Hub-Signature-256"] = "sha256=" + "0" * 64
    assert api().post("/api/webhooks/whatsapp", content=raw, headers=headers).status_code == 401
    raw, headers = signed(wh_envelope("1111", statuses=[]))
    headers.pop("X-Hub-Signature-256")
    assert api().post("/api/webhooks/whatsapp", content=raw, headers=headers).status_code == 401


def test_delivery_statuses_tracked_and_deduplicated(hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h)
    setup_reminder(api, docs)
    frozen.set(datetime(2026, 11, 17, 18, 1))
    run(db, h)
    c = api()
    for st in ("sent", "delivered", "read", "delivered"):
        raw, headers = signed(wh_envelope("1111", statuses=[
            {"id": "wamid.TEST1", "status": st, "timestamp": "1763382700", "recipient_id": "919876543210"}]))
        assert c.post("/api/webhooks/whatsapp", content=raw, headers=headers).status_code == 200
    db.expire_all()
    m = db.query(WhatsAppMessage).one()
    assert m.status == "read" and m.delivered_at and m.read_at  # never moves backwards
    assert db.query(WebhookEvent).count() == 3  # the repeated "delivered" was ignored


def test_failed_status_webhook_marks_reminder_failed(hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h)
    _, appt = setup_reminder(api, docs)
    frozen.set(datetime(2026, 11, 17, 18, 1))
    run(db, h)
    raw, headers = signed(wh_envelope("1111", statuses=[{
        "id": "wamid.TEST1", "status": "failed", "timestamp": "1763382700", "recipient_id": "919876543210",
        "errors": [{"code": 131049, "title": "This message was not delivered to maintain healthy ecosystem engagement."}]}]))
    api().post("/api/webhooks/whatsapp", content=raw, headers=headers)
    db.expire_all()
    r = db.query(ReminderSchedule).filter_by(appointment_id=appt["id"]).one()
    assert r.status == "failed" and "131049" in r.last_error
    assert db.query(WhatsAppMessage).one().status == "failed"


def test_confirm_button_confirms_appointment_and_replies(hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h)
    _, appt = setup_reminder(api, docs)
    frozen.set(datetime(2026, 11, 17, 18, 1))
    run(db, h)
    msg = db.query(WhatsAppMessage).one()
    assert tap(api, msg, "C").status_code == 200
    db.expire_all()
    a = db.get(Appointment, appt["id"])
    assert a.status == "confirmed" and a.confirmed_via == "whatsapp"
    reply = meta.sends[-1]["json"]
    assert reply["type"] == "text" and "confirmed" in reply["text"]["body"]
    # Meta redelivers the same webhook: processed once
    assert tap(api, msg, "C").json()["duplicates"] == 1
    assert len(meta.sends) == 2


def test_reschedule_button_flags_appointment_and_sends_booking_link(hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h)
    _, appt = setup_reminder(api, docs, lang="ta")
    frozen.set(datetime(2026, 11, 17, 18, 1))
    run(db, h)
    msg = db.query(WhatsAppMessage).one()
    tap(api, msg, "R")
    db.expire_all()
    assert db.get(Appointment, appt["id"]).status == "reschedule_requested"
    body = meta.sends[-1]["json"]["text"]["body"]
    assert "https://app.test/book/alpha" in body and "சரி" in body


def test_reply_from_another_number_is_ignored(hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h)
    _, appt = setup_reminder(api, docs)
    frozen.set(datetime(2026, 11, 17, 18, 1))
    run(db, h)
    msg = db.query(WhatsAppMessage).one()
    tap(api, msg, "C", from_phone="+919999999999")
    db.expire_all()
    assert db.get(Appointment, appt["id"]).status == "booked"
    assert db.query(WebhookEvent).one().outcome == "phone_mismatch"


def test_webhook_for_other_hospital_number_does_not_cross_tenants(hosp, other_hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h, phone_number_id="1111")
    go_live(db, other_hosp[0], phone_number_id="9999")
    _, appt = setup_reminder(api, docs)
    frozen.set(datetime(2026, 11, 17, 18, 1))
    run(db, h)
    msg = db.query(WhatsAppMessage).one()
    payload = wh_envelope("9999", messages=[{"from": "919876543210", "id": "wamid.X", "timestamp": "1", "type": "button",
                                             "button": {"payload": f"TT1:C:{msg.payload_ref}", "text": "Confirm"}}])
    raw, headers = signed(payload)
    api().post("/api/webhooks/whatsapp", content=raw, headers=headers)
    db.expire_all()
    assert db.get(Appointment, appt["id"]).status == "booked"


def test_followup_confirm_books_first_free_slot(hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h)
    c, appt = setup_reminder(api, docs)
    fu = c.post("/api/followups", json={"patient_id": appt["patient"]["id"], "due_date": "2026-12-02",
                                       "source_appointment_id": appt["id"]}).json()
    frozen.set(datetime(2026, 11, 25, 10, 1))
    run(db, h)
    msg = db.query(WhatsAppMessage).join(ReminderSchedule).filter(ReminderSchedule.follow_up_id == fu["id"]).one()
    tap(api, msg, "C", wamid="wamid.IN2")
    db.expire_all()
    f = db.get(FollowUp, fu["id"])
    assert f.status == "confirmed" and f.booked_appointment_id
    booked = db.get(Appointment, f.booked_appointment_id)
    assert booked.status == "confirmed" and booked.source == "followup"
    assert booked.start_at == datetime(2026, 12, 2, 9, 0, tzinfo=IST)
    assert "Wed, 2 Dec, 9:00 AM" in meta.sends[-1]["json"]["text"]["body"]
    # No 3-day reminder after confirmation
    frozen.set(datetime(2026, 11, 29, 10, 5))
    run(db, h)
    assert db.query(WhatsAppMessage).join(ReminderSchedule).filter(ReminderSchedule.follow_up_id == fu["id"]).count() == 1


def test_stop_message_opts_patient_out(hosp, api, db, frozen, meta):
    h, _, _, docs = hosp
    go_live(db, h)
    setup_reminder(api, docs)
    payload = wh_envelope("1111", messages=[{"from": "919876543210", "id": "wamid.STOP", "timestamp": "1",
                                             "type": "text", "text": {"body": "stop"}}])
    raw, headers = signed(payload)
    api().post("/api/webhooks/whatsapp", content=raw, headers=headers)
    db.expire_all()
    p = db.query(Patient).one()
    assert not p.whatsapp_opt_in and p.opted_out_at
    frozen.set(datetime(2026, 11, 17, 18, 1))
    run(db, h)
    assert meta.sends == []


def test_whatsapp_config_never_returns_token(hosp, api, db):
    c = api().login("admin@alpha.clinic.in")
    r = c.put("/api/whatsapp/config", json={"phone_number_id": "123456", "business_account_id": "654321",
                                           "access_token": "EAAsecret-token-value-1234"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_set"] and body["token_last4"] == "1234" and "EAAsecret" not in str(body)
    cfg = db.get(WhatsAppConfig, hosp[0].id)
    assert "EAAsecret" not in cfg.access_token_encrypted  # encrypted at rest
    bad = c.put("/api/whatsapp/config", json={"mode": "live", "test_recipient_allowlist": ["123"]})
    assert bad.status_code == 400
