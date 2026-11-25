"""
download_verify.py  (v2)
Phase 5/6 - Buyer-side flow. Every check here maps to one objective
from the problem statement - this is the script to narrate line-by-line
if a teacher asks "how exactly is security ensured":

  [1] Role-based access check   -> buyer's cert must chain to the marketplace CA
  [2] Authenticity check        -> developer's cert must chain to the same CA
  [3] Integrity check (hash)    -> SHA3-256 of stored ciphertext matches on-chain record
  [4] Integrity check (Merkle)  -> Merkle root matches on-chain record
  [5] Non-repudiation check     -> ECDSA signature verifies under the developer's CERTIFIED key
  [6] Confidentiality + decrypt -> AES key independently re-derived via ECDH+HKDF, never transmitted
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from crypto.crypto_core import decrypt, sha3_256_hash
from crypto.identity import verify_signature, verify_certificate, derive_model_encryption_key
from crypto.merkle import chunk_bytes, merkle_root
from marketplace.upload import upload_model


def verify_and_decrypt(upload_result: dict) -> bytes:
    payload = upload_result["payload"]
    parties = upload_result["parties"]
    model_id = upload_result["model_id"]

    with open(upload_result["encrypted_path"], "rb") as f:
        blob = f.read()
    nonce, ciphertext = blob[:12], blob[12:]

    # [1] Role-based access: is this buyer even a certified marketplace participant?
    buyer_ok = verify_certificate(parties["buyer_cert"], parties["ca_cert"])
    print(f"[1] Buyer cert chains to marketplace CA (role-based access): {'PASS' if buyer_ok else 'FAIL'}")

    # [2] Authenticity: is the claimed developer actually CA-certified?
    dev_ok = verify_certificate(parties["dev_cert"], parties["ca_cert"])
    print(f"[2] Developer cert chains to marketplace CA (authenticity): {'PASS' if dev_ok else 'FAIL'}")

    # [3] Integrity - whole-file hash
    recomputed_hash = sha3_256_hash(ciphertext)
    hash_ok = ("0x" + recomputed_hash) == payload["modelHash"]
    print(f"[3] SHA3-256 hash matches on-chain record: {'PASS' if hash_ok else 'FAIL'}")

    # [4] Integrity - Merkle root (would also support partial-chunk proofs)
    chunks = list(chunk_bytes(ciphertext))
    recomputed_root = merkle_root(chunks)
    root_ok = ("0x" + recomputed_root) == payload["merkleRoot"]
    print(f"[4] Merkle root matches on-chain record: {'PASS' if root_ok else 'FAIL'}")

    # [5] Non-repudiation: signature must verify under the CERTIFIED dev public key,
    #     not just some arbitrary key - ties the proof to a vetted identity.
    sig_ok = verify_signature(
        parties["dev_cert"].public_key(),
        bytes.fromhex(payload["signature"]),
        bytes.fromhex(recomputed_root),
    )
    print(f"[5] ECDSA signature verifies under developer's CERTIFIED key: {'PASS' if sig_ok else 'FAIL'}")

    if not (buyer_ok and dev_ok and hash_ok and root_ok and sig_ok):
        raise ValueError("One or more security checks failed - access denied, refusing to decrypt.")

    # [6] Confidentiality: buyer independently re-derives the SAME AES key the
    #     developer used, via their own ECDH(buyer_priv, dev_pub) + HKDF - the
    #     key itself was never transmitted anywhere.
    key = derive_model_encryption_key(parties["buyer_priv"], parties["dev_pub"], model_id)
    plaintext = decrypt(ciphertext, key, nonce, associated_data=model_id.encode())
    print(f"[6] Buyer independently re-derived the decryption key and decrypted. "
          f"Model size: {len(plaintext)} bytes")
    return plaintext


def demo_happy_path():
    print("=== HAPPY PATH ===")
    result = upload_model(model_id="mnist-classifier-v1")
    print()
    verify_and_decrypt(result)


def demo_tamper_detection():
    print("\n=== TAMPER DETECTION DEMO ===")
    result = upload_model(model_id="mnist-classifier-v1")

    path = result["encrypted_path"]
    with open(path, "r+b") as f:
        f.seek(20)
        byte = f.read(1)
        f.seek(20)
        f.write(bytes([byte[0] ^ 0xFF]))
    print("(tampered with one byte in the stored encrypted file)")
    print()

    try:
        verify_and_decrypt(result)
    except ValueError as e:
        print(f"[RESULT] Correctly rejected tampered file: {e}")


def demo_unauthorized_buyer():
    print("\n=== UNAUTHORIZED BUYER DEMO (role-based access) ===")
    result = upload_model(model_id="mnist-classifier-v1")

    # Simulate a buyer with NO cert from the marketplace CA (self-issued, untrusted).
    from crypto.identity import generate_ec_keypair, create_self_signed_ca, issue_developer_cert
    rogue_priv, rogue_pub = generate_ec_keypair()
    fake_ca_key, fake_ca_cert = create_self_signed_ca("Rogue CA")
    rogue_cert = issue_developer_cert(fake_ca_key, fake_ca_cert, rogue_pub, "Attacker")

    result["parties"]["buyer_priv"] = rogue_priv
    result["parties"]["buyer_pub"] = rogue_pub
    result["parties"]["buyer_cert"] = rogue_cert  # NOT signed by the real marketplace CA
    print()

    try:
        verify_and_decrypt(result)
    except ValueError as e:
        print(f"[RESULT] Correctly denied access to uncertified buyer: {e}")


if __name__ == "__main__":
    demo_happy_path()
    demo_tamper_detection()
    demo_unauthorized_buyer()
