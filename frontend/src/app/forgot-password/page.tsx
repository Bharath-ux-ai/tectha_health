"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { AuthShell } from "@/components/auth-shell";
import { Button, ErrorBox, Field } from "@/components/ui";
import { post } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ message: string }>("/api/auth/forgot-password", { email });
      setSent(r.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send the link.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell title="Reset your password" subtitle="We'll email you a link that works for 30 minutes.">
      {sent ? (
        <div className="flex flex-col gap-4">
          <p className="text-sm rounded-xl bg-ok-wash text-ok px-4 py-3">{sent}</p>
          <p className="text-sm text-muted">No email? Your hospital admin can also set a new password for you from Staff.</p>
          <Link href="/login" className="text-sm text-violet-deep hover:underline">Back to sign in</Link>
        </div>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-4">
          {error && <ErrorBox message={error} />}
          <Field label="Email" htmlFor="email">
            <input id="email" type="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </Field>
          <Button type="submit" variant="primary" loading={busy} disabled={!email}>Email me a reset link</Button>
          <Link href="/login" className="text-sm text-violet-deep hover:underline self-start">Back to sign in</Link>
        </form>
      )}
    </AuthShell>
  );
}
