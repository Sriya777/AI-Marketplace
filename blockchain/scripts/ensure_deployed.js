// ensure_deployed.js - compiles the contract if needed and (re)deploys it when the chain has no code at the
// address recorded in deployment.json (e.g. after restarting `hardhat node`, which wipes the chain).
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const { ethers } = require("ethers");

const ROOT = path.join(__dirname, "..");
const DEPLOYMENT = path.join(ROOT, "deployment.json");
const ARTIFACT = path.join(ROOT, "artifacts-custom", "ModelRegistry.json");
const SOURCE = path.join(ROOT, "contracts", "ModelRegistry.sol");
const RPC = process.env.CHAIN_RPC_URL || "http://127.0.0.1:8545";

function run(script) { execFileSync(process.execPath, [path.join(__dirname, script)], { stdio: "inherit", cwd: ROOT }); }

(async () => {
  if (!fs.existsSync(ARTIFACT) || fs.statSync(SOURCE).mtimeMs > fs.statSync(ARTIFACT).mtimeMs) run("compile.js");
  const provider = new ethers.JsonRpcProvider(RPC);
  let needDeploy = true;
  if (fs.existsSync(DEPLOYMENT)) {
    const dep = JSON.parse(fs.readFileSync(DEPLOYMENT, "utf8"));
    try { needDeploy = (await provider.getCode(dep.address)) === "0x"; } catch (e) { needDeploy = true; }
    if (!needDeploy) console.log("Contract already deployed at", dep.address);
  }
  if (needDeploy) run("deploy_raw.js");
})().catch((e) => { console.error(e.message || e); process.exit(1); });
