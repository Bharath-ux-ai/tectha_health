"use client";

import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useAction, useAuth, useLoad } from "@/components/providers";
import { Badge, Button, Empty, ErrorBox, Field, Modal, PageHeader, Spinner, Tabs } from "@/components/ui";
import { api, del, patch, post, put } from "@/lib/api";
import { fmtDateTime, WEEKDAYS } from "@/lib/format";
import type { Doctor, Hospital } from "@/lib/types";

export default function SettingsPage() {
  const [tab, setTab] = useState<"profile" | "doctors" | "audit">("profile");
  return (
    <div className="max-w-4xl">
      <PageHeader title="Hospital & doctors" subtitle="Profile, reminder times and the weekly schedules patients book from." />
      <Tabs value={tab} onChange={setTab} items={[{ value: "profile", label: "Hospital profile" }, { value: "doctors", label: "Doctors & schedules" }, { value: "audit", label: "Activity log" }]} />
      {tab === "profile" && <Profile />}
      {tab === "doctors" && <Doctors />}
      {tab === "audit" && <Audit />}
    </div>
  );
}

function Profile() {
  const { refresh } = useAuth();
  const { data, error, reload } = useLoad(() => api<Hospital>("/api/hospital"), []);
  const [form, setForm] = useState<Hospital | null>(null);
  const { busy, run } = useAction();
  useEffect(() => { if (data) setForm(data); }, [data]);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!form) return <Spinner />;
  const set = (k: keyof Hospital, v: unknown) => setForm({ ...form, [k]: v } as Hospital);
  return (
    <section className="panel p-5 sm:p-6 flex flex-col gap-5">
      <div className="grid sm:grid-cols-2 gap-4">
        <Field label="Hospital name"><input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="Phone shown to patients"><input className="input" value={form.phone || ""} onChange={(e) => set("phone", e.target.value)} /></Field>
        <div className="sm:col-span-2"><Field label="Address"><input className="input" value={form.address || ""} onChange={(e) => set("address", e.target.value)} /></Field></div>
        <Field label="Booking link" hint="Share this link on WhatsApp, Google profile and printed material."><input className="input bg-paper" readOnly value={form.booking_link} onFocus={(e) => e.target.select()} /></Field>
        <Field label="Default message language" hint="Used when a patient hasn't chosen one.">
          <select className="input" value={form.default_language} onChange={(e) => set("default_language", e.target.value)}><option value="en">English</option><option value="ta">Tamil</option></select>
        </Field>
      </div>
      <div className="border-t border-silver pt-5 grid sm:grid-cols-2 gap-4">
        <Field label="Appointment reminder time" hint="Sent the day before the visit, at this time."><input type="time" className="input" value={form.appointment_reminder_time} onChange={(e) => set("appointment_reminder_time", e.target.value)} /></Field>
        <Field label="Follow-up reminder time" hint="Sent 7 and 3 days before the follow-up date."><input type="time" className="input" value={form.followup_reminder_time} onChange={(e) => set("followup_reminder_time", e.target.value)} /></Field>
        <Field label="Patients can book up to (days ahead)"><input type="number" min={1} max={180} className="input" value={form.booking_horizon_days} onChange={(e) => set("booking_horizon_days", Number(e.target.value))} /></Field>
        <Field label="Minimum notice for online booking (minutes)"><input type="number" min={0} max={1440} className="input" value={form.min_booking_lead_minutes} onChange={(e) => set("min_booking_lead_minutes", Number(e.target.value))} /></Field>
        <Field label="Time zone"><input className="input bg-paper" readOnly value={form.timezone} /></Field>
      </div>
      <div className="flex justify-end">
        <Button variant="primary" loading={busy === "s"} onClick={async () => {
          const r = await run("s", () => patch("/api/hospital", {
            name: form.name, phone: form.phone || null, address: form.address || null, default_language: form.default_language,
            appointment_reminder_time: form.appointment_reminder_time, followup_reminder_time: form.followup_reminder_time,
            booking_horizon_days: form.booking_horizon_days, min_booking_lead_minutes: form.min_booking_lead_minutes,
          }), "Hospital profile saved");
          if (r) { reload(); refresh(); }
        }}>Save changes</Button>
      </div>
    </section>
  );
}

type Block = { weekday: number; start_time: string; end_time: string; slot_minutes: number };

function Doctors() {
  const { data, error, reload } = useLoad(() => api<{ items: Doctor[] }>("/api/doctors", { params: { include_inactive: true } }), []);
  const [editing, setEditing] = useState<Doctor | null>(null);
  const [adding, setAdding] = useState(false);
  const { busy, run } = useAction();
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end"><Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>Add doctor</Button></div>
      {data.items.length === 0 ? <div className="panel"><Empty title="No doctors yet">Add a doctor and their weekly sessions. Patients can only book times inside these sessions.</Empty></div> : data.items.map((d) => (
        <section key={d.id} className="panel p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="font-semibold">{d.name} {!d.is_active && <Badge tone="muted">Not taking bookings</Badge>}</p>
              <p className="text-sm text-muted">{d.specialty || "No specialty set"}</p>
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={() => setEditing(d)}>Edit schedule</Button>
              <Button size="sm" loading={busy === d.id} onClick={async () => { if (await run(d.id, () => patch(`/api/doctors/${d.id}`, { is_active: !d.is_active }), d.is_active ? "Bookings paused" : "Bookings resumed")) reload(); }}>
                {d.is_active ? "Pause bookings" : "Resume bookings"}
              </Button>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-7 gap-1 text-center text-xs">
            {WEEKDAYS.map((w, i) => {
              const blocks = (d.availability || []).filter((a) => a.weekday === i);
              return (
                <div key={w} className="rounded-lg bg-paper py-2 px-1">
                  <p className="font-medium text-ink-2">{w}</p>
                  {blocks.length === 0 ? <p className="text-slate mt-1">Off</p> : blocks.map((b, j) => <p key={j} className="num text-muted mt-1 leading-tight">{b.start_time}–{b.end_time}</p>)}
                </div>
              );
            })}
          </div>
        </section>
      ))}
      {adding && <DoctorModal onClose={() => setAdding(false)} onSaved={() => { setAdding(false); reload(); }} />}
      {editing && <DoctorModal doctor={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); }} />}
    </div>
  );
}

function DoctorModal({ doctor, onClose, onSaved }: { doctor?: Doctor; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(doctor?.name || "");
  const [specialty, setSpecialty] = useState(doctor?.specialty || "");
  const [blocks, setBlocks] = useState<Block[]>(doctor?.availability?.length ? doctor.availability : [0, 1, 2, 3, 4, 5].map((w) => ({ weekday: w, start_time: "09:00", end_time: "13:00", slot_minutes: 15 })));
  const { busy, run } = useAction();
  const upd = (i: number, k: keyof Block, v: string | number) => setBlocks(blocks.map((b, j) => (j === i ? { ...b, [k]: v } : b)));
  return (
    <Modal open onClose={onClose} title={doctor ? `Edit ${doctor.name}` : "Add doctor"} width="max-w-2xl">
      <div className="flex flex-col gap-4">
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Dr. Meena Sundaram" /></Field>
          <Field label="Specialty"><input className="input" value={specialty} onChange={(e) => setSpecialty(e.target.value)} placeholder="General Medicine" /></Field>
        </div>
        <div>
          <p className="label mb-2">Weekly sessions</p>
          <div className="flex flex-col gap-2">
            {blocks.map((b, i) => (
              <div key={i} className="grid grid-cols-[1fr_1fr_1fr_1fr_auto] gap-2 items-center">
                <select className="input" value={b.weekday} onChange={(e) => upd(i, "weekday", Number(e.target.value))} aria-label="Day">{WEEKDAYS.map((w, j) => <option key={w} value={j}>{w}</option>)}</select>
                <input type="time" className="input" value={b.start_time} onChange={(e) => upd(i, "start_time", e.target.value)} aria-label="Starts" />
                <input type="time" className="input" value={b.end_time} onChange={(e) => upd(i, "end_time", e.target.value)} aria-label="Ends" />
                <select className="input" value={b.slot_minutes} onChange={(e) => upd(i, "slot_minutes", Number(e.target.value))} aria-label="Slot length">
                  {[10, 15, 20, 30, 45, 60].map((m) => <option key={m} value={m}>{m} min</option>)}
                </select>
                <button className="p-2 text-muted hover:text-alert" aria-label="Remove session" onClick={() => setBlocks(blocks.filter((_, j) => j !== i))}><Trash2 className="size-4" /></button>
              </div>
            ))}
          </div>
          <Button size="sm" className="mt-2" icon={<Plus className="size-3.5" />} onClick={() => setBlocks([...blocks, { weekday: 0, start_time: "16:00", end_time: "19:00", slot_minutes: 15 }])}>Add session</Button>
        </div>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={busy === "s"} disabled={name.trim().length < 2} onClick={async () => {
            const r = await run("s", async () => {
              const d = doctor ? await patch<Doctor>(`/api/doctors/${doctor.id}`, { name, specialty: specialty || null })
                : await post<Doctor>("/api/doctors", { name, specialty: specialty || null });
              return put(`/api/doctors/${d.id}/availability`, { blocks: blocks.map((b) => ({ ...b, start_time: b.start_time.slice(0, 5), end_time: b.end_time.slice(0, 5) })) });
            }, "Doctor saved");
            if (r) onSaved();
          }}>Save doctor</Button>
          {doctor && <Button variant="danger" loading={busy === "d"} onClick={async () => { if (await run("d", () => del(`/api/doctors/${doctor.id}`), "Doctor removed")) onSaved(); }}>Remove</Button>}
        </div>
      </div>
    </Modal>
  );
}

function Audit() {
  const { data, error, reload } = useLoad(() => api<{ items: { id: string; action: string; entity_type: string | null; user: string | null; at: string; ip: string | null }[] }>("/api/audit-logs"), []);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;
  return (
    <section className="panel overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-paper/60 border-b border-silver"><tr>{["When", "Who", "What"].map((h) => <th key={h} className="table-head px-4 py-2.5">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-silver">
          {data.items.map((a) => (
            <tr key={a.id}><td className="px-4 py-2.5 text-muted whitespace-nowrap">{fmtDateTime(a.at)}</td><td className="px-4 py-2.5">{a.user || "System / patient"}</td>
              <td className="px-4 py-2.5">{a.action.replaceAll(".", " · ").replaceAll("_", " ")}</td></tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
