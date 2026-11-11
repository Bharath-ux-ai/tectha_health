export type Role = "system_admin" | "hospital_admin" | "staff";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  hospital_id: string | null;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface Hospital {
  id: string;
  name: string;
  slug: string;
  address: string | null;
  phone: string | null;
  timezone: string;
  default_language: "en" | "ta";
  appointment_reminder_time: string;
  followup_reminder_time: string;
  booking_horizon_days: number;
  min_booking_lead_minutes: number;
  is_active: boolean;
  is_demo: boolean;
  booking_link: string;
  today: string;
  local_now: string;
}

export interface Me {
  user: User;
  permissions: string[];
  hospital: Hospital | null;
}

export interface Doctor {
  id: string;
  name: string;
  specialty: string | null;
  is_active: boolean;
  availability?: { weekday: number; start_time: string; end_time: string; slot_minutes: number }[];
}

export type AppointmentStatus =
  | "booked" | "confirmed" | "reschedule_requested" | "rescheduled" | "cancelled" | "completed" | "no_show";

export interface Appointment {
  id: string;
  reference: string;
  status: AppointmentStatus;
  source: string;
  start_at: string;
  local_date: string;
  local_time: string;
  confirmed_via: string | null;
  cancel_reason?: string | null;
  reschedule_count?: number;
  follow_up_id?: string | null;
  patient: { id: string; name: string; phone: string; whatsapp_opt_in: boolean; preferred_language?: string };
  doctor: { id: string; name: string; specialty?: string | null };
}

export interface Reminder {
  id: string;
  kind: "appointment_day_before" | "followup_7d" | "followup_3d";
  due_at: string;
  status: string;
  attempts: number;
  skip_reason: string | null;
  last_error: string | null;
  next_attempt_at: string | null;
  processed_at: string | null;
  patient_name?: string;
  patient_id?: string;
  appointment_id?: string | null;
  follow_up_id?: string | null;
}

export interface Message {
  id: string;
  direction: "inbound" | "outbound";
  type: string;
  template: string | null;
  language: string | null;
  phone: string;
  body: string | null;
  status: string;
  is_simulated: boolean;
  attempt_no: number;
  error_code: string | null;
  error_message: string | null;
  sent_at: string | null;
  delivered_at: string | null;
  read_at: string | null;
  failed_at: string | null;
  created_at: string;
  reminder_id: string | null;
  patient_id: string | null;
  patient_name: string | null;
}

export interface FollowUpRow {
  id: string;
  due_date: string;
  status: string;
  days_to_due: number;
  attention: "red" | "amber" | null;
  attention_reason: string | null;
  patient: { id: string; name: string; phone: string; language: string; whatsapp_opt_in: boolean };
  doctor: string | null;
  booked_appointment_id: string | null;
  reminders: Partial<Record<"followup_7d" | "followup_3d", string>>;
  last_contact: { at: string; outcome: string } | null;
  note: string | null;
}
