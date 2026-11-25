"use client";
import { useCallback, useEffect, useState } from "react";
import { api, Json } from "@/lib/api";
import { useSession } from "@/lib/session";
import Stepper from "./Stepper";
import { Badge, Card, inputCls, Mono } from "./ui";

export function useModel(pollMs = 0) {
  const { activeModelId } = useSession();
  const [model, setModel] = useState<Json | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(async () => {
    if (!activeModelId) { setModel(null); return null; }
    try { const m = await api.get(`/models/${activeModelId}`); setModel(m); setError(""); return m; }
    catch (e) { setModel(null); setError((e as Error).message); return null; }
  }, [activeModelId]);
  useEffect(() => { reload(); }, [reload]);
  useEffect(() => { if (!pollMs) return; const t = setInterval(reload, pollMs); return () => clearInterval(t); }, [pollMs, reload]);
  return { model, reload, error };
}

export default function ModelPicker({ filter, model, label = "Active Model" }: { filter?: (m: Json) => boolean; model: Json | null; label?: string }) {
  const { activeModelId, setActiveModelId } = useSession();
  const [models, setModels] = useState<Json[]>([]);
  useEffect(() => { api.get("/models").then(setModels).catch(() => setModels([])); }, [activeModelId, model?.status]);
  const shown = filter ? models.filter(filter) : models;
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-4">
        <div className="min-w-[280px] flex-1">
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-slate-700">{label}</div>
          <select className={inputCls} value={activeModelId} onChange={(e) => setActiveModelId(e.target.value)}>
            <option value="">— Select a model —</option>
            {shown.map((m) => <option key={m.id} value={m.id}>{m.name} v{m.version} · {m.id} · {m.status}</option>)}
          </select>
        </div>
        {model && (
          <div className="flex items-center gap-2 pt-5">
            <Badge>{model.status}</Badge>
            <Mono>{model.id}</Mono>
          </div>
        )}
      </div>
      {model && (
        <div className="mt-5 border-t border-slate-100 pt-4">
          <Stepper stages={model.lifecycle} />
        </div>
      )}
    </Card>
  );
}
