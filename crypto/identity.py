"""
identity.py
Identity & key management for the AI Model Marketplace.

Provides:
    - ECC (SECP256R1 / P-256) key-pair generation per user
    - ECDSA sign / verify (SHA3-256 digest) for model ownership proofs
    - ECDH + HKDF session/key derivation
    - A local X.509 certificate authority issuing identity certificates
    - Full certificate validation (signature, issuer, validity window, usage, revocation)
    - Key / certificate (de)serialization helpers
"""

import datetime
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.x509.oid import NameOID

from .crypto_core import sha3_256_hash

SIGN_HASH = hashes.SHA3_256          # ECDSA digest algorithm


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


# ---------- ECC key pairs ----------
def generate_ec_keypair():
    """Returns (private_key, public_key) on curve SECP256R1 (P-256)."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


def private_key_to_pem(private_key) -> bytes:
    return private_key.private_bytes(serialization.Encoding.PEM,
                                     serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption())


def load_private_key_pem(pem: bytes):
    return serialization.load_pem_private_key(pem, password=None)


def public_key_to_pem(public_key) -> bytes:
    return public_key.public_bytes(serialization.Encoding.PEM,
                                   serialization.PublicFormat.SubjectPublicKeyInfo)


def public_key_to_der(public_key) -> bytes:
    return public_key.public_bytes(serialization.Encoding.DER,
                                   serialization.PublicFormat.SubjectPublicKeyInfo)


def load_public_key_pem(pem):
    if isinstance(pem, str):
        pem = pem.encode()
    return serialization.load_pem_public_key(pem)


# ---------- ECDSA sign / verify ----------
def sign_data(private_key, data: bytes) -> bytes:
    """ECDSA over P-256 with SHA3-256 digest. Returns a DER-encoded signature."""
    return private_key.sign(data, ec.ECDSA(SIGN_HASH()))


def verify_signature(public_key, signature: bytes, data: bytes) -> bool:
    try:
        public_key.verify(signature, data, ec.ECDSA(SIGN_HASH()))
        return True
    except Exception:
        return False


# ---------- ECDH + HKDF ----------
def derive_session_key(shared_secret: bytes, salt: bytes = None, info: bytes = b"marketplace-session") -> bytes:
    """Derives a 32-byte session key from a shared secret via HKDF-SHA256."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(shared_secret)


def ecdh_shared_secret(my_private_key, peer_public_key) -> bytes:
    """Both parties compute the same secret; it is never transmitted."""
    return my_private_key.exchange(ec.ECDH(), peer_public_key)


def derive_model_encryption_key(my_private_key, peer_public_key, model_id: str) -> bytes:
    """Used by the CLI demos: ECDH + HKDF bound to a model id."""
    import os
    shared = ecdh_shared_secret(my_private_key, peer_public_key)
    return derive_session_key(shared, salt=b"\x00" * 32, info=model_id.encode())


# ---------- Local X.509 certificate authority ----------
def create_self_signed_ca(common_name: str = "Marketplace Root CA", valid_days: int = 3650):
    """Creates a root CA key pair + self-signed cert. Returns (ca_key, ca_cert)."""
    ca_key = ec.generate_private_key(ec.SECP256R1())
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AI Model Marketplace"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(issuer)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - datetime.timedelta(minutes=1))
        .not_valid_after(_now() + datetime.timedelta(days=valid_days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                     content_commitment=False, key_encipherment=False,
                                     data_encipherment=False, key_agreement=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    return ca_key, ca_cert


def issue_developer_cert(ca_key, ca_cert, developer_public_key, developer_name: str,
                         role: str = None, valid_days: int = 180):
    """CA issues a certificate binding a name (+role) to a public key."""
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, developer_name)]
    if role:
        attrs.insert(0, x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, role))
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name(attrs)).issuer_name(ca_cert.subject)
        .public_key(developer_public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - datetime.timedelta(minutes=1))
        .not_valid_after(_now() + datetime.timedelta(days=valid_days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_agreement=True,
                                     content_commitment=False, key_encipherment=False,
                                     data_encipherment=False, key_cert_sign=False, crl_sign=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    return cert


def cert_to_pem(cert) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def load_cert_pem(pem):
    if isinstance(pem, str):
        pem = pem.encode()
    return x509.load_pem_x509_certificate(pem)


def cert_fingerprint_sha3(cert) -> str:
    return sha3_256_hash(cert.public_bytes(serialization.Encoding.DER))


def cert_subject_cn(cert) -> str:
    return cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value


def cert_summary(cert) -> dict:
    ou = cert.subject.get_attributes_for_oid(NameOID.ORGANIZATIONAL_UNIT_NAME)
    return {
        "subject": cert.subject.rfc4514_string(),
        "commonName": cert_subject_cn(cert),
        "role": ou[0].value if ou else None,
        "issuer": cert.issuer.rfc4514_string(),
        "serial": format(cert.serial_number, "x"),
        "notBefore": cert.not_valid_before_utc.isoformat(),
        "notAfter": cert.not_valid_after_utc.isoformat(),
        "signatureAlgorithm": cert.signature_hash_algorithm.name + "withECDSA",
        "publicKeyAlgorithm": "ECDSA P-256",
        "fingerprintSha3_256": cert_fingerprint_sha3(cert),
    }


def verify_certificate(cert, ca_cert) -> bool:
    """Signature-only check (kept for the CLI demos). Use verify_certificate_chain for full validation."""
    try:
        ca_cert.public_key().verify(cert.signature, cert.tbs_certificate_bytes,
                                    ec.ECDSA(cert.signature_hash_algorithm))
        return True
    except Exception:
        return False


def verify_certificate_chain(cert, ca_cert, revoked_serials=(), now=None) -> dict:
    """
    Full validation of an end-entity certificate against the local CA.
    Returns {"valid": bool, "checks": [{"name","ok","detail"}], "reason": str|None}.
    """
    now = now or _now()
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("issuer matches CA subject", cert.issuer == ca_cert.subject,
        f"issuer={cert.issuer.rfc4514_string()}")
    add("CA signature on certificate", verify_certificate(cert, ca_cert),
        f"{cert.signature_hash_algorithm.name} with ECDSA, verified using the CA public key")
    add("within validity period", cert.not_valid_before_utc <= now <= cert.not_valid_after_utc,
        f"{cert.not_valid_before_utc.isoformat()} -> {cert.not_valid_after_utc.isoformat()}")
    try:
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
        add("end-entity (not a CA)", not bc.ca, f"basicConstraints ca={bc.ca}")
    except x509.ExtensionNotFound:
        add("end-entity (not a CA)", False, "BasicConstraints extension missing")
    try:
        ku = cert.extensions.get_extension_for_class(x509.KeyUsage).value
        add("key usage allows signing", ku.digital_signature, f"digitalSignature={ku.digital_signature}")
    except x509.ExtensionNotFound:
        add("key usage allows signing", False, "KeyUsage extension missing")
    revoked = format(cert.serial_number, "x") in set(revoked_serials)
    add("not revoked", not revoked, f"serial={format(cert.serial_number, 'x')}")

    failed = [c["name"] for c in checks if not c["ok"]]
    return {"valid": not failed, "checks": checks, "reason": ("failed: " + ", ".join(failed)) if failed else None}
