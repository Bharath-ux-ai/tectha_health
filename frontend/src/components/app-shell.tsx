"use client";

import {
  BarChart3, Building2, CalendarDays, CalendarHeart, ClipboardList, FlaskConical, LayoutDashboard, LogOut, Menu,
  MessageSquareText, MessagesSquare, Settings, ShieldCheck, UserRound, Users, X,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import { useAuth } from "./providers";
import { cx } from "./ui";

type Item = { href: string; label: string; icon: typeof LayoutDashboard; perm?: string; show?: boolean };

export function AppShell({ children }: { children: ReactNode }) {
  const { me, can, logout } = useAuth();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [pathname]);
  if (!me) return null;
  const sys = me.user.role === "system_admin";
  const main: Item[] = sys
    ? [{ href: "/system", label: "Platform overview", icon: ShieldCheck }]
    : [
        { href: "/dashboard", label: "Today", icon: LayoutDashboard, perm: "appointments:read" },
        { href: "/appointments", label: "Appointments", icon: CalendarDays, perm: "appointments:read" },
        { href: "/follow-ups", label: "Follow-ups", icon: CalendarHeart, perm: "followups:read" },
        { href: "/patients", label: "Patients", icon: Users, perm: "patients:read" },
        { href: "/messages", label: "WhatsApp messages", icon: MessagesSquare, perm: "messages:read" },
        { href: "/reports", label: "Monthly report", icon: BarChart3, perm: "reports:read" },
      ];
  const admin: Item[] = sys ? [] : [
    { href: "/settings", label: "Hospital & doctors", icon: Building2, perm: "hospital:manage" },
    { href: "/staff", label: "Staff", icon: ClipboardList, perm: "staff:manage" },
    { href: "/whatsapp", label: "WhatsApp setup", icon: Settings, perm: "whatsapp:manage" },
    { href: "/templates", label: "Message templates", icon: MessageSquareText, perm: "templates:manage" },
    { href: "/demo", label: "Demo controls", icon: FlaskConical, perm: "demo:manage", show: !!me.hospital?.is_demo },
  ];
  const visible = (items: Item[]) => items.filter((i) => (!i.perm || can(i.perm)) && i.show !== false);

  const nav = (
    <nav className="flex flex-col gap-6 px-3" aria-label="Main">
      <ul className="flex flex-col gap-0.5">{visible(main).map((i) => <NavLink key={i.href} item={i} active={pathname.startsWith(i.href)} />)}</ul>
      {visible(admin).length > 0 && (
        <div>
          <p className="px-3 mb-1.5 text-[11px] font-medium text-slate">Administration</p>
          <ul className="flex flex-col gap-0.5">{visible(admin).map((i) => <NavLink key={i.href} item={i} active={pathname.startsWith(i.href)} />)}</ul>
        </div>
      )}
    </nav>
  );

  const userBox = (
    <div className="border-t border-white/10 px-3 pt-3 mt-auto">
      <Link href="/account" className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-white/5">
        <UserRound className="size-4 text-slate" />
        <span className="min-w-0">
          <span className="block text-sm text-white truncate">{me.user.full_name}</span>
          <span className="block text-xs text-slate truncate">{roleLabel(me.user.role)}</span>
        </span>
      </Link>
      <button onClick={logout} className="w-full flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-silver/80 hover:bg-white/5 hover:text-white">
        <LogOut className="size-4" /> Sign out
      </button>
    </div>
  );

  const brand = (
    <div className="flex items-center gap-3 px-6 h-16 shrink-0">
      <Image src="/logo-mark.png" alt="" width={34} height={24} priority />
      <div className="leading-tight">
        <p className="font-display font-semibold text-white text-[15px]">TEC THA</p>
        <p className="text-[11px] text-slate">Follow-Up Engine</p>
      </div>
    </div>
  );

  return (
    <div className="min-h-dvh lg:pl-64">
      <aside className="hidden lg:flex fixed inset-y-0 left-0 w-64 flex-col bg-ink pb-4 no-print">
        {brand}
        <div className="flex-1 overflow-y-auto pt-2">{nav}</div>
        {userBox}
      </aside>

      <header className="lg:hidden sticky top-0 z-30 flex items-center justify-between bg-ink px-4 h-14 no-print">
        <div className="flex items-center gap-2.5">
          <Image src="/logo-mark.png" alt="" width={28} height={20} />
          <span className="font-display font-semibold text-white text-sm">TEC THA</span>
        </div>
        <button onClick={() => setOpen(true)} className="p-2 text-white" aria-label="Open menu"><Menu className="size-5" /></button>
      </header>
      {open && (
        <div className="lg:hidden fixed inset-0 z-40 no-print">
          <div className="absolute inset-0 bg-ink/50" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-72 bg-ink flex flex-col pb-4">
            <div className="flex items-center justify-between pr-3">{brand}
              <button onClick={() => setOpen(false)} className="p-2 text-white" aria-label="Close menu"><X className="size-5" /></button>
            </div>
            <div className="flex-1 overflow-y-auto pt-2">{nav}</div>
            {userBox}
          </div>
        </div>
      )}

      {me.hospital && <ContextBar />}
      <main className="px-4 sm:px-6 lg:px-10 py-6 lg:py-8 max-w-[1400px]">{children}</main>
    </div>
  );
}

function NavLink({ item, active }: { item: Item; active: boolean }) {
  const Icon = item.icon;
  return (
    <li>
      <Link href={item.href} aria-current={active ? "page" : undefined}
        className={cx("relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
          active ? "bg-white/10 text-white" : "text-silver/75 hover:bg-white/5 hover:text-white")}>
        {active && <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-full bg-violet" aria-hidden />}
        <Icon className="size-4" aria-hidden /> {item.label}
      </Link>
    </li>
  );
}

function ContextBar() {
  const { me } = useAuth();
  const h = me!.hospital!;
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-silver bg-white px-4 sm:px-6 lg:px-10 py-2.5 no-print">
      <p className="text-sm font-medium text-ink-2 truncate">{h.name}</p>
      {h.is_demo && <DemoClockPill />}
    </div>
  );
}

function DemoClockPill() {
  const [label, setLabel] = useState<string | null>(null);
  const pathname = usePathname();
  useEffect(() => {
    let alive = true;
    const load = () => fetch("/api/hospital", { credentials: "same-origin", cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null)).then((d) => alive && d && setLabel(d.local_now)).catch(() => {});
    load();
    const t = setInterval(load, 30000);
    const onChange = () => load();
    window.addEventListener("tt:demo-clock", onChange);
    return () => { alive = false; clearInterval(t); window.removeEventListener("tt:demo-clock", onChange); };
  }, [pathname]);
  if (!label) return null;
  return (
    <Link href="/demo" className="inline-flex items-center gap-2 rounded-full bg-violet-wash text-violet-deep px-3 py-1 text-xs font-medium">
      <FlaskConical className="size-3.5" /> Demo clinic with fictional patients. Clock: {label}
    </Link>
  );
}

export function roleLabel(role: string) {
  return { system_admin: "System admin", hospital_admin: "Hospital admin", staff: "Reception staff" }[role] || role;
}
