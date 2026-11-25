"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Json, pct } from "@/lib/api";
import { useSession } from "@/lib/session";
import ModelPicker, { useModel } from "@/components/ModelPicker";
import { Alert, Badge, Button, Card, KV, Mono, useAction } from "@/components/ui";

export default function DeployPage() {
  const { activeModelId } = useSession();
  const { model, reload } = useModel();
  const dep = useAction(), pred = useAction();
  const [schema, setSchema] = useState<Json | null>(null);
  const [input, setInput] = useState("");
  const [result, setResult] = useState<Json | null>(null);

  useEffect(() => {
    setResult(null);
    if (activeModelId && model && model.status !== "created" && model.status !== "training") {
      api.get(`/models/${activeModelId}/schema`)
        .then((s) => {
          setSchema(s);
          if (s.sample_inputs?.[0]) {
            setInput(JSON.stringify([s.sample_inputs[0].inputs], null, 2));
          }
        })
        .catch(() => setSchema(null));
    } else {
      setSchema(null);
    }
  }, [activeModelId, model?.status]);

  const d = model?.deployment;
  const isDeployed = d?.status === "deployed";

  const handleDeploy = () => dep.run(async () => {
    await api.post(`/models/${activeModelId}/deploy`);
    await reload();
  });

  const handleUndeploy = () => dep.run(async () => {
    await api.post(`/models/${activeModelId}/undeploy`);
    await reload();
  });

  const handlePredict = () => pred.run(async () => {
    let parsedInputs;
    try {
      parsedInputs = JSON.parse(input);
    } catch {
      throw new Error("Input must be valid JSON array of feature row objects");
    }
    const res = await api.post(`/models/${activeModelId}/predict`, { inputs: parsedInputs });
    setResult(res);
    await reload();
  });

  return (
    <>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Stage 5 · Model Deployment & Inference</h1>
        </div>
      </div>

      <ModelPicker
        model={model}
        filter={(m) => m.status !== "created" && m.status !== "training"}
        label="Select Model to Deploy"
      />

      {model && (
        <>
          <Card
            title="Inference Engine Deployment"
            right={<Badge>{isDeployed ? "deployed" : d?.status === "undeployed" ? "undeployed" : "pending"}</Badge>}
          >
            {d ? (
              <dl>
                <KV k="Deployment State" v={<Badge>{d.status}</Badge>} />
                <KV k="Version Tag" v={d.version} />
                <KV k="Active Inference Endpoint" v={<Mono>POST {d.endpoint}</Mono>} />
                <KV k="Artifact SHA3-256" v={<Mono>{d.artifact_sha3}</Mono>} />
                <KV k="Cold-Start Load Latency" v={`${d.load_ms} ms`} />
                <KV k="Inference Requests Served" v={d.predictions_served ?? 0} />
                <KV k="Deployment Timestamp" v={d.deployed_at ? new Date(d.deployed_at).toLocaleString() : "—"} />
              </dl>
            ) : (
              <p className="text-sm font-medium text-slate-500 py-1">Model is not loaded in the inference engine.</p>
            )}

            <div className="mt-4 flex gap-3 border-t border-slate-100 pt-4">
              <Button onClick={handleDeploy} busy={dep.busy}>
                {isDeployed ? "Redeploy / Reload" : "Deploy Model to Inference Engine"}
              </Button>
              {isDeployed && (
                <Button kind="ghost" onClick={handleUndeploy} busy={dep.busy}>
                  Undeploy
                </Button>
              )}
            </div>
            {dep.error && <div className="mt-3"><Alert>{dep.error}</Alert></div>}
          </Card>

          {isDeployed && (
            <Card title="Live Inference Testing Console">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-600 mr-1">Load Test Sample:</span>
                {schema?.sample_inputs?.map((s: Json, i: number) => (
                  <Button
                    key={i}
                    kind="ghost"
                    onClick={() => setInput(JSON.stringify([s.inputs], null, 2))}
                    className="text-xs py-1 px-2.5"
                  >
                    Sample {i + 1} ({s.true_label})
                  </Button>
                ))}
              </div>

              <textarea
                className="h-36 w-full rounded-lg border border-slate-300 bg-white p-3 font-mono text-xs text-slate-900 shadow-2xs focus:border-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="JSON array of input feature rows"
              />

              <div className="mt-3">
                <Button onClick={handlePredict} busy={pred.busy} disabled={!input}>
                  Run Inference
                </Button>
              </div>

              {pred.error && <div className="mt-3"><Alert>{pred.error}</Alert></div>}

              {result?.predictions?.map((p: Json, i: number) => (
                <div key={i} className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="text-xs font-semibold uppercase tracking-wider text-slate-600">Predicted Class:</span>
                      <span className="text-xl font-bold text-indigo-700">{p.prediction}</span>
                      {p.confidence != null && <span className="text-xs font-semibold text-slate-600">({pct(p.confidence)} confidence)</span>}
                    </div>
                    {result.latency_ms != null && (
                      <div className="text-xs font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-2 py-0.5">
                        Latency: {result.latency_ms} ms
                      </div>
                    )}
                  </div>

                  {p.probabilities && (
                    <div className="mt-3 space-y-1.5 border-t border-slate-200/60 pt-3">
                      {Object.entries(p.probabilities).filter(([, v]) => (v as number) > 0.005).map(([k, v]) => (
                        <div key={k} className="flex items-center gap-3 text-xs font-medium">
                          <span className="w-16 font-semibold text-slate-700">{k}</span>
                          <div className="h-2 flex-1 rounded-full bg-slate-200 overflow-hidden">
                            <div className="h-2 rounded-full bg-indigo-600 transition-all" style={{ width: `${(v as number) * 100}%` }} />
                          </div>
                          <span className="w-12 text-right font-mono font-semibold text-slate-800">{pct(v as number)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}

              <div className="mt-6 border-t border-slate-100 pt-4 flex items-center justify-between">
                <div className="text-sm font-semibold text-slate-800">
                  Model is live and serving predictions. Proceed to register cryptographic record on the blockchain.
                </div>
                <Link
                  href="/registry"
                  className="inline-flex items-center justify-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-xs transition hover:bg-indigo-700"
                >
                  Proceed to Stage 6: Blockchain Registry →
                </Link>
              </div>
            </Card>
          )}
        </>
      )}

      {!activeModelId && (
        <Alert kind="info">Select a packaged model to deploy and test.</Alert>
      )}
    </>
  );
}
