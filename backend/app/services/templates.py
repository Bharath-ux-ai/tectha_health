"""Default bilingual (English/Tamil) message templates and rendering helpers.

Reminder templates must be approved by Meta before live use (category UTILITY). Reply texts are
free-form session messages, sent only right after the patient taps a button (inside WhatsApp's
24-hour customer-service window), so they don't need approval.
"""
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Hospital, MessageTemplate

TA_MONTHS = ["ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்", "ஜூலை", "ஆகஸ்ட்", "செப்டம்பர்",
             "அக்டோபர்", "நவம்பர்", "டிசம்பர்"]
TA_WEEKDAYS = ["திங்கள்", "செவ்வாய்", "புதன்", "வியாழன்", "வெள்ளி", "சனி", "ஞாயிறு"]

DEFAULT_TEMPLATES: list[dict] = [
    {
        "kind": "appointment_reminder", "language": "en", "requires_approval": True,
        "meta_template_name": "tt_appointment_reminder", "meta_language_code": "en",
        "body_text": "Hello {{1}}, this is a reminder from {{2}}. Your appointment with {{3}} is tomorrow, "
                     "{{4}} at {{5}}. Please tap Confirm, or Reschedule if you need another time.",
        "button_confirm_text": "Confirm", "button_reschedule_text": "Reschedule",
    },
    {
        "kind": "appointment_reminder", "language": "ta", "requires_approval": True,
        "meta_template_name": "tt_appointment_reminder", "meta_language_code": "ta",
        "body_text": "வணக்கம் {{1}}, {{2}} சார்பாக ஒரு நினைவூட்டல். நாளை {{4}} அன்று {{5}} மணிக்கு {{3}} "
                     "அவர்களுடன் உங்கள் சந்திப்பு உள்ளது. வருவதை உறுதிசெய்ய 'உறுதிசெய்' அழுத்தவும்; வேறு நேரம் "
                     "வேண்டுமெனில் 'நேரத்தை மாற்று' அழுத்தவும்.",
        "button_confirm_text": "உறுதிசெய்", "button_reschedule_text": "நேரத்தை மாற்று",
    },
    {
        "kind": "followup_reminder", "language": "en", "requires_approval": True,
        "meta_template_name": "tt_followup_reminder", "meta_language_code": "en",
        "body_text": "Hello {{1}}, this is {{2}}. Your follow-up visit with {{3}} is due on {{4}}. "
                     "Tap Confirm to book your visit, or Reschedule to choose another day.",
        "button_confirm_text": "Confirm", "button_reschedule_text": "Reschedule",
    },
    {
        "kind": "followup_reminder", "language": "ta", "requires_approval": True,
        "meta_template_name": "tt_followup_reminder", "meta_language_code": "ta",
        "body_text": "வணக்கம் {{1}}, {{2}} சார்பாக ஒரு நினைவூட்டல். {{3}} அவர்களிடம் உங்கள் அடுத்த "
                     "பரிசோதனை வருகை {{4}} அன்று உள்ளது. வருகையைப் பதிவு செய்ய 'உறுதிசெய்' அழுத்தவும்; வேறு நாள் "
                     "வேண்டுமெனில் 'நேரத்தை மாற்று' அழுத்தவும்.",
        "button_confirm_text": "உறுதிசெய்", "button_reschedule_text": "நேரத்தை மாற்று",
    },
    {
        "kind": "confirm_reply", "language": "en", "requires_approval": False,
        "body_text": "Thank you, {name}. Your visit on {when} is confirmed. See you at {hospital}.",
    },
    {
        "kind": "confirm_reply", "language": "ta", "requires_approval": False,
        "body_text": "நன்றி {name}. {when} அன்று உங்கள் வருகை உறுதிசெய்யப்பட்டது. {hospital} இல் சந்திப்போம்.",
    },
    {
        "kind": "reschedule_reply", "language": "en", "requires_approval": False,
        "body_text": "No problem, {name}. Choose a new time here: {booking_link} or call us on {hospital_phone}. — {hospital}",
    },
    {
        "kind": "reschedule_reply", "language": "ta", "requires_approval": False,
        "body_text": "சரி {name}. புதிய நேரத்தைத் தேர்வு செய்ய: {booking_link} அல்லது {hospital_phone} என்ற எண்ணில் "
                     "அழைக்கவும். — {hospital}",
    },
]

TEMPLATE_PARAMS = {
    "appointment_reminder": ["Patient name", "Hospital name", "Doctor name", "Date", "Time"],
    "followup_reminder": ["Patient name", "Hospital name", "Doctor name", "Follow-up date"],
}
REPLY_PLACEHOLDERS = ["name", "when", "hospital", "booking_link", "hospital_phone"]
EXAMPLE_PARAMS = {
    "appointment_reminder": ["Ravi", "TEC THA Demo Clinic", "Dr. Meena", "Wed, 18 Nov", "10:30 AM"],
    "followup_reminder": ["Ravi", "TEC THA Demo Clinic", "Dr. Meena", "Wed, 2 Dec"],
}


def example_params(kind: str, language: str) -> list[str]:
    """Example values in the template's own language (used for previews and Meta's approval examples)."""
    from datetime import date
    params = list(EXAMPLE_PARAMS[kind])
    if language == "ta":
        if kind == "appointment_reminder":
            params[3] = fmt_date(date(2026, 11, 18), "ta")
        else:
            params[3] = fmt_date(date(2026, 12, 2), "ta")
    return params


def seed_default_templates(db: Session, hospital: Hospital) -> None:
    existing = {(t.kind, t.language) for t in db.scalars(
        select(MessageTemplate).where(MessageTemplate.hospital_id == hospital.id))}
    for spec in DEFAULT_TEMPLATES:
        if (spec["kind"], spec["language"]) in existing:
            continue
        db.add(MessageTemplate(
            hospital_id=hospital.id,
            approval_status="not_submitted" if spec["requires_approval"] else "not_required",
            **spec,
        ))


def choose_template(db: Session, hospital: Hospital, kind: str, language: str) -> MessageTemplate | None:
    rows = {t.language: t for t in db.scalars(select(MessageTemplate).where(
        MessageTemplate.hospital_id == hospital.id, MessageTemplate.kind == kind, MessageTemplate.is_active.is_(True)))}
    return rows.get(language) or rows.get(hospital.default_language) or rows.get("en")


def render_numbered(body: str, params: list[str]) -> str:
    return re.sub(r"\{\{(\d+)\}\}", lambda m: params[int(m.group(1)) - 1] if 0 < int(m.group(1)) <= len(params)
                  else m.group(0), body)


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render_named(body: str, values: dict) -> str:
    return body.format_map(_SafeDict(values))


def numbered_placeholders(body: str) -> list[int]:
    return sorted({int(n) for n in re.findall(r"\{\{(\d+)\}\}", body)})


def validate_template_body(kind: str, body: str) -> None:
    from app.core.errors import ServiceError

    body = body.strip()
    if not body:
        raise ServiceError("Message text can't be empty.")
    if len(body) > 1024:
        raise ServiceError("Message text must be 1024 characters or fewer.")
    if kind in TEMPLATE_PARAMS:
        expected = list(range(1, len(TEMPLATE_PARAMS[kind]) + 1))
        if numbered_placeholders(body) != expected:
            names = ", ".join(f"{{{{{i}}}}} {n}" for i, n in enumerate(TEMPLATE_PARAMS[kind], 1))
            raise ServiceError(f"Use each placeholder exactly as listed: {names}.")
        if re.match(r"^\s*\{\{\d+\}\}", body) or re.search(r"\{\{\d+\}\}\s*[.!?]?\s*$", body):
            raise ServiceError("WhatsApp rejects templates that start or end with a placeholder. Add words around it.")
    else:
        unknown = set(re.findall(r"\{(\w+)\}", body)) - set(REPLY_PLACEHOLDERS)
        if unknown:
            raise ServiceError(f"Unknown placeholder: {', '.join(sorted(unknown))}. "
                               f"Available: {', '.join('{'+p+'}' for p in REPLY_PLACEHOLDERS)}.")


def fmt_date(dt_or_date, language: str) -> str:
    d = dt_or_date.date() if isinstance(dt_or_date, datetime) else dt_or_date
    if language == "ta":
        return f"{TA_WEEKDAYS[d.weekday()]}, {d.day} {TA_MONTHS[d.month - 1]}"
    return d.strftime("%a, ") + str(d.day) + d.strftime(" %b")


def fmt_time(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")
