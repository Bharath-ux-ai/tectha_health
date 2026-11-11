"""Doctors, availability, patients, consent, appointments, follow-ups, contact logs.

No clinical/medical information is stored: Version 1 is scheduling and reminders only.
"""
import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Time, Uuid, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import IdMixin, SoftDeleteMixin, TimestampMixin

ACTIVE_APPOINTMENT_STATUSES = ("booked", "confirmed", "reschedule_requested")
APPOINTMENT_STATUSES = ACTIVE_APPOINTMENT_STATUSES + ("rescheduled", "cancelled", "completed", "no_show")
OPEN_FOLLOWUP_STATUSES = ("scheduled", "confirmed", "reschedule_requested")
FOLLOWUP_STATUSES = OPEN_FOLLOWUP_STATUSES + ("completed", "missed", "cancelled")


class Doctor(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "doctors"
    hospital_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    specialty: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    availability: Mapped[list["DoctorAvailability"]] = relationship(
        back_populates="doctor", cascade="all, delete-orphan", order_by="DoctorAvailability.weekday"
    )

    __table_args__ = (Index("ix_doctors_hospital", "hospital_id"),)


class DoctorAvailability(IdMixin, TimestampMixin, Base):
    __tablename__ = "doctor_availability"
    hospital_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    doctor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0 = Monday … 6 = Sunday
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    slot_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)

    doctor: Mapped[Doctor] = relationship(back_populates="availability")

    __table_args__ = (
        CheckConstraint("weekday between 0 and 6", name="ck_availability_weekday"),
        CheckConstraint("end_time > start_time", name="ck_availability_range"),
        CheckConstraint("slot_minutes between 5 and 240", name="ck_availability_slot"),
        Index("ix_availability_doctor", "doctor_id", "weekday"),
    )


class Patient(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "patients"
    hospital_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(120), nullable=False)
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False)
    preferred_language: Mapped[str] = mapped_column(String(5), nullable=False, default="en")
    whatsapp_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    opt_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # fictional/demo patient

    __table_args__ = (
        CheckConstraint("preferred_language in ('en','ta')", name="ck_patients_language"),
        # Same phone + same normalised name = same person. Families sharing a phone stay separate.
        Index("uq_patients_identity", "hospital_id", "phone_e164", "name_normalized", unique=True,
              postgresql_where=text("deleted_at is null")),
        Index("ix_patients_hospital_phone", "hospital_id", "phone_e164"),
    )


class PatientConsent(IdMixin, Base):
    __tablename__ = "patient_consents"
    hospital_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="whatsapp")
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)  # booking_form | staff_verbal | whatsapp_stop | staff_update
    consent_text_version: Mapped[str | None] = mapped_column(String(20))
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (Index("ix_consents_patient", "patient_id", "created_at"),)


class Appointment(IdMixin, TimestampMixin, Base):
    __tablename__ = "appointments"
    hospital_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    reference: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)
    doctor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="booked")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="online")  # online | staff | followup
    booked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_via: Mapped[str | None] = mapped_column(String(16))  # whatsapp | staff
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reschedule_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rescheduled_to_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("appointments.id", ondelete="SET NULL"))
    follow_up_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("follow_ups.id", ondelete="SET NULL", use_alter=True, name="fk_appointments_follow_up")
    )

    patient: Mapped["Patient"] = relationship(foreign_keys=[patient_id])
    doctor: Mapped[Doctor] = relationship()

    __table_args__ = (
        CheckConstraint(
            "status in ('booked','confirmed','reschedule_requested','rescheduled','cancelled','completed','no_show')",
            name="ck_appointments_status",
        ),
        CheckConstraint("end_at > start_at", name="ck_appointments_range"),
        # The database itself refuses a second active booking for the same doctor and start time.
        Index("uq_appointments_active_slot", "doctor_id", "start_at", unique=True,
              postgresql_where=text("status in ('booked','confirmed','reschedule_requested')")),
        Index("ix_appointments_hospital_start", "hospital_id", "start_at"),
        Index("ix_appointments_hospital_status", "hospital_id", "status"),
        Index("ix_appointments_patient", "patient_id"),
    )


class FollowUp(IdMixin, TimestampMixin, Base):
    __tablename__ = "follow_ups"
    hospital_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)
    source_appointment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("appointments.id", ondelete="SET NULL"))
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("doctors.id", ondelete="SET NULL"))
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="scheduled")
    note: Mapped[str | None] = mapped_column(String(300))  # scheduling note only, never clinical detail
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reschedule_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    missed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_appointment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("appointments.id", ondelete="SET NULL"))
    booked_appointment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("appointments.id", ondelete="SET NULL"))
    reschedule_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))

    patient: Mapped[Patient] = relationship()
    doctor: Mapped[Doctor | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "status in ('scheduled','confirmed','reschedule_requested','completed','missed','cancelled')",
            name="ck_follow_ups_status",
        ),
        Index("ix_follow_ups_hospital_due", "hospital_id", "due_date"),
        Index("ix_follow_ups_hospital_status", "hospital_id", "status"),
        Index("ix_follow_ups_patient", "patient_id"),
    )


class ContactLog(IdMixin, Base):
    """Staff outreach record, e.g. calling a patient whose follow-up turned red."""
    __tablename__ = "contact_logs"
    hospital_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    follow_up_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("follow_ups.id", ondelete="CASCADE"))
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("appointments.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    method: Mapped[str] = mapped_column(String(16), nullable=False)  # phone | whatsapp | in_person
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # reached | no_answer | wrong_number | will_visit | declined
    note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (Index("ix_contact_logs_follow_up", "follow_up_id"), Index("ix_contact_logs_patient", "patient_id"))
