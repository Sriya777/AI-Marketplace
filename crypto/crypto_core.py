"""
crypto_core.py
Core symmetric cryptography for the AI Model Marketplace.

Provides:
    - CSPRNG-based key / nonce / salt generation (os.urandom)
    - AES-256-GCM authenticated encryption/decryption
    - SHA3-256 hashing (bytes and streamed files)
    - HKDF-SHA256 key derivation with explicit salt + context ("info")
    - scrypt password-based key derivation (for passwords / key-at-rest)
"""

import os
import hashlib
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

AES_KEY_SIZE = 32      # 256-bit key
NONCE_SIZE = 12        # 96-bit nonce, standard for GCM
SALT_SIZE = 32


# ---------------------------------------------------------------- CSPRNG
def random_bytes(n: int) -> bytes:
    """All randomness (keys, nonces, salts, tokens) comes from the OS CSPRNG."""
    return os.urandom(n)


def generate_key() -> bytes:
    """CSPRNG-based 256-bit AES key."""
    return random_bytes(AES_KEY_SIZE)


def generate_nonce() -> bytes:
    """CSPRNG-based 96-bit nonce. MUST be unique per (key, message)."""
    return random_bytes(NONCE_SIZE)


def generate_salt() -> bytes:
    return random_bytes(SALT_SIZE)


# ---------------------------------------------------------------- AES-256-GCM
def encrypt(plaintext: bytes, key: bytes, associated_data: bytes = b"") -> dict:
    """
    AES-256-GCM. Returns nonce + ciphertext (the 16-byte tag is appended to the
    ciphertext by AESGCM). associated_data is authenticated but not encrypted.
    """
    if len(key) != AES_KEY_SIZE:
        raise ValueError("AES-256 key must be 32 bytes")
    nonce = generate_nonce()
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data)
    return {"nonce": nonce, "ciphertext": ciphertext, "aad": associated_data}


def decrypt(ciphertext: bytes, key: bytes, nonce: bytes, associated_data: bytes = b"") -> bytes:
    """Decrypt + verify. Raises cryptography.exceptions.InvalidTag on any tampering."""
    return AESGCM(key).decrypt(nonce, ciphertext, associated_data)


# ---------------------------------------------------------------- SHA3-256
def sha3_256_hash(data: bytes) -> str:
    """Hex digest of SHA3-256(data)."""
    return hashlib.sha3_256(data).hexdigest()


def sha3_256_digest(data: bytes) -> bytes:
    return hashlib.sha3_256(data).digest()


def hash_file(path: str) -> str:
    """Streams a file through SHA3-256 (safe for large model files)."""
    h = hashlib.sha3_256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- HKDF
def hkdf_derive(key_material: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    """
    HKDF-SHA256 (RFC 5869). `salt` must be random per derivation and `info`
    binds the derived key to its purpose/context (model id, recipient, ...), so
    the same input key material can never yield the same key for two purposes.
    """
    if not salt:
        raise ValueError("HKDF requires an explicit salt")
    if not info:
        raise ValueError("HKDF requires explicit context info")
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(key_material)


# ---------------------------------------------------------------- scrypt
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1


def scrypt_derive(secret: bytes, salt: bytes, length: int = 32,
                  n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> bytes:
    """Memory-hard password-based KDF (used for user passwords and the master passphrase)."""
    return Scrypt(salt=salt, length=length, n=n, r=r, p=p).derive(secret)
