"""Unit tests for every cryptographic primitive used by the marketplace. Run: pytest tests/test_crypto_suite.py -v"""
import os, sys, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric import ec

from crypto import crypto_core as cc, keystore, keywrap, identity as idn, merkle as mk


# ---------------- SHA3-256 ----------------
def test_sha3_known_answer_vectors():
    # NIST FIPS 202 test vectors
    assert cc.sha3_256_hash(b"abc") == "3a985da74fe225b2045c172d6bd390bd855f086e3e9d525b46bfe24511431532"
    assert cc.sha3_256_hash(b"") == "a7ffc6f8bf1ed76651c14756a061d662f580ff4de43b49fa82d80a4b80f8434a"

def test_hash_file_matches_bytes(tmp_path):
    data = os.urandom(300_000)
    p = tmp_path / "f.bin"; p.write_bytes(data)
    assert cc.hash_file(str(p)) == cc.sha3_256_hash(data)

# ---------------- CSPRNG ----------------
def test_csprng_unique_and_sized():
    keys = {cc.generate_key() for _ in range(200)}
    assert len(keys) == 200 and all(len(k) == 32 for k in keys)
    assert len({cc.generate_nonce() for _ in range(200)}) == 200
    assert len(cc.generate_salt()) == 32

# ---------------- AES-256-GCM ----------------
def test_aes_gcm_roundtrip_and_authentication():
    key, pt, aad = cc.generate_key(), os.urandom(5000), b"model|1.0"
    r = cc.encrypt(pt, key, aad)
    assert cc.decrypt(r["ciphertext"], key, r["nonce"], aad) == pt
    bad = bytearray(r["ciphertext"]); bad[10] ^= 1
    with pytest.raises(InvalidTag): cc.decrypt(bytes(bad), key, r["nonce"], aad)          # ciphertext tamper
    with pytest.raises(InvalidTag): cc.decrypt(r["ciphertext"], key, r["nonce"], b"other")  # AAD tamper
    with pytest.raises(InvalidTag): cc.decrypt(r["ciphertext"], cc.generate_key(), r["nonce"], aad)  # wrong key
    with pytest.raises(ValueError): cc.encrypt(pt, b"short")

def test_aes_nonce_never_reused():
    key = cc.generate_key()
    assert len({cc.encrypt(b"x", key)["nonce"] for _ in range(500)}) == 500

# ---------------- HKDF ----------------
def test_hkdf_context_and_salt_separation():
    ikm, salt = os.urandom(32), os.urandom(32)
    a = cc.hkdf_derive(ikm, salt, b"purpose-A"); b = cc.hkdf_derive(ikm, salt, b"purpose-B")
    c = cc.hkdf_derive(ikm, os.urandom(32), b"purpose-A")
    assert a != b and a != c and len(a) == 32
    assert a == cc.hkdf_derive(ikm, salt, b"purpose-A")  # deterministic
    with pytest.raises(ValueError): cc.hkdf_derive(ikm, b"", b"x")
    with pytest.raises(ValueError): cc.hkdf_derive(ikm, salt, b"")

def test_hkdf_rfc5869_vector():
    # RFC 5869 Appendix A.1 (SHA-256)
    ikm = bytes.fromhex("0b" * 22); salt = bytes.fromhex("000102030405060708090a0b0c")
    info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
    okm = cc.hkdf_derive(ikm, salt, info, 42)
    assert okm.hex() == "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865"

def test_scrypt_deterministic_and_salted():
    s = cc.generate_salt()
    assert cc.scrypt_derive(b"pw", s) == cc.scrypt_derive(b"pw", s)
    assert cc.scrypt_derive(b"pw", s) != cc.scrypt_derive(b"pw2", s)

# ---------------- keystore ----------------
def test_keystore_password_and_private_key_at_rest():
    rec = keystore.hash_password("correct horse")
    assert keystore.verify_password("correct horse", rec) and not keystore.verify_password("wrong", rec)
    priv, _ = idn.generate_ec_keypair(); pem = idn.private_key_to_pem(priv)
    blob = keystore.encrypt_private_key(pem, "pw12345678")
    assert pem not in str(blob).encode() and b"PRIVATE KEY" not in str(blob).encode()
    assert keystore.decrypt_private_key(blob, "pw12345678") == pem
    with pytest.raises(ValueError): keystore.decrypt_private_key(blob, "bad password")

# ---------------- ECDSA / ECDH ----------------
def test_ecdsa_sign_verify_and_tamper():
    priv, pub = idn.generate_ec_keypair(); msg = b"canonical metadata"
    sig = idn.sign_data(priv, msg)
    assert idn.verify_signature(pub, sig, msg)
    assert not idn.verify_signature(pub, sig, msg + b"!")
    bad = bytearray(sig); bad[-1] ^= 1
    assert not idn.verify_signature(pub, bytes(bad), msg)
    assert not idn.verify_signature(idn.generate_ec_keypair()[1], sig, msg)  # wrong signer

def test_ecdh_shared_secret_agrees():
    a, apub = idn.generate_ec_keypair(); b, bpub = idn.generate_ec_keypair()
    assert idn.ecdh_shared_secret(a, bpub) == idn.ecdh_shared_secret(b, apub)

# ---------------- key wrapping ----------------
def test_ecies_wrap_unwrap_and_isolation():
    priv, pub = idn.generate_ec_keypair(); ck = cc.generate_key()
    blob = keywrap.ecies_wrap(pub, ck, "model-1|alice")
    assert keywrap.ecies_unwrap(priv, blob) == ck
    other, _ = idn.generate_ec_keypair()
    with pytest.raises(InvalidTag): keywrap.ecies_unwrap(other, blob)                       # other user cannot unwrap
    t = dict(blob, context="model-2|alice")
    with pytest.raises(InvalidTag): keywrap.ecies_unwrap(priv, t)                           # context binding
    assert keywrap.ecies_wrap(pub, ck, "m")["ct"] != keywrap.ecies_wrap(pub, ck, "m")["ct"]  # fresh ephemeral each time

def test_escrow_wrap():
    ms, ck = cc.generate_key(), cc.generate_key()
    b = keywrap.escrow_wrap(ms, "m1", ck)
    assert keywrap.escrow_unwrap(ms, "m1", b) == ck
    with pytest.raises(InvalidTag): keywrap.escrow_unwrap(ms, "m2", b)
    with pytest.raises(InvalidTag): keywrap.escrow_unwrap(cc.generate_key(), "m1", b)

# ---------------- X.509 ----------------
def test_x509_chain_validation():
    ca_key, ca_cert = idn.create_self_signed_ca("Test CA")
    _, pub = idn.generate_ec_keypair()
    cert = idn.issue_developer_cert(ca_key, ca_cert, pub, "alice", role="developer")
    res = idn.verify_certificate_chain(cert, ca_cert)
    assert res["valid"], res
    # wrong CA
    other_key, other_ca = idn.create_self_signed_ca("Rogue CA")
    assert not idn.verify_certificate_chain(cert, other_ca)["valid"]
    rogue_cert = idn.issue_developer_cert(other_key, other_ca, pub, "alice")
    assert not idn.verify_certificate_chain(rogue_cert, ca_cert)["valid"]
    # expired / not yet valid
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=400)
    assert not idn.verify_certificate_chain(cert, ca_cert, now=future)["valid"]
    # revoked
    assert not idn.verify_certificate_chain(cert, ca_cert, revoked_serials={format(cert.serial_number, "x")})["valid"]
    # a CA cert is not an acceptable end-entity cert
    assert not idn.verify_certificate_chain(ca_cert, ca_cert)["valid"]
    # PEM round trip + summary
    again = idn.load_cert_pem(idn.cert_to_pem(cert))
    assert idn.cert_fingerprint_sha3(again) == idn.cert_fingerprint_sha3(cert)
    assert idn.cert_summary(cert)["commonName"] == "alice" and idn.cert_summary(cert)["role"] == "developer"

# ---------------- Merkle ----------------
def _chunks(n, size=64): return [os.urandom(size) for _ in range(n)]

@pytest.mark.parametrize("n", [1, 2, 3, 5, 8, 13, 100])
def test_merkle_every_chunk_proof_verifies(n):
    ch = _chunks(n); tree = mk.build_merkle_tree(ch); root = tree[-1][0].hex()
    assert root == mk.merkle_root(ch)
    for i, c in enumerate(ch):
        assert mk.verify_proof(c, mk.get_proof(tree, i), root), f"chunk {i} of {n}"

def test_merkle_detects_tampered_chunk_and_wrong_proof():
    ch = _chunks(10); tree = mk.build_merkle_tree(ch); root = tree[-1][0].hex()
    bad = bytearray(ch[4]); bad[0] ^= 1
    assert not mk.verify_proof(bytes(bad), mk.get_proof(tree, 4), root)
    assert not mk.verify_proof(ch[4], mk.get_proof(tree, 5), root)   # proof for a different leaf

def test_merkle_no_duplicate_leaf_second_preimage():
    a, b, c = _chunks(3)
    assert mk.merkle_root([a, b, c]) != mk.merkle_root([a, b, c, c])  # classic CVE-2012-2459 collision is gone

def test_merkle_domain_separation_leaf_vs_node():
    a, b = _chunks(2)
    forged_leaf = mk.leaf_hash(a) + mk.leaf_hash(b)              # an attacker presents an internal node as a "chunk"
    assert mk.merkle_root([forged_leaf]) != mk.merkle_root([a, b])

def test_merkle_root_changes_with_any_byte():
    data = os.urandom(100_000); chunks = list(mk.chunk_bytes(data, 4096)); r = mk.merkle_root(chunks)
    t = bytearray(data); t[77_777] ^= 1
    assert mk.merkle_root(list(mk.chunk_bytes(bytes(t), 4096))) != r
