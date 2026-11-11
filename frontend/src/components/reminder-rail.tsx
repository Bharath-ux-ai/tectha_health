import { addDays, fmtDate, REMINDER_STATUS } from "@/lib/format";
import { cx } from "./ui";

type Stops = Partial<Record<"followup_7d" | "followup_3d", string>>;

function dotClass(status: string | undefined) {
  switch (status) {
    case "sent": return "bg-violet border-violet";
    case "simulated": return "bg-violet-wash border-violet";
    case "failed": return "bg-alert border-alert";
    case "skipped":
    case "cancelled": return "bg-white border-slate border-dashed";
    default: return "bg-white border-silver-2";
  }
}

/**
 * The follow-up timeline: reminder 7 days before, reminder 3 days before, the visit date.
 * The rail fills in violet up to today, so reception can see at a glance how far along a patient is.
 */
export function ReminderRail({ dueDate, today, reminders, status, compact = false }:
  { dueDate: string; today: string; reminders: Stops; status: string; compact?: boolean }) {
  const start = addDays(dueDate, -7);
  const span = 7;
  const daysIn = Math.max(0, Math.min(span, (Date.parse(today) - Date.parse(start)) / 86400000));
  const pct = (daysIn / span) * 100;
  const endTone = status === "completed" ? "bg-violet border-violet" : status === "missed" ? "bg-alert border-alert"
    : status === "confirmed" ? "bg-ok border-ok" : "bg-white border-ink-2";
  const stops = [
    { key: "followup_7d" as const, at: 0, label: "7 days", date: start },
    { key: "followup_3d" as const, at: (4 / 7) * 100, label: "3 days", date: addDays(dueDate, -3) },
  ];
  if (compact) {
    return (
      <div className="relative h-3 w-28" aria-label={`Reminders: 7-day ${reminders.followup_7d || "none"}, 3-day ${reminders.followup_3d || "none"}`}>
        <div className="absolute left-0 right-0 top-1/2 h-px bg-silver-2" />
        <div className="absolute left-0 top-1/2 h-[2px] -translate-y-px bg-violet" style={{ width: `${pct}%` }} />
        {stops.map((s) => (
          <span key={s.key} className={cx("absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2", dotClass(reminders[s.key]))}
            style={{ left: `${s.at}%` }} />
        ))}
        <span className={cx("absolute top-1/2 right-0 size-3 translate-x-1/2 -translate-y-1/2 rounded-[3px] border-2", endTone)} />
      </div>
    );
  }
  return (
    <div className="pt-2 pb-1 pr-6">
      <div className="relative h-14">
        <div className="absolute left-0 right-0 top-3 h-[3px] rounded-full bg-silver" />
        <div className="absolute left-0 top-3 h-[3px] rounded-full bg-violet transition-[width]" style={{ width: `${pct}%` }} />
        {stops.map((s) => (
          <div key={s.key} className="absolute -translate-x-1/2 flex flex-col items-center" style={{ left: `${s.at}%` }}>
            <span className={cx("size-[18px] rounded-full border-[3px]", dotClass(reminders[s.key]))} />
            <span className="mt-1.5 text-xs font-medium text-ink-2 whitespace-nowrap">{fmtDate(s.date, { weekday: undefined })}</span>
            <span className="text-[11px] text-muted whitespace-nowrap">{reminders[s.key] ? REMINDER_STATUS[reminders[s.key]!]?.label : "—"}</span>
          </div>
        ))}
        <div className="absolute right-0 translate-x-1/2 flex flex-col items-center">
          <span className={cx("size-5 rounded-md border-[3px]", endTone)} />
          <span className="mt-1 text-xs font-semibold text-ink whitespace-nowrap">{fmtDate(dueDate, { weekday: undefined })}</span>
          <span className="text-[11px] text-muted">Visit</span>
        </div>
      </div>
    </div>
  );
}
