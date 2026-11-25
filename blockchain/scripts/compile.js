// compile.js - compiles contracts/ModelRegistry.sol with the `solc` NPM package (solc-js, v0.8.20).
// Using solc-js means NO compiler binary is downloaded at runtime, so it works behind
// restrictive networks/firewalls and on Windows without extra setup.
//
// Run: node scripts/compile.js     ->  artifacts-custom/ModelRegistry.json  (abi + bytecode)

const fs = require("fs");
const path = require("path");
const solc = require("solc");

const CONTRACT_PATH = path.join(__dirname, "..", "contracts", "ModelRegistry.sol");
const OUT_DIR = path.join(__dirname, "..", "artifacts-custom");

const source = fs.readFileSync(CONTRACT_PATH, "utf8");
const input = {
  language: "Solidity",
  sources: { "ModelRegistry.sol": { content: source } },
  settings: {
    optimizer: { enabled: true, runs: 200 },
    outputSelection: { "*": { "*": ["abi", "evm.bytecode.object"] } },
  },
};

const output = JSON.parse(solc.compile(JSON.stringify(input)));
if (output.errors) {
  output.errors.forEach((e) => console.log(e.formattedMessage));
  if (output.errors.some((e) => e.severity === "error")) process.exit(1);
}
const c = output.contracts["ModelRegistry.sol"]["ModelRegistry"];
fs.mkdirSync(OUT_DIR, { recursive: true });
fs.writeFileSync(
  path.join(OUT_DIR, "ModelRegistry.json"),
  JSON.stringify({ contractName: "ModelRegistry", compiler: solc.version(), abi: c.abi, bytecode: "0x" + c.evm.bytecode.object }, null, 2)
);
console.log("Compiled OK (" + solc.version() + ") -> artifacts-custom/ModelRegistry.json");
