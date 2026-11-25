"""
parties.py
Sets up the three identities the demo needs: the Marketplace CA, a
Developer, and a Buyer. Each person gets their own EC key pair and an
X.509 certificate issued by the CA - this is what role-based access
and authenticity checks are actually checked against later, instead of
trusting bare public keys.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from crypto.identity import (
    generate_ec_keypair, create_self_signed_ca, issue_developer_cert,
)


def setup_marketplace():
    ca_key, ca_cert = create_self_signed_ca("Marketplace Root CA")

    dev_priv, dev_pub = generate_ec_keypair()
    dev_cert = issue_developer_cert(ca_key, ca_cert, dev_pub, "Sriya (Developer)")

    buyer_priv, buyer_pub = generate_ec_keypair()
    buyer_cert = issue_developer_cert(ca_key, ca_cert, buyer_pub, "Buyer-001")

    return {
        "ca_key": ca_key, "ca_cert": ca_cert,
        "dev_priv": dev_priv, "dev_pub": dev_pub, "dev_cert": dev_cert,
        "buyer_priv": buyer_priv, "buyer_pub": buyer_pub, "buyer_cert": buyer_cert,
    }
