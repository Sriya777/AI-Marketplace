"use client";
import { Json } from "@/lib/api";

const COLORS: Record<string, string> = {
  completed: "bg-emerald-600 border-emerald-600 text-white shadow-2xs",
  active: "bg-indigo-600 border-indigo-600 text-white shadow-2xs ring-2 ring-indigo-200",
  failed: "bg-rose-600 border-rose-600 text-white shadow-2xs",
  pending: "bg-white border-slate-300 text-slate-500",
};
const ICON: Record<string, string> = { completed: "✓", active: "•", failed: "✕", pending: "" };

export default function Stepper({ stages, compact = false }: { stages?: Json[]; compact?: boolean }) {
  if (!stages) return null;
  return (
    <ol className={`flex w-full items-start ${compact ? "gap-1" : "gap-0"}`}>
      {stages.map((s, i) => (
        <li key={s.id} className="flex min-w-0 flex-1 flex-col items-center text-center">
          <div className="flex w-full items-center">
            <div className={`h-0.5 flex-1 ${i === 0 ? "bg-transparent" : stages[i - 1].status === "completed" ? "bg-emerald-500" : "bg-slate-300"}`} />
            <div className={`flex ${compact ? "h-5 w-5 text-[10px]" : "h-7 w-7 text-xs"} shrink-0 items-center justify-center rounded-full border-2 font-bold ${COLORS[s.status] || "bg-white border-slate-300 text-slate-500"}`}>
              {ICON[s.status] || i + 1}
            </div>
            <div className={`h-0.5 flex-1 ${i === stages.length - 1 ? "bg-transparent" : s.status === "completed" ? "bg-emerald-500" : "bg-slate-300"}`} />
          </div>
          {!compact && (
            <span className={`mt-1.5 px-0.5 text-xs font-medium leading-tight ${s.status === "pending" ? "text-slate-500" : "text-slate-800"}`}>
              {s.label}
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}
