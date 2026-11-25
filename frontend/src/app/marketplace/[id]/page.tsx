"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, Json, fmtBytes, pct } from "@/lib/api";
import OnChainRecord from "@/components/OnChainRecord";
import { Alert, Badge, Button, Card, Field, inputCls, KV, Mono, useAction, usePassword } from "@/components/ui";

function CheckTable({ checks }: { checks: Json[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 mt-2">
      <table className="w-full text-sm text-left">
        <tbody className="divide-y divide-slate-100">
          {checks.map((c) => (
            <tr key={c.id} className="hover:bg-slate-50/50">
              <td className="w-24 py-2.5 px-3"><Badge>{c.status}</Badge></td>
              <td className="py-2.5 px-3">
                <div className="font-semibold text-slate-900">{c.title}</div>
                <div className="text-xs text-slate-600 mt-0.5">{c.detail}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ModelDetail() {
  const { id } = useParams<{ id: string }>();
  const [m, setM] = useState<Json | null>(null);
  const [error, setError] = useState("");
  const [verify, setVerify] = useState<Json | null>(null);
  const [auth, setAuth] = useState<Json | null>(null);
  const [denied, setDenied] = useState<Json | null>(null);
  const [saved, setSaved] = useState("");
  const [savedEnc, setSavedEnc] = useState("");
  const [input, setInput] = useState("");
  const [pred, setPred] = useState<Json | null>(null);
  const { pw, el: pwEl } = usePassword("Account Password");
  const act = useAction();

  const load = useCallback(() => api.get(`/marketplace/models/${id}`).then((x) => { setM(x); return x; }).catch((e) => setError(e.message)), [id]);
  useEffect(() => { load(); }, [load]);

  const doVerify = () => act.run(async () => setVerify(await api.post(`/models/${id}/verify`)));
  const downloadEncrypted = () => act.run(async () => {
    const n = await api.download(`/marketplace/models/${id}/encrypted`, `${id}_${m!.version}.enc`);
    setSavedEnc(`Saved encrypted artifact (${fmtBytes(n)}).`);
  });
  const request = () => act.run(async () => { await api.post(`/marketplace/models/${id}/access-request`, { note: "" }); await load(); });
  const access = () => act.run(async () => {
    setAuth(null); setDenied(null); setPred(null); setSaved("");
    try { setAuth(await api.post(`/marketplace/models/${id}/access`, { password: pw })); }
    catch (e) { const err = e as { body?: Json; message: string }; setDenied({ reason: err.message, steps: err.body?.steps || [] }); }
    await load();
  });
  const download = () => act.run(async () => { const n = await api.download(`/downloads/${auth!.download_token}`, auth!.filename); setSaved(`Saved ${auth!.filename} (${fmtBytes(n)})`); });
  const predict = () => act.run(async () => setPred(await api.post(`/downloads/${auth!.download_token}/predict`, { inputs: JSON.parse(input) })));

  if (error) return <Alert>{error}</Alert>;
  if (!m) return <p className="text-sm font-medium text-slate-500">Loading model details…</p>;
  const g = m.my_access, bc = m.blockchain;

  return (
    <>
      <div className="flex items-center gap-2">
        <Link href="/marketplace" className="inline-flex items-center text-xs font-semibold uppercase tracking-wider text-indigo-600 hover:text-indigo-700">
          ← Back to Marketplace
        </Link>
      </div>

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            {m.name} <span className="text-base font-medium text-slate-500">v{m.version}</span>
          </h1>
          <div className="mt-1 text-xs font-medium text-slate-600">
            {m.algorithm} · Dataset: {m.dataset_name} · <Mono>{m.id}</Mono>
          </div>
        </div>
        <Badge>registered</Badge>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Developer Identity (X.509)">
          <dl>
            <KV k="Developer" v={m.developer.username} />
            <KV k="Certificate Subject" v={m.developer.certificate_subject} />
            <KV k="Fingerprint (SHA3-256)" v={<Mono>{m.developer.certificate_fingerprint}</Mono>} />
            <KV k="Owner Wallet" v={<Mono>{m.developer.wallet}</Mono>} />
          </dl>
        </Card>
        <Card title="Blockchain Record">
          <dl>
            <KV k="Transaction" v={<Mono>{bc.tx_hash}</Mono>} />
            <KV k="Block Number" v={bc.block_number} />
            <KV k="Contract" v={<Mono>{bc.contract_address}</Mono>} />
            <KV k="Original Hash" v={<Mono>{m.original_sha3}</Mono>} />
            <KV k="Merkle Root" v={<Mono>{m.merkle_root}</Mono>} />
            <KV k="Artifact Size" v={fmtBytes(m.size_bytes)} />
          </dl>
        </Card>
      </div>

      <Card title="Training Metrics">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[["Accuracy", m.metrics.accuracy], ["Precision", m.metrics.precision_macro], ["Recall", m.metrics.recall_macro], ["F1", m.metrics.f1_macro]].map(([k, v]) => (
            <div key={k as string} className="rounded-xl border border-slate-200/90 bg-slate-50 p-3.5">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-600">{k}</div>
              <div className="text-xl font-bold text-slate-900 mt-1">{pct(v as number)}</div>
            </div>
          ))}
        </div>
        <div className="mt-3 text-xs font-medium text-slate-600 border-t border-slate-100 pt-3">
          {m.n_classes} classes, {m.n_features} features · License: <span className="font-semibold text-slate-900">{m.license}</span> ({m.license_terms.description})
        </div>
      </Card>

      <Card title="Verification & Integrity" right={<Button kind="ghost" onClick={doVerify} busy={act.busy}>Run Verification</Button>}>
        {verify && (
          <div className="mt-2 space-y-3">
            <div className="flex items-center gap-2">
              <Badge>{verify.status}</Badge>
              <span className="text-sm font-semibold text-slate-800">{verify.summary.passed} passed, {verify.summary.failed} failed</span>
            </div>
            <CheckTable checks={verify.checks} />
          </div>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button kind="ghost" onClick={downloadEncrypted} busy={act.busy}>Download Encrypted Artifact</Button>
          {savedEnc && <span className="text-xs font-semibold text-emerald-700">{savedEnc}</span>}
        </div>
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer font-semibold text-indigo-600 hover:text-indigo-700">Direct On-Chain State Inspection</summary>
          <div className="mt-3"><OnChainRecord modelId={m.id} /></div>
        </details>
      </Card>

      {!m.is_owner && (
        <Card title="Access & Authorization">
          <div className="mb-4 flex items-center gap-3 text-sm">
            <span className="font-medium text-slate-700">Access Status:</span>
            {g ? <><Badge>{g.status}</Badge><span className="text-xs font-medium text-slate-600">Downloads: {g.downloads_used}/{g.max_downloads ?? "unlimited"}</span></> : <Badge>pending</Badge>}
            {!g && <span className="text-xs text-slate-500">No active request</span>}
          </div>
          {(!g || ["exhausted", "denied"].includes(g.status)) && (
            <Button onClick={request} busy={act.busy}>Request Access ({m.license})</Button>
          )}
          {g?.status === "pending" && <Alert kind="info">Access request submitted. Awaiting developer approval.</Alert>}
          {g?.status === "approved" && (
            <div className="mt-4 max-w-md space-y-4">
              {pwEl}
              <Button onClick={access} busy={act.busy} disabled={!pw}>
                Authorize & Decrypt
              </Button>
            </div>
          )}
          {act.error && <div className="mt-4"><Alert>{act.error}</Alert></div>}
        </Card>
      )}

      {m.is_owner && <Alert kind="info">You are the publisher of this model.</Alert>}

      {(auth || denied) && (
        <Card title="Authorization Audit" right={<Badge>{auth ? "AUTHORIZED" : "DENIED"}</Badge>}>
          {denied && <div className="mb-4"><Alert>{denied.reason}</Alert></div>}
          <div className="space-y-3">
            {(auth?.steps || denied?.steps || []).map((s: Json, i: number) => (
              <div key={i} className="flex gap-3 text-sm rounded-lg border border-slate-100 p-3 bg-slate-50/50">
                <Badge>{s.status}</Badge>
                <div className="flex-1">
                  <div className="font-semibold text-slate-900 capitalize">{s.step.replace(/_/g, " ")}</div>
                  <div className="text-xs text-slate-600 mt-0.5">{s.detail}</div>
                  {s.checks && (
                    <details className="mt-2">
                      <summary className="cursor-pointer text-xs font-semibold text-indigo-600 hover:text-indigo-700">Verification Details</summary>
                      <CheckTable checks={s.checks} />
                    </details>
                  )}
                </div>
              </div>
            ))}
          </div>
          {auth && (
            <div className="mt-5 space-y-4 border-t border-slate-100 pt-5">
              <div className="text-xs font-medium text-slate-700">
                Decrypted SHA3-256: <Mono>{auth.plaintext_sha3}</Mono>
              </div>
              <div className="flex items-center gap-3">
                <Button onClick={download} busy={act.busy}>Download Model ({fmtBytes(auth.bytes)})</Button>
                {saved && <span className="text-xs font-semibold text-emerald-700">{saved}</span>}
              </div>
              <div className="rounded-xl border border-slate-200/90 bg-slate-50 p-4">
                <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-700">Test In-Browser Inference</div>
                <textarea
                  className="h-28 w-full rounded-lg border border-slate-300 bg-white p-3 font-mono text-xs text-slate-900 shadow-2xs focus:border-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={`JSON array of input rows, e.g. [{"feature": 1.0}]`}
                />
                <div className="mt-3">
                  <Button onClick={predict} busy={act.busy} disabled={!input}>Run Inference</Button>
                </div>
                {pred && (
                  <div className="mt-4 rounded-lg bg-white p-3 border border-slate-200 text-sm">
                    {pred.predictions.map((p: Json, i: number) => (
                      <div key={i} className="flex items-center gap-2">
                        <span className="font-semibold text-slate-700">Predicted Class:</span>
                        <span className="text-lg font-bold text-indigo-700">{p.prediction}</span>
                        {p.confidence != null && <span className="text-xs font-semibold text-slate-600">({pct(p.confidence)})</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </Card>
      )}
    </>
  );
}
