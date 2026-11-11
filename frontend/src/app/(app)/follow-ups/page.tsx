"use client";

import { Phone, Search } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ContactModal, FollowUpStatusBadge } from "@/components/followup-bits";
import { useAction, useAuth, useLoad } from "@/components/providers";
import { ReminderRail } from "@/components/reminder-rail";
import { Badge, Button, cx, Empty, ErrorBox, Field, Modal, PageHeader, Spinner, Tabs } from "@/components/ui";
import { api, post } from "@/lib/api";
import { addDays, ATTENTION_REASON, fmtDate, fmtPhone } from "@/lib/format";
import type { FollowUpRow } from "@/lib/types";

type View = "attention" | "upcoming" | "missed" | "completed" | "all";

function FollowUpsInner() {
  const qs = useSearchParams();
  const { can } = useAuth();
  const [view, setView] = useState<View>((qs.get("view") as View) || "attention");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => { const t = setTimeout(() => setQuery(q), 300); return () => clearTimeout(t); }, [q]);
  const { data, error, loading, reload } = useLoad(() => api<{ items: FollowUpRow[]; today: string }>("/api/followups", { params: { view, q: query } }), [view, query]);
  const [contactRow, setContactRow] = useState<FollowUpRow | null>(null);
  const [moveRow, setMoveRow] = useState<FollowUpRow | null>(null);
  const { busy, run } = useAction();
  const focus = qs.get("focus");

  const setStatus = (r: FollowUpRow, status: string, label: string) =>
    run(r.id + status, () => post(`/api/followups/${r.id}/status`, { status }), label).then((x) => x && reload());

  return (
    <div>
      <PageHeader title="Follow-ups" subtitle="Reminders go out on WhatsApp 7 and 3 days before each follow-up date." />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Tabs value={view} onChange={setView} items={[
          { value: "attention", label: "Needs a call" }, { value: "upcoming", label: "Upcoming" },
          { value: "missed", label: "Missed" }, { value: "completed", label: "Came back" }, { value: "all", label: "All" },
        ]} />
        <span className="relative mb-4 w-full sm:w-64">
          <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate" />
          <input className="input pl-9" placeholder="Search name or phone" value={q} onChange={(e) => setQ(e.target.value)} />
        </span>
      </div>

      <section className="panel overflow-hidden">
        {error ? <div className="p-4"><ErrorBox message={error} onRetry={reload} /></div> : !data || loading ? <Spinner /> : data.items.length === 0 ? (
          <Empty title={view === "attention" ? "Nobody needs a call right now" : "No follow-ups here"}>
            Follow-ups are set from an appointment, after the visit.
          </Empty>
        ) : (
          <ul className="divide-y divide-silver">
            {data.items.map((r) => {
              const open = ["scheduled", "confirmed", "reschedule_requested", "missed"].includes(r.status);
              return (
                <li key={r.id} className={cx("relative px-5 py-4 grid gap-3 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_auto] items-center",
                  focus === r.id && "bg-violet-wash/40")}>
                  {r.attention && <span className={cx("absolute left-0 top-3 bottom-3 w-[3px] rounded-full", r.attention === "red" ? "bg-alert" : "bg-caution")} aria-hidden />}
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link href={`/patients/${r.patient.id}`} className="font-medium hover:underline">{r.patient.name}</Link>
                      <FollowUpStatusBadge status={r.status} />
                      {r.attention && <Badge tone={r.attention === "red" ? "alert" : "caution"}>{ATTENTION_REASON[r.attention_reason || ""]}</Badge>}
                    </div>
                    <p className="text-sm text-muted mt-1">
                      <span className="font-medium text-ink">{fmtDate(r.due_date, { year: "numeric" })}</span>
                      {r.doctor && ` · ${r.doctor}`}
                      {open && r.days_to_due >= 0 && ` · in ${r.days_to_due} day${r.days_to_due === 1 ? "" : "s"}`}
                    </p>
                    <p className="text-xs text-muted mt-0.5">
                      <a href={`tel:${r.patient.phone}`} className="inline-flex items-center gap-1 num hover:text-ink"><Phone className="size-3" />{fmtPhone(r.patient.phone)}</a>
                      {!r.patient.whatsapp_opt_in && " · no WhatsApp consent (call instead)"}
                      {r.last_contact && ` · last contact: ${r.last_contact.outcome.replace("_", " ")}`}
                    </p>
                  </div>
                  <div className="px-6">{open && r.status !== "missed" && <ReminderRail compact dueDate={r.due_date} today={data.today} reminders={r.reminders} status={r.status} />}</div>
                  {can("followups:write") && open && (
                    <div className="flex flex-wrap gap-1.5 lg:justify-end">
                      <Button size="sm" onClick={() => setContactRow(r)}>Log call</Button>
                      <Button size="sm" onClick={() => setMoveRow(r)}>Change date</Button>
                      {r.status !== "confirmed" && r.status !== "missed" && <Button size="sm" loading={busy === r.id + "confirmed"} onClick={() => setStatus(r, "confirmed", "Marked confirmed")}>Confirmed</Button>}
                      {r.due_date <= addDays(data.today, 7) && <Button size="sm" variant="primary" loading={busy === r.id + "completed"} onClick={() => setStatus(r, "completed", "Marked as came back")}>Came back</Button>}
                      <Button size="sm" variant="ghost" loading={busy === r.id + "cancelled"} onClick={() => setStatus(r, "cancelled", "Follow-up cancelled")}>Cancel</Button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
      <ContactModal row={contactRow} open={!!contactRow} onClose={() => setContactRow(null)} onSaved={reload} />
      {moveRow && data && <MoveModal row={moveRow} today={data.today} onClose={() => setMoveRow(null)} onSaved={() => { setMoveRow(null); reload(); }} />}
    </div>
  );
}

function MoveModal({ row, today, onClose, onSaved }: { row: FollowUpRow; today: string; onClose: () => void; onSaved: () => void }) {
  const [date, setDate] = useState(row.due_date > today ? row.due_date : addDays(today, 7));
  const { busy, run } = useAction();
  return (
    <Modal open onClose={onClose} title={`New follow-up date for ${row.patient.name}`}>
      <div className="flex flex-col gap-4">
        <Field label="Follow-up date"><input type="date" className="input" min={addDays(today, 1)} value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <p className="text-sm text-muted">New reminders: {fmtDate(addDays(date, -7))} and {fmtDate(addDays(date, -3))}. Reminders for the old date are cancelled.</p>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={busy === "m"} onClick={async () => {
            const r = await run("m", () => post(`/api/followups/${row.id}/reschedule`, { due_date: date }), "Follow-up date changed");
            if (r) onSaved();
          }}>Save date</Button>
        </div>
      </div>
    </Modal>
  );
}

export default function FollowUpsPage() {
  return <Suspense><FollowUpsInner /></Suspense>;
}
