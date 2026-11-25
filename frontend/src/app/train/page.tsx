"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, Json } from "@/lib/api";
import { useSession } from "@/lib/session";
import ModelPicker, { useModel } from "@/components/ModelPicker";
import Stepper from "@/components/Stepper";
import { Alert, Badge, Button, Card, KV, Mono, Progress, useAction } from "@/components/ui";

function Spark({ points, label }: { points: number[]; label: string }) {
  if (points.length < 2) return null;
  const w = 300, h = 70, min = Math.min(...points), max = Math.max(...points), rng = max - min || 1;
  const d = points.map((p, i) => `${(i / (points.length - 1)) * w},${h - ((p - min) / rng) * (h - 8) - 4}`).join(" ");
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wider text-slate-600 mb-1">
        {label}: {points[0].toFixed(3)} → {points[points.length - 1].toFixed(3)}
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} className="h-20 w-full rounded-lg border border-slate-200 bg-slate-50">
        <polyline fill="none" stroke="#4f46e5" strokeWidth="2.5" points={d} />
      </svg>
    </div>
  );
}

export default function TrainPage() {
  const { activeModelId } = useSession();
  const { model, reload } = useModel();
  const [status, setStatus] = useState<Json | null>(null);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const tr = useAction();
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = (id: string) => {
    if (timer.current) clearInterval(timer.current);
    const tick = async () => {
      try {
        const s = await api.get(`/models/${id}/training`);
        setStatus(s);
        if (s.training?.status !== "running" && s.training?.status !== "queued") {
          if (timer.current) clearInterval(timer.current);
          reload();
        }
      } catch {
        /* continue polling */
      }
    };
    tick();
    timer.current = setInterval(tick, 700);
  };

  useEffect(() => {
    if (activeModelId) {
      api.get(`/models/${activeModelId}/training`).then((s) => {
        setStatus(s);
        if (s.training?.status === "running") {
          poll(activeModelId);
        }
      }).catch(() => {});
    }
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [activeModelId]); // eslint-disable-line

  const handleStartTraining = () => tr.run(async () => {
    if (!activeModelId) throw new Error("Select a configured model first");
    const res = await api.post(`/models/${activeModelId}/train`);
    if (res.task_id) setActiveTaskId(res.task_id);
    poll(activeModelId);
  });

  const t = status?.training;
  const isRunning = t?.status === "running" || t?.status === "queued";
  const isCompleted = t?.status === "completed" || model?.status === "trained" || model?.is_uploaded;
  const hist: Json[] = t?.history || [];
  const lossPts = hist.map((h) => h.loss).filter((x) => typeof x === "number");
  const oobPts = hist.map((h) => h.oob_accuracy ?? h.train_accuracy).filter((x) => typeof x === "number");
  const resources = t?.resource_usage || {};

  return (
    <>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Stage 2 · Model Training</h1>
        </div>
        <div>
          <Link
            href="/models/create"
            className="rounded-lg border border-slate-300 bg-white px-3.5 py-1.5 text-xs font-semibold text-slate-700 shadow-2xs hover:bg-slate-50"
          >
            + Create New Model
          </Link>
        </div>
      </div>

      <ModelPicker model={model} label="Select Model to Train" />

      {model && (
        <Card title="Model Specification">
          <dl>
            <KV k="Model Name" v={<span className="font-bold text-slate-900">{model.name} <span className="font-normal text-slate-500">v{model.version}</span></span>} />
            <KV k="Algorithm Architecture" v={model.algorithm} />
            <KV k="Dataset" v={`${model.dataset_name} · Target: ${model.target || "default"}`} />
            <KV k="Train / Test Split" v={`${Math.round((1 - (model.test_size || 0.2)) * 100)}% Train / ${Math.round((model.test_size || 0.2) * 100)}% Test (Seed: ${model.random_state || 42})`} />
            <KV k="Hyperparameters" v={<Mono>{JSON.stringify(model.params || {})}</Mono>} />
            <KV k="Current Status" v={<Badge>{model.status}</Badge>} />
          </dl>

          {!isCompleted && !isRunning && (
            <div className="mt-5 border-t border-slate-100 pt-4 flex items-center gap-3">
              <Button onClick={handleStartTraining} busy={tr.busy}>
                Start Training
              </Button>
            </div>
          )}
          {tr.error && <div className="mt-3"><Alert>{tr.error}</Alert></div>}
        </Card>
      )}

      {status && (isRunning || t?.log?.length > 0) && (
        <Card title="Training Execution & Monitoring" right={<Badge>{isRunning ? "running" : t?.status}</Badge>}>
          {status.lifecycle && <Stepper stages={status.lifecycle} />}

          <div className="mt-5 flex items-center gap-4">
            <div className="flex-1"><Progress value={t?.progress || 0} /></div>
            <span className="w-32 text-right text-sm font-semibold text-slate-800">
              {t?.progress || 0}% · {t?.stage || "idle"}
            </span>
          </div>

          <div className="mt-5 grid grid-cols-3 gap-3">
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-600">Elapsed Time</div>
              <div className="text-lg font-bold text-slate-900 mt-0.5">{resources.elapsed_sec ?? t?.seconds ?? 0}s</div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-600">CPU Compute Time</div>
              <div className="text-lg font-bold text-slate-900 mt-0.5">{resources.cpu_time_sec ?? "—"}s</div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-600">Peak Memory (RAM)</div>
              <div className="text-lg font-bold text-slate-900 mt-0.5">{resources.memory_mb ? `${resources.memory_mb} MB` : "—"}</div>
            </div>
          </div>

          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <div>
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-slate-700">Execution Log</div>
              <pre className="h-44 overflow-auto rounded-lg border border-slate-800 bg-slate-950 p-3.5 font-mono text-xs text-emerald-300">
                {(t?.log || []).join("\n") || "Awaiting execution..."}
              </pre>
            </div>
            <div className="space-y-4">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-700">Live Metric Progression</div>
              <Spark points={lossPts} label="Training Loss / Deviance" />
              <Spark points={oobPts} label="Step / Out-of-Bag Accuracy" />
            </div>
          </div>

          {t?.status === "failed" && (
            <div className="mt-4"><Alert>Training failed: {t.error}</Alert></div>
          )}

          {isCompleted && (
            <div className="mt-6 border-t border-slate-100 pt-4 flex items-center justify-between">
              <div className="text-sm font-semibold text-slate-800">
                Training finished successfully. Artifact SHA3: <Mono>{t?.artifact_sha3?.slice(0, 20)}…</Mono>
              </div>
              <Link
                href="/evaluate"
                className="inline-flex items-center justify-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-xs transition hover:bg-indigo-700"
              >
                Proceed to Stage 3: Evaluate Model →
              </Link>
            </div>
          )}
        </Card>
      )}

      {!activeModelId && (
        <Alert kind="info">
          Select an initialized model or <Link href="/models/create" className="underline font-semibold">create a new model</Link> to begin training.
        </Alert>
      )}
    </>
  );
}
