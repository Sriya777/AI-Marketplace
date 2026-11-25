# Upgrade notes — what was inspected, what changed, and why

## Inspection of the uploaded project
The uploaded ZIP was an earlier snapshot (FastAPI v1, no frontend, no deploy bridge). It was compared with the most recent build,
which is a strict superset (adds `chain.py`, the Next.js shell and compile/deploy scripts), and the upgrade was made on that base.

**Already working and kept** (extended, never rewritten from scratch): AES-256-GCM / SHA3 / CSPRNG helpers, ECC/ECDSA/ECDH/HKDF and X.509 primitives,
Merkle tree + proofs, the original CLI demos (`marketplace/*.py`, still pass), Solidity registry concept, solc-js compile + ethers deploy scripts,
web3 bridge, Next.js + wagmi/viem + MetaMask connector, the sample training demo.

**Missing or unsafe, now fixed**

| Finding | Resolution |
|---|---|
| No dataset upload / training / evaluation / deployment / inference | `ml.py`: validation, preprocessing, 7 algorithms with real progress, full metrics, artifact + hash, FastAPI inference |
| Backend stored the **AES key in plaintext in the DB** (`_demoKeyHex`) and used one hardcoded in-process identity | per-model CSPRNG key, never stored in clear; wrapped by escrow (HKDF) and to the owner (ECIES); per-user key stores; CA key encrypted |
| No users/auth, one shared "developer" | accounts with scrypt hashes, sessions, roles, per-user X.509 certificates, developer wallets |
| Signature over the Merkle root only | signature over canonical metadata that commits to every hash, the Merkle root, license and signer cert |
| Merkle tree duplicated odd leaves, no domain separation (second-preimage weakness) | domain-separated tree, odd-node promotion, regression tests |
| `verify_certificate` checked only the signature | full chain validation (issuer, validity, KeyUsage, CA flag, revocation) required before any signature is accepted |
| Contract: anyone could register, no ownership/immutability/revocation | `ModelRegistry.sol` v2 (admin-authorized wallets, owner, duplicates revert, owner-only license/revoke), 17 live-chain tests |
| Verification compared against MongoDB | every check compares against the **on-chain** record |
| In-memory dict as the only persistence | MongoDB + explicitly flagged, persistent file-backed fallback; both tested |
| Single-page frontend with a static ABI copy | 8-page dashboard; ABI/address come from the backend so redeployments are picked up |
| No access control / licensing / distribution / tamper tests | `distribution.py` (grants, licenses, ECC key exchange, decrypt-after-verify), `tamper.py` (6 real attack tests) |

**Replaced (with technical reason)**: the old `/models/upload`, `/models/{id}/verify` backend (plaintext key, shared identity); `deploy.js`-via-hardhat remains for reference, `deploy_raw.js` now writes `deployment.json`; the legacy static `contract.ts`/`OnChainRecord` (old ABI).

## Bugs found by the new test-suites (and fixed)
* Real pymongo `find()` returns a lazy cursor (not a list): `bool()/len()/indexing` misbehaved. The in-memory fallback had hidden it. Fixed with a `MongoCollection` adapter so both stores share one contract.
* My own `Database.refresh()` used `hasattr`, which is always true for pymongo collections (any attribute name returns a sub-collection). Fixed with `isinstance`; caught by the full runner's MongoDB pass.
* Test-traffic pollution: the inner attempts of the "unauthorized download" test were also logged as separate pseudo-tests, inflating the dashboard counts. Inner attempts no longer log.
* Reverted transactions: reasons are parsed from the real Hardhat/web3 error formats, and rejected attempts are real mined failed transactions with hashes.

## Gaps found in a final review against the specification (and closed)
* Endpoint coverage had never been measured: the first measurement showed 52/53 (`undeploy` never exercised). Added an opt-in access log + `tests/endpoint_coverage.py`; now 55/55 and enforced by the test runner.
* Phase 5 lists *retrieve the encrypted model* as a step: added the `retrieve_encrypted` step to the authorization report and `GET /marketplace/models/{id}/encrypted` (ciphertext only, verifiable against the chain).
* Added a dedicated `GET /models/{id}/evaluation` endpoint.
* The Deploy page labelled an undeployed model with a red "failed" badge: now "undeployed".
* UI flows without browser tests (CSV upload valid/invalid, undeploy, step-by-step protection, developer approve/deny) now have them.

## Evidence
`tests/results/TEST_REPORT.md` — 86 automated tests (crypto 28, contract 17, API/integration 28, restart-persistence 1, real-browser 12) plus a check that **all 55 API operations** were exercised (`ENDPOINT_COVERAGE.md`), run on a clean stack with MongoDB 8.3.7 and Hardhat;
the API/integration/persistence suites also pass on the file fallback (`tests/results/file_fallback/`). Screenshots: `tests/results/screenshots/`.
Known gaps (Windows execution, real MetaMask, CIFAR-10 download, public testnet) are listed in the README, section 13.
