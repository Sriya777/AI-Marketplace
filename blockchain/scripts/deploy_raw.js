// deploy_raw.js - deploys the solc-compiled ModelRegistry with ethers.js to a running node
// (e.g. `npx hardhat node`) and writes deployment.json, which the backend reads.
//
// Env: CHAIN_RPC_URL (default http://127.0.0.1:8545), CHAIN_ADMIN_PRIVATE_KEY
//      (default = Hardhat's well-known Account #0; LOCAL DEVELOPMENT ONLY)

const fs = require("fs");
const path = require("path");
const { ethers } = require("ethers");

const ARTIFACT = path.join(__dirname, "..", "artifacts-custom", "ModelRegistry.json");
const OUT = path.join(__dirname, "..", "deployment.json");
const RPC_URL = process.env.CHAIN_RPC_URL || "http://127.0.0.1:8545";
const KEY = process.env.CHAIN_ADMIN_PRIVATE_KEY ||
  "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80";

async function main() {
  if (!fs.existsSync(ARTIFACT)) throw new Error("Run `node scripts/compile.js` first");
  const { abi, bytecode } = JSON.parse(fs.readFileSync(ARTIFACT, "utf8"));
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const net = await provider.getNetwork();
  const wallet = new ethers.Wallet(KEY, provider);

  console.log(`Deploying ModelRegistry to chain ${net.chainId} (${RPC_URL}) from ${wallet.address}`);
  const factory = new ethers.ContractFactory(abi, bytecode, wallet);
  const contract = await factory.deploy();
  const receipt = await contract.deploymentTransaction().wait();
  const address = await contract.getAddress();

  const info = {
    contractName: "ModelRegistry",
    address,
    chainId: Number(net.chainId),
    rpcUrl: RPC_URL,
    deployer: wallet.address,
    txHash: receipt.hash,
    blockNumber: receipt.blockNumber,
    deployedAt: new Date().toISOString(),
  };
  fs.writeFileSync(OUT, JSON.stringify(info, null, 2));
  console.log("ModelRegistry deployed to:", address);
  console.log("tx:", receipt.hash, "block:", receipt.blockNumber);
  console.log("Saved deployment info -> blockchain/deployment.json");
}

main().catch((e) => { console.error(e.message || e); process.exit(1); });
