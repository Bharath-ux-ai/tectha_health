"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { AuthShell } from "@/components/auth-shell";
import { useAuth } from "@/components/providers";
import { Button, ErrorBox, Field } from "@/components/ui";
import { post } from "@/lib/api";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { me, loading, refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && me) router.replace(me.user.role === "system_admin" ? "/system" : "/dashboard");
  }, [me, loading, router]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/api/auth/login", { email, password });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell title="Sign in" subtitle="Use the account your hospital admin created for you.">
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        {params.get("expired") && !error && <p className="text-sm text-muted">Your session ended. Sign in again to continue.</p>}
        {params.get("reset") && <p className="text-sm text-ok">Password changed. Sign in with your new password.</p>}
        {error && <ErrorBox message={error} />}
        <Field label="Email" htmlFor="email">
          <input id="email" type="email" autoComplete="username" className="input" value={email}
            onChange={(e) => setEmail(e.target.value)} required />
        </Field>
        <Field label="Password" htmlFor="password">
          <input id="password" type="password" autoComplete="current-password" className="input" value={password}
            onChange={(e) => setPassword(e.target.value)} required />
        </Field>
        <Button type="submit" variant="primary" loading={busy} disabled={!email || !password} className="mt-2">Sign in</Button>
        <Link href="/forgot-password" className="text-sm text-violet-deep hover:underline self-start">Forgot your password?</Link>
      </form>
    </AuthShell>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
