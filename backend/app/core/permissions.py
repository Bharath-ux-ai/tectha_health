"""Role and permission catalogue. Seeded into the roles/permissions tables by the initial migration
and loaded from the database at runtime (see deps.permission_map)."""

PERMISSIONS: dict[str, str] = {
    "hospital:read": "View hospital profile and booking link",
    "hospital:manage": "Edit hospital profile and reminder settings",
    "staff:manage": "Create and manage staff accounts",
    "doctors:read": "View doctors and schedules",
    "doctors:manage": "Manage doctors and weekly schedules",
    "appointments:read": "View appointments",
    "appointments:write": "Register, reschedule and update appointments",
    "patients:read": "View patient contact details",
    "patients:write": "Update patient contact details and consent",
    "followups:read": "View follow-ups",
    "followups:write": "Schedule follow-ups and log patient contact",
    "reports:read": "View and export monthly reports",
    "messages:read": "View WhatsApp message log",
    "messages:retry": "Retry failed WhatsApp reminders",
    "whatsapp:manage": "Configure WhatsApp integration",
    "templates:manage": "Manage message templates",
    "audit:read": "View the hospital audit log",
    "demo:manage": "Control the demo clock (demo hospitals only)",
    "system:hospitals": "Create and manage hospital accounts",
    "system:settings": "Manage platform settings",
    "system:status": "Monitor system status",
}

ROLES: dict[str, tuple[str, str, list[str]]] = {
    "system_admin": (
        "System Admin",
        "TEC THA platform operator. Manages hospitals; has no access to patient data.",
        ["system:hospitals", "system:settings", "system:status"],
    ),
    "hospital_admin": (
        "Hospital Admin",
        "Manages the hospital profile, staff, schedules, WhatsApp setup and reports.",
        [p for p in PERMISSIONS if not p.startswith("system:")],
    ),
    "staff": (
        "Hospital Staff",
        "Reception staff: appointments, follow-ups and patient contact.",
        [
            "hospital:read", "doctors:read", "appointments:read", "appointments:write", "patients:read",
            "patients:write", "followups:read", "followups:write", "messages:read", "messages:retry",
        ],
    ),
}
