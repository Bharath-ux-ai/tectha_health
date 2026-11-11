"use client";

import { useEffect, useState } from "react";
import { api, post } from "@/lib/api";
import type { Appointment, Doctor } from "@/lib/types";
import { useAction } from "./providers";
import { Slot, SlotPicker } from "./slot-picker";
import { Button, Field, Modal } from "./ui";

export function useDoctors() {
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  useEffect(() => { api<{ items: Doctor[] }>("/api/doctors").then((d) => setDoctors(d.items)).catch(() => {}); }, []);
  return doctors;
}

export function DoctorDateSlot({ doctors, doctorId, setDoctorId, date, setDate, slot, setSlot, minDate }: {
  doctors: Doctor[]; doctorId: string; setDoctorId: (v: string) => void; date: string; setDate: (v: string) => void;
  slot: Slot | null; setSlot: (s: Slot | null) => void; minDate: string;
}) {
  return (
    <>
      <div className="grid sm:grid-cols-2 gap-4">
        <Field label="Doctor">
          <select className="input" value={doctorId} onChange={(e) => { setDoctorId(e.target.value); setSlot(null); }}>
            {doctors.map((d) => <option key={d.id} value={d.id}>{d.name}{d.specialty ? ` (${d.specialty})` : ""}</option>)}
          </select>
        </Field>
        <Field label="Date">
          <input type="date" className="input" min={minDate} value={date} onChange={(e) => { setDate(e.target.value); setSlot(null); }} />
        </Field>
      </div>
      {doctorId && date && (
        <div>
          <p className="label mb-2">Time</p>
          <SlotPicker url={`/api/appointments/slots?doctor_id=${doctorId}&date=${date}`} value={slot?.start_at || null} onChange={setSlot} />
        </div>
      )}
    </>
  );
}

export function RegisterAppointmentModal({ open, onClose, onCreated, today }:
  { open: boolean; onClose: () => void; onCreated: (a: Appointment) => void; today: string }) {
  const doctors = useDoctors();
  const [doctorId, setDoctorId] = useState("");
  const [date, setDate] = useState(today);
  const [slot, setSlot] = useState<Slot | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [language, setLanguage] = useState("en");
  const [consent, setConsent] = useState(false);
  const { busy, run } = useAction();
  useEffect(() => { if (!doctorId && doctors.length) setDoctorId(doctors[0].id); }, [doctors, doctorId]);
  useEffect(() => { if (open) setDate(today); }, [open, today]);
  const reset = () => { setSlot(null); setName(""); setPhone(""); setConsent(false); };
  return (
    <Modal open={open} onClose={onClose} title="Register an appointment" width="max-w-2xl">
      <div className="flex flex-col gap-5">
        {doctors.length === 0 ? <p className="text-sm text-muted">Add a doctor with a weekly schedule under Hospital &amp; doctors first.</p> : (
          <DoctorDateSlot doctors={doctors} doctorId={doctorId} setDoctorId={setDoctorId} date={date} setDate={setDate}
            slot={slot} setSlot={setSlot} minDate={today} />
        )}
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Patient name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></Field>
          <Field label="Mobile number" hint="Existing patients are matched by name and number.">
            <input className="input" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={16} />
          </Field>
          <Field label="Message language">
            <select className="input" value={language} onChange={(e) => setLanguage(e.target.value)}>
              <option value="en">English</option><option value="ta">தமிழ் (Tamil)</option>
            </select>
          </Field>
        </div>
        <label className="flex gap-3 items-start text-sm">
          <input type="checkbox" className="mt-0.5 size-4 accent-[#8a4fd8]" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>The patient agreed to receive appointment reminders on WhatsApp.<span className="block text-xs text-muted">Recorded as verbal consent with your name and the time.</span></span>
        </label>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!slot || name.trim().length < 2 || phone.replace(/\D/g, "").length < 10} loading={busy === "r"}
            onClick={async () => {
              const a = await run("r", () => post<Appointment>("/api/appointments", {
                doctor_id: doctorId, start_at: slot!.start_at, full_name: name, phone, language, whatsapp_consent: consent,
              }), "Appointment registered");
              if (a) { reset(); onCreated(a); }
            }}>Register appointment</Button>
        </div>
      </div>
    </Modal>
  );
}
