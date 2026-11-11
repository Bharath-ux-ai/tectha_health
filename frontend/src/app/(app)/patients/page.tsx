"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useLoad } from "@/components/providers";
import { Badge, Empty, ErrorBox, PageHeader, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, fmtPhone } from "@/lib/format";

type P = { id: string; full_name: string; phone: string; preferred_language: string; whatsapp_opt_in: boolean; last_appointment_at: string | null };

export default function PatientsPage() {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => { const t = setTimeout(() => setQuery(q), 300); return () => clearTimeout(t); }, [q]);
  const { data, error, loading, reload } = useLoad(() => api<{ items: P[]; total: number }>("/api/patients", { params: { q: query } }), [query]);
  return (
    <div>
      <PageHeader title="Patients" subtitle="Contact details and reminder preferences. No medical records are kept here." />
      <span className="relative block max-w-md mb-4">
        <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate" />
        <input className="input pl-9" placeholder="Search by name or mobile number" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
      </span>
      <section className="panel overflow-hidden">
        {error ? <div className="p-4"><ErrorBox message={error} onRetry={reload} /></div> : !data || loading ? <Spinner /> : data.items.length === 0 ? (
          <Empty title={query ? "No patient matches" : "No patients yet"}>Patients are added when they book online or reception registers an appointment.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-silver bg-paper/60">
                <tr>{["Name", "Mobile", "Language", "WhatsApp", "Last appointment"].map((h) => <th key={h} className="table-head px-4 py-2.5">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-silver">
                {data.items.map((p) => (
                  <tr key={p.id} className="hover:bg-paper/50">
                    <td className="px-4 py-3"><Link href={`/patients/${p.id}`} className="font-medium hover:underline">{p.full_name}</Link></td>
                    <td className="px-4 py-3 num whitespace-nowrap">{fmtPhone(p.phone)}</td>
                    <td className="px-4 py-3">{p.preferred_language === "ta" ? "Tamil" : "English"}</td>
                    <td className="px-4 py-3">{p.whatsapp_opt_in ? <Badge tone="ok">Agreed</Badge> : <Badge tone="muted">Not agreed</Badge>}</td>
                    <td className="px-4 py-3 text-muted whitespace-nowrap">{fmtDate(p.last_appointment_at, { year: "numeric" })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.total > data.items.length && <p className="px-4 py-3 text-xs text-muted border-t border-silver">Showing {data.items.length} of {data.total}. Search to narrow down.</p>}
          </div>
        )}
      </section>
    </div>
  );
}
