"""
distribution.py - PHASE 5: secure model distribution with license enforcement.

Flow of authorize_and_decrypt():
   1 access grant & license limits  ->  2 buyer + developer X.509 verification
   3 blockchain record retrieval    ->  4 hash + Merkle + signature verification (against the chain)
   5 ECC key exchange (ephemeral ECDH + HKDF) wrapping the content key to the BUYER's public key
   6 AES-256-GCM decryption         ->  7 SHA3-256(plaintext) must equal the on-chain original hash
Only if every step passes does the buyer receive a (short-lived) download token for the plaintext artifact.
"""
import io
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
from cryptography.exceptions import InvalidTag

from crypto import crypto_core as cc, identity as idn, keywrap
from crypto.crypto_core import sha3_256_hash
from . import accounts, artifacts, chain, config, ml, pki
from .db import get_db
from .verification import verify_model

LICENSES = {
    "unlimited": {"auto_approve": True, "max_downloads": None, "description": "Instant access, unlimited authorised downloads"},
    "single-use": {"auto_approve": True, "max_downloads": 1, "description": "Instant access, ONE authorised download"},
    "approval-required": {"auto_approve": False, "max_downloads": 3, "description": "Developer must approve each buyer; up to 3 downloads"},
}


class DistributionError(Exception):
    def __init__(self, status, reason, report=None):
        super().__init__(reason); self.status, self.reason, self.report = status, reason, report or []


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- access grants
def public_grant(g):
    return {"id": g["_id"], "model_id": g["model_id"], "buyer": g["buyer_name"], "buyer_id": g["buyer_id"],
            "status": g["status"], "license": g["license"], "downloads_used": g["downloads_used"],
            "max_downloads": g["max_downloads"], "requested_at": g["requested_at"], "decided_at": g.get("decided_at"),
            "note": g.get("note", "")}


def request_access(buyer: dict, model_id: str, note: str = "") -> dict:
    db = get_db()
    m = db.models.find_one({"_id": model_id})
    if not m or m["status"] != "registered":
        raise DistributionError(404, "model not found in the marketplace (only blockchain-registered models are listed)")
    if m["owner_id"] == buyer["_id"]:
        raise DistributionError(400, "you are the developer of this model")
    rec = chain.get_record(model_id) if chain.is_available() else None
    if rec is None or rec["revoked"]:
        raise DistributionError(409, "model is not available: not on-chain or revoked by its developer")
    existing = db.grants.find_one({"model_id": model_id, "buyer_id": buyer["_id"], "status": {"$in": ["pending", "approved"]}})
    if existing:
        return public_grant(existing)
    lic = LICENSES[m["license"]]
    grant = {"_id": "gr_" + uuid.uuid4().hex[:12], "model_id": model_id, "buyer_id": buyer["_id"], "buyer_name": buyer["username"],
             "owner_id": m["owner_id"], "license": m["license"], "max_downloads": lic["max_downloads"], "downloads_used": 0,
             "status": "approved" if lic["auto_approve"] else "pending", "requested_at": _now().isoformat(),
             "decided_at": _now().isoformat() if lic["auto_approve"] else None, "note": note[:300]}
    db.grants.insert_one(grant)
    return public_grant(grant)


def decide(owner: dict, grant_id: str, approve: bool) -> dict:
    db = get_db()
    g = db.grants.find_one({"_id": grant_id})
    if not g or g["owner_id"] != owner["_id"]:
        raise DistributionError(404, "request not found (or not for one of your models)")
    if g["status"] != "pending":
        raise DistributionError(409, f"request is already {g['status']}")
    db.grants.update_one({"_id": grant_id}, {"$set": {"status": "approved" if approve else "denied",
                                                       "decided_at": _now().isoformat(), "decided_by": owner["username"]}})
    return public_grant(db.grants.find_one({"_id": grant_id}))


def active_grant(buyer_id: str, model_id: str):
    return get_db().grants.find_one({"model_id": model_id, "buyer_id": buyer_id, "status": "approved"})


# ---------------------------------------------------------------- authorise + decrypt
def _tmp_dir() -> Path:
    d = config.STORAGE_DIR / "tmp"; d.mkdir(parents=True, exist_ok=True); return d


def cleanup_expired():
    db = get_db()
    for d in db.downloads.find({}):
        if datetime.fromisoformat(d["expires_at"]) < _now():
            Path(d["path"]).unlink(missing_ok=True)
            db.downloads.delete_one({"_id": d["_id"]})


def authorize_and_decrypt(buyer: dict, model_id: str, password: str, log_kind="distribution", log: bool = True) -> dict:
    db = get_db()
    cleanup_expired()
    steps = []

    def step(name, status, detail, **extra):
        steps.append({"step": name, "status": status, "detail": detail, **extra})

    def deny(code, reason, name):
        step(name, "DENIED" if code in (401, 403) else "FAIL", reason)
        if log: db.verification_logs.insert_one({"_id": "log_" + uuid.uuid4().hex[:12], "kind": log_kind, "model_id": model_id,
            "actor": buyer["username"], "status": "DENIED", "label": "access", "failed_checks": [name], "at": ml.now_iso(),
            "summary": {"passed": len([s for s in steps if s['status'] == 'PASS']), "failed": 1, "skipped": 0}, "checks": steps})
        raise DistributionError(code, reason, steps)

    m = db.models.find_one({"_id": model_id})
    if not m or m["status"] != "registered":
        deny(404, "model is not registered in the marketplace", "model_lookup")

    # 1. access grant + license limits
    g = active_grant(buyer["_id"], model_id)
    if not g:
        pend = db.grants.find_one({"model_id": model_id, "buyer_id": buyer["_id"]}, sort=[("requested_at", -1)])
        why = f"your latest access request is '{pend['status']}'" if pend else "you have not requested access to this model"
        deny(403, f"no approved access grant: {why}. The decryption key is not released.", "access_grant")
    if g["max_downloads"] is not None and g["downloads_used"] >= g["max_downloads"]:
        db.grants.update_one({"_id": g["_id"]}, {"$set": {"status": "exhausted"}})
        deny(403, f"license '{g['license']}' exhausted: {g['downloads_used']}/{g['max_downloads']} authorised downloads used", "access_grant")
    step("access_grant", "PASS", f"approved; license '{g['license']}', downloads used {g['downloads_used']}/{g['max_downloads'] or 'unlimited'}")

    # 2. certificates (buyer + developer) before anything is accepted
    bc = accounts.cert_status(buyer)
    if not bc["valid"]:
        deny(403, f"buyer certificate invalid: {bc['reason']}", "buyer_certificate")
    step("buyer_certificate", "PASS", "buyer X.509 certificate valid and chained to the marketplace CA", certificate=bc["certificate"])
    owner = db.users.find_one({"_id": m["owner_id"]})
    dc = accounts.cert_status(owner)
    if not dc["valid"]:
        deny(403, f"developer certificate invalid: {dc['reason']}", "developer_certificate")
    step("developer_certificate", "PASS", f"developer '{owner['username']}' certificate valid; signatures from this key are accepted",
         certificate=dc["certificate"])

    # 3. retrieve the ENCRYPTED model from storage (ciphertext only: unreadable without the content key)
    try:
        with artifacts.model_lock(model_id):
            retrieved = artifacts.enc_path(model_id).read_bytes()
    except OSError:
        deny(500, "the encrypted artifact is missing from storage", "retrieve_encrypted")
    step("retrieve_encrypted", "PASS", f"retrieved the encrypted artifact ({len(retrieved)} bytes, SHA3-256 {sha3_256_hash(retrieved)[:16]}...): "
         "ciphertext only, unreadable without the content key")
    del retrieved

    # 4 + 5. blockchain record + full integrity verification (hash, Merkle root, signature, ownership)
    if not chain.is_available():
        deny(503, "blockchain unavailable - cannot verify the record", "blockchain_record")
    rep = verify_model(m, actor=buyer["username"], kind="verification", label="pre-distribution", log=log)
    rec = chain.get_record(model_id)
    step("blockchain_record", "PASS" if rec and not rec["revoked"] else "FAIL",
         f"record read from chain: creator {rec['creator']}, block {rec['registeredBlock']}" if rec else "no record",
         on_chain={"creator": rec["creator"], "block": rec["registeredBlock"], "license": rec["licenseTerms"]} if rec else None)
    step("integrity_verification", rep["status"], f"{rep['summary']['passed']} checks passed, {rep['summary']['failed']} failed"
         + (f" (failed: {', '.join(rep['failed_checks'])})" if rep["failed_checks"] else ""), checks=rep["checks"])
    if rep["status"] != "PASS":
        deny(409, "integrity/authenticity verification FAILED - the model was NOT released: " + ", ".join(rep["failed_checks"]),
             "integrity_verification")

    # 6. ECC key exchange (ephemeral ECDH + HKDF) to the buyer's key. Wrong password => key cannot be unlocked.
    try:
        buyer_priv = accounts.unlock_ec_private_key(buyer, password)
    except accounts.AccountError as e:
        deny(401, str(e), "key_exchange")
    try:
        content_key = artifacts.content_key_from_escrow(m)
    except InvalidTag:
        deny(500, "content key escrow cannot be unwrapped (wrong master passphrase?)", "key_exchange")
    bcert = idn.load_cert_pem(buyer["cert_pem"])
    ctx = f"{model_id}|{buyer['username']}|{idn.cert_fingerprint_sha3(bcert)[:16]}"
    wrapped = keywrap.ecies_wrap(idn.load_public_key_pem(buyer["ec_public_pem"]), content_key, ctx)
    unwrapped = keywrap.ecies_unwrap(buyer_priv, wrapped)          # buyer-side unwrap with their private key
    step("key_exchange", "PASS", "content key wrapped to the buyer's public key via ephemeral ECDH (P-256) + HKDF-SHA256 + AES-256-GCM; "
         "only the buyer's private key can unwrap it",
         key_exchange={"scheme": wrapped["scheme"], "ephemeral_public_key": wrapped["ephemeral_public_pem"].splitlines()[1][:40] + "...",
                       "hkdf_salt": wrapped["salt"], "hkdf_info": "ai-marketplace/v1/ecies-key-wrap|" + ctx, "wrapped_key_bytes": 48})

    # 7 + 8. decrypt, then compare the plaintext hash with the immutable on-chain original hash
    try:
        with artifacts.model_lock(model_id):
            blob = artifacts.enc_path(model_id).read_bytes()
        nonce, ct = artifacts.unpack_encrypted(blob)
        plaintext = cc.decrypt(ct, unwrapped, nonce, artifacts.aad_for(m))
    except InvalidTag:
        deny(409, "AES-256-GCM authentication failed - ciphertext was modified", "decrypt")
    del content_key, unwrapped
    ph = "0x" + sha3_256_hash(plaintext)
    if ph != rec["originalHash"]:
        deny(409, "decrypted artifact hash does not match the on-chain original hash", "plaintext_hash")
    step("decrypt", "PASS", f"AES-256-GCM tag verified; decrypted {len(plaintext)} bytes")
    step("plaintext_hash", "PASS", f"SHA3-256(plaintext) {ph[:18]}... equals the on-chain original hash")

    token = secrets.token_urlsafe(24)
    path = _tmp_dir() / f"dl_{uuid.uuid4().hex}.joblib"
    path.write_bytes(plaintext)
    expires = _now() + timedelta(seconds=config.DOWNLOAD_TTL_SECONDS)
    db.downloads.insert_one({"_id": sha3_256_hash(token.encode()), "model_id": model_id, "buyer_id": buyer["_id"], "path": str(path),
        "filename": f"{model_id}_{m['version']}.joblib", "sha3": ph, "expires_at": expires.isoformat(), "fetched": 0, "created_at": ml.now_iso()})
    db.grants.update_one({"_id": g["_id"]}, {"$inc": {"downloads_used": 1}})
    g2 = db.grants.find_one({"_id": g["_id"]})
    if g2["max_downloads"] is not None and g2["downloads_used"] >= g2["max_downloads"]:
        db.grants.update_one({"_id": g["_id"]}, {"$set": {"status": "exhausted"}})
    step("release", "PASS", f"download token issued (expires in {config.DOWNLOAD_TTL_SECONDS}s); license usage "
         f"{g2['downloads_used']}/{g2['max_downloads'] or 'unlimited'}")
    if log: db.verification_logs.insert_one({"_id": "log_" + uuid.uuid4().hex[:12], "kind": log_kind, "model_id": model_id,
        "actor": buyer["username"], "status": "PASS", "label": "access", "failed_checks": [], "at": ml.now_iso(),
        "summary": {"passed": len(steps), "failed": 0, "skipped": 0}, "checks": [{k: v for k, v in s.items() if k != "checks"} for s in steps]})
    return {"status": "AUTHORIZED", "steps": steps, "download_token": token, "expires_at": expires.isoformat(),
            "filename": f"{model_id}_{m['version']}.joblib", "plaintext_sha3": ph, "bytes": len(plaintext)}


# ---------------------------------------------------------------- downloads
def get_download(buyer: dict, token: str) -> dict:
    cleanup_expired()
    d = get_db().downloads.find_one({"_id": sha3_256_hash(token.encode())})
    if not d or d["buyer_id"] != buyer["_id"]:
        raise DistributionError(404, "download not found, expired, or not yours")
    if not Path(d["path"]).exists():
        raise DistributionError(410, "download expired")
    return d


def mark_fetched(d):
    get_db().downloads.update_one({"_id": d["_id"]}, {"$inc": {"fetched": 1}})


def predict_distributed(buyer: dict, token: str, inputs) -> dict:
    """Inference using the DISTRIBUTED artifact (the buyer's decrypted copy), after re-checking its hash on-chain."""
    d = get_download(buyer, token)
    data = Path(d["path"]).read_bytes()
    rec = chain.get_record(d["model_id"]) if chain.is_available() else None
    if rec is None or "0x" + sha3_256_hash(data) != rec["originalHash"]:
        raise DistributionError(409, "distributed artifact does not match the on-chain original hash; refusing to load it")
    bundle = joblib.load(io.BytesIO(data))
    return {"model_id": d["model_id"], "artifact": "distributed copy (hash-verified against blockchain)",
            "predictions": ml.predict_with_bundle(bundle, inputs), "classes": bundle["classes"],
            "feature_columns": bundle["feature_columns"]}
