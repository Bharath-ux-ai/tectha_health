"""Authentication, role permissions and hospital (tenant) data isolation."""
from datetime import date

from app.models import PasswordResetToken, User

from app.services.hospitals import create_user
from tests.conftest import PASSWORD, at


def test_login_success_sets_httponly_cookie_and_me(hosp, api):
    h, admin, _, _ = hosp
    c = api()
    r = c.post("/api/auth/login", json={"email": "ADMIN@alpha.clinic.in", "password": PASSWORD})
    assert r.status_code == 200
    assert "token" not in r.json()  # session token lives only in the httpOnly cookie
    cookie = r.headers["set-cookie"]
    assert "tt_session=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    me = c.get("/api/auth/me").json()
    assert me["user"]["email"] == "admin@alpha.clinic.in"
    assert me["hospital"]["slug"] == "alpha"
    assert "reports:read" in me["permissions"]


def test_wrong_password_and_lockout(hosp, api):
    c = api()
    for _ in range(5):
        r = c.post("/api/auth/login", json={"email": "staff@alpha.clinic.in", "password": "wrong-password"})
        assert r.status_code == 401
        assert r.json()["detail"] == "Email or password is incorrect."
    r = c.post("/api/auth/login", json={"email": "staff@alpha.clinic.in", "password": PASSWORD})
    assert r.status_code == 423  # locked even with the right password


def test_unknown_email_gives_same_error(hosp, api):
    r = api().post("/api/auth/login", json={"email": "nobody@alpha.clinic.in", "password": "whatever"})
    assert r.status_code == 401 and r.json()["detail"] == "Email or password is incorrect."


def test_requests_without_session_are_rejected(hosp, api):
    c = api()
    assert c.get("/api/auth/me").status_code == 401
    assert c.get("/api/appointments").status_code == 401


def test_cookie_session_requires_csrf_header_on_writes(hosp, api):
    h, _, _, docs = hosp
    c = api().login("staff@alpha.clinic.in")
    c.headers.pop("X-Requested-With")
    r = c.post("/api/appointments", json={"doctor_id": str(docs[0].id), "start_at": at(date(2026, 11, 20), 10),
                                         "full_name": "Test", "phone": "9876543210"})
    assert r.status_code == 403


def test_logout_and_deactivated_user_session_ends(hosp, api, db):
    _, _, staff, _ = hosp
    c = api().login("staff@alpha.clinic.in")
    assert c.get("/api/auth/me").status_code == 200
    admin = api().login("admin@alpha.clinic.in")
    assert admin.patch(f"/api/staff/{staff.id}", json={"is_active": False}).status_code == 200
    assert c.get("/api/auth/me").status_code == 401
    assert api().post("/api/auth/login", json={"email": "staff@alpha.clinic.in", "password": PASSWORD}).status_code == 403


def test_forgot_and_reset_password_flow(hosp, api, db, monkeypatch):
    sent = {}
    monkeypatch.setattr("app.api.auth.send_email", lambda to, subject, body: sent.update(to=to, body=body) or True)
    c = api()
    r = c.post("/api/auth/forgot-password", json={"email": "staff@alpha.clinic.in"})
    assert r.status_code == 200 and "reset link" in r.json()["message"]
    # Unknown emails get the identical answer (no account enumeration)
    assert c.post("/api/auth/forgot-password", json={"email": "ghost@alpha.clinic.in"}).json() == r.json()
    token = sent["body"].split("token=")[1].split()[0]
    assert db.query(PasswordResetToken).count() == 1
    assert db.query(PasswordResetToken).first().token_hash != token  # only a hash is stored
    weak = c.post("/api/auth/reset-password", json={"token": token, "new_password": "short"})
    assert weak.status_code == 400
    ok = c.post("/api/auth/reset-password", json={"token": token, "new_password": "BrandNewPass9"})
    assert ok.status_code == 200
    again = c.post("/api/auth/reset-password", json={"token": token, "new_password": "AnotherPass99"})
    assert again.status_code == 400  # single use
    api().login("staff@alpha.clinic.in", "BrandNewPass9")


def test_change_password_signs_out_other_sessions(hosp, api):
    a = api().login("staff@alpha.clinic.in")
    b = api().login("staff@alpha.clinic.in")
    r = a.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "ChangedPass123"})
    assert r.status_code == 200
    assert a.get("/api/auth/me").status_code == 200  # this session got a fresh cookie
    assert b.get("/api/auth/me").status_code == 401


def test_staff_role_limits(hosp, api):
    c = api().login("staff@alpha.clinic.in")
    assert c.get("/api/appointments").status_code == 200
    assert c.get("/api/dashboard").status_code == 200
    for path in ("/api/reports/monthly", "/api/staff", "/api/whatsapp/config", "/api/whatsapp/templates",
                 "/api/audit-logs", "/api/system/hospitals"):
        assert c.get(path).status_code == 403, path
    assert c.patch("/api/hospital", json={"name": "Hijack"}).status_code == 403


def test_hospital_admin_cannot_use_system_endpoints(hosp, api):
    c = api().login("admin@alpha.clinic.in")
    assert c.get("/api/reports/monthly").status_code == 200
    assert c.get("/api/system/hospitals").status_code == 403
    assert c.get("/api/system/status").status_code == 403


def test_system_admin_has_no_patient_access(hosp, api, db):
    create_user(db, email="ops@tectha.clinic.in", full_name="Ops", password=PASSWORD, role_code="system_admin",
                hospital_id=None)
    db.commit()
    c = api().login("ops@tectha.clinic.in")
    assert c.get("/api/system/hospitals").status_code == 200
    assert c.get("/api/system/status").status_code == 200
    for path in ("/api/appointments", "/api/patients", "/api/followups", "/api/dashboard"):
        assert c.get(path).status_code == 403, path


def test_system_admin_onboards_hospital(api, db):
    create_user(db, email="ops@tectha.clinic.in", full_name="Ops", password=PASSWORD, role_code="system_admin",
                hospital_id=None)
    db.commit()
    c = api().login("ops@tectha.clinic.in")
    r = c.post("/api/system/hospitals", json={"name": "Kovai Care Clinic", "admin_email": "owner@kovai.clinic.in",
                                              "admin_name": "Owner", "admin_password": "OwnerPass123"})
    assert r.status_code == 201, r.text
    assert r.json()["hospital"]["slug"] == "kovai-care-clinic"
    owner = api().login("owner@kovai.clinic.in", "OwnerPass123")
    templates = owner.get("/api/whatsapp/templates").json()["items"]
    assert {(t["kind"], t["language"]) for t in templates} >= {("appointment_reminder", "en"),
                                                                ("appointment_reminder", "ta"),
                                                                ("followup_reminder", "en"), ("followup_reminder", "ta")}
    dup = c.post("/api/system/hospitals", json={"name": "Kovai Care Clinic", "admin_email": "x@kovai.clinic.in",
                                                "admin_name": "Xavier", "admin_password": "OwnerPass123"})
    assert dup.status_code == 409


def test_hospital_data_isolation(hosp, other_hosp, api, frozen):
    h_a, _, _, docs_a = hosp
    c_a = api().login("staff@alpha.clinic.in")
    r = c_a.post("/api/appointments", json={"doctor_id": str(docs_a[0].id), "start_at": at(date(2026, 11, 18), 10),
                                           "full_name": "Ravi Kumar", "phone": "9876543210"})
    assert r.status_code == 201, r.text
    appt = r.json()
    pid = appt["patient"]["id"]
    fu = c_a.post("/api/followups", json={"patient_id": pid, "due_date": "2026-12-02"}).json()

    c_b = api().login("admin@beta.clinic.in")
    assert c_b.get(f"/api/appointments/{appt['id']}").status_code == 404
    assert c_b.get(f"/api/patients/{pid}").status_code == 404
    assert c_b.get(f"/api/followups/{fu['id']}").status_code == 404
    assert c_b.post(f"/api/appointments/{appt['id']}/status", json={"status": "cancelled"}).status_code == 404
    assert c_b.post("/api/followups", json={"patient_id": pid, "due_date": "2026-12-05"}).status_code == 404
    assert c_b.patch(f"/api/patients/{pid}", json={"full_name": "Changed"}).status_code == 404
    assert c_b.get("/api/appointments", params={"date_from": "2026-11-01", "date_to": "2026-11-30"}).json()["total"] == 0
    assert c_b.get("/api/patients", params={"q": "ravi"}).json()["total"] == 0
    assert c_b.get("/api/followups", params={"view": "all"}).json()["items"] == []
    # Doctors of another hospital can't be used either
    r = c_b.post("/api/appointments", json={"doctor_id": str(docs_a[0].id), "start_at": at(date(2026, 11, 18), 11),
                                           "full_name": "Intruder", "phone": "9876500001"})
    assert r.status_code == 404


def test_staff_cannot_manage_other_hospital_staff(hosp, other_hosp, api, db):
    beta_staff = db.query(User).filter_by(email="staff@beta.clinic.in").one()
    c = api().login("admin@alpha.clinic.in")
    assert c.patch(f"/api/staff/{beta_staff.id}", json={"is_active": False}).status_code == 404
