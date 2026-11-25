import { createConnector } from "wagmi";

/**
 * Minimal hand-rolled MetaMask (window.ethereum) connector.
 *
 * Why not wagmi's built-in injected() from "wagmi/connectors": that
 * barrel file re-exports every connector (Coinbase, Safe, Base Account),
 * and the Base Account connector currently pulls in a broken transitive
 * dependency chain (@coinbase/cdp-sdk -> @x402/*) that doesn't resolve
 * under Next.js's bundler - an upstream packaging bug, not anything in
 * this app. We only need MetaMask, so implementing just that against
 * window.ethereum sidesteps the whole broken chain.
 */
export function metaMaskConnector() {
  return createConnector((config) => ({
    id: "metaMask",
    name: "MetaMask",
    type: "injected",

    async connect<withCapabilities extends boolean = false>() {
      const provider = await this.getProvider();
      const accounts = (await provider.request({
        method: "eth_requestAccounts",
      })) as `0x${string}`[];
      const chainId = await this.getChainId();
      return {
        accounts: accounts as unknown as withCapabilities extends true
          ? readonly { address: `0x${string}`; capabilities: Record<string, unknown> }[]
          : readonly `0x${string}`[],
        chainId,
      };
    },

    async disconnect() {
      // MetaMask has no programmatic disconnect; wagmi just clears local state.
    },

    async getAccounts() {
      const provider = await this.getProvider();
      const accounts = (await provider.request({
        method: "eth_accounts",
      })) as string[];
      return accounts as readonly `0x${string}`[];
    },

    async getChainId() {
      const provider = await this.getProvider();
      const hexChainId = (await provider.request({
        method: "eth_chainId",
      })) as string;
      return Number(hexChainId);
    },

    async getProvider() {
      const eth = (window as any).ethereum;
      if (!eth) throw new Error("MetaMask not found - install the browser extension.");
      return eth;
    },

    async isAuthorized() {
      try {
        const accounts = await this.getAccounts();
        return accounts.length > 0;
      } catch {
        return false;
      }
    },

    onAccountsChanged(accounts: string[]) {
      config.emitter.emit("change", {
        accounts: accounts as readonly `0x${string}`[],
      });
    },

    onChainChanged(chainId: string) {
      config.emitter.emit("change", { chainId: Number(chainId) });
    },

    onDisconnect() {
      config.emitter.emit("disconnect");
    },
  }));
}
