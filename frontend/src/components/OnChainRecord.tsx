"use client";
import { useReadContract } from "wagmi";
import { Json } from "@/lib/api";
import { hardhatLocal } from "@/lib/wagmi-config";
import { useChainConfig } from "@/lib/chainConfig";
import { Alert, Badge, KV, Mono } from "./ui";

export default function OnChainRecord({ modelId, expected }: { modelId: string; expected?: Json }) {
  const { cfg, error } = useChainConfig();
  const { data, isLoading, isError, error: readError } = useReadContract({
    address: cfg?.address,
    abi: cfg?.abi,
    functionName: "getRecord",
    args: [modelId],
    chainId: hardhatLocal.id,
    query: { enabled: !!cfg },
  });
  if (error) return <Alert>Chain configuration unavailable: {error}</Alert>;
  if (!cfg || isLoading) return <p className="text-sm font-medium text-slate-600">Reading blockchain state…</p>;
  if (isError) return <Alert kind="info">Record not found on-chain ({(readError as Error)?.message?.split("\n")[0].slice(0, 120)}).</Alert>;
  const r = data as Json;
  const same = (a: string, b?: string) => !expected || (b && a.toLowerCase() === b.toLowerCase());
  return (
    <dl>
      <KV k="Source" v="Direct RPC (ModelRegistry.getRecord)" />
      <KV k="Model ID / Version" v={`${r.modelId} · v${r.version}`} />
      <KV k="Owner (Creator)" v={<Mono>{r.creator}</Mono>} />
      <KV k="Original Hash (SHA3-256)" v={<><Mono>{r.originalHash}</Mono> {expected && <Badge>{same(r.originalHash, expected.originalHash) ? "PASS" : "FAIL"}</Badge>}</>} />
      <KV k="Encrypted Hash (SHA3-256)" v={<Mono>{r.encryptedHash}</Mono>} />
      <KV k="Merkle Root" v={<><Mono>{r.merkleRoot}</Mono> {expected && <Badge>{same(r.merkleRoot, expected.merkleRoot) ? "PASS" : "FAIL"}</Badge>}</>} />
      <KV k="Metadata Hash" v={<Mono>{r.metadataHash}</Mono>} />
      <KV k="ECDSA Signature" v={<Mono>{String(r.signature).slice(0, 66)}…</Mono>} />
      <KV k="License" v={r.licenseTerms} />
      <KV k="Registration" v={`Block ${String(r.registeredBlock)} · ${new Date(Number(r.registeredAt) * 1000).toLocaleString()}`} />
      <KV k="Revocation Status" v={<Badge>{r.revoked ? "FAIL" : "PASS"}</Badge>} />
    </dl>
  );
}
