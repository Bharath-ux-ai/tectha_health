import Image from "next/image";
import { ReactNode } from "react";

/** Two-panel frame for sign-in screens: graphite brand panel, light working panel. */
export function AuthShell({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <main className="min-h-dvh grid lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] bg-white">
      <aside className="hidden lg:flex flex-col justify-between bg-ink text-white p-12">
        <div className="flex items-center gap-3">
          <Image src="/logo-mark.png" alt="" width={44} height={31} priority />
          <span className="font-display font-semibold tracking-tight">TEC THA</span>
        </div>
        <div className="max-w-md">
          <p className="font-display text-[2.1rem] leading-[1.15] font-semibold">
            Every follow-up patient reminded. Every missed one, called.
          </p>
          <p className="mt-5 text-[15px] text-silver/80 leading-relaxed">
            Online booking, WhatsApp reminders the day before, follow-up reminders a week and three days ahead —
            and a dashboard that shows reception exactly who to phone today.
          </p>
        </div>
        <p className="text-xs text-slate">Follow-Up Engine, version 1, by Tec Tha Consultancy Services</p>
      </aside>
      <section className="flex flex-col justify-center px-6 py-12 sm:px-12">
        <div className="w-full max-w-sm mx-auto">
          <Image src="/logo-full.png" alt="Tec Tha Consultancy Services" width={168} height={83} className="lg:hidden mb-8" priority />
          <h1 className="text-2xl font-semibold">{title}</h1>
          {subtitle && <p className="text-sm text-muted mt-1.5">{subtitle}</p>}
          <div className="mt-8">{children}</div>
        </div>
      </section>
    </main>
  );
}
