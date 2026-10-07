"""Verify an App Store transaction (a StoreKit 2 "signed transaction", a JWS) and decide
what it entitles the user to.

The app sends us the JWS string StoreKit gives it. We never trust the app's say-so about
what was bought; instead we check that *Apple* signed it:

  1. The JWS header carries a certificate chain (`x5c`): leaf -> intermediate (-> root).
  2. The leaf must be issued by the intermediate, and the intermediate by Apple Root CA - G3,
     whose certificate is pinned in this repo (app/data/AppleRootCA-G3.cer) and checked by
     SHA-256 fingerprint. Both certificates must carry Apple's marker extensions, so that
     some other certificate Apple issued (for developers, Apple Pay...) can't be used to forge one.
  3. The JWS signature must verify with the leaf's public key.
  4. The signed claims must be for this app (bundleId), one of our products, and unrevoked.

Transactions made with Xcode's *local* StoreKit test file (environment "Xcode") are signed
by a throwaway local certificate. They are accepted only when `settings.storekit_local`
is on (dev), and then only the signature is checked.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import jwt
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509 import ObjectIdentifier

from .config import Settings

ROOT_CERT_PATH = Path(__file__).resolve().parent / "data" / "AppleRootCA-G3.cer"
# SHA-256 fingerprint Apple publishes for "Apple Root CA - G3".
APPLE_ROOT_SHA256 = "63343abfb89a6a03ebb57e9b3f5fa7be7c4f5c756f3017b3a8c488c3653e9179"

# Marker extensions that Apple puts on the certificates used to sign App Store data.
# NOTE: taken from Apple's open-source app-store-server-library; they could only be checked
# against our own test chain here, so confirm with a real sandbox purchase before launch.
LEAF_MARKER_OID = ObjectIdentifier("1.2.840.113635.100.6.11.1")
INTERMEDIATE_MARKER_OID = ObjectIdentifier("1.2.840.113635.100.6.2.1")

ALLOWED_ENVIRONMENTS = {"Production", "Sandbox"}
LOCAL_ENVIRONMENT = "Xcode"


class TransactionError(Exception):
    """The signed transaction is not acceptable."""


@dataclass(frozen=True)
class Transaction:
    original_transaction_id: str
    transaction_id: str
    product_id: str
    expires_at: datetime   # timezone-aware UTC
    environment: str
    revoked: bool


def load_pinned_root() -> x509.Certificate:
    der = ROOT_CERT_PATH.read_bytes()
    if hashlib.sha256(der).hexdigest() != APPLE_ROOT_SHA256:
        raise RuntimeError("AppleRootCA-G3.cer does not match Apple's published fingerprint")
    return x509.load_der_x509_certificate(der)


def _fingerprint(cert: x509.Certificate) -> str:
    return hashlib.sha256(cert.public_bytes(Encoding.DER)).hexdigest()


def _has_extension(cert: x509.Certificate, oid: ObjectIdentifier) -> bool:
    try:
        cert.extensions.get_extension_for_oid(oid)
        return True
    except x509.ExtensionNotFound:
        return False


class TransactionVerifier:
    def __init__(
        self,
        settings: Settings,
        root_cert: x509.Certificate | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.settings = settings
        self._root = root_cert  # loaded lazily; tests inject their own root
        self._clock = clock

    @property
    def root(self) -> x509.Certificate:
        if self._root is None:
            self._root = load_pinned_root()
        return self._root

    # --- public ---------------------------------------------------------------------------
    def verify(self, signed_transaction: str) -> Transaction:
        try:
            header = jwt.get_unverified_header(signed_transaction)
            unverified = jwt.decode(signed_transaction, options={"verify_signature": False})
        except jwt.PyJWTError as e:
            raise TransactionError(f"not a valid JWS: {e}") from e
        if header.get("alg") != "ES256":
            raise TransactionError("unexpected signing algorithm")

        try:
            certs = [x509.load_der_x509_certificate(base64.b64decode(c)) for c in header.get("x5c", [])]
        except Exception as e:
            raise TransactionError("unreadable certificate chain") from e
        if len(certs) < 1:
            raise TransactionError("missing certificate chain")

        environment = unverified.get("environment")
        if environment == LOCAL_ENVIRONMENT:
            if not self.settings.storekit_local:
                raise TransactionError("local StoreKit test transactions are not accepted")
        elif environment in ALLOWED_ENVIRONMENTS:
            self._verify_chain(certs)
        else:
            raise TransactionError(f"unknown environment: {environment!r}")

        try:
            claims = jwt.decode(
                signed_transaction,
                certs[0].public_key(),
                algorithms=["ES256"],
                options={"verify_exp": False, "verify_iat": False, "verify_nbf": False, "verify_aud": False},
            )
        except (jwt.PyJWTError, InvalidSignature) as e:
            raise TransactionError(f"signature check failed: {e}") from e
        return self._claims_to_transaction(claims)

    # --- internals --------------------------------------------------------------------------
    def _verify_chain(self, certs: list[x509.Certificate]) -> None:
        if len(certs) < 2:
            raise TransactionError("certificate chain too short")
        leaf, intermediate = certs[0], certs[1]
        now = self._clock()
        try:
            leaf.verify_directly_issued_by(intermediate)
            intermediate.verify_directly_issued_by(self.root)
        except (ValueError, TypeError, InvalidSignature) as e:
            raise TransactionError("certificate chain is not issued by Apple") from e
        if len(certs) > 2 and _fingerprint(certs[2]) != _fingerprint(self.root):
            raise TransactionError("unexpected root certificate")
        for cert in (leaf, intermediate):
            if not (cert.not_valid_before_utc <= now <= cert.not_valid_after_utc):
                raise TransactionError("certificate is expired or not yet valid")
        if not _has_extension(leaf, LEAF_MARKER_OID) or not _has_extension(intermediate, INTERMEDIATE_MARKER_OID):
            raise TransactionError("certificate is not an App Store signing certificate")

    def _claims_to_transaction(self, claims: dict) -> Transaction:
        if claims.get("bundleId") != self.settings.bundle_id:
            raise TransactionError("transaction is for a different app")
        product_id = claims.get("productId")
        if product_id not in self.settings.product_ids:
            raise TransactionError("unknown product")
        expires = claims.get("expiresDate")
        if not isinstance(expires, (int, float)):
            raise TransactionError("transaction has no expiry (not a subscription)")
        raw_id = claims.get("originalTransactionId")
        original_id = "" if raw_id is None else str(raw_id)   # note: "0" and 0 are real ids in Xcode tests
        if not original_id:
            raise TransactionError("transaction has no originalTransactionId")
        return Transaction(
            original_transaction_id=original_id,
            transaction_id=str(claims.get("transactionId", "")),
            product_id=product_id,
            expires_at=datetime.fromtimestamp(expires / 1000, tz=timezone.utc),
            environment=claims.get("environment", ""),
            revoked=claims.get("revocationDate") is not None,
        )
