"""
pki.py - local X.509 certificate authority + master secret handling.

* The CA private key is stored ENCRYPTED (AES-256-GCM under a key derived from the operator
  passphrase via scrypt+HKDF). The passphrase itself is never stored.
* The master secret used for the content-key escrow is derived from the same passphrase
  (scrypt, stored random salt) and held only in process memory.
"""
import json
import threading
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from crypto import identity as idn
from crypto.crypto_core import generate_salt, generate_nonce, scrypt_derive, hkdf_derive
from . import config
from .db import get_db

_lock = threading.Lock()
_state = {}

CA_DIR_NAME = "ca"
_AAD = b"ai-marketplace/v1/ca-key"


class ConfigError(RuntimeError):
    pass


def _ca_dir():
    d = config.STORAGE_DIR / CA_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def init():
    """Idempotent. Raises ConfigError if the master passphrase is missing/weak."""
    with _lock:
        if _state:
            return
        if len(config.MASTER_PASSPHRASE) < 12:
            raise ConfigError("MARKETPLACE_MASTER_PASSPHRASE must be set (min 12 chars). "
                              "Run scripts/setup (it generates one into .env) or export it manually.")
        d = _ca_dir()
        salt_path = d / "master_salt.bin"
        if not salt_path.exists():
            salt_path.write_bytes(generate_salt())
        master = scrypt_derive(config.MASTER_PASSPHRASE.encode(), salt_path.read_bytes())
        ca_key_path, ca_cert_path = d / "ca_key.enc.json", d / "ca_cert.pem"
        if ca_key_path.exists() and ca_cert_path.exists():
            blob = json.loads(ca_key_path.read_text())
            kek = hkdf_derive(master, bytes.fromhex(blob["salt"]), b"ai-marketplace/v1/ca-key-kek")
            try:
                pem = AESGCM(kek).decrypt(bytes.fromhex(blob["nonce"]), bytes.fromhex(blob["ct"]), _AAD)
            except Exception:
                raise ConfigError("MARKETPLACE_MASTER_PASSPHRASE does not match the stored CA key "
                                  "(wrong passphrase, or storage/ca belongs to another installation)")
            ca_key = idn.load_private_key_pem(pem)
            ca_cert = idn.load_cert_pem(ca_cert_path.read_bytes())
        else:
            ca_key, ca_cert = idn.create_self_signed_ca("Marketplace Local Root CA")
            salt2, nonce = generate_salt(), generate_nonce()
            kek = hkdf_derive(master, salt2, b"ai-marketplace/v1/ca-key-kek")
            ct = AESGCM(kek).encrypt(nonce, idn.private_key_to_pem(ca_key), _AAD)
            ca_key_path.write_text(json.dumps({"salt": salt2.hex(), "nonce": nonce.hex(), "ct": ct.hex()}))
            ca_cert_path.write_bytes(idn.cert_to_pem(ca_cert))
            print("[pki] generated new local CA:", idn.cert_summary(ca_cert)["subject"])
        _state.update(master=master, ca_key=ca_key, ca_cert=ca_cert)


def master_secret() -> bytes:
    init(); return _state["master"]


def ca_cert():
    init(); return _state["ca_cert"]


def issue_cert(public_key, username: str, role: str):
    init()
    return idn.issue_developer_cert(_state["ca_key"], _state["ca_cert"], public_key, username, role=role)


def revoked_serials():
    return {u["cert_serial"] for u in get_db().users.find({"cert_revoked": True}) if u.get("cert_serial")}


def validate_cert_pem(cert_pem: str) -> dict:
    cert = idn.load_cert_pem(cert_pem)
    res = idn.verify_certificate_chain(cert, ca_cert(), revoked_serials())
    res["certificate"] = idn.cert_summary(cert)
    return res
