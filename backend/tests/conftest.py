"""Shared test helpers for the account / subscription tests.

`make_chain()` builds a stand-in for Apple's certificate chain (root -> intermediate -> leaf)
with the same marker extensions Apple uses, so TransactionVerifier can be tested end to end
without real App Store data.
"""

import base64
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

from app.subscription import INTERMEDIATE_MARKER_OID, LEAF_MARKER_OID


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _cert(subject, issuer, key, signer_key, *, ca, marker=None, days=365, start=None):
    start = start or datetime.now(timezone.utc) - timedelta(days=1)
    b = (
        x509.CertificateBuilder()
        .subject_name(_name(subject))
        .issuer_name(_name(issuer))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if marker is not None:
        b = b.add_extension(x509.UnrecognizedExtension(marker, b"\x05\x00"), critical=False)
    return b.sign(signer_key, hashes.SHA256())


@dataclass
class Chain:
    root: x509.Certificate
    intermediate: x509.Certificate
    leaf: x509.Certificate
    leaf_key: ec.EllipticCurvePrivateKey

    def x5c(self, include_root: bool = False) -> list[str]:
        certs = [self.leaf, self.intermediate] + ([self.root] if include_root else [])
        return [base64.b64encode(c.public_bytes(Encoding.DER)).decode() for c in certs]


def make_chain(*, leaf_marker=LEAF_MARKER_OID, intermediate_marker=INTERMEDIATE_MARKER_OID,
               leaf_days=365, leaf_start=None) -> Chain:
    root_key, inter_key, leaf_key = (ec.generate_private_key(ec.SECP256R1()) for _ in range(3))
    root = _cert("Test Root", "Test Root", root_key, root_key, ca=True)
    inter = _cert("Test Intermediate", "Test Root", inter_key, root_key, ca=True, marker=intermediate_marker)
    leaf = _cert("Test Leaf", "Test Intermediate", leaf_key, inter_key, ca=False, marker=leaf_marker,
                 days=leaf_days, start=leaf_start)
    return Chain(root, inter, leaf, leaf_key)


def sign_transaction(chain: Chain, *, include_root=False, **overrides) -> str:
    """A StoreKit-style signed transaction (JWS, ES256, x5c header)."""
    claims = {
        "transactionId": "2000000000000002",
        "originalTransactionId": "2000000000000001",
        "bundleId": "com.libofu.yipath",
        "productId": "com.libofu.yipath.monthly",
        "type": "Auto-Renewable Subscription",
        "environment": "Sandbox",
        "expiresDate": int((time.time() + 30 * 86400) * 1000),
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, chain.leaf_key, algorithm="ES256", headers={"x5c": chain.x5c(include_root)})


@pytest.fixture
def chain() -> Chain:
    return make_chain()
