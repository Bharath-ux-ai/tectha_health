"use client";

import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect } from "react";
import { AppShell } from "@/components/app-shell";
import { useAuth } from "@/components/providers";
import { Spinner } from "@/components/ui";

export default function AppLayout({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  useEffect(() => {
    if (loading) return;
    if (!me) router.replace("/login");
    else if (me.user.role === "system_admin" && !pathname.startsWith("/system") && pathname !== "/account") router.replace("/system");
    else if (me.user.role !== "system_admin" && pathname.startsWith("/system")) router.replace("/dashboard");
  }, [me, loading, router, pathname]);
  if (loading || !me) return <Spinner />;
  return <AppShell>{children}</AppShell>;
}
