"""
accounts.py - users, sessions, per-user key material.

Each user gets, at registration:
  * an ECC P-256 key pair; the private key is stored only password-encrypted (scrypt+HKDF+AES-GCM)
  * an X.509 identity certificate issued by the local CA (binds username+role to the public key)
  * developers additionally get an Ethereum wallet (secp256k1); its key is stored password-encrypted
Passwords are stored as scrypt hashes. Sessions are opaque random tokens; only their SHA3 is stored.
"""
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from crypto import identity as idn, keystore
from crypto.crypto_core import sha3_256_hash
from . import chain, config, pki
from .db import get_db

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
ROLES = ("developer", "buyer")


class AccountError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg); self.status = status


def _now():
    return datetime.now(timezone.utc)


def public_user(u: dict) -> dict:
    cert = idn.load_cert_pem(u["cert_pem"])
    return {"id": u["_id"], "username": u["username"], "role": u["role"], "created_at": u["created_at"],
            "wallet_address": u.get("wallet_address"), "linked_wallets": u.get("linked_wallets", []),
            "certificate": idn.cert_summary(cert), "cert_revoked": bool(u.get("cert_revoked"))}


def create_user(username: str, password: str, role: str) -> dict:
    if not USERNAME_RE.match(username or ""):
        raise AccountError("username must be 3-32 chars: letters, digits, '_', '.', '-'")
    if len(password or "") < 8:
        raise AccountError("password must be at least 8 characters")
    if role not in ROLES:
        raise AccountError(f"role must be one of {ROLES}")
    priv, pub = idn.generate_ec_keypair()
    cert = pki.issue_cert(pub, username, role)
    user = {"_id": "usr_" + uuid.uuid4().hex[:12], "username": username, "role": role,
            "password": keystore.hash_password(password),
            "ec_public_pem": idn.public_key_to_pem(pub).decode(),
            "ec_private_enc": keystore.encrypt_private_key(idn.private_key_to_pem(priv), password),
            "cert_pem": idn.cert_to_pem(cert).decode(), "cert_serial": format(cert.serial_number, "x"),
            "cert_revoked": False, "created_at": _now().isoformat(), "linked_wallets": []}
    if role == "developer":
        addr, key = chain.new_wallet()
        user["wallet_address"] = addr
        user["wallet_private_enc"] = keystore.encrypt_private_key(key.encode(), password)
    try:
        get_db().users.insert_one(user)
    except DuplicateKeyError:
        raise AccountError("username already taken", 409)
    if role == "developer":
        ensure_wallet_ready(user["wallet_address"])
    return user


def ensure_wallet_ready(address: str):
    """Best effort (local chain): fund the developer wallet and authorize it on the registry."""
    try:
        if chain.is_available():
            chain.fund(address)
            chain.authorize_developer(address)
    except Exception as e:
        print("[accounts] wallet provisioning deferred:", e)


def login(username: str, password: str) -> dict:
    u = get_db().users.find_one({"username": username})
    if not u or not keystore.verify_password(password, u["password"]):
        raise AccountError("invalid username or password", 401)
    token = secrets.token_urlsafe(32)
    get_db().sessions.insert_one({"_id": sha3_256_hash(token.encode()), "user_id": u["_id"],
                                  "expires_at": (_now() + timedelta(hours=config.SESSION_TTL_HOURS)).isoformat()})
    return {"token": token, "user": public_user(u)}


def user_from_token(token: str):
    if not token:
        return None
    s = get_db().sessions.find_one({"_id": sha3_256_hash(token.encode())})
    if not s or datetime.fromisoformat(s["expires_at"]) < _now():
        return None
    return get_db().users.find_one({"_id": s["user_id"]})


def logout(token: str):
    get_db().sessions.delete_one({"_id": sha3_256_hash(token.encode())})


def unlock_ec_private_key(user: dict, password: str):
    try:
        return idn.load_private_key_pem(keystore.decrypt_private_key(user["ec_private_enc"], password))
    except ValueError:
        raise AccountError("wrong password - cannot unlock your signing key", 401)


def unlock_wallet_key(user: dict, password: str) -> str:
    if "wallet_private_enc" not in user:
        raise AccountError("this account has no custodial wallet", 400)
    try:
        return keystore.decrypt_private_key(user["wallet_private_enc"], password).decode()
    except ValueError:
        raise AccountError("wrong password - cannot unlock your wallet key", 401)


def user_wallets(user: dict) -> set:
    w = {a.lower() for a in user.get("linked_wallets", [])}
    if user.get("wallet_address"):
        w.add(user["wallet_address"].lower())
    return w


def cert_status(user: dict) -> dict:
    """Validate the user's X.509 certificate against the local CA (incl. revocation)."""
    cert = idn.load_cert_pem(user["cert_pem"])
    res = idn.verify_certificate_chain(cert, pki.ca_cert(), pki.revoked_serials())
    res["certificate"] = idn.cert_summary(cert)
    return res
