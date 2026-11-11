export const TZ = "Asia/Kolkata";

export function fmtDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = {}): string {
  if (!iso) return "—";
  const d = iso.length === 10 ? new Date(iso + "T12:00:00+05:30") : new Date(iso);
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: TZ, ...opts });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true, timeZone: TZ,
  });
}

export function fmtTime(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  const suffix = h >= 12 ? "PM" : "AM";
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${suffix}`;
}

export function fmtPhone(e164: string): string {
  if (e164.startsWith("+91") && e164.length === 13) return `+91 ${e164.slice(3, 8)} ${e164.slice(8)}`;
  return e164;
}

export function addDays(isoDate: string, n: number): string {
  const d = new Date(isoDate + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export const APPOINTMENT_STATUS: Record<string, { label: string; tone: Tone }> = {
  booked: { label: "Awaiting confirmation", tone: "neutral" },
  confirmed: { label: "Confirmed", tone: "ok" },
  reschedule_requested: { label: "Wants to reschedule", tone: "caution" },
  rescheduled: { label: "Rescheduled", tone: "muted" },
  cancelled: { label: "Cancelled", tone: "muted" },
  completed: { label: "Visited", tone: "violet" },
  no_show: { label: "Did not come", tone: "alert" },
};

export const FOLLOWUP_STATUS: Record<string, { label: string; tone: Tone }> = {
  scheduled: { label: "Scheduled", tone: "neutral" },
  confirmed: { label: "Confirmed", tone: "ok" },
  reschedule_requested: { label: "Wants another date", tone: "caution" },
  completed: { label: "Came back", tone: "violet" },
  missed: { label: "Missed", tone: "alert" },
  cancelled: { label: "Cancelled", tone: "muted" },
};

export const ATTENTION_REASON: Record<string, string> = {
  missed: "Follow-up date passed",
  no_response: "No reply to reminders",
  reminder_failed: "Reminder not delivered",
  reschedule_requested: "Asked for another date",
  needs_time: "Confirmed, needs a time",
};

export const REMINDER_STATUS: Record<string, { label: string; tone: Tone }> = {
  pending: { label: "Scheduled", tone: "neutral" },
  processing: { label: "Sending", tone: "neutral" },
  sent: { label: "Sent to WhatsApp", tone: "ok" },
  simulated: { label: "Test mode (not sent)", tone: "violet" },
  skipped: { label: "Not sent", tone: "muted" },
  failed: { label: "Failed", tone: "alert" },
  cancelled: { label: "Cancelled", tone: "muted" },
};

export const MESSAGE_STATUS: Record<string, { label: string; tone: Tone }> = {
  queued: { label: "Queued", tone: "neutral" },
  accepted: { label: "Accepted by WhatsApp", tone: "neutral" },
  sent: { label: "Sent", tone: "neutral" },
  delivered: { label: "Delivered", tone: "ok" },
  read: { label: "Read", tone: "ok" },
  failed: { label: "Failed", tone: "alert" },
  unknown: { label: "Outcome unknown", tone: "caution" },
  simulated: { label: "Test mode — not sent", tone: "violet" },
  received: { label: "Received", tone: "neutral" },
};

export const SKIP_REASON: Record<string, string> = {
  same_day_booking: "Booked for the same day",
  window_passed: "Date was too close when the follow-up was set",
  no_whatsapp_consent: "Patient has not agreed to WhatsApp messages",
  whatsapp_disabled: "WhatsApp is turned off",
  test_patient_not_allowlisted: "Demo patient — only listed test phones receive real messages",
  too_late_for_day_before: "Was due yesterday; not sent on the visit day",
  superseded_by_3_day: "Replaced by the 3-day reminder",
  appointment_passed: "Appointment time passed",
  followup_date_reached: "Follow-up date reached",
  target_changed: "Date changed",
};

export const REMINDER_KIND: Record<string, string> = {
  appointment_day_before: "Day before visit",
  followup_7d: "7 days before",
  followup_3d: "3 days before",
};

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export type Tone = "neutral" | "ok" | "caution" | "alert" | "violet" | "muted";
