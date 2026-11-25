"""
artifacts.py - where model files live and how they are read back.

  storage/models/<id>/model.joblib   plaintext artifact (exists only until the model is protected)
  storage/models/<id>/model.enc      AES-256-GCM encrypted artifact:  MAGIC | version | nonce | ciphertext+tag

After cryptographic protection the plaintext is securely deleted; from then on the only copy at rest
is the encrypted one, and the content key is available only via the escrow/owner wraps in the DB.
"""
import hashlib
import os
import threading
from pathlib import Path
from cryptography.exceptions import InvalidTag

from crypto import crypto_core as cc, keywrap
from . import config, pki

MAGIC = b"AIMKTGCM"
FORMAT_VERSION = b"\x01"
HEADER_LEN = len(MAGIC) + 1 + cc.NONCE_SIZE


_locks = {}
_locks_guard = threading.Lock()


def model_lock(model_id: str) -> threading.RLock:
    """Serialises operations that read/modify a model's stored files (re-entrant)."""
    with _locks_guard:
        return _locks.setdefault(model_id, threading.RLock())


def model_dir(model_id: str) -> Path:
    d = config.STORAGE_DIR / "models" / model_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def plain_path(model_id: str) -> Path:
    return model_dir(model_id) / "model.joblib"


def enc_path(model_id: str) -> Path:
    return model_dir(model_id) / "model.enc"


def aad_for(model: dict) -> bytes:
    """AES-GCM associated data: binds the ciphertext to this model id, version and plaintext hash."""
    return f"{model['_id']}|{model['version']}|{model['crypto']['original_sha3']}".encode()


def pack_encrypted(nonce: bytes, ciphertext: bytes) -> bytes:
    return MAGIC + FORMAT_VERSION + nonce + ciphertext


def unpack_encrypted(blob: bytes):
    if len(blob) < HEADER_LEN + 16 or not blob.startswith(MAGIC):
        raise ValueError("not an encrypted model container (bad magic / truncated)")
    return blob[len(MAGIC) + 1: HEADER_LEN], blob[HEADER_LEN:]


def secure_delete(path: Path):
    """Best-effort: overwrite with zeros then unlink (SSD wear-levelling may keep remnants)."""
    try:
        size = path.stat().st_size
        with open(path, "r+b") as f:
            f.write(b"\x00" * size); f.flush(); os.fsync(f.fileno())
    finally:
        path.unlink(missing_ok=True)


def content_key_from_escrow(model: dict) -> bytes:
    return keywrap.escrow_unwrap(pki.master_secret(), model["_id"], model["crypto"]["escrow_wrap"])


def decrypt_stored(model: dict, path=None) -> bytes:
    """Decrypt the stored encrypted artifact (raises InvalidTag if it was modified)."""
    blob = Path(path or enc_path(model["_id"])).read_bytes()
    nonce, ct = unpack_encrypted(blob)
    return cc.decrypt(ct, content_key_from_escrow(model), nonce, aad_for(model))


def read_model_bytes(model: dict) -> bytes:
    """
    Bytes of the exact artifact that was trained. Uses the plaintext file while it still exists,
    otherwise decrypts the encrypted copy. In both cases the SHA3-256 is checked against the hash
    recorded at training time BEFORE the bytes are ever unpickled.
    """
    expected = model["training"]["artifact_sha3"]
    p = plain_path(model["_id"])
    data = p.read_bytes() if p.exists() else decrypt_stored(model)
    actual = cc.sha3_256_hash(data)
    if actual != expected:
        raise ValueError(f"artifact integrity failure: sha3 {actual[:16]}... != recorded {expected[:16]}...")
    return data
