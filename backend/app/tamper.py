"""
tamper.py - PHASE 6: security / tamper test suite.

Every test performs the REAL operation and reports what actually happened. A test's `actual`
outcome is computed from the verification code / the contract's real response; `matched` only says
whether that outcome equals the expected one. Nothing is hardcoded.

  normal                 expected PASS      verify hash + signature + Merkle root against the chain
  file_tamper            expected FAIL      flip bytes in the stored encrypted artifact, verify, then restore it
  signature_tamper       expected FAIL      modify the stored signature / signed metadata, verify
  unauthorized_ownership expected REJECTED  unauthorized / non-owner wallets attempt restricted contract operations
  duplicate              expected REJECTED  register an already-registered model id (real transaction)
  unauthorized_download  expected DENIED    buyers without a valid grant / key try to obtain the model
"""
import copy
import os
import secrets
import time
import uuid

from cryptography.exceptions import InvalidTag

from crypto import crypto_core as cc, identity as idn
from . import accounts, artifacts, chain, registration
from .db import get_db
from .distribution import DistributionError, authorize_and_decrypt
from .ml import now_iso
from .verification import verify_model

TESTS = {
    "normal": ("Normal model: register, retrieve, verify hash + signature + Merkle root", "PASS"),
    "file_tamper": ("Model file tampering: modify bytes of the stored encrypted artifact", "FAIL"),
    "signature_tamper": ("Signature / metadata tampering", "FAIL"),
    "unauthorized_ownership": ("Unauthorized ownership: restricted operations from unauthorized wallets", "REJECTED"),
    "duplicate": ("Duplicate model: register an already-registered model id", "REJECTED"),
    "unauthorized_download": ("Unauthorized download: obtain the model / key without permission", "DENIED"),
}


def _flip(blob: bytes, offsets):
    b = bytearray(blob)
    for o in offsets:
        b[o] ^= 0xFF
    return bytes(b)


def _log(model_id, actor, name, result):
    get_db().verification_logs.insert_one({"_id": "log_" + uuid.uuid4().hex[:12], "kind": "tamper_test", "model_id": model_id,
        "actor": actor, "status": result["actual"], "label": name, "expected": result["expected"], "matched": result["matched"],
        "failed_checks": [c["id"] for c in result.get("checks", []) if c.get("status") == "FAIL"], "at": result["at"],
        "summary": {"passed": 0, "failed": 0, "skipped": 0}, "checks": []})


# ------------------------------------------------------------------ individual tests
def t_normal(m, user, pw):
    rep = verify_model(m, include_decrypt=True, actor=user["username"], kind="tamper_test", label="normal", log=False)
    return rep["status"], {"verification": rep["summary"], "on_chain": rep["on_chain"]}, rep["checks"]


def t_file_tamper(m, user, pw):
    path = artifacts.enc_path(m["_id"])
    with artifacts.model_lock(m["_id"]):                       # exclusive while the stored file is modified
        original = path.read_bytes()
        offsets = [artifacts.HEADER_LEN + 7, len(original) // 2, len(original) - 5]
        tampered = _flip(original, offsets)
        details = {"file": f"storage/models/{m['_id']}/model.enc", "bytes_modified": len(offsets),
                   "offsets": offsets, "before_after": [f"0x{original[o]:02x} -> 0x{tampered[o]:02x}" for o in offsets]}
        tmp = path.with_suffix(".bak"); tmp.write_bytes(original)       # backup so the model is never lost
        try:
            path.write_bytes(tampered)                                       # tamper the REAL stored artifact in place
            rep = verify_model(m, include_decrypt=True, actor=user["username"], kind="tamper_test", label="file_tamper", log=False)
            try:
                nonce, ct = artifacts.unpack_encrypted(path.read_bytes())
                cc.decrypt(ct, artifacts.content_key_from_escrow(m), nonce, artifacts.aad_for(m))
                details["gcm_decrypt_attempt"] = "unexpectedly succeeded"
            except InvalidTag:
                details["gcm_decrypt_attempt"] = "REJECTED: AES-GCM authentication tag mismatch (InvalidTag)"
        finally:
            path.write_bytes(original); tmp.unlink(missing_ok=True)           # always restore
            details["restored"] = cc.sha3_256_hash(path.read_bytes()) == m["crypto"]["encrypted_sha3"]
    details["verification"] = rep["summary"]
    details["failed_checks"] = rep["failed_checks"]
    return rep["status"], details, rep["checks"]


def t_signature_tamper(m, user, pw):
    sig = bytes.fromhex(m["crypto"]["signature_hex"])
    bad_sig = _flip(sig, [len(sig) - 3]).hex()
    r1 = verify_model(m, overrides={"crypto.signature_hex": bad_sig}, actor=user["username"], kind="tamper_test", label="sig_bytes", log=False)
    other = "unlimited" if m["license"] != "unlimited" else "single-use"
    r2 = verify_model(m, overrides={"license": other}, actor=user["username"], kind="tamper_test", label="metadata", log=False)
    details = {"case_a": {"modification": "1 byte of the stored ECDSA signature flipped", "status": r1["status"], "failed_checks": r1["failed_checks"]},
               "case_b": {"modification": f"signed metadata field 'license' changed '{m['license']}' -> '{other}'",
                          "status": r2["status"], "failed_checks": r2["failed_checks"]}}
    actual = "FAIL" if (r1["status"] == "FAIL" and r2["status"] == "FAIL") else ("PASS" if r1["status"] == r2["status"] == "PASS" else "PARTIAL")
    return actual, details, r1["checks"] + [dict(c, id="b_" + c["id"]) for c in r2["checks"] if c["status"] == "FAIL"]


def _dummy_payload(model_id):
    r = lambda: "0x" + secrets.token_hex(32)
    return chain.register_input(model_id, "1.0.0", r(), r(), r(), r(), os.urandom(71), os.urandom(91), "single-use")


def t_unauthorized_ownership(m, user, pw):
    attempts = []
    rogue_addr, rogue_key = chain.new_wallet()
    chain.fund(rogue_addr)
    a = chain.try_register_real(rogue_key, _dummy_payload(f"rogue-{secrets.token_hex(4)}"))
    attempts.append({"attempt": "unauthorized wallet registers a model (real transaction)", "wallet": rogue_addr,
                     "outcome": "ACCEPTED" if a["accepted"] else "REJECTED", "contract_message": a["reason"], "failed_tx_hash": a["txHash"]})
    p = chain.preflight_update_license(rogue_addr, m["_id"], "free-for-everyone")
    attempts.append({"attempt": "unauthorized wallet changes the license of someone else's model (eth_call)", "wallet": rogue_addr,
                     "outcome": "ACCEPTED" if p["accepted"] else "REJECTED", "contract_message": p["reason"]})
    other_addr, other_key = chain.new_wallet(); chain.fund(other_addr); chain.authorize_developer(other_addr)
    p = chain.preflight_revoke(other_addr, m["_id"])
    attempts.append({"attempt": "authorized developer (not the owner) revokes your model (eth_call)", "wallet": other_addr,
                     "outcome": "ACCEPTED" if p["accepted"] else "REJECTED", "contract_message": p["reason"]})
    actual = "REJECTED" if all(x["outcome"] == "REJECTED" for x in attempts) else "ACCEPTED"
    return actual, {"attempts": attempts}, []


def t_duplicate(m, user, pw):
    owner = get_db().users.find_one({"_id": m["owner_id"]})
    payload = registration.build_payload(m, owner)
    details = {"model_id": m["_id"]}
    if pw and user["_id"] == m["owner_id"]:
        try:
            key = accounts.unlock_wallet_key(user, pw)
            r = chain.try_register_real(key, payload)
            details["method"] = "real transaction from the owner's wallet"
            details["failed_tx_hash"] = r["txHash"]
        except accounts.AccountError as e:
            return "ERROR", {"error": str(e)}, []
    else:
        r = chain.preflight_register(owner["wallet_address"], payload)
        details["method"] = "eth_call against current chain state (no password supplied)"
    details["contract_message"] = r["reason"]
    try:                                         # the database also refuses a second record with the same id
        get_db().models.insert_one({"_id": m["_id"]})
        db_msg = "UNEXPECTED: duplicate accepted"
    except Exception as e:
        db_msg = f"rejected: {type(e).__name__}"
    details["database_duplicate_check"] = db_msg
    return ("ACCEPTED" if r["accepted"] else "REJECTED"), details, []


def t_unauthorized_download(m, user, pw):
    db = get_db()
    tmp_pw = secrets.token_urlsafe(12)
    attempts = []
    tmp = accounts.create_user("tmp_" + secrets.token_hex(4), tmp_pw, "buyer")
    try:
        def attempt(label, password):
            try:
                authorize_and_decrypt(tmp, m["_id"], password, log=False)      # the test result below is the record
                attempts.append({"attempt": label, "outcome": "GRANTED", "reason": "access was released"})
            except DistributionError as e:
                attempts.append({"attempt": label, "outcome": "DENIED", "http_status": e.status, "reason": e.reason,
                                 "key_released": False})
        attempt("buyer who never requested access", tmp_pw)
        gid = "gr_" + uuid.uuid4().hex[:12]
        db.grants.insert_one({"_id": gid, "model_id": m["_id"], "buyer_id": tmp["_id"], "buyer_name": tmp["username"],
            "owner_id": m["owner_id"], "license": m["license"], "max_downloads": 1, "downloads_used": 0, "status": "denied",
            "requested_at": now_iso(), "decided_at": now_iso()})
        attempt("buyer whose request was denied by the developer", tmp_pw)
        db.grants.update_one({"_id": gid}, {"$set": {"status": "approved"}})
        attempt("approved buyer, but wrong password (cannot unlock their private key)", "not-the-password")
    finally:
        db.grants.delete_many({"buyer_id": tmp["_id"]})
        db.users.delete_one({"_id": tmp["_id"]})
    actual = "DENIED" if all(a["outcome"] == "DENIED" for a in attempts) else "GRANTED"
    return actual, {"attempts": attempts, "note": "throwaway buyer account created for the test and deleted afterwards"}, []


RUNNERS = {"normal": t_normal, "file_tamper": t_file_tamper, "signature_tamper": t_signature_tamper,
           "unauthorized_ownership": t_unauthorized_ownership, "duplicate": t_duplicate,
           "unauthorized_download": t_unauthorized_download}


def run_test(name: str, m: dict, user: dict, password: str = None) -> dict:
    title, expected = TESTS[name]
    t0 = time.perf_counter()
    try:
        actual, details, checks = RUNNERS[name](m, user, password)
        err = None
    except Exception as e:
        actual, details, checks, err = "ERROR", {}, [], f"{type(e).__name__}: {e}"
    result = {"test": name, "title": title, "expected": expected, "actual": actual, "matched": actual == expected,
              "details": details, "checks": checks, "error": err, "at": now_iso(),
              "duration_ms": round((time.perf_counter() - t0) * 1000, 1), "model_id": m["_id"]}
    _log(m["_id"], user["username"], name, result)
    return result


def run_all(m: dict, user: dict, password: str = None) -> dict:
    results = [run_test(n, get_db().models.find_one({"_id": m["_id"]}), user, password) for n in TESTS]
    return {"model_id": m["_id"], "results": results, "all_matched": all(r["matched"] for r in results),
            "matched": sum(r["matched"] for r in results), "total": len(results)}
