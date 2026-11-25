"""
registration.py - PHASE 4: register the cryptographic proofs on the blockchain.
Allowed only after training -> deployment -> hash -> encrypt -> Merkle -> sign have all succeeded.
"""
from fastapi import HTTPException

from crypto import identity as idn
from . import accounts, chain
from .db import get_db
from .ml import now_iso


def _fail(status, msg):
    raise HTTPException(status, msg)


def build_payload(m: dict, owner: dict) -> tuple:
    cr = m["crypto"]
    cert = idn.load_cert_pem(owner["cert_pem"])
    return chain.register_input(m["_id"], m["version"], cr["original_sha3"], cr["encrypted_sha3"], cr["merkle"]["root"],
                                cr["metadata_sha3"], bytes.fromhex(cr["signature_hex"]),
                                idn.public_key_to_der(cert.public_key()), m["license"])


def payload_json(m: dict, owner: dict) -> dict:
    t = build_payload(m, owner)
    keys = ["modelId", "version", "originalHash", "encryptedHash", "merkleRoot", "metadataHash",
            "signature", "creatorPubKey", "licenseTerms"]
    out = {}
    for k, v in zip(keys, t):
        out[k] = ("0x" + v.hex()) if isinstance(v, (bytes, bytearray)) else v
    return out


def _require_ready(m):
    if m["status"] == "registered" or m.get("blockchain", {}).get("tx_hash"):
        _fail(409, "model is already registered on the blockchain")
    if m["status"] not in ("protected", "packaged", "deployed") or not m.get("crypto", {}).get("signature_hex"):
        _fail(409, "blockchain registration requires a packaged, signed cryptographic bundle (Stage 4)")
    if not chain.is_available():
        _fail(503, "blockchain node/contract unavailable: " + chain.status().get("error", "unknown"))


def _compare_with_chain(m: dict) -> dict:
    rec = chain.get_record(m["_id"])
    if rec is None: _fail(502, "registration transaction succeeded but the record cannot be read back")
    cr = m["crypto"]
    expect = {"originalHash": "0x" + cr["original_sha3"], "encryptedHash": "0x" + cr["encrypted_sha3"],
              "merkleRoot": "0x" + cr["merkle"]["root"], "metadataHash": "0x" + cr["metadata_sha3"],
              "signature": cr["signature_hex"], "version": m["version"], "licenseTerms": m["license"]}
    bad = [k for k, v in expect.items() if rec[k] != v]
    if bad: _fail(502, "on-chain record differs from local values: " + ", ".join(bad))
    return rec


def _save(m, tx, rec, via):
    info = {"tx_hash": tx["txHash"], "block_number": tx["blockNumber"], "block_timestamp": tx["blockTimestamp"],
            "gas_used": tx["gasUsed"], "creator": rec["creator"], "contract_address": chain.config_for_frontend()["address"],
            "chain_id": chain.config_for_frontend()["chainId"], "registered_via": via, "registered_at": now_iso()}
    db = get_db()
    db.models.update_one({"_id": m["_id"]}, {"$set": {"blockchain": info, "status": "registered",
                                                       "stages.registration": {"status": "completed", "at": now_iso()},
                                                       "stages.register": {"status": "completed", "at": now_iso()}}})
    return info


def register_custodial(m: dict, owner: dict, password: str) -> dict:
    _require_ready(m)
    try:
        key = accounts.unlock_wallet_key(owner, password)
    except accounts.AccountError as e:
        _fail(e.status, str(e))
    addr = chain.address_of(key)
    accounts.ensure_wallet_ready(addr)
    payload = build_payload(m, owner)
    pre = chain.preflight_register(addr, payload)
    if not pre["accepted"]:
        get_db().models.update_one({"_id": m["_id"]}, {"$set": {"stages.register": {"status": "failed", "at": now_iso(), "error": pre["reason"]}}})
        _fail(409 if "already" in pre["reason"] else 403, f"blockchain rejected the registration: {pre['reason']}")
    try:
        tx = chain.register_model(key, payload)
    except chain.ChainRevert as e:
        _fail(409, f"blockchain rejected the registration: {e.reason}")
    rec = _compare_with_chain(m)
    info = _save(m, tx, rec, "custodial wallet")
    return {"blockchain": info, "record": rec}


def register_confirm(m: dict, owner: dict, tx_hash: str) -> dict:
    """Finalise a registration that the developer sent themselves (e.g. from MetaMask)."""
    _require_ready(m)
    try:
        tx = chain.confirm_registration(tx_hash, m["_id"])
    except chain.ChainError as e:
        _fail(400, str(e))
    if tx["creator"].lower() not in accounts.user_wallets(owner):
        _fail(403, "the registering wallet is not linked to your account")
    rec = _compare_with_chain(m)
    info = _save(m, tx, rec, "MetaMask / external wallet")
    return {"blockchain": info, "record": rec}


def link_wallet(user: dict, address: str) -> dict:
    from web3 import Web3
    if not Web3.is_address(address): _fail(422, "not a valid Ethereum address")
    addr = Web3.to_checksum_address(address)
    if not chain.is_available(): _fail(503, "blockchain unavailable")
    if user["role"] != "developer": _fail(403, "only developers can link a wallet")
    owner = get_db().users.find_one({"_id": user["_id"]})
    if addr.lower() not in {a.lower() for a in owner.get("linked_wallets", [])}:
        get_db().users.update_one({"_id": user["_id"]}, {"$push": {"linked_wallets": addr}})
    tx = chain.authorize_developer(addr)
    chain.fund(addr)
    return {"address": addr, "authorized_on_chain": chain.is_authorized(addr), "authorization_tx": tx and tx["txHash"],
            "balance_eth": chain.balance_eth(addr)}
