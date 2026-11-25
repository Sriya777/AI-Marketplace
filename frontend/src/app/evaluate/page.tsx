"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Json, pct } from "@/lib/api";
import { useSession } from "@/lib/session";
import ModelPicker, { useModel } from "@/components/ModelPicker";
import { Alert, Badge, Button, Card, KV, Mono, useAction } from "@/components/ui";

function ConfusionTable({ cm }: { cm: Json }) {
  if (!cm || !cm.matrix || !cm.labels) return null;
  const max = Math.max(1, ...cm.matrix.flat());
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 mt-2">
      <table className="text-center text-xs w-full">
        <thead className="bg-slate-50 border-b border-slate-200">
          <tr>
            <th className="p-2.5 font-semibold text-slate-700 text-left">Actual ↓ / Predicted →</th>
            {cm.labels.map((l: string) => (
              <th key={l} className="p-2.5 font-bold text-slate-800">{l}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {cm.matrix.map((row: number[], i: number) => (
            <tr key={i} className="hover:bg-slate-50/50">
              <th className="p-2.5 text-left font-bold text-slate-800 bg-slate-50/30">{cm.labels[i]}</th>
              {row.map((v, j) => (
                <td
                  key={j}
                  className="h-10 w-12 border-x border-slate-100 font-bold"
                  style={{
                    background: `rgba(79,70,229,${Math.max(0.06, v / max)})`,
                    color: v / max > 0.4 ? "#ffffff" : "#0f172a"
                  }}
                >
                  {v || "0"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function EvaluatePage() {
  const { activeModelId } = useSession();
  const { model, reload } = useModel();
  const [report, setReport] = useState<Json | null>(null);
  const act = useAction();

  useEffect(() => {
    setReport(null);
    if (activeModelId) {
      api.get(`/models/${activeModelId}/evaluation`)
        .then((ev) => setReport(ev))
        .catch(() => setReport(null));
    }
  }, [activeModelId]);

  const handleEvaluate = () => act.run(async () => {
    if (!activeModelId) throw new Error("Select a trained model first");
    const res = await api.post(`/models/${activeModelId}/evaluate`);
    setReport(res);
    await reload();
  });

  const m = report?.metrics || model?.metrics;
  const isTrained = model && (model.status !== "created" && model.status !== "training");

  return (
    <>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Stage 3 · Model Evaluation</h1>
        </div>
      </div>

      <ModelPicker model={model} filter={(m) => m.status !== "created" && m.status !== "training"} label="Select Trained Model to Evaluate" />

      {model && !isTrained && (
        <Alert kind="info">
          This model has not finished training. Please complete <Link href="/train" className="underline font-semibold">Stage 2: Model Training</Link> first.
        </Alert>
      )}

      {model && isTrained && (
        <Card title="Evaluation Actions">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-semibold text-slate-900">{model.name} (v{model.version})</div>
              <div className="text-xs text-slate-600">Algorithm: {model.algorithm} · Dataset: {model.dataset_name}</div>
            </div>
            <Button onClick={handleEvaluate} busy={act.busy}>
              {report ? "Re-Run Evaluation" : "Run Model Evaluation"}
            </Button>
          </div>
          {act.error && <div className="mt-3"><Alert>{act.error}</Alert></div>}
        </Card>
      )}

      {report && m && (
        <Card title="Computed Performance Metrics" right={<Badge>{m.accuracy >= 0.8 ? "PASS" : "warning"}</Badge>}>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              ["Accuracy", m.accuracy],
              ["Precision (Macro)", m.precision_macro],
              ["Recall (Macro)", m.recall_macro],
              ["F1 Score (Macro)", m.f1_macro],
              ["Precision (Weighted)", m.precision_weighted],
              ["Recall (Weighted)", m.recall_weighted],
              ["F1 Score (Weighted)", m.f1_weighted],
              ["Evaluation Samples", report.n_samples ?? model?.training?.n_test ?? "—"]
            ].map(([k, val]) => (
              <div key={k as string} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-600">{k}</div>
                <div className="text-2xl font-bold text-slate-900 mt-1">
                  {typeof val === "number" ? pct(val) : val}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-700">Confusion Matrix</div>
              <ConfusionTable cm={report.confusion_matrix || model?.confusion_matrix} />
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-700">Per-Class Classification Report</div>
              <div className="overflow-x-auto rounded-lg border border-slate-200 mt-2">
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-50 border-b border-slate-200 text-slate-700 font-semibold uppercase tracking-wider">
                    <tr>
                      <th className="px-3 py-2.5">Class</th>
                      <th className="px-3 py-2.5">Precision</th>
                      <th className="px-3 py-2.5">Recall</th>
                      <th className="px-3 py-2.5">F1</th>
                      <th className="px-3 py-2.5">Support Samples</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {(report.per_class || model?.per_class || []).map((c: Json) => (
                      <tr key={c.label} className="hover:bg-slate-50/50">
                        <td className="px-3 py-2 font-bold text-slate-900">{c.label}</td>
                        <td className="px-3 py-2 text-slate-800">{c.precision}</td>
                        <td className="px-3 py-2 text-slate-800">{c.recall}</td>
                        <td className="px-3 py-2 text-slate-800">{c.f1}</td>
                        <td className="px-3 py-2 text-slate-800">{c.support}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <dl className="mt-6 border-t border-slate-100 pt-4">
            <KV k="Evaluation Completed At" v={report.evaluated_at ? new Date(report.evaluated_at).toLocaleString() : "—"} />
            <KV k="Evaluation Execution Time" v={report.evaluation_duration_sec ? `${report.evaluation_duration_sec}s` : "—"} />
          </dl>

          <div className="mt-6 border-t border-slate-100 pt-4 flex items-center justify-between">
            <div className="text-sm font-semibold text-slate-800">
              Evaluation passed. Model is ready for artifact packaging and cryptographic integrity sealing.
            </div>
            <Link
              href="/package"
              className="inline-flex items-center justify-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-xs transition hover:bg-indigo-700"
            >
              Approve & Proceed to Stage 4: Package Model →
            </Link>
          </div>
        </Card>
      )}

      {!activeModelId && (
        <Alert kind="info">Select a model to view or run its evaluation report.</Alert>
      )}
    </>
  );
}
