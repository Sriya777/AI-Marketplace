"use client";

import { useAccount, useConnect, useDisconnect } from "wagmi";
import { hardhatLocal } from "@/lib/wagmi-config";
import { useState } from "react";

export default function ConnectWallet() {
  const { address, isConnected, chainId } = useAccount();
  const { connect, connectors, isPending } = useConnect();
  const { disconnect } = useDisconnect();
  const [copied, setCopied] = useState(false);

  const copyAddress = () => {
    if (address) {
      navigator.clipboard.writeText(address);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const isHardhatNetwork = chainId === hardhatLocal.id;

  async function switchOrAddNetwork() {
    const eth = typeof window !== "undefined" ? (window as any).ethereum : null;
    if (!eth) return;
    const chainIdHex = "0x" + hardhatLocal.id.toString(16);
    try {
      await eth.request({ method: "wallet_switchEthereumChain", params: [{ chainId: chainIdHex }] });
    } catch {
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

  if (isConnected) {
    return (
      <div className="flex items-center gap-2">
        {/* Network status pill */}
        {isHardhatNetwork ? (
          <div className="flex items-center gap-1.5 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
            Hardhat (31337)
          </div>
        ) : (
          <button
            onClick={switchOrAddNetwork}
            title="Click to switch MetaMask to Hardhat Local (31337)"
            className="flex items-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800 transition hover:bg-amber-100"
          >
            <span className="h-2 w-2 rounded-full bg-amber-500"></span>
            Wrong Network · Switch
          </button>
        )}

        {/* Address badge */}
        <button
          onClick={copyAddress}
          title="Click to copy address"
          className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-mono font-semibold text-slate-800 shadow-2xs hover:bg-slate-100 transition"
        >
          <span>{address?.slice(0, 6)}…{address?.slice(-4)}</span>
          {copied && <span className="text-[10px] text-emerald-600 font-sans font-bold">Copied!</span>}
        </button>

        <button
          onClick={() => disconnect()}
          className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs font-semibold text-slate-600 shadow-2xs transition hover:bg-slate-50 hover:text-slate-900"
        >
          Disconnect
        </button>
      </div>
    );
  }

  const injectedConnector = connectors[0];

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => {
          if (typeof window !== "undefined" && !(window as any).ethereum) {
            alert("MetaMask extension not detected in this browser. Please install MetaMask to interact with the blockchain.");
            return;
          }
          if (injectedConnector) connect({ connector: injectedConnector });
        }}
        disabled={isPending}
        className="inline-flex items-center gap-2 rounded-lg bg-orange-600 px-3.5 py-1.5 text-xs font-semibold text-white shadow-xs transition hover:bg-orange-700 active:bg-orange-800 disabled:opacity-50"
      >
        <svg className="h-3.5 w-3.5 fill-current" viewBox="0 0 24 24">
          <path d="M21.9 8.2l-2.1-7.2c-.1-.4-.6-.6-.9-.3L12 6.8 5.1.7c-.3-.3-.8-.1-.9.3L2.1 8.2c-.2.5 0 1.1.5 1.4l9 5.8c.3.2.7.2.9 0l9-5.8c.4-.3.6-.9.4-1.4z" />
        </svg>
        {isPending ? "Connecting…" : "Connect MetaMask"}
      </button>
    </div>
  );
}
