"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/components/providers";
import { Spinner } from "@/components/ui";

export default function Home() {
  const { me, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (loading) return;
    if (!me) router.replace("/login");
    else router.replace(me.user.role === "system_admin" ? "/system" : "/dashboard");
  }, [me, loading, router]);
  return <Spinner />;
}
