// test_contract.js - behavioural tests of ModelRegistry against a LIVE chain
// (every assertion is a real transaction / eth_call; nothing is mocked).
//
//   npx hardhat node          # terminal 1
//   node scripts/deploy_raw.js && node scripts/test_contract.js
//
// Exit code is non-zero if any test fails. Results are also written to
// ../tests/results/contract_tests.json

const fs = require("fs");
const path = require("path");
const { ethers } = require("ethers");

const RPC_URL = process.env.CHAIN_RPC_URL || "http://127.0.0.1:8545";
const ADMIN_KEY = process.env.CHAIN_ADMIN_PRIVATE_KEY ||
  "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80";
const { abi, bytecode } = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "artifacts-custom", "ModelRegistry.json"), "utf8"));

const results = [];
let failures = 0;
async function test(name, fn) {
  try { const detail = await fn(); results.push({ name, passed: true, detail: detail || "" }); console.log("  PASS  " + name + (detail ? "  -> " + detail : "")); }
  catch (e) { failures++; results.push({ name, passed: false, detail: String(e.message || e) }); console.log("  FAIL  " + name + "  -> " + (e.message || e)); }
}
const reason = (e) => e.reason || e.shortMessage || e.message;
async function expectRevert(promise, expected) {
  try { await promise; } catch (e) {
    const r = reason(e);
    if (!String(r).includes(expected)) throw new Error(`reverted with "${r}", expected "${expected}"`);
    return `reverted: "${expected}"`;
  }
  throw new Error(`expected revert "${expected}" but the call succeeded`);
}

const rnd32 = () => ethers.hexlify(ethers.randomBytes(32));
function input(modelId, over = {}) {
  return { modelId, version: "1.0.0", originalHash: rnd32(), encryptedHash: rnd32(), merkleRoot: rnd32(),
           metadataHash: rnd32(), signature: ethers.hexlify(ethers.randomBytes(71)),
           creatorPubKey: ethers.hexlify(ethers.randomBytes(91)), licenseTerms: "single-use", ...over };
}

async function main() {
  const provider = new ethers.JsonRpcProvider(RPC_URL, undefined, { cacheTimeout: -1 });
  const admin = new ethers.NonceManager(new ethers.Wallet(ADMIN_KEY, provider));
  const fund = async (w) => { const t = await admin.sendTransaction({ to: w.address, value: ethers.parseEther("5") }); await t.wait(); return w; };

  const factory = new ethers.ContractFactory(abi, bytecode, admin);
  const c = await factory.deploy(); await c.waitForDeployment();
  const addr = await c.getAddress();
  console.log("Fresh contract deployed for testing at", addr);
  const as = (w) => c.connect(w);
  const newWallet = () => fund(new ethers.Wallet(ethers.Wallet.createRandom().privateKey, provider));

  const devA = await newWallet();
  const devB = await newWallet();
  const rogue = await newWallet();
  const id = "mdl_test_" + Date.now();
  const inp = input(id);

  console.log("\nContract behaviour tests");
  await test("deployer is admin and authorized developer", async () => {
    if ((await c.admin()) !== (await admin.getAddress())) throw new Error("admin mismatch");
    if (!(await c.authorizedDevelopers(await admin.getAddress()))) throw new Error("admin not authorized");
  });
  await test("non-admin cannot authorize developers", () => expectRevert(as(rogue).authorizeDeveloper(rogue.address), "Only admin"));
  await test("UNAUTHORIZED wallet cannot register a model", () => expectRevert(as(rogue).registerModel(input("rogue_" + id)), "Not an authorized developer"));
  await test("admin authorizes developer A and B", async () => {
    await (await c.authorizeDeveloper(devA.address)).wait(); await (await c.authorizeDeveloper(devB.address)).wait();
    if (!(await c.authorizedDevelopers(devA.address)) || !(await c.authorizedDevelopers(devB.address))) throw new Error("not authorized");
  });
  let regReceipt;
  await test("authorized developer registers a model (real tx)", async () => {
    const tx = await as(devA).registerModel(inp); regReceipt = await tx.wait();
    if (regReceipt.status !== 1) throw new Error("tx failed");
    return `tx ${regReceipt.hash.slice(0, 12)}... block ${regReceipt.blockNumber}`;
  });
  await test("record can be retrieved and matches what was registered", async () => {
    const r = await c.getRecord(id);
    const checks = { modelId: r.modelId === id, creator: r.creator === devA.address, originalHash: r.originalHash === inp.originalHash,
      encryptedHash: r.encryptedHash === inp.encryptedHash, merkleRoot: r.merkleRoot === inp.merkleRoot,
      metadataHash: r.metadataHash === inp.metadataHash, signature: r.signature === inp.signature,
      pubKey: r.creatorPubKey === inp.creatorPubKey, license: r.licenseTerms === "single-use",
      block: Number(r.registeredBlock) === regReceipt.blockNumber, notRevoked: r.revoked === false };
    const bad = Object.entries(checks).filter(([, v]) => !v).map(([k]) => k);
    if (bad.length) throw new Error("mismatch: " + bad.join(","));
    return `owner=${r.creator.slice(0, 10)}... timestamp=${r.registeredAt}`;
  });
  await test("DUPLICATE registration by the owner is rejected", () => expectRevert(as(devA).registerModel(input(id)), "Model already registered"));
  await test("DUPLICATE registration by another authorized developer is rejected", () => expectRevert(as(devB).registerModel(input(id)), "Model already registered"));
  await test("non-owner cannot update the license", () => expectRevert(as(devB).updateLicense(id, "free-for-all"), "Not the model owner"));
  await test("non-owner cannot revoke the model", () => expectRevert(as(devB).revokeModel(id), "Not the model owner"));
  await test("unauthorized wallet cannot update the license", () => expectRevert(as(rogue).updateLicense(id, "x"), "Not the model owner"));
  await test("owner can update license; integrity fields stay immutable", async () => {
    await (await as(devA).updateLicense(id, "unlimited")).wait();
    const r = await c.getRecord(id);
    if (r.licenseTerms !== "unlimited") throw new Error("license not updated");
    if (r.originalHash !== inp.originalHash || r.merkleRoot !== inp.merkleRoot || r.signature !== inp.signature) throw new Error("integrity fields changed!");
  });
  await test("invalid inputs rejected (zero hash, empty id)", async () => {
    await expectRevert(as(devA).registerModel(input("z_" + id, { merkleRoot: ethers.ZeroHash })), "Invalid hash");
    return await expectRevert(as(devA).registerModel(input("", {})), "Invalid model id");
  });
  await test("unknown model id -> Model not found", () => expectRevert(c.getRecord("does-not-exist"), "Model not found"));
  await test("owner can revoke; further changes blocked", async () => {
    await (await as(devA).revokeModel(id)).wait();
    if (!(await c.getRecord(id)).revoked) throw new Error("not revoked");
    return await expectRevert(as(devA).updateLicense(id, "again"), "Model revoked");
  });
  await test("model enumeration (modelCount / modelIdAt)", async () => {
    const n = Number(await c.modelCount()); if (n !== 1) throw new Error("count=" + n);
    if ((await c.modelIdAt(0)) !== id) throw new Error("modelIdAt mismatch");
  });
  await test("admin can revoke a developer; they can no longer register", async () => {
    await (await c.revokeDeveloper(devB.address)).wait();
    return await expectRevert(as(devB).registerModel(input("b_" + id)), "Not an authorized developer");
  });

  console.log(`\n${results.length - failures}/${results.length} contract tests passed`);
  const outDir = path.join(__dirname, "..", "..", "tests", "results");
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, "contract_tests.json"),
    JSON.stringify({ ranAt: new Date().toISOString(), chain: RPC_URL, contract: addr, total: results.length, failed: failures, results }, null, 2));
  process.exit(failures ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(2); });
