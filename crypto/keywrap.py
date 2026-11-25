"""
keywrap.py
Distribution of the per-model AES content key.

    content_key  = CSPRNG 256-bit key that encrypts the model once (AES-256-GCM)

Two wrapping mechanisms (both use HKDF with a random salt and explicit context):

1. ECIES-style ECC key exchange (ephemeral ECDH P-256 + HKDF + AES-GCM):
     wrap for the developer (owner copy) and, at distribution time, for the
     authorized buyer. Only the holder of the matching EC private key can unwrap.
2. Escrow wrap (marketplace master secret + HKDF + AES-GCM):
     lets the marketplace hand the key to a buyer ONLY after the access policy and
     blockchain/Merkle/signature checks pass. The master secret is derived from an
     operator passphrase (scrypt) and is never stored.
"""

import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import serialization
from .crypto_core import generate_salt, generate_nonce, hkdf_derive

_b64e = lambda b: base64.b64encode(b).decode()
_b64d = lambda s: base64.b64decode(s.encode())

ECIES_INFO_PREFIX = b"ai-marketplace/v1/ecies-key-wrap|"
ESCROW_INFO_PREFIX = b"ai-marketplace/v1/escrow-kek|"


def _pub_pem(pub) -> bytes:
    return pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def ecies_wrap(recipient_public_key, content_key: bytes, context: str) -> dict:
    """Ephemeral-static ECDH -> HKDF(salt random, info=context) -> AES-256-GCM wrap."""
    eph_priv = ec.generate_private_key(ec.SECP256R1())
    shared = eph_priv.exchange(ec.ECDH(), recipient_public_key)
    salt = generate_salt()
    info = ECIES_INFO_PREFIX + context.encode()
    kek = hkdf_derive(shared, salt, info, 32)
    nonce = generate_nonce()
    ct = AESGCM(kek).encrypt(nonce, content_key, info)
    return {"scheme": "ECDH-P256+HKDF-SHA256+AES-256-GCM",
            "ephemeral_public_pem": _pub_pem(eph_priv.public_key()).decode(),
            "salt": _b64e(salt), "nonce": _b64e(nonce), "ct": _b64e(ct), "context": context}


def ecies_unwrap(recipient_private_key, blob: dict) -> bytes:
    eph_pub = serialization.load_pem_public_key(blob["ephemeral_public_pem"].encode())
    shared = recipient_private_key.exchange(ec.ECDH(), eph_pub)
    info = ECIES_INFO_PREFIX + blob["context"].encode()
    kek = hkdf_derive(shared, _b64d(blob["salt"]), info, 32)
    return AESGCM(kek).decrypt(_b64d(blob["nonce"]), _b64d(blob["ct"]), info)


def escrow_wrap(master_secret: bytes, model_id: str, content_key: bytes) -> dict:
    salt = generate_salt()
    info = ESCROW_INFO_PREFIX + model_id.encode()
    kek = hkdf_derive(master_secret, salt, info, 32)
    nonce = generate_nonce()
    ct = AESGCM(kek).encrypt(nonce, content_key, info)
    return {"scheme": "HKDF-SHA256+AES-256-GCM", "salt": _b64e(salt), "nonce": _b64e(nonce), "ct": _b64e(ct)}


def escrow_unwrap(master_secret: bytes, model_id: str, blob: dict) -> bytes:
    info = ESCROW_INFO_PREFIX + model_id.encode()
    kek = hkdf_derive(master_secret, _b64d(blob["salt"]), info, 32)
    return AESGCM(kek).decrypt(_b64d(blob["nonce"]), _b64d(blob["ct"]), info)
