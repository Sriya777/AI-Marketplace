"""
upload.py  (v2)
Phase 5/6 - Full upload flow using CA-issued identities and a real
ECDH+HKDF key exchange, not a bare random key.

Flow:
    model file
      -> developer + buyer both hold CA-issued X.509 certs (role check)
      -> AES key = ECDH(dev_priv, buyer_pub) -> HKDF (NOT sent anywhere)
      -> AES-256-GCM encrypt with that derived key
      -> SHA3-256 hash + Merkle root over the ciphertext
      -> developer signs the root with ECDSA (their CA-certified key)
      -> print the payload that would go to ModelRegistry.registerModel()
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from crypto.crypto_core import encrypt, sha3_256_hash
from crypto.identity import sign_data, derive_model_encryption_key
from crypto.merkle import chunk_bytes, merkle_root
from marketplace.parties import setup_marketplace

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "artifacts", "mnist_classifier.joblib")
ENCRYPTED_OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "artifacts", "mnist_classifier.enc")


def upload_model(model_id: str, license_terms: str = "single-use"):
    parties = setup_marketplace()
    print(f"[0] CA issued certs to developer and buyer "
          f"(Subject CN's: '{parties['dev_cert'].subject.rfc4514_string()}', "
          f"'{parties['buyer_cert'].subject.rfc4514_string()}')")

    with open(MODEL_PATH, "rb") as f:
        plaintext = f.read()

    # Key is DERIVED, never transmitted: both sides compute the same
    # value independently via ECDH(their_priv, other's_pub) + HKDF.
    key = derive_model_encryption_key(parties["dev_priv"], parties["buyer_pub"], model_id)
    print(f"[1] AES key derived via ECDH+HKDF (never sent over the wire): "
          f"{key.hex()[:16]}...")

    result = encrypt(plaintext, key, associated_data=model_id.encode())
    with open(ENCRYPTED_OUT_PATH, "wb") as f:
        f.write(result["nonce"] + result["ciphertext"])
    print(f"[2] Encrypted model written to {ENCRYPTED_OUT_PATH} "
          f"({len(result['ciphertext'])} bytes ciphertext)")

    model_hash = sha3_256_hash(result["ciphertext"])
    print(f"[3] SHA3-256(model): {model_hash}")

    chunks = list(chunk_bytes(result["ciphertext"]))
    root = merkle_root(chunks)
    print(f"[4] Merkle root over {len(chunks)} chunks: {root}")

    signature = sign_data(parties["dev_priv"], bytes.fromhex(root))
    print(f"[5] Developer signed root with CA-certified key. Signature length: {len(signature)} bytes")

    payload = {
        "modelId": model_id,
        "modelHash": "0x" + model_hash,
        "merkleRoot": "0x" + root,
        "signature": signature.hex(),
        "licenseTerms": license_terms,
    }
    print("\n[6] On-chain registration payload:")
    for k, v in payload.items():
        preview = v if len(str(v)) < 80 else str(v)[:77] + "..."
        print(f"    {k}: {preview}")

    return {
        "payload": payload,
        "nonce": result["nonce"],
        "encrypted_path": ENCRYPTED_OUT_PATH,
        "parties": parties,
        "model_id": model_id,
    }


if __name__ == "__main__":
    upload_model(model_id="mnist-classifier-v1")
