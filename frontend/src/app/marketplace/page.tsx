"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, Json, pct, short } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Alert, Badge, Button, Card, useAction } from "@/components/ui";

export default function MarketplacePage() {
  const { user } = useSession();
  const [models, setModels] = useState<Json[]>([]);
  const [incoming, setIncoming] = useState<Json[]>([]);
  const [mine, setMine] = useState<Json[]>([]);
  const act = useAction();
  const dev = user?.role === "developer";

  const load = useCallback(() => {
    api.get("/marketplace/models").then(setModels).catch(() => {});
    api.get("/marketplace/my-requests").then(setMine).catch(() => {});
    if (dev) api.get("/marketplace/incoming").then(setIncoming).catch(() => {});
  }, [dev]);
  useEffect(() => { load(); }, [load]);

  const decide = (id: string, approve: boolean) => act.run(async () => { await api.post(`/marketplace/requests/${id}/decision`, { approve }); load(); });

  return (
    <>
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Marketplace</h1>
      </div>

      {act.error && <Alert>{act.error}</Alert>}

      {dev && incoming.length > 0 && (
        <Card title="Incoming Access Requests">
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-sm text-left">
              <thead className="bg-slate-50 border-b border-slate-200 text-xs font-semibold uppercase tracking-wider text-slate-700">
                <tr>
                  <th className="py-2.5 px-3">Buyer</th>
                  <th className="py-2.5 px-3">Model</th>
                  <th className="py-2.5 px-3">License</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3">Downloads</th>
                  <th className="py-2.5 px-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {incoming.map((g) => (
                  <tr key={g.id} className="hover:bg-slate-50/50">
                    <td className="py-2.5 px-3 font-semibold text-slate-900">{g.buyer}</td>
                    <td className="py-2.5 px-3 font-mono text-xs">{short(g.model_id, 8)}</td>
                    <td className="py-2.5 px-3 text-slate-700">{g.license}</td>
                    <td className="py-2.5 px-3"><Badge>{g.status}</Badge></td>
                    <td className="py-2.5 px-3 font-mono text-xs">{g.downloads_used}/{g.max_downloads ?? "∞"}</td>
                    <td className="py-2.5 px-3 text-right space-x-2">
                      {g.status === "pending" && (
                        <>
                          <Button onClick={() => decide(g.id, true)} busy={act.busy} className="py-1 px-3 text-xs">Approve</Button>
                          <Button kind="danger" onClick={() => decide(g.id, false)} busy={act.busy} className="py-1 px-3 text-xs">Deny</Button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {models.map((m) => (
          <Card key={m.id} className="flex flex-col justify-between">
            <div>
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-lg font-bold text-slate-900">{m.name}</div>
                  <div className="text-xs font-medium text-slate-500">v{m.version} · {m.algorithm}</div>
                </div>
                <Badge>registered</Badge>
              </div>

              <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                {[["Accuracy", m.metrics.accuracy], ["F1", m.metrics.f1_macro], ["Recall", m.metrics.recall_macro]].map(([k, v]) => (
                  <div key={k as string} className="rounded-lg border border-slate-200/90 bg-slate-50 p-2">
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-600">{k}</div>
                    <div className="text-sm font-bold text-slate-900 mt-0.5">{pct(v as number)}</div>
                  </div>
                ))}
              </div>

              <dl className="mt-4 space-y-1.5 text-xs text-slate-700 border-t border-slate-100 pt-3">
                <div className="flex justify-between">
                  <span className="text-slate-500 font-medium">Developer:</span>
                  <span className="font-semibold text-slate-900">{m.developer.username}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500 font-medium">License:</span>
                  <span className="font-semibold text-slate-900">{m.license}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500 font-medium">Transaction:</span>
                  <span className="font-mono text-slate-800">{short(m.blockchain.tx_hash, 8)}</span>
                </div>
              </dl>
            </div>

            <Link href={`/marketplace/${m.id}`} className="mt-5 block w-full rounded-lg bg-indigo-600 px-3 py-2 text-center text-sm font-semibold text-white shadow-xs transition hover:bg-indigo-700">
              View Details & Access →
            </Link>
          </Card>
        ))}
        {models.length === 0 && <p className="text-sm font-medium text-slate-500 py-3">No registered models available.</p>}
      </div>

      {mine.length > 0 && (
        <Card title="My Access Requests">
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-sm text-left">
              <thead className="bg-slate-50 border-b border-slate-200 text-xs font-semibold uppercase tracking-wider text-slate-700">
                <tr>
                  <th className="py-2.5 px-3">Model</th>
                  <th className="py-2.5 px-3">License</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3">Downloads</th>
                  <th className="py-2.5 px-3">Requested At</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {mine.map((g) => (
                  <tr key={g.id} className="hover:bg-slate-50/50">
                    <td className="py-2.5 px-3">
                      <Link className="font-mono text-xs font-semibold text-indigo-600 hover:underline" href={`/marketplace/${g.model_id}`}>
                        {short(g.model_id, 8)}
                      </Link>
                    </td>
                    <td className="py-2.5 px-3 text-slate-700">{g.license}</td>
                    <td className="py-2.5 px-3"><Badge>{g.status}</Badge></td>
                    <td className="py-2.5 px-3 font-mono text-xs">{g.downloads_used}/{g.max_downloads ?? "∞"}</td>
                    <td className="py-2.5 px-3 text-xs font-medium text-slate-600">{new Date(g.requested_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}
