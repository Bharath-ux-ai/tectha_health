"use client";

import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { AppointmentActions, AppointmentStatusBadge } from "@/components/appointment-bits";
import { useAuth, useLoad } from "@/components/providers";
import { RegisterAppointmentModal, useDoctors } from "@/components/register-appointment";
import { Button, Empty, ErrorBox, PageHeader, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { APPOINTMENT_STATUS, fmtDate, fmtPhone, fmtTime } from "@/lib/format";
import type { Appointment } from "@/lib/types";

type List = { items: Appointment[]; total: number; page: number; page_size: number; date_from: string; date_to: string; today: string };

function AppointmentsInner() {
  const qs = useSearchParams();
  const { can, me } = useAuth();
  const doctors = useDoctors();
  const [from, setFrom] = useState(qs.get("date") || "");
  const [to, setTo] = useState(qs.get("date") || "");
  const [status, setStatus] = useState("");
  const [doctorId, setDoctorId] = useState("");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [registerOpen, setRegisterOpen] = useState(false);
  useEffect(() => { const t = setTimeout(() => { setQuery(q); setPage(1); }, 300); return () => clearTimeout(t); }, [q]);
  const { data, error, loading, reload } = useLoad(() => api<List>("/api/appointments", {
    params: { date_from: from || undefined, date_to: to || from || undefined, status, doctor_id: doctorId, q: query, page },
  }), [from, to, status, doctorId, query, page]);
  const today = data?.today || "";
  useEffect(() => { if (data && !from) { setFrom(data.date_from); setTo(data.date_to); } }, [data, from]);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div>
      <PageHeader title="Appointments" subtitle={me?.hospital ? <>Patients book at <a className="text-violet-deep hover:underline" href={me.hospital.booking_link} target="_blank" rel="noreferrer">{me.hospital.booking_link.replace(/^https?:\/\//, "")}</a></> : undefined}
        actions={can("appointments:write") && <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setRegisterOpen(true)}>Register appointment</Button>} />

      <div className="panel p-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-[1.4fr_repeat(4,minmax(0,1fr))] items-end">
        <label className="flex flex-col gap-1.5">
          <span className="label">Search</span>
          <span className="relative">
            <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate" />
            <input className="input pl-9" placeholder="Name, phone or reference" value={q} onChange={(e) => setQ(e.target.value)} />
          </span>
        </label>
        <label className="flex flex-col gap-1.5"><span className="label">From</span>
          <input type="date" className="input" value={from} onChange={(e) => { setFrom(e.target.value); if (!to || e.target.value > to) setTo(e.target.value); setPage(1); }} /></label>
        <label className="flex flex-col gap-1.5"><span className="label">To</span>
          <input type="date" className="input" value={to} min={from} onChange={(e) => { setTo(e.target.value); setPage(1); }} /></label>
        <label className="flex flex-col gap-1.5"><span className="label">Status</span>
          <select className="input" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All</option>
            <option value="pending">Awaiting confirmation</option>
            {Object.entries(APPOINTMENT_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select></label>
        <label className="flex flex-col gap-1.5"><span className="label">Doctor</span>
          <select className="input" value={doctorId} onChange={(e) => { setDoctorId(e.target.value); setPage(1); }}>
            <option value="">All doctors</option>
            {doctors.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select></label>
      </div>

      <section className="panel mt-4 overflow-hidden">
        {error ? <div className="p-4"><ErrorBox message={error} onRetry={reload} /></div> : !data || loading ? <Spinner /> : data.items.length === 0 ? (
          <Empty title="No appointments match">Change the dates or filters.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-silver bg-paper/60">
                <tr>
                  {["When", "Patient", "Doctor", "Reference", "Status", ""].map((h) => <th key={h} className="table-head px-4 py-2.5">{h}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-silver">
                {data.items.map((a) => (
                  <tr key={a.id} className="hover:bg-paper/50">
                    <td className="px-4 py-3 whitespace-nowrap"><span className="num font-medium">{fmtTime(a.local_time)}</span><span className="block text-xs text-muted">{fmtDate(a.local_date)}</span></td>
                    <td className="px-4 py-3"><Link href={`/appointments/${a.id}`} className="font-medium hover:underline">{a.patient.name}</Link>
                      <span className="block text-xs text-muted num">{fmtPhone(a.patient.phone)}</span></td>
                    <td className="px-4 py-3 whitespace-nowrap">{a.doctor.name}</td>
                    <td className="px-4 py-3 num text-muted whitespace-nowrap">{a.reference}</td>
                    <td className="px-4 py-3"><AppointmentStatusBadge status={a.status} /></td>
                    <td className="px-4 py-3">{can("appointments:write") && today && <AppointmentActions appt={a} today={today} onChanged={reload} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > data.page_size && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-silver text-sm">
            <span className="text-muted">{data.total} appointments</span>
            <div className="flex gap-2">
              <Button size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
              <span className="self-center num">{page} / {pages}</span>
              <Button size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
            </div>
          </div>
        )}
      </section>
      {today && <RegisterAppointmentModal open={registerOpen} onClose={() => setRegisterOpen(false)} today={today}
        onCreated={() => { setRegisterOpen(false); reload(); }} />}
    </div>
  );
}

export default function AppointmentsPage() {
  return <Suspense><AppointmentsInner /></Suspense>;
}
