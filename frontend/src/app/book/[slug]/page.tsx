"use client";

import { CalendarCheck2, MapPin, Phone } from "lucide-react";
import { use, useEffect, useMemo, useState } from "react";
import { Slot, SlotPicker } from "@/components/slot-picker";
import { Button, cx, ErrorBox, Spinner } from "@/components/ui";
import { api, ApiError, post } from "@/lib/api";
import { fmtTime } from "@/lib/format";

type Lang = "en" | "ta";
type Profile = { name: string; address: string | null; phone: string | null; today: string; booking_horizon_days: number;
  default_language: Lang; is_demo: boolean; doctors: { id: string; name: string; specialty: string | null }[] };
type Confirmation = { reference: string; hospital: string; doctor: string; date: string; time: string; patient_name: string;
  whatsapp_reminder: boolean; hospital_phone: string | null; address: string | null };

const T = {
  en: {
    book: "Book an appointment", doctor: "Doctor", day: "Day", time: "Time", details: "Your details",
    name: "Full name", phone: "Mobile number", phoneHint: "10-digit mobile number. We send reminders here.",
    consent: "Send me appointment reminders on WhatsApp", consentHint: "Day-before reminders with Confirm and Reschedule buttons. Reply STOP anytime.",
    submit: "Book appointment", booked: "You're booked", ref: "Booking reference", keep: "Show this reference at the reception desk.",
    remind: "We'll send a WhatsApp reminder the evening before.", noRemind: "You chose not to get WhatsApp reminders.",
    another: "Book another appointment", choose: "Choose a time to continue.", closed: "No open days in the next few weeks. Please call the hospital.",
    demo: "Demo clinic. Use fictional details only.", nameErr: "Enter your name.", phoneErr: "Enter your 10-digit mobile number.",
  },
  ta: {
    book: "சந்திப்பை முன்பதிவு செய்யுங்கள்", doctor: "மருத்துவர்", day: "நாள்", time: "நேரம்", details: "உங்கள் விவரங்கள்",
    name: "முழு பெயர்", phone: "கைபேசி எண்", phoneHint: "10 இலக்க கைபேசி எண். நினைவூட்டல்கள் இங்கு அனுப்பப்படும்.",
    consent: "WhatsApp-இல் சந்திப்பு நினைவூட்டல்களை அனுப்பவும்", consentHint: "முந்தைய நாள் நினைவூட்டல், உறுதிசெய் / நேரத்தை மாற்று பொத்தான்களுடன். எப்போது வேண்டுமானாலும் STOP அனுப்பலாம்.",
    submit: "முன்பதிவு செய்", booked: "முன்பதிவு உறுதியானது", ref: "முன்பதிவு எண்", keep: "வரவேற்பு மேசையில் இந்த எண்ணைக் காட்டவும்.",
    remind: "முந்தைய நாள் மாலை WhatsApp நினைவூட்டல் அனுப்புவோம்.", noRemind: "WhatsApp நினைவூட்டல் வேண்டாம் எனத் தேர்ந்தெடுத்துள்ளீர்கள்.",
    another: "மற்றொரு சந்திப்பு", choose: "தொடர ஒரு நேரத்தைத் தேர்ந்தெடுக்கவும்.", closed: "அடுத்த சில வாரங்களில் காலியான நாள் இல்லை. மருத்துவமனையை அழைக்கவும்.",
    demo: "இது டெமோ மருத்துவமனை. கற்பனை விவரங்களை மட்டும் பயன்படுத்தவும்.", nameErr: "உங்கள் பெயரை உள்ளிடவும்.", phoneErr: "10 இலக்க கைபேசி எண்ணை உள்ளிடவும்.",
  },
};

const TA_DAYS = ["ஞா", "தி", "செ", "பு", "வி", "வெ", "ச"];

export default function BookingPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const [lang, setLang] = useState<Lang>("en");
  const t = T[lang];
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [doctorId, setDoctorId] = useState<string>("");
  const [dates, setDates] = useState<{ date: string; open_slots: number }[] | null>(null);
  const [day, setDay] = useState<string>("");
  const [slot, setSlot] = useState<Slot | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [consent, setConsent] = useState(true);
  const [website, setWebsite] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const [done, setDone] = useState<Confirmation | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    api<Profile>(`/api/public/hospitals/${slug}`).then((p) => {
      setProfile(p);
      setLang(p.default_language);
      if (p.doctors.length) setDoctorId(p.doctors[0].id);
    }).catch((e) => setLoadErr(e.message));
  }, [slug]);

  useEffect(() => {
    if (!doctorId) return;
    setDates(null);
    setSlot(null);
    api<{ dates: { date: string; open_slots: number }[] }>(`/api/public/hospitals/${slug}/dates`, { params: { doctor_id: doctorId } })
      .then((d) => {
        setDates(d.dates);
        const first = d.dates.find((x) => x.open_slots > 0);
        setDay((cur) => (cur && d.dates.some((x) => x.date === cur && x.open_slots > 0) ? cur : first?.date || ""));
      }).catch((e) => setLoadErr(e.message));
  }, [doctorId, slug, refreshKey]);

  const doctor = profile?.doctors.find((d) => d.id === doctorId);
  const digits = phone.replace(/\D/g, "");
  const nameOk = name.trim().length >= 2;
  const phoneOk = digits.length === 10 || (digits.length === 12 && digits.startsWith("91"));
  const slotsUrl = useMemo(() => (doctorId && day ? `/api/public/hospitals/${slug}/slots?doctor_id=${doctorId}&date=${day}` : null), [slug, doctorId, day]);

  async function submit() {
    setTouched(true);
    if (!slot || !nameOk || !phoneOk) return;
    setBusy(true);
    setError(null);
    try {
      const r = await post<Confirmation>(`/api/public/hospitals/${slug}/appointments`, {
        doctor_id: doctorId, start_at: slot.start_at, full_name: name.trim(), phone, language: lang, whatsapp_consent: consent, website,
      });
      setDone(r);
      window.scrollTo({ top: 0 });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Booking failed.");
      if (e instanceof ApiError && e.status === 409) { setSlot(null); setRefreshKey((k) => k + 1); }
    } finally {
      setBusy(false);
    }
  }

  if (loadErr) return <Frame><ErrorBox message={loadErr} /></Frame>;
  if (!profile) return <Frame><Spinner /></Frame>;

  const header = (
    <div className="flex items-start justify-between gap-4">
      <div>
        <h1 className="text-xl sm:text-2xl font-semibold">{profile.name}</h1>
        <div className="mt-2 flex flex-col gap-1 text-sm text-muted">
          {profile.address && <span className="flex items-center gap-1.5"><MapPin className="size-3.5" />{profile.address}</span>}
          {profile.phone && <a href={`tel:${profile.phone.replace(/\s/g, "")}`} className="flex items-center gap-1.5 hover:text-ink"><Phone className="size-3.5" />{profile.phone}</a>}
        </div>
      </div>
      <div className="flex rounded-full border border-silver-2 p-0.5 text-sm shrink-0" role="group" aria-label="Language">
        {(["en", "ta"] as Lang[]).map((l) => (
          <button key={l} onClick={() => setLang(l)} aria-pressed={lang === l}
            className={cx("px-3 py-1 rounded-full", lang === l ? "bg-ink text-white" : "text-muted")}>{l === "en" ? "English" : "தமிழ்"}</button>
        ))}
      </div>
    </div>
  );

  if (done) {
    return (
      <Frame>
        {header}
        <section className="panel mt-6 p-6 sm:p-8 text-center">
          <CalendarCheck2 className="size-10 mx-auto text-violet" />
          <h2 className="mt-3 text-xl font-semibold">{t.booked}</h2>
          <p className="mt-1 text-muted">{done.patient_name}</p>
          <p className="mt-5 text-sm text-muted">{t.ref}</p>
          <p className="num text-3xl font-semibold tracking-wide mt-1">{done.reference}</p>
          <dl className="mt-6 grid grid-cols-2 gap-y-3 text-left max-w-sm mx-auto text-sm">
            <dt className="text-muted">{t.doctor}</dt><dd className="font-medium">{done.doctor}</dd>
            <dt className="text-muted">{t.day}</dt><dd className="font-medium">{dayLabel(done.date, lang, true)}</dd>
            <dt className="text-muted">{t.time}</dt><dd className="font-medium">{fmtTime(done.time)}</dd>
          </dl>
          <p className="mt-6 text-sm">{done.whatsapp_reminder ? t.remind : t.noRemind}</p>
          <p className="mt-1 text-sm text-muted">{t.keep}</p>
          <Button className="mt-6" onClick={() => { setDone(null); setSlot(null); setName(""); setPhone(""); setTouched(false); setRefreshKey((k) => k + 1); }}>{t.another}</Button>
        </section>
      </Frame>
    );
  }

  return (
    <Frame>
      {header}
      {profile.is_demo && <p className="mt-4 text-xs rounded-lg bg-violet-wash text-violet-deep px-3 py-2">{t.demo}</p>}
      <h2 className="mt-8 text-lg font-semibold">{t.book}</h2>

      {profile.doctors.length > 1 && (
        <section className="mt-5">
          <p className="label mb-2">{t.doctor}</p>
          <div className="grid sm:grid-cols-2 gap-2">
            {profile.doctors.map((d) => (
              <button key={d.id} onClick={() => setDoctorId(d.id)} aria-pressed={doctorId === d.id}
                className={cx("text-left rounded-xl border px-4 py-3 transition-colors",
                  doctorId === d.id ? "border-violet bg-violet-wash/60" : "border-silver-2 bg-white hover:border-slate")}>
                <span className="block font-medium">{d.name}</span>
                {d.specialty && <span className="block text-sm text-muted">{d.specialty}</span>}
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="mt-6">
        <p className="label mb-2">{t.day}</p>
        {!dates ? <Spinner /> : dates.every((d) => d.open_slots === 0) ? <p className="text-sm text-muted">{t.closed}</p> : (
          <div className="flex gap-2 overflow-x-auto pb-2 -mx-1 px-1 snap-x">
            {dates.map((d) => {
              const full = d.open_slots === 0;
              return (
                <button key={d.date} disabled={full} onClick={() => { setDay(d.date); setSlot(null); }} aria-pressed={day === d.date}
                  className={cx("snap-start shrink-0 w-16 rounded-xl border py-2 flex flex-col items-center",
                    full && "opacity-40 cursor-not-allowed border-silver",
                    !full && day !== d.date && "border-silver-2 bg-white hover:border-slate",
                    day === d.date && "border-ink bg-ink text-white")}>
                  <span className="text-[11px] opacity-80">{weekday(d.date, lang)}</span>
                  <span className="num text-lg font-semibold leading-tight">{Number(d.date.slice(8))}</span>
                  <span className="text-[11px] opacity-80">{month(d.date, lang)}</span>
                </button>
              );
            })}
          </div>
        )}
      </section>

      {day && (
        <section className="mt-5">
          <p className="label mb-2">{t.time}{doctor && profile.doctors.length > 1 ? ` · ${doctor.name}` : ""}</p>
          <SlotPicker url={slotsUrl} value={slot?.start_at || null} onChange={setSlot} lang={lang} refreshKey={refreshKey} />
        </section>
      )}

      <section className="mt-8">
        <p className="label mb-3">{t.details}</p>
        <div className="grid sm:grid-cols-2 gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm text-muted" htmlFor="name">{t.name}</label>
            <input id="name" className="input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name"
              aria-invalid={touched && !nameOk} maxLength={120} />
            {touched && !nameOk && <p className="text-xs text-alert">{t.nameErr}</p>}
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-sm text-muted" htmlFor="phone">{t.phone}</label>
            <input id="phone" className="input" value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel"
              autoComplete="tel" aria-invalid={touched && !phoneOk} placeholder="98765 43210" maxLength={16} />
            <p className={cx("text-xs", touched && !phoneOk ? "text-alert" : "text-muted")}>{touched && !phoneOk ? t.phoneErr : t.phoneHint}</p>
          </div>
        </div>
        <input tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} className="hidden" aria-hidden name="website" />
        <label className="mt-4 flex gap-3 items-start rounded-xl border border-silver-2 bg-white p-4 cursor-pointer">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-1 size-4 accent-[#8a4fd8]" />
          <span>
            <span className="block text-sm font-medium">{t.consent}</span>
            <span className="block text-xs text-muted mt-0.5">{t.consentHint}</span>
          </span>
        </label>
      </section>

      {error && <div className="mt-5"><ErrorBox message={error} /></div>}
      <div className="sticky bottom-0 mt-6 -mx-4 px-4 py-4 bg-paper/95 backdrop-blur border-t border-silver sm:static sm:border-0 sm:bg-transparent sm:p-0 sm:mx-0">
        {slot && <p className="text-sm mb-3"><span className="text-muted">{dayLabel(day, lang, true)}, </span><span className="font-medium">{fmtTime(slot.time)}</span>{doctor && <span className="text-muted"> · {doctor.name}</span>}</p>}
        <Button variant="primary" className="w-full sm:w-auto" loading={busy} disabled={!slot} onClick={submit}>{t.submit}</Button>
        {!slot && <p className="text-xs text-muted mt-2">{t.choose}</p>}
      </div>
    </Frame>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh bg-paper">
      <div className="h-1 bg-violet" />
      <main className="max-w-2xl mx-auto px-4 py-8 sm:py-12">{children}</main>
      <footer className="max-w-2xl mx-auto px-4 pb-28 sm:pb-10 text-xs text-muted">
        Your name and number are used only for this hospital&apos;s appointments and reminders. Booking powered by TEC THA.
      </footer>
    </div>
  );
}

function weekday(iso: string, lang: Lang) {
  const d = new Date(iso + "T12:00:00+05:30");
  return lang === "ta" ? TA_DAYS[d.getUTCDay()] : d.toLocaleDateString("en-IN", { weekday: "short", timeZone: "Asia/Kolkata" });
}
const TA_MONTHS = ["ஜன", "பிப்", "மார்", "ஏப்", "மே", "ஜூன்", "ஜூலை", "ஆக", "செப்", "அக்", "நவ", "டிச"];
function month(iso: string, lang: Lang) {
  const m = Number(iso.slice(5, 7)) - 1;
  return lang === "ta" ? TA_MONTHS[m] : new Date(iso + "T12:00:00Z").toLocaleDateString("en-IN", { month: "short" });
}
function dayLabel(iso: string, lang: Lang, long = false) {
  return `${weekday(iso, lang)}, ${Number(iso.slice(8))} ${month(iso, lang)}${long ? "" : ""}`;
}
