"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import { useAction, useLoad } from "@/components/providers";
import { Badge, Button, ErrorBox, Field, Modal, PageHeader, Spinner, Stat } from "@/components/ui";
import { api, patch, post, put } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import type { Hospital } from "@/lib/types";

type H = Hospital & { created_at: string; users: number; patients: number; appointments: number; appointments_30d: number; whatsapp_mode: string };
type Status = {
  database: boolean; worker: { ok: boolean; last_heartbeat: string | null; last_run: Record<string, number> | null };
  reminders_24h: Record<string, number>; reminders_pending: number; reminders_overdue: number; hospitals: number;
  live_messaging_enabled: boolean; environment: string; whatsapp_platform: { app_secret_set: boolean; verify_token_set: boolean; graph_version: string };
};

export default function SystemPage() {
  const status = useLoad(() => api<Status>("/api/system/status"), []);
  const hospitals = useLoad(() => api<{ items: H[] }>("/api/system/hospitals"), []);
  const [adding, setAdding] = useState(false);
  const { busy, run } = useAction();
  const s = status.data;
  return (
    <div>
      <PageHeader title="Platform overview" subtitle="Hospitals on TEC THA and the health of the reminder system. Patient data is not visible here."
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>Onboard hospital</Button>} />
      {status.error ? <ErrorBox message={status.error} onRetry={status.reload} /> : !s ? <Spinner /> : (
        <section className="panel p-5 grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-5">
          <Stat label="Database" value={s.database ? "OK" : "Down"} tone={s.database ? "ok" : "alert"} />
          <Stat label="Reminder worker" value={s.worker.ok ? "Running" : "Not running"} tone={s.worker.ok ? "ok" : "alert"} hint={s.worker.last_heartbeat ? `Last pass ${fmtDateTime(s.worker.last_heartbeat)}` : "No pass recorded"} />
          <Stat label="Overdue reminders" value={s.reminders_overdue} tone={s.reminders_overdue ? "alert" : undefined} hint="Real hospitals, >15 min late" />
          <Stat label="Scheduled reminders" value={s.reminders_pending} />
          <Stat label="Failed (24h)" value={s.reminders_24h.failed || 0} tone={s.reminders_24h.failed ? "alert" : undefined} />
          <Stat label="Sent (24h)" value={s.reminders_24h.sent || 0} hint={`${s.reminders_24h.simulated || 0} in test mode`} />
        </section>
      )}
      {s && (
        <section className="panel p-5 mt-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="font-semibold">Live WhatsApp sending</h2>
            <p className="text-sm text-muted">Emergency switch for all hospitals. When paused, reminders wait and go out once resumed.</p>
            <div className="flex flex-wrap gap-2 mt-2">
              <Badge tone={s.whatsapp_platform.app_secret_set ? "ok" : "alert"}>Webhook secret {s.whatsapp_platform.app_secret_set ? "set" : "missing"}</Badge>
              <Badge tone={s.whatsapp_platform.verify_token_set ? "ok" : "alert"}>Verify token {s.whatsapp_platform.verify_token_set ? "set" : "missing"}</Badge>
              <Badge>Graph {s.whatsapp_platform.graph_version}</Badge><Badge>{s.environment}</Badge>
            </div>
          </div>
          <Button variant={s.live_messaging_enabled ? "danger" : "primary"} loading={busy === "kill"} onClick={async () => {
            if (await run("kill", () => put("/api/system/settings", { live_messaging_enabled: !s.live_messaging_enabled }), s.live_messaging_enabled ? "Live sending paused" : "Live sending resumed")) status.reload();
          }}>{s.live_messaging_enabled ? "Pause live sending" : "Resume live sending"}</Button>
        </section>
      )}
      <section className="panel mt-6 overflow-hidden">
        <h2 className="font-semibold px-5 py-4 border-b border-silver">Hospitals</h2>
        {hospitals.error ? <div className="p-4"><ErrorBox message={hospitals.error} /></div> : !hospitals.data ? <Spinner /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-paper/60 border-b border-silver"><tr>{["Hospital", "Booking link", "WhatsApp", "Users", "Patients", "Bookings (30 days)", ""].map((h) => <th key={h} className="table-head px-4 py-2.5">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-silver">
                {hospitals.data.items.map((h) => (
                  <tr key={h.id}>
                    <td className="px-4 py-3"><p className="font-medium">{h.name}</p><p className="text-xs text-muted">{h.is_demo ? "Demo clinic" : `Since ${fmtDateTime(h.created_at)}`}</p></td>
                    <td className="px-4 py-3"><a className="text-violet-deep hover:underline" href={h.booking_link} target="_blank" rel="noreferrer">/book/{h.slug}</a></td>
                    <td className="px-4 py-3"><Badge tone={h.whatsapp_mode === "live" ? "ok" : h.whatsapp_mode === "test" ? "violet" : "muted"}>{h.whatsapp_mode}</Badge></td>
                    <td className="px-4 py-3 num">{h.users}</td><td className="px-4 py-3 num">{h.patients}</td><td className="px-4 py-3 num">{h.appointments_30d}</td>
                    <td className="px-4 py-3 text-right">
                      <Button size="sm" variant={h.is_active ? "danger" : "secondary"} loading={busy === h.id} onClick={async () => {
                        if (await run(h.id, () => patch(`/api/system/hospitals/${h.id}`, { is_active: !h.is_active }), h.is_active ? "Hospital suspended" : "Hospital reactivated")) hospitals.reload();
                      }}>{h.is_active ? "Suspend" : "Reactivate"}</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {adding && <Onboard onClose={() => setAdding(false)} onSaved={() => { setAdding(false); hospitals.reload(); status.reload(); }} />}
    </div>
  );
}

function Onboard({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ name: "", slug: "", address: "", phone: "", default_language: "ta", admin_name: "", admin_email: "", admin_password: "" });
  const { busy, run } = useAction();
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal open onClose={onClose} title="Onboard a hospital" width="max-w-2xl">
      <div className="flex flex-col gap-4">
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Hospital or clinic name"><input className="input" value={f.name} onChange={set("name")} /></Field>
          <Field label="Booking link name" hint="Lowercase, e.g. kovai-care. Leave blank to use the name."><input className="input" value={f.slug} onChange={set("slug")} /></Field>
          <Field label="Address"><input className="input" value={f.address} onChange={set("address")} /></Field>
          <Field label="Phone"><input className="input" value={f.phone} onChange={set("phone")} /></Field>
          <Field label="Default patient language"><select className="input" value={f.default_language} onChange={set("default_language")}><option value="ta">Tamil</option><option value="en">English</option></select></Field>
        </div>
        <p className="label border-t border-silver pt-4">First hospital admin</p>
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Name"><input className="input" value={f.admin_name} onChange={set("admin_name")} /></Field>
          <Field label="Email"><input type="email" className="input" value={f.admin_email} onChange={set("admin_email")} /></Field>
          <Field label="Temporary password" hint="10+ characters, an uppercase letter and a number."><input className="input" value={f.admin_password} onChange={set("admin_password")} autoComplete="new-password" /></Field>
        </div>
        <p className="text-xs text-muted">The hospital starts in WhatsApp test mode with English and Tamil templates ready to submit.</p>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={busy === "o"} onClick={async () => {
            if (await run("o", () => post("/api/system/hospitals", { ...f, slug: f.slug || null, address: f.address || null, phone: f.phone || null }), "Hospital onboarded")) onSaved();
          }}>Create hospital</Button>
        </div>
      </div>
    </Modal>
  );
}
