"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Json, short } from "@/lib/api";
import { useSession } from "@/lib/session";
import Stepper from "@/components/Stepper";
import { Badge, Card, KV, Mono } from "@/components/ui";

const Stat = ({ label, value, tone = "slate" }: { label: string; value: React.ReactNode; tone?: string }) => (
  <div className="rounded-xl border border-slate-200/90 bg-white p-5 shadow-xs transition hover:shadow-sm">
    <div className="text-xs font-semibold uppercase tracking-wider text-slate-600">{label}</div>
    <div className={`mt-2 text-3xl font-bold tracking-tight ${tone === "good" ? "text-emerald-600" : tone === "bad" ? "text-rose-600" : "text-slate-900"}`}>{value}</div>
  </div>
);

export default function Dashboard() {
  const { user, setActiveModelId } = useSession();
  const [stats, setStats] = useState<Json | null>(null);
  const [health, setHealth] = useState<Json | null>(null);
  const [models, setModels] = useState<Json[]>([]);
  const [logs, setLogs] = useState<Json[]>([]);

  useEffect(() => {
    const load = () => {
      api.get("/dashboard/stats").then(setStats).catch(() => {});
      api.get("/health").then(setHealth).catch(() => {});
      api.get("/models").then(setModels).catch(() => {});
      api.get("/security/logs?limit=8").then(setLogs).catch(() => {});
    };
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const dev = user?.role === "developer";

  const getNextStageLink = (m: Json) => {
    if (m.status === "created") return { href: "/train", label: "Train →" };
    if (m.status === "training") return { href: "/train", label: "Monitor →" };
    if (m.status === "trained" && !m.evaluation && !m.metrics) return { href: "/evaluate", label: "Evaluate →" };
    if (m.status === "trained" || m.status === "evaluated") return { href: "/package", label: "Package →" };
    if (m.status === "packaged" || m.status === "protected") return { href: "/deploy", label: "Deploy →" };
    if (m.status === "deployed" && !m.blockchain?.tx_hash) return { href: "/registry", label: "Register →" };
    return { href: `/marketplace/${m.id}`, label: "Marketplace →" };
  };

  return (
    <>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Dashboard</h1>
        </div>
        {dev && (
          <Link
            href="/models/create"
            className="inline-flex items-center rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white shadow-xs transition hover:bg-indigo-700"
          >
            + New Model / Upload
          </Link>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label={dev ? "My Pipeline Models" : "Marketplace Models"} value={dev ? stats?.models_total ?? "…" : stats?.models_registered ?? "…"} />
        <Stat label="Trained Models" value={stats?.models_trained ?? "…"} />
        <Stat label="Deployed Endpoints" value={stats?.models_deployed ?? "…"} />
        <Stat label="Blockchain Registered" value={stats?.models_registered ?? "…"} tone="good" />
        <Stat label="Integrity Verifications" value={stats?.verifications_passed ?? "…"} tone="good" />
        <Stat label="Failed Checks" value={stats?.verifications_failed ?? "…"} tone={stats?.verifications_failed ? "bad" : "slate"} />
        <Stat label="Security Tests" value={stats ? `${stats.tamper_tests_as_expected}/${stats.tamper_tests_run}` : "…"} tone="good" />
        <Stat label="Access Denied" value={stats?.access_denied ?? "…"} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Blockchain Infrastructure">
          {stats?.chain?.connected ? (
            <dl>
              <KV k="Status" v={<Badge>PASS</Badge>} />
              <KV k="Network" v={`Chain ID ${stats.chain.chainId} (${stats.chain.rpcUrl})`} />
              <KV k="Block Number" v={stats.chain.blockNumber} />
              <KV k="Smart Contract" v={<Mono>{stats.chain.contractAddress}</Mono>} />
              <KV k="Registered Models" v={stats.chain.modelCount} />
            </dl>
          ) : (
            <div className="text-sm font-semibold text-rose-700">Blockchain network unreachable: {stats?.chain?.error || "…"}</div>
          )}
        </Card>

        <Card title="Backend Runtime Services">
          <dl>
            <KV k="Database Engine" v={health ? <><Badge>{health.database.fallback ? "FAIL" : "PASS"}</Badge> <span className="ml-2 text-slate-700">{health.database.mode}</span></> : "…"} />
            <KV k="Storage State" v={health?.database?.detail || "…"} />
            <KV k="API Gateway" v={health ? `FastAPI ${health.version}` : "…"} />
            <KV k="PKI Certificate Authority" v={health?.ca?.initialised ? "Active & Verified" : "…"} />
            {dev && <KV k="Pending Access Requests" v={stats?.pending_requests ?? "…"} />}
          </dl>
        </Card>
      </div>

      <Card
        title={dev ? "Model Development & Deployment Lifecycle" : "Available Models"}
        right={dev && <Link href="/models/create" className="text-xs font-bold uppercase tracking-wider text-indigo-600 hover:text-indigo-700">+ Create / Upload Model</Link>}
      >
        {models.length === 0 && (
          <p className="text-sm text-slate-500 py-3">{dev ? "No models created yet. Start with Stage 1: Create / Upload Model." : "No models registered."}</p>
        )}
        <div className="divide-y divide-slate-100">
          {models.map((m) => {
            const nextAction = getNextStageLink(m);
            return (
              <div key={m.id} className="py-4 first:pt-1 last:pb-1">
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <span className="font-semibold text-slate-900">{m.name}</span>
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-semibold text-slate-600">v{m.version}</span>
                    <Badge>{m.status}</Badge>
                    <span className="text-xs text-slate-500 font-mono">{m.algorithm}</span>
                    {m.metrics?.accuracy != null && (
                      <span className="text-xs font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-1.5 py-0.5">
                        {(m.metrics.accuracy * 100).toFixed(1)}% acc
                      </span>
                    )}
                  </div>
                  {dev && m.owner_id ? (
                    <Link
                      href={nextAction.href}
                      onClick={() => setActiveModelId(m.id)}
                      className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-indigo-600 shadow-2xs hover:bg-slate-50"
                    >
                      {nextAction.label}
                    </Link>
                  ) : (
                    <Link
                      href={`/marketplace/${m.id}`}
                      className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-indigo-600 shadow-2xs hover:bg-slate-50"
                    >
                      View →
                    </Link>
                  )}
                </div>
                <Stepper stages={m.lifecycle} compact />
              </div>
            );
          })}
        </div>
      </Card>

      <Card title="System Activity & Verification Audit Log">
        {logs.length === 0 ? (
          <p className="text-sm text-slate-500 py-2">No verification log entries recorded.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/70 text-xs font-semibold uppercase tracking-wider text-slate-700">
                  <th className="py-2.5 px-3">Timestamp</th>
                  <th className="py-2.5 px-3">Operation</th>
                  <th className="py-2.5 px-3">Model</th>
                  <th className="py-2.5 px-3">Actor</th>
                  <th className="py-2.5 px-3">Result</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {logs.map((l) => (
                  <tr key={l.id} className="hover:bg-slate-50/60 transition-colors">
                    <td className="py-2.5 px-3 text-xs font-medium text-slate-600">{new Date(l.at).toLocaleTimeString()}</td>
                    <td className="py-2.5 px-3 font-medium text-slate-900">{l.kind}{l.label ? ` · ${l.label}` : ""}</td>
                    <td className="py-2.5 px-3 font-mono text-xs">{short(l.model_id, 8)}</td>
                    <td className="py-2.5 px-3 text-slate-700 font-medium">{l.actor}</td>
                    <td className="py-2.5 px-3"><Badge>{l.status}</Badge></td>
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
