"use client";

import { useState } from "react";
import { post } from "@/lib/api";
import { APPOINTMENT_STATUS } from "@/lib/format";
import type { Appointment } from "@/lib/types";
import { useAction } from "./providers";
import { Badge, Button, Field, Modal } from "./ui";

export function AppointmentStatusBadge({ status }: { status: string }) {
  const s = APPOINTMENT_STATUS[status] || { label: status, tone: "neutral" as const };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

/** Quick actions that make sense for an appointment in its current state, relative to today. */
export function AppointmentActions({ appt, today, onChanged, size = "sm" }:
  { appt: Appointment; today: string; onChanged: () => void; size?: "sm" | "md" }) {
  const { busy, run } = useAction();
  const [cancelOpen, setCancelOpen] = useState(false);
  const [reason, setReason] = useState("");
  const active = ["booked", "confirmed", "reschedule_requested"].includes(appt.status);
  const dayReached = appt.local_date <= today;
  const set = (status: string, label: string, extra: Record<string, unknown> = {}) =>
    run(status, () => post(`/api/appointments/${appt.id}/status`, { status, ...extra }), label).then((r) => r && onChanged());
  return (
    <div className="flex flex-wrap gap-1.5 justify-end">
      {active && appt.status !== "confirmed" && !dayReached && (
        <Button size={size} loading={busy === "confirmed"} onClick={() => set("confirmed", "Marked confirmed")}>Confirm</Button>
      )}
      {active && dayReached && (
        <>
          <Button size={size} variant={size === "md" ? "primary" : "secondary"} loading={busy === "completed"} onClick={() => set("completed", "Marked as visited")}>Visited</Button>
          <Button size={size} loading={busy === "no_show"} onClick={() => set("no_show", "Marked as did not come")}>Didn&apos;t come</Button>
        </>
      )}
      {appt.status === "no_show" && (
        <Button size={size} loading={busy === "completed"} onClick={() => set("completed", "Marked as visited")}>Came late</Button>
      )}
      {active && <Button size={size} variant="ghost" onClick={() => setCancelOpen(true)}>Cancel</Button>}
      <Modal open={cancelOpen} onClose={() => setCancelOpen(false)} title="Cancel this appointment?">
        <p className="text-sm text-muted mb-4">The slot opens up for other patients and no reminder will be sent.</p>
        <Field label="Reason (optional)">
          <input className="input" value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Patient called to cancel" />
        </Field>
        <div className="flex justify-end gap-2 mt-5">
          <Button onClick={() => setCancelOpen(false)}>Keep appointment</Button>
          <Button variant="danger" loading={busy === "cancelled"} onClick={async () => {
            await set("cancelled", "Appointment cancelled", { reason: reason || null });
            setCancelOpen(false);
          }}>Cancel appointment</Button>
        </div>
      </Modal>
    </div>
  );
}
