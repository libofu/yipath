"""End-to-end tests of sign-in, profile, subscription gating and account deletion over HTTP."""

import hashlib
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from tests.conftest import make_chain, sign_transaction
from tests.test_auth import AUD, NONCE, _jwk, apple_key, token as apple_token  # noqa: F401  (fixture reuse)

from app.advice.service import AdviceService
from app.auth import AppleVerifier
from app.config import Settings
from app.main import app, get_apple_verifier, get_service, get_settings, get_store, get_tx_verifier
from app.store import Store
from app.subscription import TransactionVerifier
from tests.test_advice import FakeLlm

PROFILE = {"birth_date": "2000-01-01", "birth_hour": 12, "mbti": "INFJ"}


@pytest.fixture
def env(tmp_path, apple_key):
    store = Store(tmp_path / "t.sqlite3")
    llm = FakeLlm()
    chain = make_chain()
    settings = Settings()
    state = {"settings": settings}
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_settings] = lambda: state["settings"]
    app.dependency_overrides[get_service] = lambda: AdviceService(store, llm)
    app.dependency_overrides[get_apple_verifier] = lambda: AppleVerifier(AUD, jwks_fetcher=lambda: [_jwk(apple_key, "k1")])
    app.dependency_overrides[get_tx_verifier] = lambda: TransactionVerifier(settings, root_cert=chain.root)
    client = TestClient(app)
    yield type("Env", (), dict(client=client, store=store, llm=llm, chain=chain, key=apple_key, state=state))
    app.dependency_overrides.clear()


def sign_in(env, sub="001.apple-user"):
    r = env.client.post("/auth/apple", json={"identity_token": apple_token(env.key, sub=sub), "nonce": NONCE})
    assert r.status_code == 200, r.text
    return r.json()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def age(env, user_id, days):
    created = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(env.store.path) as c:
        c.execute("UPDATE users SET created_at = ? WHERE id = ?", (created, user_id))


# --- sign in ------------------------------------------------------------------------------------

def test_sign_in_creates_an_account_without_a_profile(env):
    s = sign_in(env)
    assert s["has_profile"] is False and s["token"]
    assert env.client.get("/profile", headers=auth(s["token"])).status_code == 404


def test_signing_in_again_finds_the_same_account_and_profile(env):
    first = sign_in(env)
    env.client.put("/profile", json=PROFILE, headers=auth(first["token"]))
    second = sign_in(env)
    assert second["user_id"] == first["user_id"] and second["has_profile"] is True
    assert second["token"] != first["token"]            # a fresh session each time
    got = env.client.get("/profile", headers=auth(second["token"]))
    assert got.status_code == 200 and got.json()["birth_date"] == "2000-01-01"
    assert env.client.get("/profile", headers=auth(first["token"])).status_code == 200   # old session still valid


def test_different_apple_ids_are_different_accounts(env):
    assert sign_in(env, "a")["user_id"] != sign_in(env, "b")["user_id"]


def test_bad_identity_tokens_are_rejected(env):
    for body in [
        {"identity_token": "garbage", "nonce": NONCE},
        {"identity_token": apple_token(env.key), "nonce": "wrong-nonce"},
        {"identity_token": apple_token(env.key, aud="com.other.app"), "nonce": NONCE},
    ]:
        assert env.client.post("/auth/apple", json=body).status_code == 401


# --- the paywall gate -------------------------------------------------------------------------------

def test_readings_need_a_profile_first(env):
    s = sign_in(env)
    assert env.client.get("/reading/today", headers=auth(s["token"])).status_code == 409


def test_trial_user_can_read_then_gets_402_when_it_ends(env):
    s = sign_in(env)
    h = auth(s["token"])
    env.client.put("/profile", json=PROFILE, headers=h)
    assert env.client.get("/reading/today", params={"date": "2026-10-07"}, headers=h).status_code == 200
    assert env.client.get("/subscription", headers=h).json()["status"] == "trial"
    age(env, s["user_id"], 4)
    assert env.client.get("/reading/today", params={"date": "2026-10-07"}, headers=h).status_code == 402
    assert env.client.get("/reading/week", headers=h).status_code == 402
    assert env.client.get("/subscription", headers=h).json()["status"] == "expired"


def test_verified_purchase_unlocks_readings(env):
    s = sign_in(env)
    h = auth(s["token"])
    env.client.put("/profile", json=PROFILE, headers=h)
    age(env, s["user_id"], 10)
    assert env.client.get("/reading/today", params={"date": "2026-10-07"}, headers=h).status_code == 402

    r = env.client.post("/subscription/verify", json={"signed_transaction": sign_transaction(env.chain)}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "subscribed"
    assert r.json()["product_id"] == "com.libofu.yipath.monthly"
    assert env.client.get("/reading/today", params={"date": "2026-10-07"}, headers=h).status_code == 200


def test_forged_or_foreign_transactions_are_rejected(env):
    s = sign_in(env)
    h = auth(s["token"])
    age(env, s["user_id"], 10)
    impostor = make_chain()
    for jws in [sign_transaction(impostor), sign_transaction(env.chain, bundleId="com.other.app"), "junk"]:
        assert env.client.post("/subscription/verify", json={"signed_transaction": jws}, headers=h).status_code == 400
    assert env.client.get("/subscription", headers=h).json()["status"] == "expired"


def test_revoked_purchase_does_not_unlock(env):
    s = sign_in(env)
    h = auth(s["token"])
    age(env, s["user_id"], 10)
    jws = sign_transaction(env.chain, revocationDate=int(time.time() * 1000))
    r = env.client.post("/subscription/verify", json={"signed_transaction": jws}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "expired"


def test_a_subscription_cannot_be_shared_between_accounts(env):
    a, b = sign_in(env, "a"), sign_in(env, "b")
    jws = sign_transaction(env.chain)
    assert env.client.post("/subscription/verify", json={"signed_transaction": jws}, headers=auth(a["token"])).status_code == 200
    assert env.client.post("/subscription/verify", json={"signed_transaction": jws}, headers=auth(b["token"])).status_code == 409


def test_subscription_endpoints_require_login(env):
    assert env.client.get("/subscription").status_code == 401
    assert env.client.post("/subscription/verify", json={"signed_transaction": "x"}).status_code == 401


# --- deleting the account ---------------------------------------------------------------------------------

def test_delete_account_erases_everything(env):
    s = sign_in(env)
    h = auth(s["token"])
    env.client.put("/profile", json=PROFILE, headers=h)
    env.client.get("/reading/today", params={"date": "2026-10-07"}, headers=h)
    env.client.post("/subscription/verify", json={"signed_transaction": sign_transaction(env.chain)}, headers=h)

    assert env.client.delete("/account", headers=h).status_code == 204
    assert env.client.get("/profile", headers=h).status_code == 401      # the session is gone too
    with sqlite3.connect(env.store.path) as c:
        for table in ("users", "sessions", "subscriptions", "readings"):
            assert c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    # the same Apple ID can come back and starts fresh
    again = sign_in(env)
    assert again["has_profile"] is False and again["user_id"] != s["user_id"]


# --- developer shortcut stays out of production -----------------------------------------------------------------

def test_anonymous_signup_works_in_dev_and_is_hidden_in_production(env):
    assert env.client.post("/profile", json=PROFILE).status_code == 200
    env.state["settings"] = Settings(env="production")
    assert env.client.post("/profile", json=PROFILE).status_code == 404


# --- database migration ------------------------------------------------------------------------------------------

def test_old_dev_database_is_migrated(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as c:
        c.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, token_hash TEXT NOT NULL UNIQUE,
                                profile_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        """)
        token = "old-token"
        c.execute("INSERT INTO users (token_hash, profile_json) VALUES (?, ?)",
                  (hashlib.sha256(token.encode()).hexdigest(), '{"birth_date":"2000-01-01","birth_hour":12,"birth_minute":0,"mbti":null}'))
    store = Store(path)
    uid, profile = store.user_by_token(token)
    assert uid == 1 and profile.birth_date.isoformat() == "2000-01-01"
    assert store.login_apple("someone")[0] == 2        # new tables work alongside the migrated user
