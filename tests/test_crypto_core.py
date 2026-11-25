"""
test_crypto_core.py
Run: python tests/test_crypto_core.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from crypto.crypto_core import generate_key, encrypt, decrypt, sha3_256_hash
from cryptography.exceptions import InvalidTag


def run():
    print("=== crypto_core round-trip test ===")

    plaintext = b"FAKE_MODEL_WEIGHTS_BINARY_BLOB_" * 1000
    original_hash = sha3_256_hash(plaintext)
    print(f"[1] Original SHA3-256: {original_hash[:16]}...")

    key = generate_key()
    result = encrypt(plaintext, key, associated_data=b"model_id=demo-v1")
    print(f"[2] Encrypted. Nonce: {result['nonce'].hex()[:16]}..., "
          f"ciphertext len: {len(result['ciphertext'])} bytes")

    recovered = decrypt(result["ciphertext"], key, result["nonce"],
                         associated_data=b"model_id=demo-v1")
    assert recovered == plaintext, "Decrypted plaintext does not match original!"
    print("[3] Decrypted successfully, plaintext matches original.")

    recovered_hash = sha3_256_hash(recovered)
    assert recovered_hash == original_hash, "Hash mismatch after decrypt!"
    print(f"[4] Post-decrypt SHA3-256 matches original: {recovered_hash[:16]}...")

    tampered = bytearray(result["ciphertext"])
    tampered[0] ^= 0xFF
    try:
        decrypt(bytes(tampered), key, result["nonce"], associated_data=b"model_id=demo-v1")
        print("[5] FAILED: tampered ciphertext was accepted (should never happen)")
    except InvalidTag:
        print("[5] Tamper correctly detected (InvalidTag raised).")

    print("=== ALL CHECKS PASSED ===")


if __name__ == "__main__":
    run()
