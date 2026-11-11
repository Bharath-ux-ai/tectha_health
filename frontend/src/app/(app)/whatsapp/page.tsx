"use client";

import { CheckCircle2, Circle, Copy } from "lucide-react";
import { useEffect, useState } from "react";
import { useAction, useLoad, useToast } from "@/components/providers";
import { Badge, Button, cx, ErrorBox, Field, PageHeader, Spinner } from "@/components/ui";
import { api, post, put } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

type Config = {
  mode: "disabled" | "test" | "live"; phone_number_id: string | null; business_account_id: string | null; display_phone_number: string | null;
  token_set: boolean; token_last4: string | null; test_recipient_allowlist: string[]; last_verified_at: string | null; last_error: string | null;
  webhook_url: string; is_demo: boolean;
  platform: { app_secret_set: boolean; verify_token_set: boolean; graph_version: string; live_messaging_enabled: boolean };
  readiness: { key: string; ok: boolean; label: string }[];
};

const MODES = [
  { value: "test", title: "Test mode", text: "Reminders are created and shown here, but nothing is sent to patients. Use this while setting up." },
  { value: "live", title: "Live", text: "Reminders are sent to patients through the WhatsApp Business Platform." },
  { value: "disabled", title: "Off", text: "No reminders are created or sent." },
] as const;

export default function WhatsAppPage() {
  const { data, error, reload, setData } = useLoad(() => api<Config>("/api/whatsapp/config"), []);
  const [form, setForm] = useState({ phone_number_id: "", business_account_id: "", access_token: "", allowlist: "" });
  const [testPhone, setTestPhone] = useState("");
  const { busy, run } = useAction();
  const toast = useToast();
  useEffect(() => {
    if (data) setForm((f) => ({ ...f, phone_number_id: data.phone_number_id || "", business_account_id: data.business_account_id || "", allowlist: data.test_recipient_allowlist.join(", ") }));
  }, [data]);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;

  const save = async (extra: Record<string, unknown> = {}, msg = "WhatsApp settings saved") => {
    const r = await run("save", () => put<Config>("/api/whatsapp/config", {
      phone_number_id: form.phone_number_id, business_account_id: form.business_account_id,
      access_token: form.access_token || undefined,
      test_recipient_allowlist: form.allowlist.split(/[,\n]/).map((s) => s.trim()).filter(Boolean), ...extra,
    }), msg);
    if (r) { setData(r); setForm((f) => ({ ...f, access_token: "" })); }
  };

  return (
    <div className="max-w-4xl">
      <PageHeader title="WhatsApp setup" subtitle="Connect your hospital's WhatsApp Business number so reminders reach patients." />

      <section className="panel p-5">
        <h2 className="font-semibold mb-3">Sending mode</h2>
        <div className="grid sm:grid-cols-3 gap-3">
          {MODES.map((m) => (
            <button key={m.value} onClick={() => m.value !== data.mode && save({ mode: m.value }, `Switched to ${m.title.toLowerCase()}`)}
              className={cx("text-left rounded-xl border p-4 transition-colors", data.mode === m.value ? "border-violet bg-violet-wash/50" : "border-silver-2 hover:border-slate")}
              aria-pressed={data.mode === m.value}>
              <p className="font-medium flex items-center gap-2">{data.mode === m.value ? <CheckCircle2 className="size-4 text-violet" /> : <Circle className="size-4 text-slate" />}{m.title}</p>
              <p className="text-xs text-muted mt-1.5">{m.text}</p>
            </button>
          ))}
        </div>
        {!data.platform.live_messaging_enabled && <p className="mt-3 text-sm text-caution">The platform team has paused live sending for all hospitals. Reminders wait and go out when it resumes.</p>}
      </section>

      <section className="panel p-5 mt-6">
        <h2 className="font-semibold mb-1">Setup checklist</h2>
        <p className="text-sm text-muted mb-4">Live sending needs all four.</p>
        <ul className="flex flex-col gap-2">
          {data.readiness.map((r) => (
            <li key={r.key} className="flex items-center gap-2.5 text-sm">
              {r.ok ? <CheckCircle2 className="size-4 text-ok" /> : <Circle className="size-4 text-slate" />}<span className={r.ok ? "" : "text-muted"}>{r.label}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel p-5 mt-6 flex flex-col gap-4">
        <div>
          <h2 className="font-semibold">Business number credentials</h2>
          <p className="text-sm text-muted mt-1">From Meta WhatsApp Manager → API setup. The access token should be a permanent System User token with the <code>whatsapp_business_messaging</code> and <code>whatsapp_business_management</code> permissions.</p>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Phone number ID"><input className="input num" inputMode="numeric" value={form.phone_number_id} onChange={(e) => setForm({ ...form, phone_number_id: e.target.value.replace(/\D/g, "") })} /></Field>
          <Field label="WhatsApp Business Account ID"><input className="input num" inputMode="numeric" value={form.business_account_id} onChange={(e) => setForm({ ...form, business_account_id: e.target.value.replace(/\D/g, "") })} /></Field>
          <div className="sm:col-span-2">
            <Field label="Access token" hint={data.token_set ? `A token ending in …${data.token_last4} is saved (encrypted). Leave blank to keep it.` : "Stored encrypted. It is never shown again after saving."}>
              <input className="input" type="password" autoComplete="off" value={form.access_token} onChange={(e) => setForm({ ...form, access_token: e.target.value })} placeholder={data.token_set ? "••••••••••••" : "EAAG…"} />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field label="Test phones" hint={data.is_demo ? "Demo clinic: real messages go only to these numbers (e.g. the hospital owner's phone during a demo)." : "Phones allowed to receive test messages. Separate with commas."}>
              <input className="input" value={form.allowlist} onChange={(e) => setForm({ ...form, allowlist: e.target.value })} placeholder="98765 43210" />
            </Field>
          </div>
        </div>
        {data.last_error && <ErrorBox message={data.last_error} />}
        {data.last_verified_at && !data.last_error && <p className="text-sm text-ok">Verified {fmtDateTime(data.last_verified_at)}{data.display_phone_number && ` — sending from ${data.display_phone_number}`}.</p>}
        <div className="flex flex-wrap justify-end gap-2">
          <Button loading={busy === "verify"} disabled={!data.token_set || !data.phone_number_id} onClick={async () => {
            const r = await run("verify", () => post<{ ok: boolean; error: string | null; config: Config }>("/api/whatsapp/config/verify"));
            if (r) { setData(r.config); toast(r.ok ? "ok" : "error", r.ok ? "WhatsApp accepted the credentials" : r.error || "Verification failed"); }
          }}>Check connection</Button>
          <Button variant="primary" loading={busy === "save"} onClick={() => save()}>Save</Button>
        </div>
      </section>

      <section className="panel p-5 mt-6 flex flex-col gap-3">
        <h2 className="font-semibold">Send a real test message</h2>
        <p className="text-sm text-muted">Sends the approved appointment reminder to a phone on your test list, to check everything end to end.</p>
        <div className="flex flex-wrap gap-2">
          <input className="input max-w-xs" placeholder="98765 43210" value={testPhone} onChange={(e) => setTestPhone(e.target.value)} />
          <Button loading={busy === "test"} disabled={!testPhone} onClick={async () => {
            const r = await run("test", () => post<{ ok: boolean; error: string | null }>("/api/whatsapp/test-message", { phone: testPhone }));
            if (r) toast(r.ok ? "ok" : "error", r.ok ? "WhatsApp accepted the test message" : r.error || "Not sent");
          }}>Send test message</Button>
        </div>
      </section>

      <section className="panel p-5 mt-6">
        <h2 className="font-semibold">Webhook (for your TEC THA administrator)</h2>
        <p className="text-sm text-muted mt-1 mb-3">Delivery receipts and Confirm / Reschedule taps arrive here. Subscribe the Meta app to the <code>messages</code> field.</p>
        <div className="flex items-center gap-2">
          <code className="flex-1 min-w-0 truncate rounded-lg bg-paper border border-silver px-3 py-2 text-sm">{data.webhook_url}</code>
          <Button size="sm" icon={<Copy className="size-3.5" />} onClick={() => navigator.clipboard.writeText(data.webhook_url).then(() => toast("ok", "Copied"))}>Copy</Button>
        </div>
        <div className="flex flex-wrap gap-2 mt-3">
          <Badge tone={data.platform.app_secret_set ? "ok" : "alert"}>App secret {data.platform.app_secret_set ? "configured" : "missing on server"}</Badge>
          <Badge tone={data.platform.verify_token_set ? "ok" : "alert"}>Verify token {data.platform.verify_token_set ? "configured" : "missing on server"}</Badge>
          <Badge>Graph API {data.platform.graph_version}</Badge>
        </div>
      </section>
    </div>
  );
}
