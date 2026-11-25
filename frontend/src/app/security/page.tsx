"use client";
import { useEffect, useState } from "react";
import { api, Json, short } from "@/lib/api";
import { useSession } from "@/lib/session";
import ModelPicker, { useModel } from "@/components/ModelPicker";
import { Alert, Badge, Button, Card, JsonBlock, Mono, useAction, usePassword } from "@/components/ui";

function Checks({ checks }: { checks: Json[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 mt-2">
      <table className="w-full text-sm text-left">
        <tbody className="divide-y divide-slate-100">
          {checks.map((c) => (
            <tr key={c.id} className="hover:bg-slate-50/50">
              <td className="w-24 py-2.5 px-3"><Badge>{c.status}</Badge></td>
              <td className="py-2.5 px-3">
                <div className="font-semibold text-slate-900">{c.title}</div>
                <div className="text-xs text-slate-600 mt-0.5 break-words">{c.detail}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function SecurityPage() {
  const { user, activeModelId } = useSession();
  const { model } = useModel();
  const dev = user?.role === "developer";
  const { pw, el: pwEl } = usePassword("Developer Password");
  const act = useAction();
  const [tests, setTests] = useState<Json[]>([]);
  const [results, setResults] = useState<Record<string, Json>>({});
  const [verify, setVerify] = useState<Json | null>(null);
  const [logs, setLogs] = useState<Json[]>([]);
  const [running, setRunning] = useState("");

  const loadLogs = () => api.get(`/security/logs?limit=25${activeModelId ? `&model_id=${activeModelId}` : ""}`).then(setLogs).catch(() => {});
  useEffect(() => { api.get("/security/tests").then(setTests).catch(() => {}); }, []);
  useEffect(() => { setResults({}); setVerify(null); loadLogs(); }, [activeModelId]); // eslint-disable-line

  const doVerify = () => act.run(async () => { setVerify(await api.post(`/models/${activeModelId}/verify`)); loadLogs(); });
  const runOne = async (t: string) => {
    setRunning(t);
    await act.run(async () => { const r = await api.post(`/security/${activeModelId}/tests/${t}`, { password: pw || null }); setResults((x) => ({ ...x, [t]: r })); loadLogs(); });
    setRunning("");
  };
  const runAll = () => act.run(async () => {
    setResults({});
    const r = await api.post(`/security/${activeModelId}/run-all`, { password: pw || null });
    const o: Record<string, Json> = {}; r.results.forEach((x: Json) => (o[x.test] = x)); setResults(o); loadLogs();
  });
  const registered = model?.status === "registered";
  const owner = dev && model?.owner_id === user?.id;

  return (
    <>
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Security Verification</h1>
      </div>
      <ModelPicker model={model} filter={(m) => m.status === "registered"} label="Registered Model" />
      {act.error && <Alert>{act.error}</Alert>}

      {registered && (
        <>
          <Card title="Integrity & Ownership Verification" right={<Button onClick={doVerify} busy={act.busy}>Run Verification</Button>}>
            {verify && (
              <div className="space-y-3">
                <div className="flex items-center gap-3">
                  <Badge>{verify.status}</Badge>
                  <span className="text-sm font-semibold text-slate-800">
                    {verify.summary.passed} passed · {verify.summary.failed} failed · Creator: <Mono>{verify.on_chain?.creator}</Mono>
                  </span>
                </div>
                <Checks checks={verify.checks} />
              </div>
            )}
          </Card>

          <Card title="Security & Resistance Tests" right={owner && <Button onClick={runAll} busy={act.busy && !running}>Run All Tests</Button>}>
            {!owner && <Alert kind="info">Security testing is restricted to the publisher of this model.</Alert>}
            {owner && <div className="mb-5 max-w-md">{pwEl}</div>}
            <div className="space-y-4">
              {tests.map((t, i) => {
                const r = results[t.id];
                return (
                  <div key={t.id} className="rounded-xl border border-slate-200/90 bg-slate-50/50 p-4 transition-all">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-semibold text-slate-900">{i + 1}. {t.title}</div>
                        <div className="text-xs font-medium text-slate-600 mt-1">Expected: <Badge>{t.expected}</Badge></div>
                      </div>
                      <div className="flex items-center gap-3">
                        {r && (
                          <div className="flex items-center gap-2">
                            <Badge>{r.actual}</Badge>
                            <span className={`text-xs font-bold ${r.matched ? "text-emerald-700" : "text-rose-700"}`}>
                              {r.matched ? "Expected" : "Unexpected"}
                            </span>
                          </div>
                        )}
                        {owner && <Button kind="ghost" onClick={() => runOne(t.id)} busy={running === t.id} className="py-1 px-3 text-xs">Run</Button>}
                      </div>
                    </div>
                    {r && (
                      <div className="mt-3 space-y-3 text-sm border-t border-slate-200/60 pt-3">
                        {r.error && <Alert>{r.error}</Alert>}
                        {r.details?.attempts?.map((a: Json, k: number) => (
                          <div key={k} className="rounded-lg bg-white border border-slate-200 p-3">
                            <div className="flex items-center gap-2 font-semibold text-slate-800"><Badge>{a.outcome}</Badge><span>{a.attempt}</span></div>
                            <div className="mt-1 text-xs text-slate-600">{a.contract_message || a.reason}{a.http_status ? ` (HTTP ${a.http_status})` : ""}{a.failed_tx_hash && <> · Failed Tx <Mono>{short(a.failed_tx_hash, 8)}</Mono></>}</div>
                          </div>
                        ))}
                        {r.details?.case_a && ["case_a", "case_b"].map((c) => (
                          <div key={c} className="rounded-lg bg-white border border-slate-200 p-3">
                            <div className="flex items-center gap-2 font-semibold text-slate-800"><Badge>{r.details[c].status}</Badge><span>{r.details[c].modification}</span></div>
                            <div className="mt-1 text-xs text-slate-600">Failed checks: {r.details[c].failed_checks.join(", ")}</div>
                          </div>
                        ))}
                        {r.details?.before_after && (
                          <div className="rounded-lg bg-white border border-slate-200 p-3 text-xs text-slate-700">
                            Modified {r.details.bytes_modified} bytes at offsets {r.details.offsets.join(", ")}. Failed checks: <b className="text-slate-900">{r.details.failed_checks.join(", ")}</b>. Restored: <Badge>{r.details.restored ? "PASS" : "FAIL"}</Badge>
                          </div>
                        )}
                        {r.details?.contract_message && (
                          <div className="rounded-lg bg-white border border-slate-200 p-3 text-xs text-slate-700">
                            Contract response: <b className="text-slate-900">{r.details.contract_message}</b> · {r.details.method}
                          </div>
                        )}
                        {r.checks?.length > 0 && (
                          <details>
                            <summary className="cursor-pointer text-xs font-semibold text-indigo-600 hover:text-indigo-700">Verification Details ({r.checks.length} checks)</summary>
                            <Checks checks={r.checks} />
                          </details>
                        )}
                        <details>
                          <summary className="cursor-pointer text-xs font-medium text-slate-500">Raw Result Payload</summary>
                          <div className="mt-1"><JsonBlock data={r} max={240} /></div>
                        </details>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </Card>
        </>
      )}
      {!registered && <Alert kind="info">Select a registered model to inspect verification and security resistance.</Alert>}

      <Card title="Verification Audit Log">
        {logs.length === 0 ? <p className="text-sm font-medium text-slate-500 py-2">No verification log entries recorded.</p> : (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-sm text-left">
              <thead className="bg-slate-50 border-b border-slate-200 text-xs font-semibold uppercase tracking-wider text-slate-700">
                <tr>
                  <th className="py-2.5 px-3">Timestamp</th>
                  <th className="py-2.5 px-3">Operation</th>
                  <th className="py-2.5 px-3">Actor</th>
                  <th className="py-2.5 px-3">Result</th>
                  <th className="py-2.5 px-3">Failed Checks</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {logs.map((l) => (
                  <tr key={l.id} className="hover:bg-slate-50/50">
                    <td className="py-2.5 px-3 text-xs font-medium text-slate-600">{new Date(l.at).toLocaleTimeString()}</td>
                    <td className="py-2.5 px-3 font-semibold text-slate-900">{l.kind}{l.label ? ` · ${l.label}` : ""}</td>
                    <td className="py-2.5 px-3 text-slate-700 font-medium">{l.actor}</td>
                    <td className="py-2.5 px-3"><Badge>{l.status}</Badge></td>
                    <td className="py-2.5 px-3 text-xs font-medium text-rose-700">{(l.failed_checks || []).join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
