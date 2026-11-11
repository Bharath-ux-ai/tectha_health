"use client";

import { Download, Printer, Save } from "lucide-react";
import { useState } from "react";
import { useAction, useLoad } from "@/components/providers";
import { Button, ErrorBox, PageHeader, Spinner, Stat } from "@/components/ui";
import { api, post } from "@/lib/api";
import { fmtDate, fmtDateTime } from "@/lib/format";

type Report = {
  month: string; month_label: string; hospital: string; summary: string; brought_back: number; includes_simulated_messages: boolean;
  appointments: { total: number; completed: number; cancelled: number; missed: number; rescheduled: number; still_open: number; confirmed_on_whatsapp: number; completion_rate: number | null };
  follow_ups: { scheduled: number; completed: number; returned_after_reminder: number; returned_without_delivered_reminder: number; due_this_month: number; due_completed: number; due_missed: number; due_open: number; retention_rate: number | null };
  patients: { seen: number; returning: number; new: number };
  messages: { accepted: number; delivered: number; read: number; failed: number; simulated: number };
  brought_back_list: { patient: string; follow_up_date: string; completed_at: string | null }[];
  saved_at: string | null;
};

function shiftMonth(m: string, n: number) {
  const [y, mo] = m.split("-").map(Number);
  const d = new Date(Date.UTC(y, mo - 1 + n, 1));
  return d.toISOString().slice(0, 7);
}

export default function ReportsPage() {
  const [month, setMonth] = useState<string | null>(null);
  const { data: r, error, reload } = useLoad(() => api<Report>("/api/reports/monthly", { params: { month } }), [month]);
  const { busy, run } = useAction();
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!r) return <Spinner />;
  const pct = (v: number | null) => (v === null ? "—" : `${v}%`);
  const f = r.follow_ups;
  return (
    <div className="max-w-5xl">
      <PageHeader title="Monthly report" subtitle={r.hospital}
        actions={<>
          <input type="month" className="input !w-44 num" value={r.month} onChange={(e) => e.target.value && setMonth(e.target.value)} aria-label="Month" />
          <Button onClick={() => setMonth(shiftMonth(r.month, -1))}>Previous month</Button>
          <Button icon={<Download className="size-4" />} onClick={() => { window.location.href = `/api/reports/monthly/${r.month}/export.csv`; }}>Export CSV</Button>
          <Button icon={<Printer className="size-4" />} onClick={() => window.print()}>Print / PDF</Button>
          <Button icon={<Save className="size-4" />} loading={busy === "s"} onClick={async () => { if (await run("s", () => post(`/api/reports/monthly/${r.month}/save`), "Report saved")) reload(); }}>Save copy</Button>
        </>} />

      <section className="panel p-6 sm:p-8">
        <p className="text-sm text-muted">{r.month_label}</p>
        <p className="font-display text-3xl sm:text-[2.6rem] leading-tight font-semibold mt-2 max-w-2xl">
          We brought back <span className="num text-violet-deep">{r.brought_back}</span> patient{r.brought_back === 1 ? "" : "s"} this month.
        </p>
        <p className="text-sm text-muted mt-4 max-w-2xl">
          Counted only when a follow-up visit was recorded <em>and</em> WhatsApp confirmed the reminder was delivered, read or answered before the visit.
          {f.returned_without_delivered_reminder > 0 && ` ${f.returned_without_delivered_reminder} more came back without a delivered reminder and are not counted.`}
        </p>
        {r.includes_simulated_messages && <p className="mt-3 text-xs rounded-lg bg-violet-wash text-violet-deep px-3 py-2 inline-block">Demo clinic: test-mode reminders (not really sent) are counted as delivered.</p>}
        {r.saved_at && <p className="text-xs text-muted mt-3">Copy saved {fmtDateTime(r.saved_at)}.</p>}
      </section>

      <div className="grid gap-6 md:grid-cols-2 mt-6">
        <section className="panel p-5">
          <h2 className="font-semibold mb-4">Follow-ups</h2>
          <div className="grid grid-cols-2 gap-5">
            <Stat label="Due this month" value={f.due_this_month} />
            <Stat label="Return rate" value={pct(f.retention_rate)} tone="violet" hint={`${f.due_completed} of ${f.due_this_month} came back`} />
            <Stat label="Missed" value={f.due_missed} tone={f.due_missed ? "alert" : undefined} />
            <Stat label="Still open" value={f.due_open} />
            <Stat label="Scheduled by staff" value={f.scheduled} />
            <Stat label="Completed this month" value={f.completed} />
          </div>
        </section>
        <section className="panel p-5">
          <h2 className="font-semibold mb-4">Appointments</h2>
          <div className="grid grid-cols-2 gap-5">
            <Stat label="Total" value={r.appointments.total} />
            <Stat label="Visited" value={r.appointments.completed} tone="violet" hint={r.appointments.completion_rate !== null ? `${pct(r.appointments.completion_rate)} of non-cancelled` : undefined} />
            <Stat label="Cancelled" value={r.appointments.cancelled} />
            <Stat label="Did not come" value={r.appointments.missed} tone={r.appointments.missed ? "alert" : undefined} />
            <Stat label="Confirmed on WhatsApp" value={r.appointments.confirmed_on_whatsapp} tone="ok" />
            <Stat label="No outcome yet" value={r.appointments.still_open} />
          </div>
        </section>
        <section className="panel p-5">
          <h2 className="font-semibold mb-4">Patients</h2>
          <div className="grid grid-cols-3 gap-5">
            <Stat label="Seen" value={r.patients.seen} />
            <Stat label="Returning" value={r.patients.returning} tone="violet" />
            <Stat label="New" value={r.patients.new} />
          </div>
        </section>
        <section className="panel p-5">
          <h2 className="font-semibold mb-4">WhatsApp reminders</h2>
          <div className="grid grid-cols-3 gap-5">
            <Stat label="Accepted" value={r.messages.accepted} />
            <Stat label="Delivered or read" value={r.messages.delivered + r.messages.read} tone="ok" />
            <Stat label="Failed" value={r.messages.failed} tone={r.messages.failed ? "alert" : undefined} />
            {r.messages.simulated > 0 && <Stat label="Test mode (not sent)" value={r.messages.simulated} />}
          </div>
        </section>
      </div>

      <section className="panel mt-6 overflow-hidden">
        <h2 className="font-semibold px-5 py-4 border-b border-silver">Patients brought back</h2>
        {r.brought_back_list.length === 0 ? <p className="px-5 py-4 text-sm text-muted">None recorded this month.</p> : (
          <table className="w-full text-sm">
            <thead className="bg-paper/60 border-b border-silver"><tr>{["Patient", "Follow-up date", "Visit recorded"].map((h) => <th key={h} className="table-head px-5 py-2.5">{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-silver">
              {r.brought_back_list.map((b, i) => (
                <tr key={i}><td className="px-5 py-2.5 font-medium">{b.patient}</td><td className="px-5 py-2.5">{fmtDate(b.follow_up_date, { year: "numeric" })}</td><td className="px-5 py-2.5 text-muted">{fmtDateTime(b.completed_at)}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
