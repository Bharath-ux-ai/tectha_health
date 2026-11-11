export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

type Options = { method?: string; body?: unknown; params?: Record<string, string | number | boolean | undefined | null> };

/** Same-origin JSON client. The session lives in an httpOnly cookie; the custom header is our CSRF guard. */
export async function api<T = any>(path: string, opts: Options = {}): Promise<T> {
  let url = path;
  if (opts.params) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(opts.params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
    const s = q.toString();
    if (s) url += (url.includes("?") ? "&" : "?") + s;
  }
  let res: Response;
  try {
    res = await fetch(url, {
      method: opts.method || "GET",
      credentials: "same-origin",
      headers: { "X-Requested-With": "tectha", ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const message = (data && (data.detail as string)) || (res.status >= 500 ? "Something went wrong on the server. Try again." : `Request failed (${res.status}).`);
    if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/auth/")) {
      window.dispatchEvent(new CustomEvent("tt:unauthorized"));
    }
    throw new ApiError(res.status, typeof message === "string" ? message : "Request failed.", data?.code);
  }
  return data as T;
}

export const post = <T = any>(path: string, body?: unknown) => api<T>(path, { method: "POST", body: body ?? {} });
export const put = <T = any>(path: string, body?: unknown) => api<T>(path, { method: "PUT", body: body ?? {} });
export const patch = <T = any>(path: string, body?: unknown) => api<T>(path, { method: "PATCH", body: body ?? {} });
export const del = <T = any>(path: string) => api<T>(path, { method: "DELETE" });
