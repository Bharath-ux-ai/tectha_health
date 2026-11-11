"use client";

import { useState } from "react";
import { roleLabel } from "@/components/app-shell";
import { useAction, useAuth } from "@/components/providers";
import { Button, Field, PageHeader } from "@/components/ui";
import { post } from "@/lib/api";

export default function AccountPage() {
  const { me, logout } = useAuth();
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const { busy, run } = useAction();
  if (!me) return null;
  return (
    <div className="max-w-xl">
      <PageHeader title="Your account" subtitle={`${me.user.full_name} · ${me.user.email} · ${roleLabel(me.user.role)}`} />
      <section className="panel p-5 flex flex-col gap-4">
        <h2 className="font-semibold">Change password</h2>
        <Field label="Current password"><input type="password" className="input" value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" /></Field>
        <Field label="New password" hint="At least 10 characters, with an uppercase letter and a number."><input type="password" className="input" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" /></Field>
        <Field label="Repeat new password" error={pw2 && pw !== pw2 ? "Passwords don't match." : null}><input type="password" className="input" value={pw2} onChange={(e) => setPw2(e.target.value)} autoComplete="new-password" /></Field>
        <div className="flex justify-end">
          <Button variant="primary" disabled={!cur || !pw || pw !== pw2} loading={busy === "p"} onClick={async () => {
            if (await run("p", () => post("/api/auth/change-password", { current_password: cur, new_password: pw }), "Password changed. Other devices were signed out.")) { setCur(""); setPw(""); setPw2(""); }
          }}>Change password</Button>
        </div>
      </section>
      <section className="panel p-5 mt-6 flex items-center justify-between gap-4">
        <div><h2 className="font-semibold">Sign out everywhere</h2><p className="text-sm text-muted">Ends your sessions on every device, including this one.</p></div>
        <Button variant="danger" loading={busy === "all"} onClick={async () => { if (await run("all", () => post("/api/auth/logout-all"))) logout(); }}>Sign out everywhere</Button>
      </section>
    </div>
  );
}
