"use client";

import { ChevronLeft, ChevronRight, Copy, MessageSquareWarning, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { AppointmentActions, AppointmentStatusBadge } from "@/components/appointment-bits";
import { AttentionItem, ContactModal, FollowUpStatusBadge } from "@/components/followup-bits";
import { useAuth, useLoad, useToast } from "@/components/providers";
import { RegisterAppointmentModal } from "@/components/register-appointment";
import { ReminderRail } from "@/components/reminder-rail";
import { Button, cx, Empty, ErrorBox, PageHeader, Spinner, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { addDays, fmtDate, fmtDateTime, fmtPhone, fmtTime } from "@/lib/format";
import type { Appointment, FollowUpRow } from "@/lib/types";

type Dashboard = {
  date: string; today: string; now: string;
  counts: Record<string, number>;
  appointments: Appointment[]; attention: FollowUpRow[]; attention_red: number; upcoming_followups: FollowUpRow[];
  needs_outcome: Appointment[]; reminders: { failed_recent: number; pending: number; next_due_at: string | null };
};

export default function DashboardPage() {
  const { me, can } = useAuth();
  const toast = useToast();
  const [day, setDay] = useState<string | null>(null);
  const { data, error, loading, reload } = useLoad(() => api<Dashboard>("/api/dashboard", { params: { on: day } }), [day]);
  const [contactRow, setContactRow] = useState<FollowUpRow | null>(null);
  const [registerOpen, setRegisterOpen] = useState(false);
  const isAdmin = me?.user.role === "hospital_admin";

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;
  const isToday = data.date === data.today;
  const c = data.counts;

  return (
    <div>
      <PageHeader
        title={isToday ? "Today" : fmtDate(data.date, { weekday: "long" })}
        subtitle={fmtDate(data.date, { weekday: "long", month: "long", year: "numeric" })}
        actions={<>
          <div className="flex items-center rounded-[10px] border border-silver-2 bg-white">
            <button className="p-2 text-muted hover:text-ink" aria-label="Previous day" onClick={() => setDay(addDays(data.date, -1))}><ChevronLeft className="size-4" /></button>
            <input type="date" aria-label="Pick a day" className="text-sm bg-transparent px-1 h-9 num" value={data.date} onChange={(e) => setDay(e.target.value || null)} />
            <button className="p-2 text-muted hover:text-ink" aria-label="Next day" onClick={() => setDay(addDays(data.date, 1))}><ChevronRight className="size-4" /></button>
          </div>
          {!isToday && <Button onClick={() => setDay(null)}>Back to today</Button>}
          {me?.hospital && (
            <Button icon={<Copy className="size-4" />} onClick={() => navigator.clipboard.writeText(me.hospital!.booking_link).then(() => toast("ok", "Booking link copied"))}>
              Copy booking link
            </Button>
          )}
          {can("appointments:write") && <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setRegisterOpen(true)}>Register appointment</Button>}
        </>}
      />

      <section className="panel px-5 py-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-x-6 gap-y-4" aria-label="Day summary">
        <Stat label="Appointments" value={c.total - (c.cancelled || 0)} />
        <Stat label="Confirmed" value={c.confirmed} tone="ok" />
        <Stat label="Awaiting confirmation" value={c.pending_confirmation} />
        <Stat label="Cancelled" value={c.cancelled} />
        <Stat label="Visited" value={c.completed} tone="violet" hint={c.no_show ? `${c.no_show} did not come` : undefined} />
        <Stat label="Patients to call" value={data.attention_red} tone={data.attention_red ? "alert" : undefined} hint="Missed or no reply" />
      </section>

      {isAdmin && <AdminOverview />}

      {isAdmin && (data.reminders.failed_recent > 0) && (
        <Link href="/messages?status=failed" className="mt-4 flex items-center gap-2 rounded-xl border border-alert/25 bg-alert-wash px-4 py-3 text-sm text-alert">
          <MessageSquareWarning className="size-4" /> {data.reminders.failed_recent} WhatsApp reminder{data.reminders.failed_recent > 1 ? "s" : ""} failed recently. Review and retry.
        </Link>
      )}

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        <section className="panel overflow-hidden" aria-labelledby="appts-h">
          <div className="flex items-center justify-between px-5 py-4 border-b border-silver">
            <h2 id="appts-h" className="font-semibold">{isToday ? "Today's appointments" : "Appointments"}</h2>
            <Link href={`/appointments?date=${data.date}`} className="text-sm text-violet-deep hover:underline">Open full list</Link>
          </div>
          {loading ? <Spinner /> : data.appointments.length === 0 ? (
            <Empty title="No appointments on this day">Share the booking link with patients, or register a walk-in.</Empty>
          ) : (
            <ul className="divide-y divide-silver">
              {data.appointments.map((a) => (
                <li key={a.id} className={cx("px-5 py-3.5 flex flex-wrap items-center gap-x-4 gap-y-2", a.status === "cancelled" && "opacity-60")}>
                  <span className="num w-20 shrink-0 whitespace-nowrap font-semibold text-[15px]">{fmtTime(a.local_time)}</span>
                  <div className="min-w-0 flex-1 basis-48">
                    <Link href={`/appointments/${a.id}`} className="font-medium hover:underline">{a.patient.name}</Link>
                    <p className="text-xs text-muted num">{fmtPhone(a.patient.phone)} · {a.doctor.name}{!a.patient.whatsapp_opt_in && " · no WhatsApp consent"}</p>
                  </div>
                  <AppointmentStatusBadge status={a.status} />
                  {can("appointments:write") && <AppointmentActions appt={a} today={data.today} onChanged={reload} />}
                </li>
              ))}
            </ul>
          )}
        </section>

        <div className="flex flex-col gap-6">
          <section className="panel" aria-labelledby="att-h">
            <div className="px-5 py-4 border-b border-silver">
              <h2 id="att-h" className="font-semibold">Call these patients</h2>
              <p className="text-xs text-muted mt-0.5">Red: follow-up missed or no reply two days before. Amber: asked for another date.</p>
            </div>
            {data.attention.length === 0 ? <Empty title="Nobody needs a call right now" /> : (
              <ul className="p-3 flex flex-col gap-2">
                {data.attention.map((r) => <AttentionItem key={r.id} row={r} today={data.today} onLog={setContactRow} />)}
              </ul>
            )}
          </section>

          <section className="panel" aria-labelledby="up-h">
            <div className="flex items-center justify-between px-5 py-4 border-b border-silver">
              <h2 id="up-h" className="font-semibold">Follow-ups in the next 14 days</h2>
              <Link href="/follow-ups?view=upcoming" className="text-sm text-violet-deep hover:underline">All</Link>
            </div>
            {data.upcoming_followups.length === 0 ? <Empty title="No follow-ups coming up" /> : (
              <ul className="divide-y divide-silver">
                {data.upcoming_followups.slice(0, 8).map((r) => (
                  <li key={r.id} className="px-5 py-3 flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <Link href={`/patients/${r.patient.id}`} className="font-medium text-sm hover:underline">{r.patient.name}</Link>
                      <p className="text-xs text-muted">{fmtDate(r.due_date)} · in {r.days_to_due} day{r.days_to_due === 1 ? "" : "s"}</p>
                    </div>
                    <div className="flex items-center gap-4">
                      <ReminderRail compact dueDate={r.due_date} today={data.today} reminders={r.reminders} status={r.status} />
                      <FollowUpStatusBadge status={r.status} />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>

      {data.needs_outcome.length > 0 && can("appointments:write") && (
        <section className="panel mt-6" aria-labelledby="out-h">
          <div className="px-5 py-4 border-b border-silver">
            <h2 id="out-h" className="font-semibold">Earlier visits without an outcome</h2>
            <p className="text-xs text-muted mt-0.5">Mark them visited or not, so follow-ups and the monthly report stay accurate.</p>
          </div>
          <ul className="divide-y divide-silver">
            {data.needs_outcome.map((a) => (
              <li key={a.id} className="px-5 py-3 flex flex-wrap items-center gap-x-4 gap-y-2">
                <span className="text-sm text-muted w-full sm:w-48 whitespace-nowrap">{fmtDate(a.local_date)}, {fmtTime(a.local_time)}</span>
                <Link href={`/appointments/${a.id}`} className="font-medium w-full sm:w-auto sm:flex-1 hover:underline">{a.patient.name}</Link>
                <AppointmentActions appt={a} today={data.today} onChanged={reload} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {data.reminders.next_due_at && (
        <p className="mt-6 text-xs text-muted">{data.reminders.pending} WhatsApp reminders scheduled. Next one goes out {fmtDateTime(data.reminders.next_due_at)}.</p>
      )}

      <ContactModal row={contactRow} open={!!contactRow} onClose={() => setContactRow(null)} onSaved={reload} />
      <RegisterAppointmentModal open={registerOpen} onClose={() => setRegisterOpen(false)} today={data.today}
        onCreated={() => { setRegisterOpen(false); reload(); }} />
    </div>
  );
}

/** Extra strip for hospital admins: this month's outcome and the WhatsApp connection state. */
function AdminOverview() {
  const { data } = useLoad(() => Promise.all([
    api<{ brought_back: number; month_label: string; follow_ups: { completed: number; retention_rate: number | null; due_open: number } }>("/api/reports/monthly"),
    api<{ mode: string; readiness: { ok: boolean }[] }>("/api/whatsapp/config"),
  ]), []);
  if (!data) return null;
  const [rep, wa] = data;
  const ready = wa.readiness.filter((r) => r.ok).length;
  return (
    <section className="mt-4 grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <Link href="/reports" className="panel px-5 py-4 flex flex-wrap items-center gap-x-8 gap-y-3 hover:border-slate">
        <div>
          <p className="text-xs text-muted">{rep.month_label} so far</p>
          <p className="font-display text-lg font-semibold">We brought back <span className="num text-violet-deep">{rep.brought_back}</span> patient{rep.brought_back === 1 ? "" : "s"}</p>
        </div>
        <Stat label="Follow-ups completed" value={rep.follow_ups.completed} />
        <Stat label="Follow-up return rate" value={rep.follow_ups.retention_rate === null ? "—" : `${rep.follow_ups.retention_rate}%`} />
      </Link>
      <Link href="/whatsapp" className="panel px-5 py-4 hover:border-slate">
        <p className="text-xs text-muted">WhatsApp</p>
        <p className="font-medium mt-0.5">{wa.mode === "live" ? "Live — sending to patients" : wa.mode === "test" ? "Test mode — nothing is sent" : "Turned off"}</p>
        <p className="text-xs text-muted mt-1">{ready} of {wa.readiness.length} setup steps done</p>
      </Link>
    </section>
  );
}
