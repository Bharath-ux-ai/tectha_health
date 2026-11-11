"use client";

import { RotateCw } from "lucide-react";
import { post } from "@/lib/api";
import { fmtDateTime, MESSAGE_STATUS, REMINDER_KIND, REMINDER_STATUS, SKIP_REASON } from "@/lib/format";
import type { Message, Reminder } from "@/lib/types";
import { useAction, useAuth } from "./providers";
import { Badge, Button, cx, Empty } from "./ui";

export function ReminderList({ reminders, onChanged }: { reminders: Reminder[]; onChanged: () => void }) {
  const { can } = useAuth();
  const { busy, run } = useAction();
  const shown = reminders.filter((r) => r.status !== "cancelled");
  if (!shown.length) return <p className="text-sm text-muted">No reminder scheduled.</p>;
  return (
    <ul className="flex flex-col gap-2">
      {shown.map((r) => {
        const st = REMINDER_STATUS[r.status] || { label: r.status, tone: "neutral" as const };
        return (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-silver px-4 py-3">
            <div className="min-w-0">
              <p className="text-sm font-medium">{REMINDER_KIND[r.kind]}{r.patient_name ? ` — ${r.patient_name}` : ""}</p>
              <p className="text-xs text-muted">
                {r.status === "pending" ? `Goes out ${fmtDateTime(r.next_attempt_at || r.due_at)}` : r.processed_at ? `${fmtDateTime(r.processed_at)}` : `Due ${fmtDateTime(r.due_at)}`}
                {r.attempts > 1 && ` · ${r.attempts} attempts`}
              </p>
              {r.skip_reason && <p className="text-xs text-muted mt-0.5">{SKIP_REASON[r.skip_reason] || r.skip_reason.replaceAll("_", " ")}</p>}
              {r.last_error && <p className="text-xs text-alert mt-0.5">{r.last_error}</p>}
            </div>
            <div className="flex items-center gap-2">
              <Badge tone={st.tone}>{st.label}</Badge>
              {r.status === "failed" && can("messages:retry") && (
                <Button size="sm" icon={<RotateCw className="size-3.5" />} loading={busy === r.id}
                  onClick={async () => { const x = await run(r.id, () => post(`/api/whatsapp/reminders/${r.id}/retry`), "Retry finished"); if (x) onChanged(); }}>
                  Retry
                </Button>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** WhatsApp-style thread. Test-mode messages are always labelled as not sent. */
export function MessageList({ messages, showPatient = false }: { messages: Message[]; showPatient?: boolean }) {
  if (!messages.length) return <Empty title="No messages yet" />;
  return (
    <ul className="flex flex-col gap-3">
      {messages.map((m) => {
        const st = MESSAGE_STATUS[m.status] || { label: m.status, tone: "neutral" as const };
        const inbound = m.direction === "inbound";
        return (
          <li key={m.id} className={cx("flex flex-col max-w-[92%] sm:max-w-[75%]", inbound ? "self-start items-start" : "self-end items-end")}>
            {showPatient && m.patient_name && <span className="text-xs text-muted mb-1">{inbound ? "From" : "To"} {m.patient_name}</span>}
            <div className={cx("rounded-2xl px-4 py-2.5 text-sm whitespace-pre-line",
              inbound ? "bg-white border border-silver rounded-tl-sm" : "bg-[#e9f7e3] text-ink rounded-tr-sm",
              m.is_simulated && !inbound && "bg-violet-wash")}>
              {m.body}
            </div>
            <div className="flex flex-wrap items-center gap-2 mt-1 text-[11px] text-muted">
              <span>{fmtDateTime(m.sent_at || m.created_at)}</span>
              {!inbound && <Badge tone={st.tone} className="!text-[11px] !py-0">{st.label}</Badge>}
              {inbound && m.is_simulated && <span>simulated tap</span>}
              {m.attempt_no > 1 && <span>attempt {m.attempt_no}</span>}
            </div>
            {m.error_message && <p className="text-[11px] text-alert mt-0.5">{m.error_code}: {m.error_message}</p>}
          </li>
        );
      })}
    </ul>
  );
}
