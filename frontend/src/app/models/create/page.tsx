"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, Json } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Alert, Badge, Button, Card, Field, inputCls, Mono, useAction } from "@/components/ui";

export default function CreateModelPage() {
  const router = useRouter();
  const { setActiveModelId } = useSession();
  const [tab, setTab] = useState<"configure" | "upload">("configure");

  // Architecture & Dataset configuration state
  const [samples, setSamples] = useState<Json[]>([]);
  const [datasets, setDatasets] = useState<Json[]>([]);
  const [dsId, setDsId] = useState("");
  const [algos, setAlgos] = useState<Json[]>([]);
  const [algo, setAlgo] = useState("random_forest");
  const [params, setParams] = useState<Json>({});
  const [target, setTarget] = useState("");
  const [testSize, setTestSize] = useState(0.2);
  const [seed, setSeed] = useState(42);
  const [name, setName] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [createdModel, setCreatedModel] = useState<Json | null>(null);

  // Upload model artifact state
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadName, setUploadName] = useState("");
  const [uploadVersion, setUploadVersion] = useState("1.0.0");

  const act = useAction();
  const upAct = useAction();

  const loadDatasets = async () => setDatasets(await api.get("/datasets"));

  useEffect(() => {
    api.get("/datasets/samples").then(setSamples).catch(() => {});
    api.get("/ml/algorithms").then(setAlgos).catch(() => {});
    loadDatasets().catch(() => {});
  }, []);

  const spec = algos.find((a) => a.id === algo);
  useEffect(() => {
    if (spec) setParams(Object.fromEntries(spec.params.map((p: Json) => [p.name, p.default])));
  }, [algo, algos.length]); // eslint-disable-line

  const ds = datasets.find((d) => d.id === dsId);
  const v = ds?.validation;

  const handleUseSample = (n: string) => act.run(async () => {
    const d = await api.post(`/datasets/samples/${n}/use`);
    await loadDatasets();
    setDsId(d.id);
  });

  const handleCreateModel = () => act.run(async () => {
    if (!ds || !v?.valid) throw new Error("Select a valid dataset before creating model configuration");
    const res = await api.post("/models/create", {
      dataset_id: dsId,
      algorithm: algo,
      params,
      target_column: target || null,
      test_size: testSize,
      random_state: seed,
      name: name || null,
      version: version || "1.0.0"
    });
    setCreatedModel(res);
    setActiveModelId(res.id);
  });

  const handleUploadModel = () => upAct.run(async () => {
    if (!uploadFile) throw new Error("Select a .joblib or .pkl model artifact file");
    if (!uploadName.trim()) throw new Error("Provide a model name");
    const formData = new FormData();
    formData.append("file", uploadFile);
    formData.append("name", uploadName);
    formData.append("version", uploadVersion);
    const res = await api.upload("/models/upload", formData);
    setCreatedModel(res);
    setActiveModelId(res.id);
  });

  return (
    <>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Stage 1 · Model Creation & Upload</h1>
        </div>
      </div>

      <div className="grid grid-cols-2 rounded-xl border border-slate-200 bg-slate-100 p-1 text-sm font-semibold max-w-md">
        <button
          onClick={() => { setTab("configure"); setCreatedModel(null); }}
          className={`rounded-lg py-2 transition ${tab === "configure" ? "bg-white text-slate-900 shadow-xs" : "text-slate-600 hover:text-slate-900"}`}
        >
          1. Configure Architecture
        </button>
        <button
          onClick={() => { setTab("upload"); setCreatedModel(null); }}
          className={`rounded-lg py-2 transition ${tab === "upload" ? "bg-white text-slate-900 shadow-xs" : "text-slate-600 hover:text-slate-900"}`}
        >
          2. Upload Pre-Trained Model
        </button>
      </div>

      {createdModel && (
        <Card className="border-l-4 border-l-emerald-500 bg-emerald-50/50">
          <div className="flex items-start justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-emerald-800">Model Initialized Successfully</div>
              <div className="text-lg font-bold text-slate-900 mt-1">
                {createdModel.name} <span className="text-sm font-normal text-slate-600">v{createdModel.version}</span>
              </div>
              <div className="text-xs font-mono text-slate-600 mt-0.5">ID: {createdModel.id}</div>
            </div>
            <Badge>{createdModel.status || "created"}</Badge>
          </div>
          <div className="mt-4 flex gap-3 border-t border-emerald-200/60 pt-3">
            {tab === "configure" ? (
              <Link
                href="/train"
                className="inline-flex items-center justify-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-xs transition hover:bg-indigo-700"
              >
                Proceed to Stage 2: Train Model →
              </Link>
            ) : (
              <Link
                href="/evaluate"
                className="inline-flex items-center justify-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-xs transition hover:bg-indigo-700"
              >
                Proceed to Stage 3: Evaluate Model →
              </Link>
            )}
          </div>
        </Card>
      )}

      {tab === "configure" && !createdModel && (
        <>
          <Card title="Dataset Selection & Validation">
            <div className="grid gap-6 lg:grid-cols-2">
              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-700">Sample Benchmark Datasets</div>
                <div className="flex flex-wrap gap-2">
                  {samples.map((s) => (
                    <Button key={s.name} kind="ghost" disabled={!s.available} title={s.description} onClick={() => handleUseSample(s.name)}>
                      {s.name}
                    </Button>
                  ))}
                </div>
              </div>
              <div>
                <Field label="Active Dataset">
                  <select className={inputCls} value={dsId} onChange={(e) => setDsId(e.target.value)}>
                    <option value="">— Select Dataset —</option>
                    {datasets.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name} · {d.validation.n_rows} rows · {d.validation.valid ? "Valid" : "Invalid"}
                      </option>
                    ))}
                  </select>
                </Field>
                {ds && v && (
                  <div className="mt-3 space-y-2 text-sm">
                    <div className="flex items-center gap-2">
                      <Badge>{v.valid ? "PASS" : "FAIL"}</Badge>
                      <span className="font-medium text-slate-800">
                        {v.n_rows} rows × {v.n_cols} columns · Target: <Mono>{v.target}</Mono> · {v.classes.length} classes
                      </span>
                    </div>
                    {v.errors.map((e: string) => <Alert key={e}>{e}</Alert>)}
                    {v.warnings.slice(0, 3).map((e: string) => <Alert key={e} kind="info">{e}</Alert>)}
                    <div className="text-xs font-medium text-slate-600">SHA3-256: <Mono>{ds.sha3.slice(0, 24)}…</Mono></div>
                  </div>
                )}
              </div>
            </div>
          </Card>

          <Card title="Model Architecture & Training Parameters">
            <div className="grid gap-4 md:grid-cols-3">
              <Field label="Architecture Algorithm">
                <select className={inputCls} value={algo} onChange={(e) => setAlgo(e.target.value)}>
                  {algos.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
                </select>
              </Field>

              {spec?.params.map((p: Json) => (
                <Field key={p.name} label={p.label}>
                  <input className={inputCls} value={params[p.name] ?? ""} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })} />
                </Field>
              ))}

              <Field label={`Test Split Ratio: ${Math.round(testSize * 100)}%`}>
                <input type="range" min={0.1} max={0.5} step={0.05} value={testSize} onChange={(e) => setTestSize(+e.target.value)} className="w-full mt-2" />
              </Field>

              <Field label="Random Seed">
                <input type="number" className={inputCls} value={seed} onChange={(e) => setSeed(+e.target.value)} />
              </Field>

              <Field label="Target Column Override">
                <input className={inputCls} value={target} onChange={(e) => setTarget(e.target.value)} placeholder={v?.target || "default"} />
              </Field>

              <Field label="Model Name">
                <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder={ds ? `${ds.name}-${algo}` : "my-model"} />
              </Field>

              <Field label="Version Tag">
                <input className={inputCls} value={version} onChange={(e) => setVersion(e.target.value)} />
              </Field>
            </div>

            <div className="mt-5 flex items-center gap-3">
              <Button onClick={handleCreateModel} busy={act.busy} disabled={!ds || !v?.valid}>
                Create & Validate Model Configuration
              </Button>
              {!ds && <span className="text-sm font-medium text-slate-500">Select a valid dataset first</span>}
            </div>
            {act.error && <div className="mt-3"><Alert>{act.error}</Alert></div>}
          </Card>
        </>
      )}

      {tab === "upload" && !createdModel && (
        <Card title="Upload Pre-Trained Model Artifact">
          <div className="max-w-xl space-y-4">
            <Field label="Model Artifact (.joblib or .pkl)">
              <input
                type="file"
                accept=".joblib,.pkl,.pickle"
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                className="block w-full text-sm text-slate-700 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border file:border-slate-300 file:bg-white file:text-xs file:font-semibold file:text-slate-700 hover:file:bg-slate-50 cursor-pointer"
              />
            </Field>

            <Field label="Model Name">
              <input
                className={inputCls}
                value={uploadName}
                onChange={(e) => setUploadName(e.target.value)}
                placeholder="e.g. churn-predictor-v1"
                required
              />
            </Field>

            <Field label="Version Tag">
              <input
                className={inputCls}
                value={uploadVersion}
                onChange={(e) => setUploadVersion(e.target.value)}
                placeholder="1.0.0"
                required
              />
            </Field>

            <div className="pt-2">
              <Button onClick={handleUploadModel} busy={upAct.busy} disabled={!uploadFile || !uploadName}>
                Upload & Validate Artifact
              </Button>
            </div>
            {upAct.error && <Alert>{upAct.error}</Alert>}
          </div>
        </Card>
      )}
    </>
  );
}
