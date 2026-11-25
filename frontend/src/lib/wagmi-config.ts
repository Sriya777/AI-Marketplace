import { http, createConfig } from "wagmi";
import { defineChain } from "viem";
import { metaMaskConnector } from "./metamask-connector";

// Hardhat's local node, chain id 31337. Swap for Polygon Amoy's chain
// definition (from viem/chains: polygonAmoy) if deploying to that
// testnet instead - everything else in the app stays the same.
export const hardhatLocal = defineChain({
  id: 31337,
  name: "Hardhat Local",
  nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 },
  rpcUrls: { default: { http: ["http://127.0.0.1:8545"] } },
});

export const wagmiConfig = createConfig({
  chains: [hardhatLocal],
  connectors: [metaMaskConnector()],
  transports: {
    [hardhatLocal.id]: http(),
  },
});
