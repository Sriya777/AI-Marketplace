"""
verification.py - integrity / ownership / authenticity verification.

The BLOCKCHAIN record is the authority: every local value (DB, files) is compared against what the
contract returns. Nothing here returns a hardcoded status; each check is computed from real data.
"""
import copy
import uuid
from pathlib import Path

from cryptography.exceptions import InvalidTag

from crypto import crypto_core as cc, identity as idn, merkle as mk
from . import accounts, artifacts, chain, config, pki
from .db import get_db
from .ml import now_iso
from .protection import canonical_metadata


def _set_dotted(doc, dotted, value):
    cur = doc
    parts = dotted.split(".")
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def verify_model(model: dict, *, artifact_path=None, overrides=None, include_decrypt=False,
                 actor="system", kind="verification", label=None, log=True) -> dict:
    """
    overrides: dotted-path -> value applied to an in-memory COPY of the stored record, used by the
    tamper tests to model "an attacker modified the stored signature/metadata".
    artifact_path: verify a different file than the stored one (used for sandboxed tests).
    """
    m = copy.deepcopy(model)
    for k, v in (overrides or {}).items():
        _set_dotted(m, k, v)
    checks = []

    def add(cid, title, ok, detail, expected=None, actual=None, skip=False):
        checks.append({"id": cid, "title": title, "status": "SKIP" if skip else ("PASS" if ok else "FAIL"),
                       "detail": detail, "expected": expected, "actual": actual})

    cr = m.get("crypto") or {}
    owner = get_db().users.find_one({"_id": m["owner_id"]})
    rec = None
    chain_error = None
    try:
        rec = chain.get_record(m["_id"])
    except Exception as e:
        chain_error = str(e)[:200]

    # 1. developer certificate (X.509)
    if owner:
        cert = idn.load_cert_pem(owner["cert_pem"])
        cres = idn.verify_certificate_chain(cert, pki.ca_cert(), pki.revoked_serials())
        fp_ok = cr.get("signer", {}).get("cert_fingerprint") == idn.cert_fingerprint_sha3(cert)
        add("certificate", "Developer X.509 certificate chains to the marketplace CA", cres["valid"] and fp_ok,
            ("; ".join(f"{c['name']}: {'ok' if c['ok'] else 'FAILED'}" for c in cres["checks"])) +
            ("" if fp_ok else "; signer fingerprint does not match certificate"),
            "valid CA-issued certificate", cres["reason"] or "valid")
    else:
        cert = None
        add("certificate", "Developer X.509 certificate chains to the marketplace CA", False, "developer account not found")

    # 2. on-chain record
    if chain_error:
        add("chain_record", "Record exists on the blockchain", False, f"blockchain unavailable: {chain_error}")
    elif rec is None:
        add("chain_record", "Record exists on the blockchain", False, "no on-chain record for this model id",
            "registered record", "not registered")
    else:
        add("chain_record", "Record exists on the blockchain and is not revoked", not rec["revoked"],
            f"creator {rec['creator']}, block {rec['registeredBlock']}, revoked={rec['revoked']}",
            "registered, not revoked", "revoked" if rec["revoked"] else "registered")

    if rec is None or not cr.get("merkle"):
        for cid, title in [("ownership", "On-chain creator wallet belongs to the developer"),
                           ("encrypted_hash", "SHA3-256 of the encrypted artifact matches the blockchain"),
                           ("merkle_root", "Merkle root of the artifact chunks matches the blockchain"),
                           ("metadata_hash", "Signed-metadata hash matches the blockchain"),
                           ("signature", "ECDSA signature verifies under the certified developer key"),
                           ("signature_onchain", "Stored signature and public key equal the on-chain values")]:
            add(cid, title, False, "cannot evaluate: no on-chain record / incomplete cryptographic data", skip=True)
        return _finish(m, checks, actor, kind, label, log, artifact_path)

    # 3. ownership
    wallets = accounts.user_wallets(owner) if owner else set()
    add("ownership", "On-chain creator wallet belongs to the developer", rec["creator"].lower() in wallets,
        f"on-chain creator {rec['creator']}; developer wallets {sorted(wallets)}", "creator in developer wallets", rec["creator"])

    # 4. encrypted artifact hash
    path = Path(artifact_path) if artifact_path else artifacts.enc_path(m["_id"])
    with artifacts.model_lock(m["_id"]):
        try:
            blob = path.read_bytes()
        except OSError as e:
            blob = None
            add("encrypted_hash", "SHA3-256 of the encrypted artifact matches the blockchain", False, f"cannot read artifact: {e}")
        else:
            sha = "0x" + cc.sha3_256_hash(blob)
            add("encrypted_hash", "SHA3-256 of the encrypted artifact matches the blockchain", sha == rec["encryptedHash"],
                f"computed {sha[:18]}... vs on-chain {rec['encryptedHash'][:18]}...", rec["encryptedHash"], sha)

    # 5. Merkle root (+ localise the tampered chunks)
    if blob is not None:
        chunks = list(mk.chunk_bytes(blob, cr["merkle"]["chunk_size"]))
        leaves = mk.leaves_from_chunks(chunks)
        root = "0x" + mk.root_from_leaves(leaves)
        ok = root == rec["merkleRoot"]
        detail = f"{len(chunks)} chunks of {cr['merkle']['chunk_size']} bytes; computed root {root[:18]}... vs on-chain {rec['merkleRoot'][:18]}..."
        stored = [bytes.fromhex(x) for x in cr["merkle"]["leaves"]]
        stored_ok = ("0x" + mk.root_from_leaves(stored)) == rec["merkleRoot"]
        if not ok and stored_ok:
            bad = [i for i in range(max(len(leaves), len(stored))) if i >= len(leaves) or i >= len(stored) or leaves[i] != stored[i]]
            detail += f". Mismatching chunk index(es): {bad[:20]}{' ...' if len(bad) > 20 else ''} of {len(stored)}"
        add("merkle_root", "Merkle root of the artifact chunks matches the blockchain", ok, detail, rec["merkleRoot"], root)
    else:
        add("merkle_root", "Merkle root of the artifact chunks matches the blockchain", False, "artifact unreadable", skip=True)

    # 6. metadata hash + 7. signature (recomputed from stored fields, never trusting the stored string)
    try:
        _, meta_json = canonical_metadata(m)
        meta_bytes = meta_json.encode()
        meta_sha = "0x" + cc.sha3_256_hash(meta_bytes)
        stored_same = meta_json == cr.get("metadata_json")
        add("metadata_hash", "Signed-metadata hash matches the blockchain", meta_sha == rec["metadataHash"],
            f"canonical metadata recomputed from stored fields: {meta_sha[:18]}... vs on-chain {rec['metadataHash'][:18]}..."
            + ("" if stored_same else " (stored canonical string differs from recomputed)"), rec["metadataHash"], meta_sha)
        try:
            sig = bytes.fromhex(cr["signature_hex"])
            sig_ok = idn.verify_signature(cert.public_key(), sig, meta_bytes)
        except Exception:
            sig, sig_ok = b"", False
        add("signature", "ECDSA signature verifies under the certified developer key", sig_ok,
            f"ECDSA P-256 / SHA3-256 over canonical metadata ({len(meta_bytes)} bytes), key from the developer's X.509 certificate",
            "valid signature", "valid" if sig_ok else "INVALID signature")
        same_sig = cr.get("signature_hex") == rec["signature"]
        same_key = bool(cert) and idn.public_key_to_der(cert.public_key()).hex() == rec["creatorPubKey"]
        add("signature_onchain", "Stored signature and public key equal the on-chain values", same_sig and same_key,
            f"signature equal={same_sig}, public key equal={same_key}", "identical to on-chain", "identical" if (same_sig and same_key) else "differs")
    except Exception as e:
        add("metadata_hash", "Signed-metadata hash matches the blockchain", False, f"cannot rebuild canonical metadata: {e}")
        add("signature", "ECDSA signature verifies under the certified developer key", False, "no metadata", skip=True)
        add("signature_onchain", "Stored signature and public key equal the on-chain values", False, "no metadata", skip=True)

    # 8. optional decryption + plaintext hash vs chain
    if include_decrypt:
        if blob is None:
            add("decrypt", "AES-256-GCM authentication + plaintext hash equals on-chain original hash", False, "artifact unreadable", skip=True)
        else:
            try:
                nonce, ct = artifacts.unpack_encrypted(blob)
                plain = cc.decrypt(ct, artifacts.content_key_from_escrow(m), nonce, artifacts.aad_for(m))
                ph = "0x" + cc.sha3_256_hash(plain)
                add("decrypt", "AES-256-GCM authentication + plaintext hash equals on-chain original hash", ph == rec["originalHash"],
                    f"GCM tag verified; SHA3-256(plaintext) {ph[:18]}... vs on-chain {rec['originalHash'][:18]}...", rec["originalHash"], ph)
            except InvalidTag:
                add("decrypt", "AES-256-GCM authentication + plaintext hash equals on-chain original hash", False,
                    "GCM authentication tag FAILED (ciphertext/AAD was modified)", "valid tag", "InvalidTag")
            except Exception as e:
                add("decrypt", "AES-256-GCM authentication + plaintext hash equals on-chain original hash", False, f"{type(e).__name__}: {str(e)[:120]}")

    return _finish(m, checks, actor, kind, label, log, artifact_path, rec)


def _finish(m, checks, actor, kind, label, log, artifact_path, rec=None):
    failed = [c["id"] for c in checks if c["status"] == "FAIL"]
    passed = [c for c in checks if c["status"] == "PASS"]
    status = "PASS" if (not failed and passed) else "FAIL"
    report = {"model_id": m["_id"], "status": status, "checks": checks, "at": now_iso(), "actor": actor,
              "summary": {"passed": len(passed), "failed": len(failed), "skipped": len([c for c in checks if c["status"] == "SKIP"])},
              "failed_checks": failed, "on_chain": None if not rec else {
                  "creator": rec["creator"], "block": rec["registeredBlock"], "timestamp": rec["registeredAt"],
                  "license": rec["licenseTerms"], "revoked": rec["revoked"]}}
    if log:
        get_db().verification_logs.insert_one({"_id": "log_" + uuid.uuid4().hex[:12], "kind": kind, "model_id": m["_id"],
            "actor": actor, "status": status, "label": label, "failed_checks": failed, "at": report["at"],
            "summary": report["summary"], "checks": checks})
    return report


# ---------------------------------------------------------------- Merkle chunk proofs
def _leaves_and_tree(m):
    leaves = [bytes.fromhex(x) for x in m["crypto"]["merkle"]["leaves"]]
    return leaves, mk.build_tree_from_leaves(leaves)


def chunk_proof(m: dict, index: int) -> dict:
    mm = m["crypto"]["merkle"]
    if not 0 <= index < mm["chunk_count"]:
        raise ValueError(f"chunk index must be 0..{mm['chunk_count'] - 1}")
    leaves, tree = _leaves_and_tree(m)
    return {"index": index, "chunk_count": mm["chunk_count"], "leaf_hash": leaves[index].hex(),
            "proof": [{"sibling": s, "sibling_is_left": left} for s, left in mk.get_proof(tree, index)],
            "root": mm["root"]}


def verify_chunk(m: dict, index: int) -> dict:
    """Read ONE chunk from the stored encrypted artifact and verify it against the on-chain Merkle root via its proof path."""
    p = chunk_proof(m, index)
    mm = m["crypto"]["merkle"]
    with artifacts.model_lock(m["_id"]):
        with open(artifacts.enc_path(m["_id"]), "rb") as f:
            f.seek(index * mm["chunk_size"])
            chunk = f.read(mm["chunk_size"])
    proof = [(x["sibling"], x["sibling_is_left"]) for x in p["proof"]]
    rec = chain.get_record(m["_id"]) if chain.is_available() else None
    onchain_root = rec["merkleRoot"][2:] if rec else None
    ok_vs_stored = mk.verify_proof(chunk, proof, mm["root"])
    ok_vs_chain = bool(onchain_root) and mk.verify_proof(chunk, proof, onchain_root)
    return {**p, "chunk_bytes": len(chunk), "computed_leaf_hash": mk.leaf_hash(chunk).hex(), "on_chain_root": onchain_root,
            "valid_against_stored_root": ok_vs_stored, "valid_against_onchain_root": ok_vs_chain,
            "status": "PASS" if ok_vs_chain else "FAIL"}
