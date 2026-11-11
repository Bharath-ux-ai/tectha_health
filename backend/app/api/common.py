"""Shared serialisers for API responses. Explicit field lists so nothing sensitive leaks by accident."""
from app.core.clock import to_local
from app.models import Appointment, Doctor, FollowUp, Hospital, Patient, User, WhatsAppMessage


def iso(dt):
    return dt.isoformat() if dt else None


def user_out(u: User) -> dict:
    return {"id": str(u.id), "email": u.email, "full_name": u.full_name, "role": u.role_code,
            "hospital_id": str(u.hospital_id) if u.hospital_id else None, "is_active": u.is_active,
            "last_login_at": iso(u.last_login_at), "created_at": iso(u.created_at)}


def doctor_out(d: Doctor, with_schedule: bool = True) -> dict:
    out = {"id": str(d.id), "name": d.name, "specialty": d.specialty, "is_active": d.is_active}
    if with_schedule:
        out["availability"] = [{"weekday": a.weekday, "start_time": a.start_time.strftime("%H:%M"),
                                "end_time": a.end_time.strftime("%H:%M"), "slot_minutes": a.slot_minutes}
                               for a in sorted(d.availability, key=lambda a: (a.weekday, a.start_time))]
    return out


def patient_out(p: Patient) -> dict:
    return {"id": str(p.id), "full_name": p.full_name, "phone": p.phone_e164, "preferred_language": p.preferred_language,
            "whatsapp_opt_in": p.whatsapp_opt_in, "opt_in_at": iso(p.opt_in_at), "opted_out_at": iso(p.opted_out_at),
            "is_test": p.is_test, "created_at": iso(p.created_at)}


def appointment_out(h: Hospital, a: Appointment) -> dict:
    local = to_local(h, a.start_at)
    return {
        "id": str(a.id), "reference": a.reference, "status": a.status, "source": a.source,
        "start_at": iso(a.start_at), "end_at": iso(a.end_at), "local_date": local.date().isoformat(),
        "local_time": local.strftime("%H:%M"), "confirmed_at": iso(a.confirmed_at), "confirmed_via": a.confirmed_via,
        "cancelled_at": iso(a.cancelled_at), "cancel_reason": a.cancel_reason, "completed_at": iso(a.completed_at),
        "reschedule_count": a.reschedule_count, "follow_up_id": str(a.follow_up_id) if a.follow_up_id else None,
        "patient": {"id": str(a.patient.id), "name": a.patient.full_name, "phone": a.patient.phone_e164,
                    "whatsapp_opt_in": a.patient.whatsapp_opt_in, "preferred_language": a.patient.preferred_language},
        "doctor": {"id": str(a.doctor.id), "name": a.doctor.name, "specialty": a.doctor.specialty},
        "created_at": iso(a.created_at),
    }


def followup_out(fu: FollowUp) -> dict:
    return {
        "id": str(fu.id), "due_date": fu.due_date.isoformat(), "status": fu.status, "note": fu.note,
        "confirmed_at": iso(fu.confirmed_at), "completed_at": iso(fu.completed_at), "missed_at": iso(fu.missed_at),
        "reschedule_requested_at": iso(fu.reschedule_requested_at), "reschedule_count": fu.reschedule_count,
        "source_appointment_id": str(fu.source_appointment_id) if fu.source_appointment_id else None,
        "booked_appointment_id": str(fu.booked_appointment_id) if fu.booked_appointment_id else None,
        "completed_appointment_id": str(fu.completed_appointment_id) if fu.completed_appointment_id else None,
        "doctor": {"id": str(fu.doctor.id), "name": fu.doctor.name} if fu.doctor else None,
        "patient": {"id": str(fu.patient.id), "name": fu.patient.full_name, "phone": fu.patient.phone_e164,
                    "whatsapp_opt_in": fu.patient.whatsapp_opt_in},
        "created_at": iso(fu.created_at),
    }


def message_out(m: WhatsAppMessage, patient_name: str | None = None) -> dict:
    return {
        "id": str(m.id), "direction": m.direction, "type": m.message_type, "template": m.template_name,
        "language": m.language, "phone": m.phone_e164, "body": m.body_preview, "status": m.status,
        "is_simulated": m.is_simulated, "attempt_no": m.attempt_no, "error_code": m.error_code,
        "error_message": m.error_message, "sent_at": iso(m.sent_at), "delivered_at": iso(m.delivered_at),
        "read_at": iso(m.read_at), "failed_at": iso(m.failed_at), "created_at": iso(m.created_at),
        "reminder_id": str(m.reminder_id) if m.reminder_id else None,
        "patient_id": str(m.patient_id) if m.patient_id else None, "patient_name": patient_name,
    }


def hospital_out(h: Hospital) -> dict:
    from app.core.clock import hospital_now
    from app.services.whatsapp.sender import booking_link
    local_now = to_local(h, hospital_now(h))
    return {
        "id": str(h.id), "name": h.name, "slug": h.slug, "address": h.address, "phone": h.phone,
        "timezone": h.timezone, "default_language": h.default_language,
        "appointment_reminder_time": h.appointment_reminder_time.strftime("%H:%M"),
        "followup_reminder_time": h.followup_reminder_time.strftime("%H:%M"),
        "booking_horizon_days": h.booking_horizon_days, "min_booking_lead_minutes": h.min_booking_lead_minutes,
        "is_active": h.is_active, "is_demo": h.is_demo, "booking_link": booking_link(h),
        "today": local_now.date().isoformat(), "local_now": local_now.strftime("%a %d %b %Y, %I:%M %p"),
        "created_at": iso(h.created_at),
    }
