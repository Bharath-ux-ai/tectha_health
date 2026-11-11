"use client";

import { RefreshCw, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { useAction, useLoad } from "@/components/providers";
import { Badge, Button, cx, ErrorBox, Field, PageHeader, Spinner } from "@/components/ui";
import { api, post, put } from "@/lib/api";
import type { Tone } from "@/lib/format";

type Template = {
  id: string; kind: string; language: "en" | "ta"; requires_approval: boolean; meta_template_name: string | null; meta_language_code: string | null;
  category: string; body_text: string; button_confirm_text: string | null; button_reschedule_text: string | null; approval_status: string;
  rejection_reason: string | null; is_active: boolean; preview: string; placeholders: string[];
};

const KIND: Record<string, { title: string; text: string }> = {
  appointment_reminder: { title: "Appointment reminder", text: "Sent the evening before a visit, with Confirm and Reschedule buttons." },
  followup_reminder: { title: "Follow-up reminder", text: "Sent 7 and 3 days before a follow-up date." },
  confirm_reply: { title: "Reply after Confirm", text: "Sent right after the patient taps Confirm." },
  reschedule_reply: { title: "Reply after Reschedule", text: "Sent right after the patient taps Reschedule, with the booking link." },
};
const APPROVAL: Record<string, { label: string; tone: Tone }> = {
  not_submitted: { label: "Not submitted", tone: "muted" }, pending: { label: "Waiting for WhatsApp", tone: "caution" },
  approved: { label: "Approved", tone: "ok" }, rejected: { label: "Rejected", tone: "alert" }, paused: { label: "Paused by WhatsApp", tone: "alert" },
  not_required: { label: "No approval needed", tone: "neutral" },
};

export default function TemplatesPage() {
  const { data, error, reload, setData } = useLoad(() => api<{ items: Template[] }>("/api/whatsapp/templates"), []);
  const [selected, setSelected] = useState<string | null>(null);
  const { busy, run } = useAction();
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;
  const current = data.items.find((t) => t.id === selected) || data.items[0];
  const kinds = Object.keys(KIND);
  return (
    <div className="max-w-6xl">
      <PageHeader title="Message templates" subtitle="Short, polite messages in English and Tamil. Reminder templates must be approved by WhatsApp before live use."
        actions={<Button icon={<RefreshCw className="size-4" />} loading={busy === "sync"} onClick={async () => {
          const r = await run("sync", () => post<{ items: Template[]; updated: number }>("/api/whatsapp/templates/sync"));
          if (r) setData({ items: r.items });
        }}>Check approval status</Button>} />
      <div className="grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)]">
        <nav className="panel p-2 self-start" aria-label="Templates">
          {kinds.map((k) => (
            <div key={k} className="mb-1">
              <p className="px-3 pt-2 pb-1 text-xs text-muted">{KIND[k].title}</p>
              {data.items.filter((t) => t.kind === k).map((t) => (
                <button key={t.id} onClick={() => setSelected(t.id)} aria-current={current.id === t.id}
                  className={cx("w-full flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm text-left", current.id === t.id ? "bg-violet-wash text-ink" : "hover:bg-paper")}>
                  <span>{t.language === "ta" ? "தமிழ் Tamil" : "English"}</span>
                  <Badge tone={APPROVAL[t.approval_status]?.tone}>{APPROVAL[t.approval_status]?.label}</Badge>
                </button>
              ))}
            </div>
          ))}
        </nav>
        {current && <Editor key={current.id} t={current} onSaved={(t) => setData({ items: data.items.map((x) => (x.id === t.id ? t : x)) })} />}
      </div>
    </div>
  );
}

function Editor({ t, onSaved }: { t: Template; onSaved: (t: Template) => void }) {
  const [body, setBody] = useState(t.body_text);
  const [confirmText, setConfirmText] = useState(t.button_confirm_text || "");
  const [reschedText, setReschedText] = useState(t.button_reschedule_text || "");
  const [name, setName] = useState(t.meta_template_name || "");
  const { busy, run } = useAction();
  useEffect(() => { setBody(t.body_text); }, [t.body_text]);
  const changed = body !== t.body_text || confirmText !== (t.button_confirm_text || "") || reschedText !== (t.button_reschedule_text || "") || name !== (t.meta_template_name || "");
  return (
    <section className="panel p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">{KIND[t.kind].title} — {t.language === "ta" ? "Tamil" : "English"}</h2>
          <p className="text-sm text-muted mt-0.5">{KIND[t.kind].text}</p>
        </div>
        <Badge tone={APPROVAL[t.approval_status]?.tone}>{APPROVAL[t.approval_status]?.label}</Badge>
      </div>
      {t.rejection_reason && <p className="mt-3 text-sm text-alert">WhatsApp: {t.rejection_reason}</p>}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px] mt-5">
        <div className="flex flex-col gap-4">
          <Field label="Message text" hint={<>Placeholders: {t.placeholders.map((p, i) => <code key={p} className="mr-2">{t.requires_approval ? `{{${i + 1}}} ${p}` : p}</code>)}</>}>
            <textarea className="input font-[inherit]" rows={6} value={body} onChange={(e) => setBody(e.target.value)} maxLength={1024} lang={t.language} />
          </Field>
          {t.requires_approval && (
            <div className="grid sm:grid-cols-2 gap-4">
              <Field label="Confirm button"><input className="input" maxLength={25} value={confirmText} onChange={(e) => setConfirmText(e.target.value)} /></Field>
              <Field label="Reschedule button"><input className="input" maxLength={25} value={reschedText} onChange={(e) => setReschedText(e.target.value)} /></Field>
              <div className="sm:col-span-2"><Field label="WhatsApp template name" hint="Must match the template name in WhatsApp Manager."><input className="input num" value={name} onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"))} /></Field></div>
            </div>
          )}
          {t.requires_approval && changed && <p className="text-xs text-caution">Saving new wording needs WhatsApp approval again before live reminders can use it.</p>}
          <div className="flex flex-wrap gap-2 justify-end">
            <Button variant="primary" disabled={!changed} loading={busy === "save"} onClick={async () => {
              const r = await run("save", () => put<Template>(`/api/whatsapp/templates/${t.id}`, {
                body_text: body, ...(t.requires_approval ? { button_confirm_text: confirmText, button_reschedule_text: reschedText, meta_template_name: name } : {}),
              }), "Template saved");
              if (r) onSaved(r);
            }}>Save</Button>
            {t.requires_approval && (
              <Button icon={<Send className="size-4" />} disabled={changed || t.approval_status === "approved" || t.approval_status === "pending"} loading={busy === "submit"}
                onClick={async () => { const r = await run("submit", () => post<Template>(`/api/whatsapp/templates/${t.id}/submit`), "Sent to WhatsApp for approval"); if (r) onSaved(r); }}>
                Submit for approval
              </Button>
            )}
          </div>
        </div>
        <div>
          <p className="label mb-2">Preview</p>
          <div className="rounded-2xl bg-[#ece5dd] p-4">
            <div className="rounded-xl rounded-tl-sm bg-white p-3 text-sm shadow-sm whitespace-pre-line" lang={t.language}>{t.preview}</div>
            {t.requires_approval && (
              <div className="mt-1 grid gap-1">
                {[confirmText, reschedText].map((b, i) => <div key={i} className="rounded-xl bg-white py-2 text-center text-sm text-[#0a7cff] shadow-sm">{b}</div>)}
              </div>
            )}
          </div>
          <p className="text-xs text-muted mt-2">Example values shown. Category: {t.category.toLowerCase()}.</p>
        </div>
      </div>
    </section>
  );
}
