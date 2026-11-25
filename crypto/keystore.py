"""
keystore.py
Password-protected storage of private keys and password hashing.

Private keys are NEVER stored in plaintext:
    key_enc = AES-256-GCM( HKDF( scrypt(password, salt1), salt2, info ), private_key_bytes )
Passwords are stored only as scrypt hashes.
"""

import base64
import hmac
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .crypto_core import (
    generate_salt, generate_nonce, scrypt_derive, hkdf_derive,
    SCRYPT_N, SCRYPT_R, SCRYPT_P,
)

_b64e = lambda b: base64.b64encode(b).decode()
_b64d = lambda s: base64.b64decode(s.encode())

KEYSTORE_INFO = b"ai-marketplace/v1/keystore|private-key-at-rest"
KEYSTORE_AAD = b"ai-marketplace/v1/keystore"


def hash_password(password: str) -> dict:
    salt = generate_salt()
    digest = scrypt_derive(password.encode(), salt)
    return {"alg": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P,
            "salt": _b64e(salt), "hash": _b64e(digest)}


def verify_password(password: str, record: dict) -> bool:
    salt = _b64d(record["salt"])
    digest = scrypt_derive(password.encode(), salt, n=record["n"], r=record["r"], p=record["p"])
    return hmac.compare_digest(digest, _b64d(record["hash"]))


def _derive_wrapping_key(password: str, salt1: bytes, salt2: bytes) -> bytes:
    master = scrypt_derive(password.encode(), salt1)
    return hkdf_derive(master, salt2, KEYSTORE_INFO, 32)


def encrypt_private_key(private_bytes: bytes, password: str) -> dict:
    """Encrypt serialized private-key bytes under a password. Returns a JSON-able blob."""
    salt1, salt2, nonce = generate_salt(), generate_salt(), generate_nonce()
    key = _derive_wrapping_key(password, salt1, salt2)
    ct = AESGCM(key).encrypt(nonce, private_bytes, KEYSTORE_AAD)
    return {"v": 1, "kdf": "scrypt+hkdf-sha256", "cipher": "aes-256-gcm",
            "salt1": _b64e(salt1), "salt2": _b64e(salt2), "nonce": _b64e(nonce), "ct": _b64e(ct)}


def decrypt_private_key(blob: dict, password: str) -> bytes:
    """Raises ValueError on wrong password (GCM tag failure)."""
    key = _derive_wrapping_key(password, _b64d(blob["salt1"]), _b64d(blob["salt2"]))
    try:
        return AESGCM(key).decrypt(_b64d(blob["nonce"]), _b64d(blob["ct"]), KEYSTORE_AAD)
    except InvalidTag:
        raise ValueError("wrong password or corrupted key store")
