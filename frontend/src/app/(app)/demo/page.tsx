"use client";

import { ExternalLink, Play, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useAction, useAuth, useLoad } from "@/components/providers";
import { Badge, Button, cx, ErrorBox, Field, PageHeader, Spinner } from "@/components/ui";
import { api, post } from "@/lib/api";
import { fmtDate, fmtDateTime, MESSAGE_STATUS } from "@/lib/format";

type Step = { key: string; title: string; detail: string; at: string | null; run_engine: boolean };
type State = {
  local_now: string; now: string; start_monday: string; scenario: Record<string, string>; steps: Step[];
  whatsapp_mode: string; allowlist: string[];
  ravi: { id: string; name: string; phone: string } | null;
  ravi_messages: { id: string; direction: string; status: string; body: string; is_simulated: boolean; at: string; has_buttons: boolean }[];
};

export default function DemoPage() {
  const { me } = useAuth();
  const { data: s, error, reload, setData } = useLoad(() => api<State>("/api/demo"), []);
  const { busy, run } = useAction();
  const [clock, setClock] = useState("");
  const [start, setStart] = useState("");
  const [done, setDone] = useState<string[]>([]);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!s) return <Spinner />;
  const notify = () => window.dispatchEvent(new Event("tt:demo-clock"));
  const apply = (st: State) => { setData(st); notify(); };
  const link = me?.hospital?.booking_link || "#";

  return (
    <div className="max-w-6xl">
      <PageHeader title="Demo controls" subtitle="Walk a hospital owner through Mr. Ravi's story. All patients here are fictional."
        actions={<>
          <a href={link} target="_blank" rel="noreferrer"><Button icon={<ExternalLink className="size-4" />}>Open booking page</Button></a>
          <Link href="/dashboard"><Button>Open dashboard</Button></Link>
        </>} />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <section className="panel p-5 sm:p-6">
          <div className="flex flex-wrap items-baseline justify-between gap-2 mb-5">
            <h2 className="font-semibold">The story</h2>
            <p className="text-sm text-muted">Demo clock: <span className="font-medium text-ink num">{s.local_now}</span></p>
          </div>
          <ol className="relative flex flex-col gap-1">
            {s.steps.map((st, i) => {
              const isDone = done.includes(st.key);
              const isNext = s.steps.find((x) => !done.includes(x.key))?.key === st.key;
              return (
                <li key={st.key} className="relative grid grid-cols-[2rem_minmax(0,1fr)_auto] gap-3 items-start py-3">
                  {i < s.steps.length - 1 && <span className="absolute left-[15px] top-11 bottom-[-4px] w-px bg-silver-2" aria-hidden />}
                  <span className={cx("num size-8 rounded-full grid place-items-center text-sm font-semibold border-2",
                    isDone ? "bg-violet border-violet text-white" : "bg-white border-silver-2 text-ink-2")}>{i + 1}</span>
                  <div className="min-w-0">
                    <p className="font-medium">{st.title}</p>
                    <p className="text-sm text-muted">{st.detail}</p>
                    {st.at && <p className="text-xs text-muted mt-0.5">Clock → {fmtDateTime(st.at)}</p>}
                  </div>
                  <Button size="sm" variant={isNext ? "primary" : "secondary"} icon={<Play className="size-3.5" />} loading={busy === st.key}
                    onClick={async () => {
                      const r = await run(st.key, () => post<{ state: State }>("/api/demo/step", { key: st.key }), `${st.title}: done`);
                      if (r) { apply(r.state); setDone((d) => [...new Set([...d, st.key])]); if (st.key === "book") window.open(link, "_blank"); }
                    }}>
                    {st.key === "book" ? "Set clock & open page" : "Run"}
                  </Button>
                </li>
              );
            })}
          </ol>
          <p className="text-xs text-muted mt-4">Follow-up on {fmtDate(s.scenario.follow_up, { year: "numeric" })}; reminders on {fmtDate(s.scenario.reminder_7d)} and {fmtDate(s.scenario.reminder_3d)}.
            Step 4 can also be done by hand from Ravi&apos;s appointment, to show the staff screen.</p>
        </section>

        <div className="flex flex-col gap-6">
          <section className="panel p-5">
            <h2 className="font-semibold mb-1">Ravi&apos;s WhatsApp</h2>
            <p className="text-xs text-muted mb-4">{s.whatsapp_mode === "live" ? `Live: real messages go only to ${s.allowlist.join(", ")}.` : "Test mode: messages are simulated and never leave the server."}</p>
            {!s.ravi ? <p className="text-sm text-muted">Book as &ldquo;Ravi&rdquo; on the booking page first.</p> : s.ravi_messages.length === 0 ? <p className="text-sm text-muted">No messages yet. Run step 2.</p> : (
              <ul className="flex flex-col gap-3 rounded-2xl bg-[#ece5dd] p-3 max-h-[28rem] overflow-y-auto">
                {s.ravi_messages.map((m) => (
                  <li key={m.id} className={cx("max-w-[88%]", m.direction === "inbound" ? "self-end" : "self-start")}>
                    <div className={cx("rounded-xl px-3 py-2 text-sm shadow-sm", m.direction === "inbound" ? "bg-[#d9fdd3] rounded-tr-sm" : "bg-white rounded-tl-sm")}>{m.body}</div>
                    {m.has_buttons && (
                      <div className="grid grid-cols-2 gap-1 mt-1">
                        {(["C", "R"] as const).map((a) => (
                          <button key={a} disabled={busy !== null || s.whatsapp_mode === "live"} className="rounded-lg bg-white py-1.5 text-xs text-[#0a7cff] shadow-sm disabled:opacity-50"
                            onClick={async () => { const r = await run(m.id + a, () => post<{ state: State }>("/api/demo/simulate-reply", { message_id: m.id, action: a }), a === "C" ? "Confirm tapped" : "Reschedule tapped"); if (r) apply(r.state); }}>
                            {a === "C" ? "Confirm" : "Reschedule"}
                          </button>
                        ))}
                      </div>
                    )}
                    <p className="text-[10px] text-muted mt-0.5">{fmtDateTime(m.at)} · {m.direction === "inbound" ? (m.is_simulated ? "simulated tap" : "received") : MESSAGE_STATUS[m.status]?.label}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="panel p-5 flex flex-col gap-4">
            <h2 className="font-semibold">Clock and reset</h2>
            <Field label="Set the demo clock (hospital time)">
              <div className="flex gap-2">
                <input type="datetime-local" className="input" value={clock} onChange={(e) => setClock(e.target.value)} />
                <Button disabled={!clock} loading={busy === "clock"} onClick={async () => { const r = await run("clock", () => post<State>("/api/demo/clock", { local_datetime: clock }), "Clock set"); if (r) apply(r); }}>Set</Button>
              </div>
            </Field>
            <Button loading={busy === "engine"} onClick={async () => { const r = await run("engine", () => post("/api/demo/run-engine"), "Reminder engine ran"); if (r) reload(); }}>Run reminder engine now</Button>
            <div className="border-t border-silver pt-4">
              <Field label="Demo week starts on (a Monday)" hint="Reset removes all demo patients, then replays two weeks of history so the monthly report has numbers.">
                <div className="flex gap-2">
                  <input type="date" className="input" value={start || s.start_monday} onChange={(e) => setStart(e.target.value)} />
                  <Button variant="danger" icon={<RotateCcw className="size-4" />} loading={busy === "reset"} onClick={async () => {
                    const r = await run("reset", () => post<State>("/api/demo/reset", { start_monday: start || s.start_monday }), "Demo reset");
                    if (r) { apply(r); setDone([]); }
                  }}>Reset demo</Button>
                </div>
              </Field>
            </div>
            <p className="text-xs text-muted">To send a real reminder to the owner&apos;s phone: add it under <Link href="/whatsapp" className="text-violet-deep hover:underline">WhatsApp setup → Test phones</Link>, switch to Live, and book as Ravi with that number. <Badge tone="violet">Needs approved templates</Badge></p>
          </section>
        </div>
      </div>
    </div>
  );
}
