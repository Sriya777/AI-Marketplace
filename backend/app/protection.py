"""
protection.py - PHASE 3: applied cryptography pipeline.

    hash      SHA3-256 of the exact trained artifact (must equal the training + deployment hash)
    encrypt   AES-256-GCM with a CSPRNG key + nonce; key wrapped (escrow + ECC owner copy via HKDF)
    merkle    chunk the ciphertext, hash leaves (SHA3-256), build the tree, record the root
    sign      verify the developer's X.509 certificate, then ECDSA-sign the canonical metadata
              (which commits to every hash above) with the developer's P-256 key

Every step reads the REAL output of the previous one from the model document.
"""
import json
import os
import random
import time

from fastapi import HTTPException

from crypto import crypto_core as cc, identity as idn, keywrap, merkle as mk
from . import accounts, artifacts, config, pki
from .db import get_db
from .ml import now_iso

SCHEMA = "ai-model-marketplace/metadata/v1"


def _fail(status, msg):
    raise HTTPException(status, msg)


def _stage(model_id, name, status, **extra):
    get_db().models.update_one({"_id": model_id}, {"$set": {f"stages.{name}": {"status": status, "at": now_iso(), **extra}}})


def _get(model_id):
    return get_db().models.find_one({"_id": model_id})


def _require_unprotected(m):
    if m["status"] in ("protected", "registered"):
        _fail(409, "model is already cryptographically protected (artifacts are immutable once signed)")


def _require_trained(m):
    if m.get("training", {}).get("status") != "completed" and not m.get("is_uploaded"):
        _fail(409, "model training must complete before packaging")


# ---------------------------------------------------------------- canonical metadata
def canonical_metadata(m: dict) -> tuple:
    """Deterministic metadata that is signed. Built ONLY from fields stored on the model document."""
    cr, mm = m["crypto"], m["crypto"].get("merkle", {})
    metrics = m.get("metrics") or {"accuracy": 0.0, "f1_macro": 0.0}
    f = lambda x: f"{float(x):.6f}"
    obj = {
        "schema": SCHEMA, "modelId": m["_id"], "version": m["version"], "name": m["name"], "algorithm": m["algorithm"],
        "dataset": {"name": m.get("dataset_name"), "sha3": m.get("dataset_sha3")},
        "metrics": {"accuracy": f(metrics.get("accuracy", 0.0)), "f1Macro": f(metrics.get("f1_macro", 0.0))},
        "original": {"sha3": cr["original_sha3"], "bytes": cr["original_bytes"]},
        "encrypted": {"sha3": cr["encrypted_sha3"], "bytes": cr["encrypted_bytes"], "cipher": "AES-256-GCM",
                      "aad": "modelId|version|originalSha3"},
        "merkle": {"root": mm.get("root"), "chunkSize": mm.get("chunk_size"), "chunkCount": mm.get("chunk_count"),
                   "hash": "SHA3-256", "leafPrefix": "0x00", "nodePrefix": "0x01"},
        "license": m["license"],
        "developer": {"username": cr["signer"]["username"], "certFingerprintSha3": cr["signer"]["cert_fingerprint"],
                      "certSerial": cr["signer"]["cert_serial"]},
    }
    return obj, json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ---------------------------------------------------------------- step 1: hash
def step_hash(model_id: str) -> dict:
    m = _get(model_id); _require_unprotected(m); _require_trained(m)
    if m.get("crypto", {}).get("encrypted_sha3"):
        _fail(409, "hash step cannot be re-run after encryption")
    t0 = time.perf_counter()
    with artifacts.model_lock(model_id):
        data = artifacts.read_model_bytes(m)
    orig = cc.sha3_256_hash(data)
    train_sha = m.get("training", {}).get("artifact_sha3")
    if train_sha and orig != train_sha:
        _stage(model_id, "hash", "failed", error="artifact differs from recorded training hash")
        _fail(409, "the artifact being protected does not match training hash")
    get_db().models.update_one({"_id": model_id}, {"$set": {"crypto.original_sha3": orig, "crypto.original_bytes": len(data),
                                                              "crypto.hashed_at": now_iso()}})
    _stage(model_id, "hash", "completed")
    return {"step": "hash", "algorithm": "SHA3-256", "original_sha3": orig, "bytes": len(data),
            "equals_training_hash": orig == train_sha if train_sha else True,
            "ms": round((time.perf_counter() - t0) * 1000, 1)}


# ---------------------------------------------------------------- step 2: encrypt
def step_encrypt(model_id: str, owner: dict) -> dict:
    m = _get(model_id); _require_unprotected(m)
    cr = m.get("crypto", {})
    if not cr.get("original_sha3"): _fail(409, "run the hash step first")
    if cr.get("merkle"): _fail(409, "encryption cannot be re-run after the Merkle tree was built")
    t0 = time.perf_counter()
    with artifacts.model_lock(model_id):
        data = artifacts.read_model_bytes(m)
        if cc.sha3_256_hash(data) != cr["original_sha3"]: _fail(409, "artifact changed since hashing")
        content_key = cc.generate_key()                              # CSPRNG 256-bit
        aad = artifacts.aad_for(m)
        enc = cc.encrypt(data, content_key, aad)                     # CSPRNG 96-bit nonce inside
        blob = artifacts.pack_encrypted(enc["nonce"], enc["ciphertext"])
        tmp = artifacts.enc_path(model_id).with_suffix(".tmp")
        tmp.write_bytes(blob); os.replace(tmp, artifacts.enc_path(model_id))
    enc_sha = cc.sha3_256_hash(blob)
    escrow = keywrap.escrow_wrap(pki.master_secret(), model_id, content_key)
    owner_wrap = keywrap.ecies_wrap(idn.load_public_key_pem(owner["ec_public_pem"]), content_key,
                                    f"{model_id}|{owner['username']}")
    # self-test: the stored ciphertext must decrypt (via the escrow path) back to the exact original bytes
    check = cc.decrypt(enc["ciphertext"], keywrap.escrow_unwrap(pki.master_secret(), model_id, escrow), enc["nonce"], aad)
    if check != data: _fail(500, "encryption self-test failed")
    del content_key
    get_db().models.update_one({"_id": model_id}, {"$set": {
        "crypto.encrypted_sha3": enc_sha, "crypto.encrypted_bytes": len(blob), "crypto.nonce_hex": enc["nonce"].hex(),
        "crypto.cipher": "AES-256-GCM", "crypto.aad": aad.decode(), "crypto.escrow_wrap": escrow,
        "crypto.owner_wrap": owner_wrap, "crypto.encrypted_at": now_iso()}})
    _stage(model_id, "encrypt", "completed")
    return {"step": "encrypt", "cipher": "AES-256-GCM", "key_bits": 256, "key_source": "os.urandom (CSPRNG)",
            "nonce_hex": enc["nonce"].hex(), "aad": aad.decode(), "plaintext_bytes": len(data), "encrypted_bytes": len(blob),
            "encrypted_sha3": enc_sha, "auth_tag_bytes": 16,
            "key_wrapping": [{"for": "marketplace escrow", "scheme": escrow["scheme"], "hkdf_salt": escrow["salt"][:16] + "...",
                              "info": "ai-marketplace/v1/escrow-kek|" + model_id},
                             {"for": f"developer {owner['username']}", "scheme": owner_wrap["scheme"],
                              "hkdf_salt": owner_wrap["salt"][:16] + "...", "context": owner_wrap["context"]}],
            "roundtrip_selftest": "decrypted ciphertext == original artifact",
            "ms": round((time.perf_counter() - t0) * 1000, 1)}


# ---------------------------------------------------------------- step 3: merkle
def step_merkle(model_id: str) -> dict:
    m = _get(model_id); _require_unprotected(m)
    cr = m.get("crypto", {})
    if not cr.get("encrypted_sha3"): _fail(409, "run the encrypt step first")
    if cr.get("signature_hex"): _fail(409, "Merkle tree cannot be rebuilt after signing")
    t0 = time.perf_counter()
    with artifacts.model_lock(model_id):
        blob = artifacts.enc_path(model_id).read_bytes()
    if cc.sha3_256_hash(blob) != cr["encrypted_sha3"]: _fail(409, "encrypted artifact changed since encryption")
    chunks = list(mk.chunk_bytes(blob, config.CHUNK_SIZE))
    leaves = mk.leaves_from_chunks(chunks)
    tree = mk.build_tree_from_leaves(leaves)
    root = tree[-1][0].hex()
    for i in sorted({0, len(chunks) // 2, len(chunks) - 1}):                       # self-test proofs
        assert mk.verify_proof(chunks[i], mk.get_proof(tree, i), root)
    get_db().models.update_one({"_id": model_id}, {"$set": {"crypto.merkle": {
        "root": root, "chunk_size": config.CHUNK_SIZE, "chunk_count": len(chunks), "height": len(tree) - 1,
        "leaves": [l.hex() for l in leaves], "hash": "SHA3-256 (domain separated)", "built_at": now_iso()}}})
    _stage(model_id, "merkle", "completed")
    return {"step": "merkle", "root": root, "chunk_size": config.CHUNK_SIZE, "chunk_count": len(chunks),
            "tree_height": len(tree) - 1, "leaf_hash": "SHA3-256(0x00 || chunk)", "node_hash": "SHA3-256(0x01 || left || right)",
            "sample_leaf_hashes": [l.hex() for l in leaves[:3]], "proof_selftest": "first/middle/last chunk proofs verified",
            "ms": round((time.perf_counter() - t0) * 1000, 1)}


# ---------------------------------------------------------------- step 4: sign
def step_sign(model_id: str, user: dict, password: str) -> dict:
    m = _get(model_id); _require_unprotected(m)
    cr = m.get("crypto", {})
    if not cr.get("merkle"): _fail(409, "run the Merkle step first")
    t0 = time.perf_counter()
    cs = accounts.cert_status(user)                                   # verify the certificate BEFORE accepting a signature
    if not cs["valid"]:
        _stage(model_id, "sign", "failed", error=cs["reason"])
        _fail(403, f"your X.509 certificate is not valid: {cs['reason']}")
    try:
        priv = accounts.unlock_ec_private_key(user, password)
    except accounts.AccountError as e:
        _fail(e.status, str(e))
    cert = idn.load_cert_pem(user["cert_pem"])
    if idn.public_key_to_der(priv.public_key()) != idn.public_key_to_der(cert.public_key()):
        _fail(500, "private key does not match certificate")
    m["crypto"]["signer"] = {"username": user["username"], "cert_fingerprint": idn.cert_fingerprint_sha3(cert),
                             "cert_serial": format(cert.serial_number, "x")}
    meta_obj, meta_json = canonical_metadata(m)
    meta_sha3 = cc.sha3_256_hash(meta_json.encode())
    signature = idn.sign_data(priv, meta_json.encode())
    if not idn.verify_signature(cert.public_key(), signature, meta_json.encode()): _fail(500, "signature self-check failed")
    get_db().models.update_one({"_id": model_id}, {"$set": {
        "crypto.signer": m["crypto"]["signer"], "crypto.metadata_json": meta_json, "crypto.metadata_sha3": meta_sha3,
        "crypto.signature_hex": signature.hex(), "crypto.signature_alg": "ECDSA P-256 / SHA3-256 (DER)",
        "crypto.signed_at": now_iso(), "status": "protected"}})
    _stage(model_id, "sign", "completed")
    # The plaintext artifact is no longer needed at rest: only the encrypted copy remains on disk.
    pp = artifacts.plain_path(model_id)
    deleted = False
    if pp.exists():
        with artifacts.model_lock(model_id):
            artifacts.secure_delete(pp); deleted = True
    return {"step": "sign", "algorithm": "ECDSA P-256 with SHA3-256", "signer": user["username"],
            "certificate_valid": True, "certificate_checks": cs["checks"], "certificate": cs["certificate"],
            "metadata_sha3": meta_sha3, "signature_hex": signature.hex(), "signature_bytes": len(signature),
            "signed_fields": sorted(meta_obj.keys()), "canonical_metadata": meta_obj,
            "plaintext_artifact_securely_deleted": deleted,
            "ms": round((time.perf_counter() - t0) * 1000, 1)}


def set_license(model_id: str, license_name: str):
    from .distribution import LICENSES
    m = _get(model_id); _require_unprotected(m)
    if license_name not in LICENSES: _fail(422, f"license must be one of {list(LICENSES)}")
    get_db().models.update_one({"_id": model_id}, {"$set": {"license": license_name}})


def protect_all(model_id: str, user: dict, password: str) -> dict:
    results = []
    for fn in (lambda: step_hash(model_id), lambda: step_encrypt(model_id, user),
               lambda: step_merkle(model_id), lambda: step_sign(model_id, user, password)):
        results.append(fn())
    return {"model_id": model_id, "steps": results, "status": "protected"}


def package_model(model_id: str, user: dict, password: str, license: str = None) -> dict:
    import sys
    import numpy as np
    import pandas as pd
    import sklearn

    if license:
        set_license(model_id, license)
    res = protect_all(model_id, user, password)
    m = _get(model_id)
    manifest = {
        "format": "ai-marketplace-package/v1",
        "model_id": model_id,
        "name": m.get("name"),
        "version": m.get("version"),
        "algorithm": m.get("algorithm"),
        "license": m.get("license"),
        "runtime_dependencies": {
            "python": sys.version.split()[0],
            "scikit-learn": sklearn.__version__,
            "pandas": pd.__version__,
            "numpy": np.__version__
        },
        "artifact_sha3": m.get("crypto", {}).get("original_sha3"),
        "encrypted_sha3": m.get("crypto", {}).get("encrypted_sha3"),
        "merkle_root": m.get("crypto", {}).get("merkle", {}).get("root"),
        "packaged_at": now_iso()
    }
    get_db().models.update_one(
        {"_id": model_id},
        {"$set": {
            "status": "packaged",
            "package_manifest": manifest,
            "stages.packaging": {"status": "completed", "at": now_iso()}
        }}
    )
    return {
        "model_id": model_id,
        "status": "packaged",
        "manifest": manifest,
        "steps": res["steps"],
        "crypto": m.get("crypto")
    }
