import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import ServiceError
from app.core.phone import InvalidPhone, normalize_name, normalize_phone
from app.models import Hospital, Patient, PatientConsent

CONSENT_TEXT_VERSION = "v1-2026"


def find_or_create_patient(
    db: Session,
    hospital: Hospital,
    *,
    full_name: str,
    phone: str,
    language: str | None = None,
    whatsapp_consent: bool | None = None,
    consent_source: str = "booking_form",
    user_id: uuid.UUID | None = None,
    is_test: bool = False,
) -> Patient:
    """Match on (normalised phone, normalised name) within the hospital to avoid duplicate records.
    Family members sharing one phone stay separate because their names differ."""
    name = " ".join(full_name.split())
    if len(name) < 2:
        raise ServiceError("Enter the patient's name.")
    try:
        e164 = normalize_phone(phone)
    except InvalidPhone as exc:
        raise ServiceError(str(exc)) from exc
    norm = normalize_name(name)
    if not norm:
        raise ServiceError("Enter the patient's name.")
    language = language if language in ("en", "ta") else hospital.default_language

    patient = db.scalar(
        select(Patient).where(
            Patient.hospital_id == hospital.id,
            Patient.phone_e164 == e164,
            Patient.name_normalized == norm,
            Patient.deleted_at.is_(None),
        )
    )
    if patient is None:
        patient = Patient(
            hospital_id=hospital.id, full_name=name, name_normalized=norm, phone_e164=e164,
            preferred_language=language, is_test=is_test,
        )
        try:
            with db.begin_nested():
                db.add(patient)
                db.flush()
        except IntegrityError:
            patient = db.scalar(
                select(Patient).where(
                    Patient.hospital_id == hospital.id, Patient.phone_e164 == e164,
                    Patient.name_normalized == norm, Patient.deleted_at.is_(None),
                )
            )
    else:
        patient.preferred_language = language
    if whatsapp_consent is not None:
        set_consent(db, patient, whatsapp_consent, source=consent_source, user_id=user_id)
    return patient


def set_consent(db: Session, patient: Patient, granted: bool, *, source: str, user_id: uuid.UUID | None = None) -> None:
    """Record consent changes as an append-only history plus the current state on the patient."""
    if granted == patient.whatsapp_opt_in and (patient.opt_in_at or patient.opted_out_at):
        return  # no change
    if not granted and source == "booking_form" and patient.whatsapp_opt_in:
        return  # an unticked box on a later booking does not revoke earlier consent; STOP or staff can
    now = utcnow()
    patient.whatsapp_opt_in = granted
    if granted:
        patient.opt_in_at = now
        patient.opted_out_at = None
    else:
        patient.opted_out_at = now
    db.add(
        PatientConsent(
            hospital_id=patient.hospital_id, patient_id=patient.id, channel="whatsapp", granted=granted,
            source=source, consent_text_version=CONSENT_TEXT_VERSION, recorded_by_user_id=user_id,
        )
    )
