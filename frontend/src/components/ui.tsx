"use client";
import { useState } from "react";
import { Json } from "@/lib/api";

export const Card = ({ title, children, right, className = "" }: { title?: React.ReactNode; children: React.ReactNode; right?: React.ReactNode; className?: string }) => (
  <section className={`rounded-xl border border-slate-200/90 bg-white p-5 shadow-xs ${className}`}>
    {(title || right) && (
      <div className="mb-4 flex items-center justify-between gap-3 border-b border-slate-100 pb-3">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-800">{title}</h2>
        {right}
      </div>
    )}
    {children}
  </section>
);

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { kind?: "primary" | "ghost" | "danger"; busy?: boolean };
export const Button = ({ kind = "primary", busy, children, className = "", disabled, ...rest }: BtnProps) => {
  const styles = {
    primary: "bg-indigo-600 text-white hover:bg-indigo-700 active:bg-indigo-800 shadow-xs focus:ring-2 focus:ring-indigo-500/25",
    ghost: "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 hover:text-slate-900 active:bg-slate-100 shadow-2xs",
    danger: "bg-rose-600 text-white hover:bg-rose-700 active:bg-rose-800 shadow-xs focus:ring-2 focus:ring-rose-500/25",
  }[kind];
  return (
    <button {...rest} disabled={disabled || busy}
      className={`inline-flex items-center justify-center rounded-lg px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}>
      {busy ? "Working…" : children}
    </button>
  );
};

const BADGE: Record<string, string> = {
  PASS: "border-emerald-200 bg-emerald-50 text-emerald-800",
  completed: "border-emerald-200 bg-emerald-50 text-emerald-800",
  approved: "border-emerald-200 bg-emerald-50 text-emerald-800",
  AUTHORIZED: "border-emerald-200 bg-emerald-50 text-emerald-800",
  registered: "border-emerald-200 bg-emerald-50 text-emerald-800",
  REJECTED: "border-amber-200 bg-amber-50 text-amber-800",
  DENIED: "border-rose-200 bg-rose-50 text-rose-800",
  FAIL: "border-rose-200 bg-rose-50 text-rose-800",
  failed: "border-rose-200 bg-rose-50 text-rose-800",
  denied: "border-rose-200 bg-rose-50 text-rose-800",
  ERROR: "border-rose-200 bg-rose-50 text-rose-800",
  training_failed: "border-rose-200 bg-rose-50 text-rose-800",
  active: "border-indigo-200 bg-indigo-50 text-indigo-800",
  deployed: "border-indigo-200 bg-indigo-50 text-indigo-800",
  training: "border-indigo-200 bg-indigo-50 text-indigo-800",
  protected: "border-sky-200 bg-sky-50 text-sky-800",
  trained: "border-teal-200 bg-teal-50 text-teal-800",
  pending: "border-slate-200 bg-slate-100 text-slate-700",
  SKIP: "border-slate-200 bg-slate-100 text-slate-700",
  exhausted: "border-slate-300 bg-slate-200 text-slate-800",
};
export const Badge = ({ children }: { children: string }) => (
  <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold tracking-wide ${BADGE[children] || "border-slate-200 bg-slate-100 text-slate-700"}`}>
    {children}
  </span>
);

export const Field = ({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) => (
  <label className="block text-sm">
    <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-slate-700">{label}</span>
    {children}
    {hint && <span className="mt-1 block text-xs text-slate-500 font-normal">{hint}</span>}
  </label>
);

export const inputCls = "w-full rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-sm text-slate-900 placeholder:text-slate-400 shadow-2xs transition focus:border-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 disabled:bg-slate-100 disabled:text-slate-500 disabled:cursor-not-allowed";

export const Mono = ({ children, className = "" }: { children: React.ReactNode; className?: string }) => (
  <code className={`break-all rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-xs font-medium text-slate-800 ${className}`}>{children}</code>
);

export const KV = ({ k, v }: { k: string; v: React.ReactNode }) => (
  <div className="grid grid-cols-[180px_1fr] items-baseline gap-3 py-1.5 text-sm border-b border-slate-100/80 last:border-0">
    <dt className="font-medium text-slate-600">{k}</dt>
    <dd className="min-w-0 break-words font-semibold text-slate-900">{v}</dd>
  </div>
);

export const JsonBlock = ({ data, max = 360 }: { data: Json; max?: number }) => (
  <pre className="overflow-auto rounded-lg border border-slate-800 bg-slate-950 p-3.5 font-mono text-xs leading-relaxed text-slate-200" style={{ maxHeight: max }}>
    {JSON.stringify(data, null, 2)}
  </pre>
);

export const Alert = ({ kind = "error", children }: { kind?: "error" | "ok" | "info"; children: React.ReactNode }) => {
  const c = {
    error: "border-l-4 border-l-rose-500 border-rose-200 bg-rose-50 text-rose-900",
    ok: "border-l-4 border-l-emerald-500 border-emerald-200 bg-emerald-50 text-emerald-900",
    info: "border-l-4 border-l-indigo-500 border-indigo-200 bg-indigo-50 text-indigo-900",
  }[kind];
  return <div className={`rounded-lg border p-3 text-sm font-medium ${c}`}>{children}</div>;
};

export const Progress = ({ value }: { value: number }) => (
  <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200">
    <div className="h-full rounded-full bg-indigo-600 transition-all duration-300" style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
  </div>
);

export function usePassword(label = "Account password") {
  const [pw, setPw] = useState("");
  const el = (
    <Field label={label} hint="Required to unlock your encrypted signing key">
      <input type="password" className={inputCls} value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" placeholder="Enter account password" />
    </Field>
  );
  return { pw, el };
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true); setError("");
    try { return await fn(); }
    catch (e) { setError((e as Error).message); return undefined; }
    finally { setBusy(false); }
  };
  return { busy, error, setError, run };
}
