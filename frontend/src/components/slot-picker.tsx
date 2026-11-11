"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { cx, ErrorBox, Spinner } from "./ui";

export type Slot = { start_at: string; time: string; available: boolean };

const PARTS: { key: string; from: number; to: number; en: string; ta: string }[] = [
  { key: "m", from: 0, to: 12, en: "Morning", ta: "காலை" },
  { key: "a", from: 12, to: 16, en: "Afternoon", ta: "மதியம்" },
  { key: "e", from: 16, to: 24, en: "Evening", ta: "மாலை" },
];

export function SlotPicker({ url, value, onChange, lang = "en", refreshKey = 0 }:
  { url: string | null; value: string | null; onChange: (s: Slot | null) => void; lang?: "en" | "ta"; refreshKey?: number }) {
  const [slots, setSlots] = useState<Slot[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!url) return;
    let alive = true;
    setSlots(null);
    setError(null);
    api<{ slots: Slot[] }>(url).then((d) => alive && setSlots(d.slots)).catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, [url, refreshKey]);
  if (!url) return null;
  if (error) return <ErrorBox message={error} />;
  if (!slots) return <Spinner label={lang === "ta" ? "நேரங்களை ஏற்றுகிறது" : "Loading times"} />;
  const open = slots.filter((s) => s.available);
  if (open.length === 0) {
    return <p className="text-sm text-muted py-4">{lang === "ta" ? "இந்த நாளில் காலியான நேரம் இல்லை. வேறு நாளைத் தேர்ந்தெடுக்கவும்." : "No free times on this day. Pick another day."}</p>;
  }
  return (
    <div className="flex flex-col gap-4">
      {PARTS.map((p) => {
        const items = slots.filter((s) => { const h = Number(s.time.slice(0, 2)); return h >= p.from && h < p.to; });
        if (!items.length) return null;
        return (
          <div key={p.key}>
            <p className="text-xs text-muted mb-2">{lang === "ta" ? p.ta : p.en}</p>
            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-2">
              {items.map((s) => (
                <button key={s.start_at} type="button" disabled={!s.available} onClick={() => onChange(s)}
                  aria-pressed={value === s.start_at}
                  className={cx("h-10 rounded-[10px] text-sm border transition-colors num",
                    !s.available && "border-silver bg-paper text-slate line-through cursor-not-allowed",
                    s.available && value !== s.start_at && "border-silver-2 bg-white hover:border-violet",
                    value === s.start_at && "border-violet-cta bg-violet-cta text-white")}>
                  {fmtTime(s.time)}
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
