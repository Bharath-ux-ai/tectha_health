"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { AuthShell } from "@/components/auth-shell";
import { Button, ErrorBox, Field } from "@/components/ui";
import { post } from "@/lib/api";

function ResetForm() {
  const token = useSearchParams().get("token") || "";
  const router = useRouter();
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (pw !== pw2) return setError("The two passwords don't match.");
    setBusy(true);
    setError(null);
    try {
      await post("/api/auth/reset-password", { token, new_password: pw });
      router.replace("/login?reset=1");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset the password.");
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <AuthShell title="Link incomplete" subtitle="Open the full link from the email, or request a new one.">
        <Link href="/forgot-password" className="text-sm text-violet-deep hover:underline">Request a new link</Link>
      </AuthShell>
    );
  }
  return (
    <AuthShell title="Choose a new password" subtitle="At least 10 characters, with an uppercase letter and a number.">
      <form onSubmit={submit} className="flex flex-col gap-4">
        {error && <ErrorBox message={error} />}
        <Field label="New password" htmlFor="pw">
          <input id="pw" type="password" autoComplete="new-password" className="input" value={pw} onChange={(e) => setPw(e.target.value)} />
        </Field>
        <Field label="Repeat new password" htmlFor="pw2">
          <input id="pw2" type="password" autoComplete="new-password" className="input" value={pw2} onChange={(e) => setPw2(e.target.value)} />
        </Field>
        <Button type="submit" variant="primary" loading={busy} disabled={!pw || !pw2}>Save new password</Button>
      </form>
    </AuthShell>
  );
}

export default function ResetPasswordPage() {
  return <Suspense><ResetForm /></Suspense>;
}
