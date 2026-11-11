"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import { roleLabel } from "@/components/app-shell";
import { useAction, useAuth, useLoad } from "@/components/providers";
import { Badge, Button, ErrorBox, Field, Modal, PageHeader, Spinner } from "@/components/ui";
import { api, patch, post } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import type { User } from "@/lib/types";

export default function StaffPage() {
  const { me } = useAuth();
  const { data, error, reload } = useLoad(() => api<{ items: User[] }>("/api/staff"), []);
  const [adding, setAdding] = useState(false);
  const [pwFor, setPwFor] = useState<User | null>(null);
  const { busy, run } = useAction();
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;
  return (
    <div className="max-w-4xl">
      <PageHeader title="Staff" subtitle="Reception staff handle appointments and follow-ups. Admins also manage settings, WhatsApp and reports."
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>Add staff member</Button>} />
      <section className="panel overflow-hidden">
        <ul className="divide-y divide-silver">
          {data.items.map((u) => (
            <li key={u.id} className="px-5 py-4 flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="font-medium">{u.full_name} {u.id === me?.user.id && <span className="text-xs text-muted">(you)</span>}</p>
                <p className="text-sm text-muted">{u.email}</p>
                <p className="text-xs text-muted mt-0.5">{u.last_login_at ? `Last signed in ${fmtDateTime(u.last_login_at)}` : "Never signed in"}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={u.role === "hospital_admin" ? "violet" : "neutral"}>{roleLabel(u.role)}</Badge>
                {!u.is_active && <Badge tone="muted">Deactivated</Badge>}
                {u.id !== me?.user.id && (
                  <>
                    <Button size="sm" loading={busy === u.id + "r"} onClick={async () => { if (await run(u.id + "r", () => patch(`/api/staff/${u.id}`, { role: u.role === "staff" ? "hospital_admin" : "staff" }), "Role changed")) reload(); }}>
                      Make {u.role === "staff" ? "admin" : "staff"}
                    </Button>
                    <Button size="sm" onClick={() => setPwFor(u)}>Set password</Button>
                    <Button size="sm" variant={u.is_active ? "danger" : "secondary"} loading={busy === u.id + "a"}
                      onClick={async () => { if (await run(u.id + "a", () => patch(`/api/staff/${u.id}`, { is_active: !u.is_active }), u.is_active ? "Account deactivated" : "Account reactivated")) reload(); }}>
                      {u.is_active ? "Deactivate" : "Reactivate"}
                    </Button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>
      {adding && <AddModal onClose={() => setAdding(false)} onSaved={() => { setAdding(false); reload(); }} />}
      {pwFor && <PasswordModal user={pwFor} onClose={() => setPwFor(null)} />}
    </div>
  );
}

function AddModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ full_name: "", email: "", role: "staff", password: "" });
  const { busy, run } = useAction();
  return (
    <Modal open onClose={onClose} title="Add staff member">
      <div className="flex flex-col gap-4">
        <Field label="Full name"><input className="input" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
        <Field label="Email (used to sign in)"><input type="email" className="input" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="Role">
          <select className="input" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}><option value="staff">Reception staff</option><option value="hospital_admin">Hospital admin</option></select>
        </Field>
        <Field label="Temporary password" hint="At least 10 characters with an uppercase letter and a number. Share it privately; they can change it after signing in.">
          <input className="input" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete="new-password" />
        </Field>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={busy === "a"} onClick={async () => { if (await run("a", () => post("/api/staff", f), "Staff member added")) onSaved(); }}>Add staff member</Button>
        </div>
      </div>
    </Modal>
  );
}

function PasswordModal({ user, onClose }: { user: User; onClose: () => void }) {
  const [pw, setPw] = useState("");
  const { busy, run } = useAction();
  return (
    <Modal open onClose={onClose} title={`Set a new password for ${user.full_name}`}>
      <div className="flex flex-col gap-4">
        <p className="text-sm text-muted">They'll be signed out everywhere and must use this password next time.</p>
        <Field label="New password"><input className="input" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" /></Field>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={busy === "p"} onClick={async () => { if (await run("p", () => post(`/api/staff/${user.id}/password`, { password: pw }), "Password set")) onClose(); }}>Set password</Button>
        </div>
      </div>
    </Modal>
  );
}
