"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Json, fmtBytes } from "@/lib/api";
import { useSession } from "@/lib/session";
import ModelPicker, { useModel } from "@/components/ModelPicker";
import { Alert, Badge, Button, Card, Field, inputCls, JsonBlock, KV, Mono, useAction, usePassword } from "@/components/ui";

export default function PackagePage() {
  const { activeModelId } = useSession();
  const { model, reload } = useModel();
  const { pw, el: pwEl } = usePassword("Developer Account Password");
  const [license, setLicense] = useState("single-use");
  const [packageResult, setPackageResult] = useState<Json | null>(null);
  const [chunk, setChunk] = useState(0);
  const [chunkRes, setChunkRes] = useState<Json | null>(null);
  const act = useAction();
  const vAct = useAction();

  const isPackaged = model && (model.status === "packaged" || model.status === "protected" || model.status === "registered");
  const cr = model?.crypto || {};

  useEffect(() => {
    setPackageResult(null);
    setChunkRes(null);
    if (model?.license) setLicense(model.license);
  }, [activeModelId, model?.license]);

  const handlePackage = () => act.run(async () => {
    if (!activeModelId) throw new Error("Select a model first");
    if (!pw) throw new Error("Enter your account password to unlock your cryptographic signing key");
    const res = await api.post(`/models/${activeModelId}/package`, {
      password: pw,
      license
    });
    setPackageResult(res);
    await reload();
  });

  const handleVerifyChunk = () => vAct.run(async () => {
    if (!activeModelId) return;
    const res = await api.post(`/models/${activeModelId}/merkle/verify-chunk`, { index: chunk });
    setChunkRes(res);
  });

  return (
    <>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Stage 4 · Model Packaging & Cryptographic Integrity</h1>
        </div>
      </div>

      <ModelPicker
        model={model}
        filter={(m) => m.status !== "created" && m.status !== "training"}
        label="Select Model to Package"
      />

      {model && (
        <Card title="Packaging Configuration & Credentials">
          <div className="grid gap-4 md:grid-cols-3">
            <Field label="Distribution License Policy">
              <select className={inputCls} disabled={isPackaged} value={license} onChange={(e) => setLicense(e.target.value)}>
                <option value="single-use">Single-Use (1 Authorised Download)</option>
                <option value="unlimited">Unlimited Downloads</option>
                <option value="approval-required">Approval-Required (Developer Approves Each Request)</option>
              </select>
            </Field>

            {pwEl}

            <div className="flex items-end">
              <Button onClick={handlePackage} busy={act.busy} disabled={isPackaged || !pw} className="w-full">
                {isPackaged ? "Model Already Packaged" : "Package & Sign Artifact"}
              </Button>
            </div>
          </div>
          {act.error && <div className="mt-3"><Alert>{act.error}</Alert></div>}
        </Card>
      )}

      {isPackaged && cr.original_sha3 && (
        <>
          <Card title="Package Manifest & Cryptographic Sealing" right={<Badge>packaged</Badge>}>
            <dl>
              <KV k="Artifact SHA3-256" v={<Mono>{cr.original_sha3}</Mono>} />
              <KV k="Ciphertext Size" v={fmtBytes(cr.encrypted_bytes || cr.original_bytes)} />
              <KV k="Authenticated Cipher" v={cr.cipher || "AES-256-GCM (256-bit key)"} />
              <KV k="Initialization Nonce" v={<Mono>{cr.nonce_hex || "—"}</Mono>} />
              <KV k="Merkle Root" v={<Mono>{cr.merkle?.root || "—"}</Mono>} />
              <KV k="Merkle Tree Topology" v={cr.merkle ? `${cr.merkle.chunk_count} chunks × ${cr.merkle.chunk_size} bytes (Height ${cr.merkle.height})` : "—"} />
              <KV k="ECDSA Digital Signature" v={<Mono>{cr.signature_hex || "—"}</Mono>} />
              <KV k="Signer Authority" v={cr.signer?.username ? `${cr.signer.username} (Cert: ${cr.signer.cert_fingerprint?.slice(0, 16)}…)` : "X.509 Certified Developer"} />
              <KV k="Packaging Timestamp" v={cr.signed_at ? new Date(cr.signed_at).toLocaleString() : "—"} />
            </dl>

            {model.package_manifest && (
              <details className="mt-4 text-sm">
                <summary className="cursor-pointer font-semibold text-indigo-600 hover:text-indigo-700">View Runtime Dependencies Manifest</summary>
                <div className="mt-2"><JsonBlock data={model.package_manifest} /></div>
              </details>
            )}

            {cr.merkle && (
              <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
                <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-700">Chunk Proof Verification</div>
                <div className="flex items-end gap-3 max-w-md">
                  <div className="flex-1">
                    <Field label={`Chunk Index (0–${(cr.merkle.chunk_count || 1) - 1})`}>
                      <input
                        type="number"
                        className={inputCls}
                        value={chunk}
                        min={0}
                        max={(cr.merkle.chunk_count || 1) - 1}
                        onChange={(e) => setChunk(+e.target.value)}
                      />
                    </Field>
                  </div>
                  <Button onClick={handleVerifyChunk} busy={vAct.busy}>Verify Chunk Proof</Button>
                </div>
                {chunkRes && (
                  <div className="mt-3 text-xs space-y-1 border-t border-slate-200/60 pt-2 font-medium">
                    <div className="flex items-center gap-2">
                      <Badge>{chunkRes.valid_against_stored_root ? "PASS" : "FAIL"}</Badge>
                      <span className="font-semibold text-slate-800">Chunk Valid Against Stored Merkle Root</span>
                    </div>
                    <div className="text-slate-600">
                      Leaf Hash: <Mono>{chunkRes.leaf_hash}</Mono> · Proof length: {chunkRes.proof?.length} hashes
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className="mt-6 border-t border-slate-100 pt-4 flex items-center justify-between">
              <div className="text-sm font-semibold text-slate-800">
                Model is packaged, encrypted, and signed. Ready for live deployment.
              </div>
              <Link
                href="/deploy"
                className="inline-flex items-center justify-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-xs transition hover:bg-indigo-700"
              >
                Proceed to Stage 5: Deploy Model →
              </Link>
            </div>
          </Card>
        </>
      )}
    </>
  );
}
