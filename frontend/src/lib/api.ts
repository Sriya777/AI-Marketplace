// Thin typed client for the FastAPI backend (via the Next.js /api proxy).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Json = any;

const TOKEN_KEY = "aimkt.token";

export const tokenStore = {
  get: (): string => (typeof window === "undefined" ? "" : localStorage.getItem(TOKEN_KEY) || ""),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  status: number;
  body: Json;
  constructor(status: number, message: string, body: Json) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

function messageOf(body: Json, fallback: string): string {
  const d = body?.detail;
  if (typeof d === "string") return d;
  if (d?.message) return `${d.message}${d.errors ? ": " + d.errors.join("; ") : ""}`;
  if (Array.isArray(d)) return d.map((x: Json) => x.msg).join("; ");
  return fallback;
}

async function request(method: string, path: string, body?: Json, form?: FormData): Promise<Json> {
  const headers: Record<string, string> = {};
  const t = tokenStore.get();
  if (t) headers["Authorization"] = `Bearer ${t}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}`, { method, headers, body: form ?? (body !== undefined ? JSON.stringify(body) : undefined) });
  let data: Json = null;
  const text = await res.text();
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new ApiError(res.status, messageOf(data, `HTTP ${res.status}`), data);
  return data;
}

export const api = {
  get: (p: string) => request("GET", p),
  post: (p: string, body: Json = {}) => request("POST", p, body),
  upload: (p: string, form: FormData) => request("POST", p, undefined, form),
  /** Authenticated binary download -> triggers a browser save dialog. */
  async download(path: string, filename: string) {
    const res = await fetch(`/api${path}`, { headers: { Authorization: `Bearer ${tokenStore.get()}` } });
    if (!res.ok) throw new ApiError(res.status, `download failed (HTTP ${res.status})`, null);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    return blob.size;
  },
};

export const short = (s?: string | null, n = 10) => (s ? (s.length > 2 * n + 3 ? `${s.slice(0, n + 2)}…${s.slice(-n)}` : s) : "—");
export const pct = (x?: number | null) => (x == null ? "—" : `${(x * 100).toFixed(2)}%`);
export const fmtBytes = (n?: number | null) => (n == null ? "—" : n > 1048576 ? `${(n / 1048576).toFixed(2)} MB` : `${(n / 1024).toFixed(1)} KB`);
