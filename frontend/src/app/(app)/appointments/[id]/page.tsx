"use client";

import { ArrowLeft, CalendarPlus, Phone } from "lucide-react";
import Link from "next/link";
import { use, useState } from "react";
import { AppointmentActions, AppointmentStatusBadge } from "@/components/appointment-bits";
import { FollowUpStatusBadge } from "@/components/followup-bits";
import { MessageList, ReminderList } from "@/components/message-bits";
import { useAction, useAuth, useLoad } from "@/components/providers";
import { DoctorDateSlot, useDoctors } from "@/components/register-appointment";
import { ReminderRail } from "@/components/reminder-rail";
import { Slot } from "@/components/slot-picker";
import { Button, ErrorBox, Field, Modal, PageHeader, Spinner } from "@/components/ui";
import { api, post } from "@/lib/api";
import { addDays, fmtDate, fmtDateTime, fmtPhone, fmtTime } from "@/lib/format";
import type { Appointment, Message, Reminder } from "@/lib/types";

type FollowUp = { id: string; due_date: string; status: string; doctor: { name: string } | null };
type Detail = Appointment & { today: string; reminders: Reminder[]; messages: Message[]; follow_ups: FollowUp[]; confirmed_at: string | null; completed_at: string | null; created_at: string };

export default function AppointmentDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { can } = useAuth();
  const { data: a, error, reload } = useLoad(() => api<Detail>(`/api/appointments/${id}`), [id]);
  const [rescheduleOpen, setRescheduleOpen] = useState(false);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!a) return <Spinner />;
  const today = a.today;
  const active = ["booked", "confirmed", "reschedule_requested"].includes(a.status);
  const openFollowUp = a.follow_ups.find((f) => ["scheduled", "confirmed", "reschedule_requested"].includes(f.status));

  return (
    <div className="max-w-4xl">
      <Link href="/appointments" className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink mb-3"><ArrowLeft className="size-4" />Appointments</Link>
      <PageHeader title={a.patient.name} subtitle={<span className="num">{a.reference}</span>}
        actions={<>
          {can("appointments:write") && active && <Button onClick={() => setRescheduleOpen(true)}>Reschedule</Button>}
          {can("appointments:write") && <AppointmentActions appt={a} today={today} onChanged={reload} size="md" />}
        </>} />

      <section className="panel p-5 grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <Info label="When" value={<>{fmtDate(a.local_date, { weekday: "long" })}<span className="block num">{fmtTime(a.local_time)}</span></>} />
        <Info label="Doctor" value={a.doctor.name} />
        <Info label="Status" value={<><AppointmentStatusBadge status={a.status} />{a.confirmed_via && <span className="block text-xs text-muted mt-1">Confirmed via {a.confirmed_via === "whatsapp" ? "WhatsApp" : "staff"}</span>}</>} />
        <Info label="Patient" value={<><a href={`tel:${a.patient.phone}`} className="num inline-flex items-center gap-1.5 hover:underline"><Phone className="size-3.5" />{fmtPhone(a.patient.phone)}</a>
          <Link href={`/patients/${a.patient.id}`} className="block text-xs text-violet-deep hover:underline mt-1">Patient record</Link></>} />
        {a.cancel_reason && <div className="sm:col-span-2 lg:col-span-4 text-sm text-muted">Note: {a.cancel_reason}</div>}
        <p className="sm:col-span-2 lg:col-span-4 text-xs text-muted">
          Booked {a.source === "online" ? "online" : a.source === "followup" ? "from a follow-up reminder" : "by staff"} on {fmtDateTime(a.created_at)}.
          {!a.patient.whatsapp_opt_in && " The patient has not agreed to WhatsApp reminders."}
        </p>
      </section>

      <section className="panel mt-6 p-5">
        <div className="flex items-center justify-between gap-3 mb-3">
          <h2 className="font-semibold">Next follow-up</h2>
        </div>
        {openFollowUp ? (
          <div>
            <div className="flex flex-wrap items-center gap-3 mb-2">
              <span className="font-medium">{fmtDate(openFollowUp.due_date, { weekday: "long", year: "numeric" })}</span>
              <FollowUpStatusBadge status={openFollowUp.status} />
              <Link href={`/follow-ups?focus=${openFollowUp.id}`} className="text-sm text-violet-deep hover:underline">Manage</Link>
            </div>
            <FollowUpRail id={openFollowUp.id} today={today} />
          </div>
        ) : can("followups:write") ? (
          <ScheduleFollowUp appt={a} today={today} onSaved={reload} />
        ) : <p className="text-sm text-muted">No follow-up set.</p>}
        {a.follow_ups.filter((f) => f !== openFollowUp).length > 0 && (
          <ul className="mt-4 text-sm text-muted">
            {a.follow_ups.filter((f) => f !== openFollowUp).map((f) => <li key={f.id}>{fmtDate(f.due_date)} — <FollowUpStatusBadge status={f.status} /></li>)}
          </ul>
        )}
      </section>

      <section className="panel mt-6 p-5">
        <h2 className="font-semibold mb-3">Reminder</h2>
        <ReminderList reminders={a.reminders} onChanged={reload} />
        {a.messages.length > 0 && <div className="mt-5"><h3 className="text-sm font-medium mb-2">WhatsApp messages</h3><MessageList messages={a.messages} /></div>}
      </section>

      <RescheduleModal appt={a} today={today} open={rescheduleOpen} onClose={() => setRescheduleOpen(false)} onSaved={() => { setRescheduleOpen(false); reload(); }} />
    </div>
  );
}

function Info({ label, value }: { label: string; value: React.ReactNode }) {
  return <div><p className="text-xs text-muted mb-1">{label}</p><div className="text-sm font-medium">{value}</div></div>;
}

function FollowUpRail({ id, today }: { id: string; today: string }) {
  const { data } = useLoad(() => api<{ due_date: string; status: string; reminders: Reminder[] }>(`/api/followups/${id}`), [id]);
  if (!data) return null;
  const map: Record<string, string> = {};
  data.reminders.filter((r) => r.status !== "cancelled").forEach((r) => { map[r.kind] = r.status; });
  return <div className="max-w-xl px-8"><ReminderRail dueDate={data.due_date} today={today} reminders={map} status={data.status} /></div>;
}

const QUICK = [{ label: "1 week", days: 7 }, { label: "2 weeks", days: 14 }, { label: "1 month", days: 30 }, { label: "3 months", days: 91 }];

function ScheduleFollowUp({ appt, today, onSaved }: { appt: Detail; today: string; onSaved: () => void }) {
  const base = appt.local_date > today ? appt.local_date : today;
  const [date, setDate] = useState(addDays(base, 14));
  const [note, setNote] = useState("");
  const { busy, run } = useAction();
  return (
    <div className="flex flex-col gap-4 max-w-xl">
      <p className="text-sm text-muted">Set the date the doctor asked the patient to come back. WhatsApp reminders go out 7 days and 3 days before.</p>
      <div className="flex flex-wrap gap-2">
        {QUICK.map((q) => (
          <Button key={q.days} size="sm" variant={date === addDays(base, q.days) ? "primary" : "secondary"} onClick={() => setDate(addDays(base, q.days))}>{q.label}</Button>
        ))}
      </div>
      <div className="grid sm:grid-cols-2 gap-4">
        <Field label="Follow-up date"><input type="date" className="input" min={addDays(today, 1)} value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label="Note for reception (optional)" hint="No medical details."><input className="input" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      {date && <p className="text-sm">Reminders on <b>{fmtDate(addDays(date, -7))}</b> and <b>{fmtDate(addDays(date, -3))}</b>{addDays(date, -7) <= today && " (dates already passed are skipped)"}.</p>}
      <div><Button variant="primary" icon={<CalendarPlus className="size-4" />} loading={busy === "f"} disabled={!date}
        onClick={async () => {
          const r = await run("f", () => post("/api/followups", { patient_id: appt.patient.id, due_date: date, source_appointment_id: appt.id, doctor_id: appt.doctor.id, note: note || null }), "Follow-up scheduled");
          if (r) onSaved();
        }}>Schedule follow-up</Button></div>
    </div>
  );
}

function RescheduleModal({ appt, today, open, onClose, onSaved }: { appt: Detail; today: string; open: boolean; onClose: () => void; onSaved: () => void }) {
  const doctors = useDoctors();
  const [doctorId, setDoctorId] = useState(appt.doctor.id);
  const [date, setDate] = useState(appt.local_date >= today ? appt.local_date : today);
  const [slot, setSlot] = useState<Slot | null>(null);
  const { busy, run } = useAction();
  return (
    <Modal open={open} onClose={onClose} title={`Reschedule ${appt.patient.name}`} width="max-w-2xl">
      <div className="flex flex-col gap-5">
        <p className="text-sm text-muted">Currently {fmtDate(appt.local_date)} at {fmtTime(appt.local_time)}. The day-before reminder moves with the appointment.</p>
        <DoctorDateSlot doctors={doctors} doctorId={doctorId} setDoctorId={setDoctorId} date={date} setDate={setDate} slot={slot} setSlot={setSlot} minDate={today} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!slot} loading={busy === "r"} onClick={async () => {
            const r = await run("r", () => post(`/api/appointments/${appt.id}/reschedule`, { doctor_id: doctorId, start_at: slot!.start_at }), "Appointment moved");
            if (r) onSaved();
          }}>Move appointment</Button>
        </div>
      </div>
    </Modal>
  );
}
