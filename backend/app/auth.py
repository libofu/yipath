"""Sign in with Apple: verify the identity token the iOS app gets from Apple.

The app sends us the JWT (`identityToken`). We check, using Apple's public keys, that
Apple signed it, that it is meant for this app (audience), that it hasn't expired, and
that it carries the nonce this sign-in attempt used (so an old token can't be replayed).
The token's `sub` is the user's stable Apple ID for this app; that is what we key accounts on.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections.abc import Callable

import jwt

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"


class AuthError(Exception):
    """The identity token is not acceptable."""


def fetch_apple_jwks() -> list[dict]:
    import httpx

    response = httpx.get(APPLE_JWKS_URL, timeout=10)
    response.raise_for_status()
    return response.json()["keys"]


class AppleVerifier:
    def __init__(
        self,
        audience: str,
        jwks_fetcher: Callable[[], list[dict]] = fetch_apple_jwks,
        ttl_seconds: int = 3600,
        clock: Callable[[], float] = time.time,
    ):
        self.audience = audience
        self._fetch = jwks_fetcher
        self._ttl = ttl_seconds
        self._clock = clock
        self._keys: dict[str, dict] = {}
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def _key_for(self, kid: str) -> dict:
        with self._lock:
            stale = self._clock() - self._fetched_at > self._ttl
            if stale or kid not in self._keys:
                # Refresh on expiry, and once more for an unknown kid in case Apple rotated keys.
                try:
                    self._keys = {k["kid"]: k for k in self._fetch()}
                except Exception as e:  # network or parse problem
                    raise AuthError("could not load Apple's signing keys") from e
                self._fetched_at = self._clock()
            if kid not in self._keys:
                raise AuthError("unknown signing key")
            return self._keys[kid]

    def verify(self, identity_token: str, raw_nonce: str) -> str:
        """Returns Apple's stable user id (`sub`), or raises AuthError."""
        if not raw_nonce:
            raise AuthError("nonce is required")
        try:
            header = jwt.get_unverified_header(identity_token)
            if header.get("alg") != "RS256":
                raise AuthError("unexpected signing algorithm")
            key = jwt.PyJWK.from_dict(self._key_for(header.get("kid", ""))).key
            claims = jwt.decode(
                identity_token,
                key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=APPLE_ISSUER,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except AuthError:
            raise
        except jwt.PyJWTError as e:
            raise AuthError(f"invalid identity token: {e}") from e

        expected = hashlib.sha256(raw_nonce.encode()).hexdigest()
        if not hmac.compare_digest(str(claims.get("nonce", "")), expected):
            raise AuthError("nonce does not match")
        return str(claims["sub"])
