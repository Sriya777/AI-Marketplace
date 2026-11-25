"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount, useBalance, useConnect } from "wagmi";
import { createWalletClient, custom } from "viem";
import { api, Json, short } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useChainConfig } from "@/lib/chainConfig";
import { hardhatLocal } from "@/lib/wagmi-config";
import ModelPicker, { useModel } from "@/components/ModelPicker";
import OnChainRecord from "@/components/OnChainRecord";
import { Alert, Badge, Button, Card, JsonBlock, KV, Mono, useAction, usePassword } from "@/components/ui";

declare global { interface Window { ethereum?: { request: (a: { method: string; params?: unknown[] }) => Promise<unknown> } } }

async function ensureHardhatNetwork() {
  const eth = window.ethereum;
  if (!eth) throw new Error("MetaMask is not installed in this browser.");
  const chainIdHex = "0x" + hardhatLocal.id.toString(16);
  try { await eth.request({ method: "wallet_switchEthereumChain", params: [{ chainId: chainIdHex }] }); }
  catch {
    await eth.request({
      method: "wallet_addEthereumChain",
      params: [{
        chainId: chainIdHex,
        chainName: "Hardhat Local",
        nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 },
        rpcUrls: ["http://127.0.0.1:8545"]
      }]
    });
  }
}

export default function RegistryPage() {
  const { activeModelId, user, refreshUser } = useSession();
  const { model, reload } = useModel();
  const { cfg } = useChainConfig();
  const { address, isConnected, chainId } = useAccount();
  const { connect, connectors } = useConnect();
  const { data: bal } = useBalance({ address, chainId: hardhatLocal.id });
  const { pw, el: pwEl } = usePassword("Developer Account Password");
  const act = useAction();
  const [chainStatus, setChainStatus] = useState<Json | null>(null);
  const [payload, setPayload] = useState<Json | null>(null);
  const [onchain, setOnchain] = useState<Json | null>(null);
  const [mmLog, setMmLog] = useState<string[]>([]);

  const status = model?.status;
  const isRegistered = status === "registered";
  const isPackaged = status === "packaged" || status === "protected" || isRegistered;

  useEffect(() => {
    api.get("/chain/status").then(setChainStatus).catch(() => {});
  }, [status]);

  useEffect(() => {
    setPayload(null);
    setOnchain(null);
    if (!activeModelId) return;
    if (isPackaged && !isRegistered) {
      api.get(`/models/${activeModelId}/chain-payload`).then(setPayload).catch(() => {});
    }
    if (isRegistered) {
      api.get(`/models/${activeModelId}/onchain`).then(setOnchain).catch(() => {});
    }
  }, [activeModelId, isPackaged, isRegistered]);

  const registerCustodial = () => act.run(async () => {
    if (!pw) throw new Error("Enter developer password to unlock wallet private key");
    await api.post(`/models/${activeModelId}/register`, { password: pw });
    await reload();
  });

  const registerMetaMask = () => act.run(async () => {
    const log = (s: string) => setMmLog((l) => [...l, s]);
    setMmLog([]);
    if (!window.ethereum) throw new Error("MetaMask is not installed in this browser.");
    if (!cfg) throw new Error("Blockchain configuration is not available");
    log("Switching MetaMask to local network…");
    await ensureHardhatNetwork();
    const wallet = createWalletClient({ chain: hardhatLocal, transport: custom(window.ethereum) });
    const [account] = await wallet.requestAddresses();
    log(`Using wallet address ${account}`);
    log("Authorizing wallet on-chain…");
    await api.post("/me/wallets/link", { address: account });
    await refreshUser();
    const p = await api.get(`/models/${activeModelId}/chain-payload`);
    log("Submitting registerModel() transaction to smart contract…");
    const hash = await wallet.writeContract({ address: cfg.address, abi: cfg.abi, functionName: "registerModel", args: [p], account });
    log(`Transaction broadcast: ${hash}`);
    log("Awaiting block confirmation and verifying receipt…");
    await api.post(`/models/${activeModelId}/register/confirm`, { tx_hash: hash });
    log("Registration confirmed on-chain.");
    await reload();
  });

  const bc = model?.blockchain;

  return (
    <>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Stage 6 · Blockchain Registration</h1>
        </div>
      </div>

      <ModelPicker
        model={model}
        filter={(m) => m.status === "packaged" || m.status === "protected" || m.status === "registered" || m.status === "deployed"}
        label="Select Packaged Model to Register"
      />

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Blockchain Network State">
          {chainStatus?.connected ? (
            <dl>
              <KV k="Connection Status" v={<Badge>PASS</Badge>} />
              <KV k="Chain ID" v={chainStatus.chainId} />
              <KV k="Block Height" v={chainStatus.blockNumber} />
              <KV k="ModelRegistry Contract" v={<Mono>{chainStatus.contractAddress}</Mono>} />
              <KV k="Confirmed Models" v={chainStatus.modelCount} />
            </dl>
          ) : (
            <Alert>Blockchain node unreachable: {chainStatus?.error || "Local node not running on port 8545"}</Alert>
          )}
        </Card>

        <Card title="Developer Wallets">
          <dl>
            <KV k="Custodial Developer Wallet" v={<Mono>{user?.wallet_address}</Mono>} />
            <KV k="Balance & Authorization" v={`${user?.wallet_balance_eth?.toFixed?.(3) ?? "—"} ETH · ${user?.wallet_authorized ? "Authorized" : "Unauthorized"}`} />
            <KV k="MetaMask Status" v={isConnected ? <><Mono>{address}</Mono> <Badge>{chainId === hardhatLocal.id ? "PASS" : "FAIL"}</Badge></> : "Not connected"} />
            {isConnected && <KV k="MetaMask Balance" v={bal ? `${Number(bal.formatted).toFixed(3)} ETH` : "—"} />}
          </dl>
          <div className="mt-4">
            <Button kind="ghost" onClick={() => act.run(ensureHardhatNetwork)}>
              Switch MetaMask to Hardhat Local
            </Button>
          </div>
        </Card>
      </div>

      {model && !isPackaged && (
        <Alert kind="info">
          This model has not been packaged yet. Please complete <Link href="/package" className="underline font-semibold">Stage 4: Model Packaging</Link> before blockchain registration.
        </Alert>
      )}

      {model && isPackaged && !isRegistered && (
        <Card title="Execute On-Chain Registration">
          {payload && (
            <dl className="mb-5">
              <KV k="Original Artifact Hash" v={<Mono>{payload.originalHash}</Mono>} />
              <KV k="Encrypted Artifact Hash" v={<Mono>{payload.encryptedHash}</Mono>} />
              <KV k="Merkle Root" v={<Mono>{payload.merkleRoot}</Mono>} />
              <KV k="Signed Metadata Hash" v={<Mono>{payload.metadataHash}</Mono>} />
              <KV k="ECDSA Signature" v={<Mono>{short(payload.signature, 24)}</Mono>} />
              <KV k="License Policy" v={payload.licenseTerms} />
            </dl>
          )}

          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-700">Option A: Developer Custodial Wallet</div>
              {pwEl}
              <div className="mt-4">
                <Button onClick={registerCustodial} busy={act.busy} disabled={!pw}>
                  Register via Custodial Wallet
                </Button>
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-700">Option B: MetaMask Extension Wallet</div>
              {!isConnected ? (
                <div className="space-y-3">
                  <p className="text-xs text-slate-600">Connect your MetaMask browser extension to submit on-chain registration.</p>
                  <Button
                    onClick={() => {
                      if (typeof window !== "undefined" && !window.ethereum) {
                        alert("MetaMask extension not detected. Please install MetaMask in your browser.");
                        return;
                      }
                      const c = connectors[0];
                      if (c) connect({ connector: c });
                    }}
                  >
                    Connect MetaMask
                  </Button>
                </div>
              ) : chainId !== hardhatLocal.id ? (
                <div className="space-y-3">
                  <Alert kind="info">MetaMask is on a different network. Please switch to Hardhat Local (31337).</Alert>
                  <Button onClick={() => act.run(ensureHardhatNetwork)} busy={act.busy}>
                    Switch MetaMask to Hardhat Local (31337)
                  </Button>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="flex items-center justify-between text-xs font-mono bg-white p-2.5 rounded-lg border border-slate-200">
                    <span className="font-semibold text-slate-800">{short(address || "", 12)}</span>
                    <span className="text-slate-500 font-sans font-medium">{bal ? `${Number(bal.formatted).toFixed(3)} ETH` : "—"}</span>
                  </div>
                  <Button onClick={registerMetaMask} busy={act.busy}>
                    Register via MetaMask
                  </Button>
                  {mmLog.length > 0 && <pre className="mt-3 rounded-lg border border-slate-800 bg-slate-950 p-3 font-mono text-xs text-emerald-300 whitespace-pre-wrap">{mmLog.join("\n")}</pre>}
                </div>
              )}
            </div>
          </div>
          {act.error && <div className="mt-4"><Alert>{act.error}</Alert></div>}
        </Card>
      )}

      {model && isRegistered && bc && (
        <>
          <Card title="Blockchain Transaction Confirmation" right={<Badge>registered</Badge>}>
            <dl>
              <KV k="Transaction Hash" v={<Mono>{bc.tx_hash}</Mono>} />
              <KV k="Block Number" v={bc.block_number} />
              <KV k="Block Timestamp" v={new Date(bc.block_timestamp * 1000).toLocaleString()} />
              <KV k="Gas Used" v={bc.gas_used} />
              <KV k="Smart Contract" v={<Mono>{bc.contract_address}</Mono>} />
              <KV k="Registered Owner Wallet" v={<Mono>{bc.creator}</Mono>} />
              <KV k="Registration Mechanism" v={bc.registered_via} />
            </dl>
          </Card>

          <Card title="Verified On-Chain State (Direct RPC Query)">
            <OnChainRecord modelId={model.id} expected={onchain?.record ? { originalHash: onchain.record.originalHash, merkleRoot: onchain.record.merkleRoot } : undefined} />
            {onchain && (
              <details className="mt-4 text-sm">
                <summary className="cursor-pointer font-semibold text-indigo-600 hover:text-indigo-700">Raw Smart Contract Record</summary>
                <div className="mt-2"><JsonBlock data={onchain.record} /></div>
              </details>
            )}
          </Card>

          <div className="mt-4">
            <Link
              href="/marketplace"
              className="inline-flex items-center justify-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-xs transition hover:bg-indigo-700"
            >
              Browse in Marketplace →
            </Link>
          </div>
        </>
      )}
    </>
  );
}
