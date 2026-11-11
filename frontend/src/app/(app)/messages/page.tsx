"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ReminderList } from "@/components/message-bits";
import { useLoad } from "@/components/providers";
import { Badge, Button, Empty, ErrorBox, PageHeader, Spinner, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDateTime, fmtPhone, MESSAGE_STATUS } from "@/lib/format";
import type { Message, Reminder } from "@/lib/types";

type Tab = "queue" | "failed" | "log";

function MessagesInner() {
  const qs = useSearchParams();
  const [tab, setTab] = useState<Tab>(qs.get("status") === "failed" ? "failed" : "queue");
  return (
    <div>
      <PageHeader title="WhatsApp messages" subtitle="Scheduled reminders, failures to retry, and every message sent or received." />
      <Tabs value={tab} onChange={setTab} items={[{ value: "queue", label: "Scheduled" }, { value: "failed", label: "Failed" }, { value: "log", label: "Message log" }]} />
      {tab === "log" ? <Log /> : <Queue status={tab === "queue" ? "pending" : "failed"} />}
    </div>
  );
}

function Queue({ status }: { status: string }) {
  const { data, error, reload } = useLoad(() => api<{ items: Reminder[]; counts: Record<string, number> }>("/api/whatsapp/reminders", { params: { status } }), [status]);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;
  const c = data.counts;
  return (
    <div>
      <p className="text-sm text-muted mb-3">
        All time: {c.sent || 0} sent, {c.simulated || 0} in test mode, {c.skipped || 0} not needed, {c.failed || 0} failed, {c.pending || 0} scheduled.
      </p>
      {data.items.length === 0 ? <div className="panel"><Empty title={status === "failed" ? "No failed reminders" : "Nothing scheduled"} /></div>
        : <ReminderList reminders={data.items} onChanged={reload} />}
      {status === "failed" && data.items.length > 0 && <p className="text-xs text-muted mt-3">Retry sends the reminder again once. Reminders that already reached WhatsApp are never sent twice.</p>}
    </div>
  );
}

function Log() {
  const [page, setPage] = useState(1);
  const { data, error, reload } = useLoad(() => api<{ items: Message[]; total: number }>("/api/whatsapp/messages", { params: { page } }), [page]);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;
  if (!data.items.length) return <div className="panel"><Empty title="No messages yet" /></div>;
  return (
    <section className="panel overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-paper/60 border-b border-silver"><tr>{["Time", "Patient", "Direction", "Message", "Status"].map((h) => <th key={h} className="table-head px-4 py-2.5">{h}</th>)}</tr></thead>
          <tbody className="divide-y divide-silver">
            {data.items.map((m) => {
              const st = MESSAGE_STATUS[m.status] || { label: m.status, tone: "neutral" as const };
              return (
                <tr key={m.id} className="align-top">
                  <td className="px-4 py-3 whitespace-nowrap text-muted">{fmtDateTime(m.sent_at || m.created_at)}</td>
                  <td className="px-4 py-3 whitespace-nowrap">{m.patient_id ? <Link href={`/patients/${m.patient_id}`} className="font-medium hover:underline">{m.patient_name}</Link> : <span className="num">{fmtPhone(m.phone)}</span>}</td>
                  <td className="px-4 py-3">{m.direction === "inbound" ? "From patient" : m.type === "template" ? "Reminder" : "Reply"}</td>
                  <td className="px-4 py-3 max-w-md"><p className="line-clamp-2">{m.body}</p>{m.error_message && <p className="text-xs text-alert mt-1">{m.error_code}: {m.error_message}</p>}</td>
                  <td className="px-4 py-3"><Badge tone={st.tone}>{m.direction === "inbound" ? (m.is_simulated ? "Simulated tap" : "Received") : st.label}</Badge></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {data.total > 50 && (
        <div className="flex justify-end gap-2 px-4 py-3 border-t border-silver">
          <Button size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Newer</Button>
          <Button size="sm" disabled={page * 50 >= data.total} onClick={() => setPage(page + 1)}>Older</Button>
        </div>
      )}
    </section>
  );
}

export default function MessagesPage() {
  return <Suspense><MessagesInner /></Suspense>;
}
