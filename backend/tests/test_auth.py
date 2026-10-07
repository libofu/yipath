import hashlib
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import APPLE_ISSUER, AppleVerifier, AuthError

AUD = "com.libofu.yipath"
NONCE = "raw-nonce-123"


def _jwk(private_key, kid: str) -> dict:
    d = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    d.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return d


@pytest.fixture(scope="module")
def apple_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(key, *, kid="k1", aud=AUD, iss=APPLE_ISSUER, sub="001234.abc", nonce=NONCE, exp_in=600, **extra):
    claims = {"iss": iss, "aud": aud, "sub": sub, "iat": int(time.time()) - 5, "exp": int(time.time()) + exp_in}
    if nonce is not None:
        claims["nonce"] = hashlib.sha256(nonce.encode()).hexdigest()
    claims.update(extra)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def verifier(key, kid="k1", fetches=None):
    def fetch():
        if fetches is not None:
            fetches.append(1)
        return [_jwk(key, kid)]
    return AppleVerifier(AUD, jwks_fetcher=fetch)


def test_valid_token_returns_the_apple_user_id(apple_key):
    assert verifier(apple_key).verify(token(apple_key), NONCE) == "001234.abc"


@pytest.mark.parametrize("bad", [
    dict(aud="com.someone.else"),
    dict(iss="https://evil.example"),
    dict(exp_in=-10),
    dict(nonce="a-different-nonce"),
    dict(nonce=None),
])
def test_rejects_bad_claims(apple_key, bad):
    with pytest.raises(AuthError):
        verifier(apple_key).verify(token(apple_key, **bad), NONCE)


def test_rejects_missing_request_nonce(apple_key):
    with pytest.raises(AuthError):
        verifier(apple_key).verify(token(apple_key), "")


def test_rejects_token_signed_by_someone_else(apple_key):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(AuthError):
        verifier(apple_key).verify(token(other), NONCE)


def test_rejects_unknown_key_id_and_garbage(apple_key):
    with pytest.raises(AuthError):
        verifier(apple_key).verify(token(apple_key, kid="rotated-away"), NONCE)
    with pytest.raises(AuthError):
        verifier(apple_key).verify("not.a.jwt", NONCE)


def test_rejects_alg_none_and_hs256_downgrades(apple_key):
    forged_none = jwt.encode({"iss": APPLE_ISSUER, "aud": AUD, "sub": "x", "iat": 1, "exp": 4102444800}, key=None, algorithm="none")
    with pytest.raises(AuthError):
        verifier(apple_key).verify(forged_none, NONCE)


def test_keys_are_cached_and_refetched_for_a_new_kid(apple_key):
    fetches = []
    v = verifier(apple_key, fetches=fetches)
    v.verify(token(apple_key), NONCE)
    v.verify(token(apple_key), NONCE)
    assert len(fetches) == 1                      # second call used the cache
    with pytest.raises(AuthError):
        v.verify(token(apple_key, kid="new-kid"), NONCE)
    assert len(fetches) == 2                      # unknown kid triggered one refresh


def test_apple_being_unreachable_is_an_auth_error(apple_key):
    def boom():
        raise OSError("network down")
    with pytest.raises(AuthError):
        AppleVerifier(AUD, jwks_fetcher=boom).verify(token(apple_key), NONCE)
