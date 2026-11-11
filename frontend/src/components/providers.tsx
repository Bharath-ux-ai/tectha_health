"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, ApiError, post } from "@/lib/api";
import type { Me } from "@/lib/types";

/* ---------------- toasts ---------------- */
type Toast = { id: number; kind: "ok" | "error"; text: string };
const ToastCtx = createContext<(kind: Toast["kind"], text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 7000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 left-4 sm:left-auto z-50 flex flex-col gap-2 items-end no-print" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className="flex items-start gap-2 rounded-xl bg-ink text-white px-4 py-3 text-sm shadow-lg max-w-sm">
            {t.kind === "ok" ? <CheckCircle2 className="size-4 mt-0.5 text-[#7fd6a5] shrink-0" /> : <XCircle className="size-4 mt-0.5 text-[#ff9a8f] shrink-0" />}
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ---------------- auth ---------------- */
type AuthState = { me: Me | null; loading: boolean; refresh: () => Promise<void>; logout: () => Promise<void>; can: (p: string) => boolean };
const AuthCtx = createContext<AuthState>({ me: null, loading: true, refresh: async () => {}, logout: async () => {}, can: () => false });
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const refresh = useCallback(async () => {
    try {
      setMe(await api<Me>("/api/auth/me"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setMe(null);
      else throw e;
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    refresh().catch(() => setLoading(false));
    const onUnauth = () => { setMe(null); router.replace("/login?expired=1"); };
    window.addEventListener("tt:unauthorized", onUnauth);
    return () => window.removeEventListener("tt:unauthorized", onUnauth);
  }, [refresh, router]);
  const logout = useCallback(async () => {
    await post("/api/auth/logout").catch(() => {});
    setMe(null);
    router.replace("/login");
  }, [router]);
  const can = useCallback((p: string) => !!me?.permissions.includes(p), [me]);
  return <AuthCtx.Provider value={{ me, loading, refresh, logout, can }}>{children}</AuthCtx.Provider>;
}

/* ---------------- data loading ---------------- */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn()
      .then((d) => { if (alive) { setData(d); setError(null); } })
      .catch((e) => { if (alive) setError(e instanceof Error ? e.message : "Could not load."); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload, setData };
}

/** Wraps an async action with loading state and toasts. */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const run = useCallback(async <T,>(key: string, fn: () => Promise<T>, okText?: string): Promise<T | undefined> => {
    setBusy(key);
    try {
      const r = await fn();
      if (okText) toast("ok", okText);
      return r;
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Something went wrong.");
      return undefined;
    } finally {
      setBusy(null);
    }
  }, [toast]);
  return { busy, run };
}
