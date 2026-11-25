"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Json, fmtBytes } from "@/lib/api";
import { useSession } from "@/lib/session";
import ModelPicker, { useModel } from "@/components/ModelPicker";
import { Alert, Badge, Button, Card, Field, inputCls, JsonBlock, KV, Mono, useAction, usePassword } from "@/components/ui";

export default function ProtectPage() {
  const { activeModelId } = useSession();
  const { model, reload } = useModel();
  const { pw, el: pwEl } = usePassword("Account Password");
  const act = useAction();
  const [out, setOut] = useState<Record<string, Json>>({});
  const [chunk, setChunk] = useState(0);
  const [chunkRes, setChunkRes] = useState<Json | null>(null);
  const [cert, setCert] = useState<Json | null>(null);
  const cr = model?.crypto || {};
  const protectedNow = model && ["protected", "registered"].includes(model.status);

  useEffect(() => { setOut({}); setChunkRes(null); }, [activeModelId]);
  useEffect(() => { if (protectedNow) api.get("/auth/me").then((u) => setCert(u.certificate_status)).catch(() => {}); }, [protectedNow]);

  const step = (name: string, path: string, body?: Json) => act.run(async () => {
    const r = await api.post(`/models/${activeModelId}/${path}`, body ?? {});
    setOut((o) => ({ ...o, [name]: r })); await reload();
  });
  const all = () => act.run(async () => {
    const r = await api.post(`/models/${activeModelId}/protect`, { password: pw });
    const o: Record<string, Json> = {}; r.steps.forEach((s: Json) => (o[s.step] = s)); setOut(o); await reload();
  });
  const setLicense = (l: string) => act.run(async () => { await api.post(`/models/${activeModelId}/license`, { license: l }); await reload(); });
  const verifyChunk = () => act.run(async () => setChunkRes(await api.post(`/models/${activeModelId}/merkle/verify-chunk`, { index: chunk })));

  const done = { hash: !!cr.original_sha3, encrypt: !!cr.encrypted_sha3, merkle: !!cr.merkle, sign: !!cr.signature_hex };
  const deployed = model?.deployment?.status === "deployed";
  const locked = !!protectedNow;
  const Step = ({ n, title, ok, children }: { n: number; title: string; ok: boolean; children: React.ReactNode }) => (
    <Card title={`${n} · ${title}`} right={<Badge>{ok ? "completed" : "pending"}</Badge>}>{children}</Card>
  );

  return (
    <>
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Cryptographic Protection</h1>
      </div>
      <ModelPicker model={model} filter={(m) => m.deployment || m.status === "protected" || m.status === "registered"} label="Deployed Model" />

      {model && !deployed && !protectedNow && (
        <Alert kind="info">
          Please deploy this model first in <Link href="/deploy" className="underline font-semibold">Deploy Model</Link> before applying cryptographic protection.
        </Alert>
      )}
      {act.error && <Alert>{act.error}</Alert>}

      {model && (deployed || protectedNow) && (
        <>
          <Card title="Protection Controls">
            <div className="grid gap-4 md:grid-cols-3">
              <Field label="Distribution License">
                <select className={inputCls} disabled={locked} value={model.license} onChange={(e) => setLicense(e.target.value)}>
                  <option value="single-use">Single-Use (1 Authorised Download)</option>
                  <option value="unlimited">Unlimited Downloads</option>
                  <option value="approval-required">Approval-Required (Manual Approval)</option>
                </select>
              </Field>
              {pwEl}
              <div className="flex items-end">
                <Button onClick={all} busy={act.busy} disabled={locked || !pw} className="w-full">
                  Run All Protection Steps
                </Button>
              </div>
            </div>
          </Card>

          <Step n={1} title="SHA3-256 Artifact Hash" ok={done.hash}>
            {cr.original_sha3 && (
              <dl>
                <KV k="SHA3-256 Hash" v={<Mono>{cr.original_sha3}</Mono>} />
                <KV k="Artifact Size" v={fmtBytes(cr.original_bytes)} />
                <KV k="Training Hash Match" v={<Badge>{cr.original_sha3 === model.training?.artifact_sha3 ? "PASS" : "FAIL"}</Badge>} />
                <KV k="Deployment Hash Match" v={<Badge>{cr.original_sha3 === model.deployment?.artifact_sha3 ? "PASS" : "FAIL"}</Badge>} />
              </dl>
            )}
            <div className="mt-3">
              <Button kind="ghost" onClick={() => step("hash", "crypto/hash")} busy={act.busy} disabled={locked || done.encrypt}>
                Compute Hash
              </Button>
            </div>
          </Step>

          <Step n={2} title="AES-256-GCM Encryption" ok={done.encrypt}>
            {cr.encrypted_sha3 && (
              <dl>
                <KV k="Cipher" v={cr.cipher} />
                <KV k="Initialization Nonce" v={<Mono>{cr.nonce_hex}</Mono>} />
                <KV k="Authenticated Data (AAD)" v={<Mono>{cr.aad}</Mono>} />
                <KV k="Encrypted Size" v={fmtBytes(cr.encrypted_bytes)} />
                <KV k="Encrypted SHA3-256" v={<Mono>{cr.encrypted_sha3}</Mono>} />
              </dl>
            )}
            {out.encrypt && (
              <details className="mt-3 text-sm">
                <summary className="cursor-pointer font-semibold text-indigo-600 hover:text-indigo-700">Key-Wrapping Details</summary>
                <div className="mt-2"><JsonBlock data={out.encrypt.key_wrapping} /></div>
              </details>
            )}
            <div className="mt-3">
              <Button kind="ghost" onClick={() => step("encrypt", "crypto/encrypt")} busy={act.busy} disabled={locked || !done.hash || done.merkle}>
                Encrypt Artifact
              </Button>
            </div>
          </Step>

          <Step n={3} title="Merkle Tree Construction" ok={done.merkle}>
            {cr.merkle && (
              <dl>
                <KV k="Merkle Root" v={<Mono>{cr.merkle.root}</Mono>} />
                <KV k="Tree Topology" v={`${cr.merkle.chunk_count} chunks × ${cr.merkle.chunk_size} bytes (Height ${cr.merkle.height})`} />
              </dl>
            )}
            <div className="mt-3">
              <Button kind="ghost" onClick={() => step("merkle", "crypto/merkle")} busy={act.busy} disabled={locked || !done.encrypt || done.sign}>
                Build Merkle Tree
              </Button>
            </div>
            {done.merkle && (
              <div className="mt-4 rounded-xl border border-slate-200/90 bg-slate-50 p-4">
                <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-700">Verify Chunk Proof</div>
                <div className="flex items-end gap-3 max-w-md">
                  <div className="flex-1">
                    <Field label={`Chunk Index (0–${cr.merkle.chunk_count - 1})`}>
                      <input type="number" className={inputCls} value={chunk} min={0} max={cr.merkle.chunk_count - 1} onChange={(e) => setChunk(+e.target.value)} />
                    </Field>
                  </div>
                  <Button onClick={verifyChunk} busy={act.busy}>Verify Chunk</Button>
                </div>
                {chunkRes && (
                  <div className="mt-4 space-y-2 text-sm border-t border-slate-200/60 pt-3">
                    <div className="flex items-center gap-2">
                      <Badge>{chunkRes.valid_against_stored_root ? "PASS" : "FAIL"}</Badge>
                      <span className="font-semibold text-slate-800">Stored Root Verification</span>
                      {chunkRes.on_chain_root ? (
                        <>
                          <span className="text-slate-300">·</span>
                          <Badge>{chunkRes.valid_against_onchain_root ? "PASS" : "FAIL"}</Badge>
                          <span className="font-semibold text-slate-800">On-Chain Root Verification</span>
                        </>
                      ) : null}
                    </div>
                    <div className="text-xs text-slate-600">
                      Leaf Hash: <Mono>{chunkRes.leaf_hash}</Mono> · {chunkRes.chunk_bytes} bytes · Proof: {chunkRes.proof.length} hashes
                    </div>
                  </div>
                )}
              </div>
            )}
          </Step>

          <Step n={4} title="Identity & ECDSA Signature" ok={done.sign}>
            {cert && (
              <dl className="mb-2">
                <KV k="Certificate Subject" v={<><Badge>{cert.valid ? "PASS" : "FAIL"}</Badge> <span className="ml-2 font-medium">{cert.certificate.subject}</span></>} />
                <KV k="Issuer Authority" v={cert.certificate.issuer} />
                <KV k="Serial Number" v={<Mono>{cert.certificate.serial}</Mono>} />
                <KV k="Validity Period" v={`${cert.certificate.notBefore.slice(0, 10)} → ${cert.certificate.notAfter.slice(0, 10)}`} />
                <KV k="Fingerprint (SHA3-256)" v={<Mono>{cert.certificate.fingerprintSha3_256}</Mono>} />
              </dl>
            )}
            {cr.signature_hex && (
              <dl>
                <KV k="ECDSA Signature" v={<Mono>{cr.signature_hex}</Mono>} />
                <KV k="Algorithm" v={cr.signature_alg} />
                <KV k="Metadata Hash" v={<Mono>{cr.metadata_sha3}</Mono>} />
              </dl>
            )}
            {out.sign && (
              <div className="mt-3 space-y-2">
                <div className="flex items-center gap-2">
                  <Badge>{out.sign.plaintext_artifact_securely_deleted ? "PASS" : "pending"}</Badge>
                  <span className="text-sm font-semibold text-slate-800">Plaintext artifact purged; only authenticated ciphertext retained</span>
                </div>
                <details className="text-sm">
                  <summary className="cursor-pointer font-semibold text-indigo-600 hover:text-indigo-700">Signed Metadata Payload</summary>
                  <div className="mt-2"><JsonBlock data={out.sign.canonical_metadata} /></div>
                </details>
              </div>
            )}
            {!done.sign && done.merkle && !pw && <div className="mt-3"><Alert kind="info">Enter account password above to authorize signing</Alert></div>}
            <div className="mt-3">
              <Button kind="ghost" onClick={() => step("sign", "crypto/sign", { password: pw })} busy={act.busy} disabled={locked || !done.merkle || !pw}>
                Verify Certificate & Sign
              </Button>
            </div>
          </Step>

          {protectedNow && (
            <Card>
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-slate-800">Artifacts are cryptographically protected and immutable.</span>
                <Link href="/registry" className="inline-flex items-center justify-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-xs transition hover:bg-indigo-700">
                  Continue to Blockchain Registry →
                </Link>
              </div>
            </Card>
          )}
        </>
      )}
    </>
  );
}
