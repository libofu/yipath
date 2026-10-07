"""The App Store Server Notifications webhook: renewals, expiry, refunds."""

import sqlite3
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from tests.conftest import make_chain, sign_notification, sign_transaction

from app.config import Settings
from app.entitlement import compute_entitlement
from app.main import app, get_settings, get_store, get_tx_verifier
from app.store import Store
from app.subscription import TransactionError, TransactionVerifier

SETTINGS = Settings()
DAY = 86400


def ms(days_from_now: float) -> int:
    return int((time.time() + days_from_now * DAY) * 1000)


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    chain = make_chain()
    verifier = TransactionVerifier(SETTINGS, root_cert=chain.root)
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    app.dependency_overrides[get_tx_verifier] = lambda: verifier
    client = TestClient(app)

    def subscribe(expires_in_days=10, **over):
        """A user who has a verified subscription on file."""
        uid, _ = store.create_user()
        store.save_subscription(uid, verifier.verify(sign_transaction(chain, expiresDate=ms(expires_in_days), **over)))
        return uid

    def notify(kind, *, inner=None, **kw):
        payload = sign_notification(chain, kind, transaction=inner, **kw)
        return client.post("/apple/notifications", json={"signedPayload": payload})

    yield type("Env", (), dict(client=client, store=store, chain=chain, subscribe=subscribe, notify=notify, verifier=verifier))
    app.dependency_overrides.clear()


def status(env, uid):
    return compute_entitlement(env.store, SETTINGS, uid)


def stored(env, uid):
    return env.store.get_subscription(uid)   # (product_id, expires_at, revoked)


def tx(env, **over):
    return sign_transaction(env.chain, **over)


# --- the happy paths -----------------------------------------------------------------------------

def test_renewal_extends_the_subscription(env):
    uid = env.subscribe(expires_in_days=1)
    before = stored(env, uid)[1]
    r = env.notify("DID_RENEW", inner=tx(env, expiresDate=ms(31)))
    assert r.status_code == 200 and r.json() == {"handled": True}
    assert stored(env, uid)[1] > before
    assert status(env, uid).status == "subscribed"


def test_refund_ends_access_immediately(env):
    uid = env.subscribe(expires_in_days=20)
    with sqlite3.connect(env.store.path) as c:   # long past the trial, so only the subscription grants access
        c.execute("UPDATE users SET created_at = '2020-01-01 00:00:00'")
    assert status(env, uid).status == "subscribed"

    r = env.notify("REFUND", inner=tx(env, expiresDate=ms(20), revocationDate=ms(0)))
    assert r.status_code == 200 and r.json() == {"handled": True}
    assert stored(env, uid)[2] is True
    assert status(env, uid).status == "expired"      # 20 paid days remained, but a refund cancels them


def test_refund_is_honoured_even_if_apple_omits_the_revocation_date(env):
    uid = env.subscribe(expires_in_days=20)
    env.notify("REFUND", inner=tx(env, expiresDate=ms(20)))     # no revocationDate in the transaction
    assert stored(env, uid)[2] is True
    env.notify("REVOKE", inner=tx(env, expiresDate=ms(20)))     # family-sharing revoke behaves the same
    assert stored(env, uid)[2] is True


def test_expiry_notification_leaves_the_user_without_access(env, tmp_path):
    uid = env.subscribe(expires_in_days=5)
    with sqlite3.connect(env.store.path) as c:   # the user has been around longer than the trial
        c.execute("UPDATE users SET created_at = '2020-01-01 00:00:00'")
    later = datetime.now(timezone.utc).replace(year=2099)
    r = env.notify("EXPIRED", inner=tx(env, expiresDate=ms(5)), subtype="VOLUNTARY")
    assert r.status_code == 200
    assert compute_entitlement(env.store, SETTINGS, uid, now=later).status == "expired"


# --- ordering and idempotence -------------------------------------------------------------------------

def test_an_older_notification_arriving_late_cannot_shorten_the_subscription(env):
    uid = env.subscribe(expires_in_days=30)
    longer = stored(env, uid)[1]
    env.notify("DID_CHANGE_RENEWAL_STATUS", inner=tx(env, expiresDate=ms(2)))
    assert stored(env, uid)[1] == longer


def test_a_refunded_subscription_stays_refunded(env):
    uid = env.subscribe(expires_in_days=10)
    env.notify("REFUND", inner=tx(env, expiresDate=ms(10), revocationDate=ms(0)))
    env.notify("DID_RENEW", inner=tx(env, expiresDate=ms(40)))   # a stale/late renewal must not undo it
    assert stored(env, uid)[2] is True


def test_the_same_notification_twice_is_harmless(env):
    uid = env.subscribe(expires_in_days=1)
    inner = tx(env, expiresDate=ms(31))
    first = env.notify("DID_RENEW", inner=inner).json()
    snapshot = stored(env, uid)
    second = env.notify("DID_RENEW", inner=inner).json()
    assert first == second == {"handled": True}
    assert stored(env, uid) == snapshot


# --- things that are not an error ------------------------------------------------------------------------

def test_a_subscription_we_never_saw_is_ignored_but_acknowledged(env):
    r = env.notify("DID_RENEW", inner=tx(env, originalTransactionId="999999"))
    assert r.status_code == 200 and r.json() == {"handled": False}
    with sqlite3.connect(env.store.path) as c:
        assert c.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0] == 0


def test_apples_test_notification_is_acknowledged(env):
    r = env.notify("TEST")
    assert r.status_code == 200 and r.json() == {"handled": False}


# --- forgery and bad input -------------------------------------------------------------------------------------

def test_a_notification_signed_by_someone_else_is_rejected(env):
    uid = env.subscribe(expires_in_days=20)
    impostor = make_chain()
    forged = sign_notification(impostor, "REFUND", transaction=sign_transaction(impostor, revocationDate=ms(0)))
    assert env.client.post("/apple/notifications", json={"signedPayload": forged}).status_code == 400
    assert stored(env, uid)[2] is False     # nothing changed


def test_a_real_notification_wrapping_a_forged_transaction_is_rejected(env):
    uid = env.subscribe(expires_in_days=20)
    forged_inner = sign_transaction(make_chain(), revocationDate=ms(0))
    r = env.notify("REFUND", inner=forged_inner)
    assert r.status_code == 400
    assert stored(env, uid)[2] is False


@pytest.mark.parametrize("kwargs", [
    dict(bundle_id="com.other.app"),
    dict(environment="Xcode"),          # Apple never sends local test transactions
    dict(environment="Staging"),
])
def test_wrong_app_or_environment_is_rejected(env, kwargs):
    assert env.notify("DID_RENEW", inner=tx(env), **kwargs).status_code == 400


def test_local_storekit_flag_does_not_open_the_webhook(env):
    dev = TransactionVerifier(Settings(storekit_local=True), root_cert=env.chain.root)
    payload = sign_notification(env.chain, "DID_RENEW", transaction=tx(env, environment="Xcode"), environment="Xcode")
    with pytest.raises(TransactionError, match="local StoreKit"):
        dev.verify_notification(payload)


def test_garbage_and_missing_fields_are_rejected(env):
    for junk in ["", "abc", "a.b.c"]:
        assert env.client.post("/apple/notifications", json={"signedPayload": junk}).status_code == 400
    assert env.client.post("/apple/notifications", json={}).status_code == 422
    assert env.notify("", inner=tx(env)).status_code == 400    # a notification with no type


def test_tampering_with_the_payload_breaks_the_signature(env):
    payload = sign_notification(env.chain, "DID_RENEW", transaction=tx(env))
    head, body, sig = payload.split(".")
    forged = body[:-4] + ("AAAA" if body[-4:] != "AAAA" else "BBBB")
    assert env.client.post("/apple/notifications", json={"signedPayload": f"{head}.{forged}.{sig}"}).status_code == 400


def test_the_webhook_needs_no_login_but_the_app_endpoints_still_do(env):
    assert env.notify("TEST").status_code == 200       # Apple has no token to send
    assert env.client.get("/subscription").status_code == 401
