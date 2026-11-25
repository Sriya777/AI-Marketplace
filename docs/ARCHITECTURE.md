# Architecture & security design

## 1. Components

```
 Browser (Next.js · wagmi/viem · MetaMask)                         ┌───────────────────────────┐
        │  /api/*  (proxied by the Next.js server)                 │  MongoDB (or file dev DB) │
        ▼                                                          │  users · datasets · models │
 FastAPI backend ──────────────────────────────────────────────────►  grants · downloads ·      │
   ml.py          train / evaluate / deploy / infer (scikit-learn)  │  sessions · verification_ │
   protection.py  SHA3 → AES-GCM → Merkle → ECDSA                   │  logs                     │
   registration   web3.py ──┐                                       └───────────────────────────┘
   verification   ◄─────────┤  JSON-RPC            storage/models/<id>/model.enc  (ciphertext only)
   distribution             ▼                      storage/ca/  (CA cert + passphrase-encrypted CA key)
   tamper tests      Hardhat chain ── ModelRegistry.sol  (authoritative integrity + ownership records)
```

## 2. Data flow (each stage uses the previous stage's real output)

| Stage | Input | Output (stored) |
|---|---|---|
| Train | validated CSV | `model.joblib` (full preprocessing + estimator pipeline), SHA3-256 `artifact_sha3`, metrics |
| Deploy | `model.joblib` | in-memory model; `deployment.artifact_sha3` **must equal** `artifact_sha3` |
| Hash | artifact bytes | `original_sha3` (= training hash = deployed hash, enforced) |
| Encrypt | artifact bytes | `model.enc` (AES-256-GCM), `encrypted_sha3`, wrapped keys; plaintext is then securely deleted |
| Merkle | `model.enc` | 16 KiB-chunk SHA3 tree, root, leaf hashes |
| Sign | all of the above + license + developer cert | canonical metadata JSON, `metadata_sha3`, ECDSA signature |
| Register | the values above | one `registerModel` transaction (hashes, root, metadata hash, signature, public key, license, owner) |
| Verify | stored file + DB + **chain record** | 8 PASS/FAIL checks; every comparison is against the on-chain values |
| Distribute | grant + buyer password | the encrypted model is retrieved, then (only if every check passes) decrypted for the authorized buyer |

Lifecycle order is enforced server-side (e.g. protection is refused for a model that was not deployed; registration is refused before signing).

## 3. Cryptography inventory

| Technique | Where | Parameters / notes |
|---|---|---|
| **AES-256-GCM** | model encryption (`protection.step_encrypt`) | CSPRNG 256-bit key, 96-bit nonce, 128-bit tag; AAD = `modelId|version|originalSha3` binds ciphertext to the model |
| **SHA3-256** | file hashes, Merkle tree, metadata hash, certificate fingerprints, ECDSA digest | NIST FIPS 202 vectors tested |
| **ECC / ECDSA** | developer identity + signature | NIST P-256; ECDSA with SHA3-256 over the **canonical metadata** (which contains original/encrypted hashes, Merkle root, license, signer cert fingerprint) |
| **ECDH + HKDF** | key distribution (`keywrap.ecies_wrap`) | ephemeral-static ECDH (P-256) → HKDF-SHA256 (random 32-byte salt, `info` = purpose + model + recipient) → AES-GCM wrap of the content key. Used for the developer's copy and for each authorized buyer |
| **HKDF** | KEKs everywhere | escrow KEK (`info`=model id), key-store wrapping key, CA-key KEK, ECIES KEKs. Explicit salt + context are mandatory (tested; RFC 5869 vector) |
| **scrypt** | passwords, master passphrase | N=2^15, r=8, p=1; passwords stored only as scrypt hashes |
| **Merkle tree** | integrity of the ciphertext | leaf = SHA3(0x00‖chunk), node = SHA3(0x01‖l‖r) (domain separation); odd nodes promoted, not duplicated (CVE-2012-2459 class); single-chunk proofs |
| **X.509** | identities | local CA (P-256). End-entity certs carry role, KeyUsage, BasicConstraints. Validation = issuer, CA signature, validity window, not-a-CA, key usage, revocation. A signature is accepted only after the signer's certificate validates |
| **CSPRNG** | keys, nonces, salts, tokens, IDs | `os.urandom` / `secrets` only |

## 4. Who holds which secret

| Secret | Where | Protection |
|---|---|---|
| User password | nowhere | only a scrypt hash |
| User ECC private key | DB (`ec_private_enc`) | AES-GCM under HKDF(scrypt(password)); unlocked per action |
| Developer wallet key | DB (`wallet_private_enc`) | same |
| CA private key | `storage/ca/ca_key.enc.json` | AES-GCM under HKDF(scrypt(master passphrase)) |
| Master passphrase | environment / `.env` only | never written to DB/storage |
| Content key (AES) | **nowhere in the clear** | wrapped (a) for escrow under a master-derived KEK, (b) to the developer's public key (ECIES). Buyer copies are derived on demand and discarded |
| Plaintext model | memory (deployed) | file securely deleted after signing; reloaded by decrypting the stored ciphertext |

An automated test scans the whole database and storage for private-key PEMs, the master passphrase, user passwords and the content key (hex and base64) and finds none.

## 5. Blockchain design

*On-chain*: model id, version, owner wallet, original hash, encrypted hash, Merkle root, metadata hash, ECDSA signature, signer public key (DER), license text, timestamp, block number, revoked flag.
*Never on-chain*: the model, any key, the dataset.

Contract rules (all covered by tests against a live chain): admin-only developer authorization; registration only by authorized wallets; `msg.sender` = immutable owner;
duplicate ids revert; no function can modify hashes/root/signature; only the owner can update the license or revoke; invalid inputs (zero hash, empty id) revert.
The EVM cannot verify P-256 signatures, so the signature + public key are stored as a verification reference and checked off-chain by anyone who reads the record.

## 6. The eight verification checks (what each one stops)

| # | Check | Mechanism | Stops |
|---|---|---|---|
| 1 | Developer certificate chains to the CA | CA signature, validity, KeyUsage, not revoked | impersonation with a self-made key / rogue CA |
| 2 | Record exists on-chain, not revoked | `getRecord` | unregistered or withdrawn models |
| 3 | Creator wallet belongs to the developer | wallet ∈ developer's wallets | registering someone else's work |
| 4 | SHA3-256(ciphertext) == on-chain `encryptedHash` | collision resistance | any modification of the stored file |
| 5 | Merkle root of the chunks == on-chain root | recomputed tree; mismatching chunk indices are reported | same, with **localization** of the tampered chunks |
| 6 | SHA3-256(canonical metadata recomputed from stored fields) == on-chain `metadataHash` | | editing license/hashes/metrics in the database |
| 7 | ECDSA signature valid under the **certified** public key | signature unforgeability | forged or modified signed metadata |
| 8 | Stored signature & key == on-chain signature & key | | swapping the signature/key in the database |

On download, additionally: AES-GCM tag verification, `SHA3-256(plaintext) == on-chain originalHash`.

## 7. Threat model → defense → proof

| Attack | Defense | Test |
|---|---|---|
| Flip bytes in the stored encrypted model | checks 4, 5 (the tampered chunk indices are reported), GCM `InvalidTag`; distribution refuses and the key exchange never starts | `test_21`, `test_20`, browser test |
| Modify signature or signed metadata | checks 6, 7, 8 | `test_21` |
| Register without authorization | contract `Not an authorized developer` (real failed transaction with a hash) | `test_21`, contract tests |
| Change/revoke someone else's model | contract `Not the model owner` | same |
| Re-register an existing id | contract `Model already registered`; DB unique key | same |
| Download without permission | no grant / denied / pending / exhausted license → 403; wrong password → private key cannot be unlocked → no key exchange | `test_18/19/21` |
| Rogue-CA certificate | certificate chain validation fails | `test_03`, CLI demo |
| Stolen database dump | no plaintext keys/passwords/models; keys need user password or master passphrase | `test_12` |
| Merkle second-preimage / duplicated-leaf collision | domain separation; no leaf duplication | `test_crypto_suite` |

## 8. Suggested emphasis per course

* **Applied Cryptography:** §3–§4 and §6 — why each primitive, parameter choices, key hierarchy, nonce/AAD handling, Merkle hardening, certificate validation, known-answer tests.
* **Blockchain:** §5 and §7 — what is on/off-chain and why, authorization/ownership/immutability in the contract, the blockchain as the authoritative record that every verification is compared against, real transactions and real failed transactions, MetaMask/wagmi/viem integration, direct on-chain reads from the browser.

## 9. MongoDB collections

`users` (credentials hash, encrypted keys, certificate, wallets) · `datasets` (validation report) · `models` (training metrics, deployment, crypto, blockchain info, license) ·
`grants` (access requests/approvals/usage counters) · `downloads` (short-lived decrypted-download tokens) · `sessions` (hashed tokens) · `verification_logs` (every verification, access decision and tamper test).
