"use client";

import { ArrowLeft, Phone } from "lucide-react";
import Link from "next/link";
import { use, useState } from "react";
import { AppointmentStatusBadge } from "@/components/appointment-bits";
import { FollowUpStatusBadge } from "@/components/followup-bits";
import { MessageList } from "@/components/message-bits";
import { useAction, useAuth, useLoad } from "@/components/providers";
import { Badge, Button, Field, Modal, PageHeader, Spinner, ErrorBox, Tabs } from "@/components/ui";
import { api, patch } from "@/lib/api";
import { ATTENTION_REASON, fmtDate, fmtDateTime, fmtPhone, fmtTime } from "@/lib/format";
import type { Appointment, Message } from "@/lib/types";

type Detail = {
  id: string; full_name: string; phone: string; preferred_language: "en" | "ta"; whatsapp_opt_in: boolean; opt_in_at: string | null;
  opted_out_at: string | null; is_test: boolean; created_at: string;
  appointments: Appointment[]; messages: Message[];
  follow_ups: { id: string; due_date: string; status: string; attention: string | null; attention_reason: string | null; doctor: { name: string } | null }[];
  consents: { granted: boolean; source: string; at: string; version: string }[];
  contacts: { id: string; method: string; outcome: string; note: string | null; at: string; by: string | null }[];
};

const SOURCES: Record<string, string> = { booking_form: "Online booking form", staff_verbal: "Told reception", staff_update: "Changed by staff", whatsapp_stop: "Sent STOP on WhatsApp" };

export default function PatientDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { can } = useAuth();
  const { data: p, error, reload } = useLoad(() => api<Detail>(`/api/patients/${id}`), [id]);
  const [tab, setTab] = useState<"visits" | "messages" | "consent">("visits");
  const [editOpen, setEditOpen] = useState(false);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!p) return <Spinner />;
  return (
    <div className="max-w-5xl">
      <Link href="/patients" className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink mb-3"><ArrowLeft className="size-4" />Patients</Link>
      <PageHeader title={p.full_name}
        subtitle={<a href={`tel:${p.phone}`} className="inline-flex items-center gap-1.5 num hover:text-ink"><Phone className="size-3.5" />{fmtPhone(p.phone)}</a>}
        actions={can("patients:write") && <Button onClick={() => setEditOpen(true)}>Edit contact details</Button>} />

      <section className="panel p-5 grid sm:grid-cols-3 gap-5">
        <div><p className="text-xs text-muted mb-1">Message language</p><p className="text-sm font-medium">{p.preferred_language === "ta" ? "Tamil" : "English"}</p></div>
        <div><p className="text-xs text-muted mb-1">WhatsApp reminders</p>
          {p.whatsapp_opt_in ? <Badge tone="ok">Agreed {p.opt_in_at && `on ${fmtDate(p.opt_in_at, { year: "numeric" })}`}</Badge>
            : <Badge tone="muted">{p.opted_out_at ? `Declined ${fmtDate(p.opted_out_at)}` : "Not agreed"}</Badge>}</div>
        <div><p className="text-xs text-muted mb-1">Record</p><p className="text-sm">{p.is_test ? "Fictional demo patient" : `Since ${fmtDate(p.created_at, { year: "numeric" })}`}</p></div>
      </section>

      <div className="mt-6">
        <Tabs value={tab} onChange={setTab} items={[
          { value: "visits", label: `Appointments & follow-ups` }, { value: "messages", label: `WhatsApp (${p.messages.length})` },
          { value: "consent", label: "Consent & contact log" },
        ]} />
        {tab === "visits" && (
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="panel">
              <h2 className="font-semibold px-5 py-4 border-b border-silver">Appointments</h2>
              {p.appointments.length === 0 ? <p className="p-5 text-sm text-muted">None.</p> : (
                <ul className="divide-y divide-silver">
                  {p.appointments.map((a) => (
                    <li key={a.id} className="px-5 py-3 flex items-center justify-between gap-3">
                      <div><Link href={`/appointments/${a.id}`} className="text-sm font-medium hover:underline">{fmtDate(a.local_date, { year: "numeric" })}, {fmtTime(a.local_time)}</Link>
                        <p className="text-xs text-muted">{a.doctor.name} · <span className="num">{a.reference}</span></p></div>
                      <AppointmentStatusBadge status={a.status} />
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section className="panel">
              <h2 className="font-semibold px-5 py-4 border-b border-silver">Follow-ups</h2>
              {p.follow_ups.length === 0 ? <p className="p-5 text-sm text-muted">None. Set one from an appointment after the visit.</p> : (
                <ul className="divide-y divide-silver">
                  {p.follow_ups.map((f) => (
                    <li key={f.id} className="px-5 py-3 flex items-center justify-between gap-3">
                      <div><Link href={`/follow-ups?view=all&focus=${f.id}`} className="text-sm font-medium hover:underline">{fmtDate(f.due_date, { year: "numeric" })}</Link>
                        <p className="text-xs text-muted">{f.doctor?.name}{f.attention && <span className={f.attention === "red" ? "text-alert" : "text-caution"}> · {ATTENTION_REASON[f.attention_reason || ""]}</span>}</p></div>
                      <FollowUpStatusBadge status={f.status} />
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
        {tab === "messages" && <section className="panel p-5 bg-paper/40"><MessageList messages={[...p.messages].reverse()} /></section>}
        {tab === "consent" && (
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="panel">
              <h2 className="font-semibold px-5 py-4 border-b border-silver">Consent history</h2>
              <ul className="divide-y divide-silver">
                {p.consents.length === 0 && <li className="px-5 py-3 text-sm text-muted">No consent recorded.</li>}
                {p.consents.map((c, i) => (
                  <li key={i} className="px-5 py-3 text-sm flex justify-between gap-3">
                    <span>{c.granted ? "Agreed to WhatsApp reminders" : "Declined / stopped reminders"}<span className="block text-xs text-muted">{SOURCES[c.source] || c.source} · text {c.version}</span></span>
                    <span className="text-xs text-muted whitespace-nowrap">{fmtDateTime(c.at)}</span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="panel">
              <h2 className="font-semibold px-5 py-4 border-b border-silver">Contact log</h2>
              <ul className="divide-y divide-silver">
                {p.contacts.length === 0 && <li className="px-5 py-3 text-sm text-muted">No calls logged.</li>}
                {p.contacts.map((c) => (
                  <li key={c.id} className="px-5 py-3 text-sm">
                    <div className="flex justify-between gap-3"><span className="font-medium capitalize">{c.method.replace("_", " ")}: {c.outcome.replace("_", " ")}</span>
                      <span className="text-xs text-muted whitespace-nowrap">{fmtDateTime(c.at)}</span></div>
                    {c.note && <p className="text-muted mt-0.5">{c.note}</p>}
                    {c.by && <p className="text-xs text-muted mt-0.5">by {c.by}</p>}
                  </li>
                ))}
              </ul>
            </section>
          </div>
        )}
      </div>
      {editOpen && <EditModal p={p} onClose={() => setEditOpen(false)} onSaved={() => { setEditOpen(false); reload(); }} />}
    </div>
  );
}

function EditModal({ p, onClose, onSaved }: { p: Detail; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(p.full_name);
  const [phone, setPhone] = useState(p.phone);
  const [lang, setLang] = useState(p.preferred_language);
  const [optIn, setOptIn] = useState(p.whatsapp_opt_in);
  const { busy, run } = useAction();
  return (
    <Modal open onClose={onClose} title="Edit contact details">
      <div className="flex flex-col gap-4">
        <Field label="Full name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></Field>
        <Field label="Mobile number"><input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={16} /></Field>
        <Field label="Message language">
          <select className="input" value={lang} onChange={(e) => setLang(e.target.value as "en" | "ta")}><option value="en">English</option><option value="ta">Tamil</option></select>
        </Field>
        <label className="flex gap-3 items-start text-sm">
          <input type="checkbox" className="mt-0.5 size-4 accent-[#8a4fd8]" checked={optIn} onChange={(e) => setOptIn(e.target.checked)} />
          <span>Patient agrees to WhatsApp reminders<span className="block text-xs text-muted">Only tick this if the patient told you so. The change is logged with your name.</span></span>
        </label>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={busy === "s"} onClick={async () => {
            const r = await run("s", () => patch(`/api/patients/${p.id}`, { full_name: name, phone, preferred_language: lang, whatsapp_opt_in: optIn }), "Patient updated");
            if (r) onSaved();
          }}>Save</Button>
        </div>
      </div>
    </Modal>
  );
}
