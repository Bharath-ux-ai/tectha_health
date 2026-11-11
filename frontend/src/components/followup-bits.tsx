"use client";

import { Phone } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { post } from "@/lib/api";
import { ATTENTION_REASON, fmtDate, fmtPhone, FOLLOWUP_STATUS } from "@/lib/format";
import type { FollowUpRow } from "@/lib/types";
import { useAction } from "./providers";
import { ReminderRail } from "./reminder-rail";
import { Badge, Button, cx, Field, Modal } from "./ui";

const OUTCOMES = [
  { value: "reached", label: "Spoke to the patient" },
  { value: "will_visit", label: "Patient will come (mark confirmed)" },
  { value: "no_answer", label: "No answer" },
  { value: "wrong_number", label: "Wrong number" },
  { value: "declined", label: "Patient does not want to come" },
];

export function ContactModal({ row, open, onClose, onSaved }: { row: FollowUpRow | null; open: boolean; onClose: () => void; onSaved: () => void }) {
  const [method, setMethod] = useState("phone");
  const [outcome, setOutcome] = useState("reached");
  const [note, setNote] = useState("");
  const { busy, run } = useAction();
  if (!row) return null;
  return (
    <Modal open={open} onClose={onClose} title={`Log contact with ${row.patient.name}`}>
      <div className="flex flex-col gap-4">
        <a href={`tel:${row.patient.phone}`} className="flex items-center gap-2 text-violet-deep font-medium"><Phone className="size-4" />{fmtPhone(row.patient.phone)}</a>
        <Field label="How did you contact them?">
          <select className="input" value={method} onChange={(e) => setMethod(e.target.value)}>
            <option value="phone">Phone call</option><option value="whatsapp">WhatsApp message</option><option value="in_person">In person</option>
          </select>
        </Field>
        <Field label="What happened?">
          <select className="input" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            {OUTCOMES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </Field>
        <Field label="Note (optional)" hint="Scheduling notes only. Don't record medical details.">
          <textarea className="input" rows={2} maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={busy === "c"} onClick={async () => {
            const ok = await run("c", () => post(`/api/followups/${row.id}/contacts`, { method, outcome, note: note || null }), "Contact logged");
            if (ok) { setNote(""); onSaved(); onClose(); }
          }}>Save</Button>
        </div>
      </div>
    </Modal>
  );
}

export function AttentionItem({ row, today, onLog }: { row: FollowUpRow; today: string; onLog: (r: FollowUpRow) => void }) {
  const red = row.attention === "red";
  return (
    <li className={cx("relative rounded-xl border p-3.5 pl-4", red ? "border-alert/30 bg-alert-wash/60" : "border-caution/25 bg-caution-wash/60")}>
      <span className={cx("absolute left-0 top-3 bottom-3 w-[3px] rounded-full", red ? "bg-alert" : "bg-caution")} aria-hidden />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href={`/patients/${row.patient.id}`} className="font-medium hover:underline">{row.patient.name}</Link>
          <p className={cx("text-xs font-medium mt-0.5", red ? "text-alert" : "text-caution")}>
            {ATTENTION_REASON[row.attention_reason || ""] || row.attention_reason}
          </p>
          <p className="text-xs text-muted mt-1">
            Follow-up {fmtDate(row.due_date)}{row.doctor ? ` with ${row.doctor}` : ""}
            {row.last_contact && <> · last contact: {row.last_contact.outcome.replace("_", " ")}</>}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2 shrink-0">
          <a href={`tel:${row.patient.phone}`} className="text-sm font-medium text-ink num inline-flex items-center gap-1.5"><Phone className="size-3.5" />{fmtPhone(row.patient.phone)}</a>
          <Button size="sm" onClick={() => onLog(row)}>Log call</Button>
        </div>
      </div>
      {row.status !== "missed" && <div className="mt-2"><ReminderRail compact dueDate={row.due_date} today={today} reminders={row.reminders} status={row.status} /></div>}
    </li>
  );
}

export function FollowUpStatusBadge({ status }: { status: string }) {
  const s = FOLLOWUP_STATUS[status] || { label: status, tone: "neutral" as const };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}
