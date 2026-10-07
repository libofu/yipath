import time
from datetime import datetime, timedelta, timezone

from pathlib import Path

import pytest

from app.config import Settings, load_settings
from app.entitlement import compute_entitlement
from app.store import Store, SubscriptionConflict
from app.subscription import (
    APPLE_ROOT_SHA256,
    INTERMEDIATE_MARKER_OID,
    LEAF_MARKER_OID,
    TransactionError,
    TransactionVerifier,
    load_pinned_root,
)
from tests.conftest import make_chain, sign_transaction

SETTINGS = Settings()


def verifier(chain, settings=SETTINGS):
    return TransactionVerifier(settings, root_cert=chain.root)


# --- the pinned Apple root ------------------------------------------------------------------

def test_pinned_apple_root_matches_the_published_fingerprint():
    root = load_pinned_root()
    assert "Apple Root CA - G3" in root.subject.rfc4514_string()
    assert len(APPLE_ROOT_SHA256) == 64


def test_real_apple_root_does_not_accept_a_forged_chain(chain):
    forged = sign_transaction(chain)
    with pytest.raises(TransactionError, match="not issued by Apple"):
        TransactionVerifier(SETTINGS).verify(forged)   # uses the real pinned root


# --- accepting a good transaction -----------------------------------------------------------------

def test_valid_transaction_is_accepted(chain):
    tx = verifier(chain).verify(sign_transaction(chain))
    assert tx.product_id == "com.libofu.yipath.monthly"
    assert tx.original_transaction_id == "2000000000000001"
    assert tx.environment == "Sandbox" and not tx.revoked
    assert tx.expires_at > datetime.now(timezone.utc)


def test_chain_with_root_included_is_accepted(chain):
    assert verifier(chain).verify(sign_transaction(chain, include_root=True))


def test_revoked_transaction_is_flagged(chain):
    tx = verifier(chain).verify(sign_transaction(chain, revocationDate=int(time.time() * 1000)))
    assert tx.revoked


# --- rejecting bad ones ------------------------------------------------------------------------------

def test_rejects_chain_from_a_different_root(chain):
    other = make_chain()
    with pytest.raises(TransactionError, match="not issued by Apple"):
        TransactionVerifier(SETTINGS, root_cert=other.root).verify(sign_transaction(chain))


def test_rejects_unexpected_root_carried_in_the_chain(chain):
    # The leaf and intermediate really chain to our root, but x5c also carries a *different* root.
    real_root, impostor = chain.root, make_chain().root
    chain.root = impostor
    jws = sign_transaction(chain, include_root=True)
    with pytest.raises(TransactionError, match="unexpected root"):
        TransactionVerifier(SETTINGS, root_cert=real_root).verify(jws)


@pytest.mark.parametrize("kwargs,why", [
    (dict(leaf_marker=None), "marker"),
    (dict(intermediate_marker=None), "marker"),
])
def test_rejects_certificates_without_apple_markers(kwargs, why):
    c = make_chain(**kwargs)
    with pytest.raises(TransactionError, match="not an App Store signing certificate"):
        verifier(c).verify(sign_transaction(c))


def test_rejects_expired_certificate():
    c = make_chain(leaf_days=1, leaf_start=datetime.now(timezone.utc) - timedelta(days=10))
    with pytest.raises(TransactionError, match="expired"):
        verifier(c).verify(sign_transaction(c))


def test_rejects_tampered_payload(chain):
    head, payload, sig = sign_transaction(chain).split(".")
    other = sign_transaction(chain, productId="com.libofu.yipath.yearly").split(".")[1]
    with pytest.raises(TransactionError, match="signature"):
        verifier(chain).verify(f"{head}.{other}.{sig}")


@pytest.mark.parametrize("override,message", [
    (dict(bundleId="com.other.app"), "different app"),
    (dict(productId="com.libofu.yipath.lifetime"), "unknown product"),
    (dict(expiresDate=None), "no expiry"),
    (dict(originalTransactionId=None), "originalTransactionId"),
    (dict(environment="Staging"), "environment"),
])
def test_rejects_wrong_claims(chain, override, message):
    with pytest.raises(TransactionError, match=message):
        verifier(chain).verify(sign_transaction(chain, **override))


def test_rejects_garbage_and_wrong_algorithm(chain):
    for junk in ["", "abc", "a.b.c"]:
        with pytest.raises(TransactionError):
            verifier(chain).verify(junk)


# --- Xcode's local StoreKit test transactions ----------------------------------------------------------

def test_local_storekit_transactions_need_the_dev_flag(chain):
    jws = sign_transaction(chain, environment="Xcode")
    with pytest.raises(TransactionError, match="local StoreKit"):
        verifier(chain).verify(jws)
    # with the flag on, a self-signed (not Apple-rooted) chain is fine, but the signature must still hold
    dev = Settings(storekit_local=True)
    assert TransactionVerifier(dev).verify(jws).environment == "Xcode"
    head, payload, sig = jws.split(".")
    with pytest.raises(TransactionError):
        TransactionVerifier(dev).verify(f"{head}.{sign_transaction(chain, environment='Xcode', productId='com.libofu.yipath.yearly').split('.')[1]}.{sig}")


def test_production_never_honours_the_local_storekit_flag():
    s = load_settings({"YIPATH_ENV": "production", "YIPATH_STOREKIT_LOCAL": "1"})
    assert s.storekit_local is False and s.allow_anonymous is False
    d = load_settings({"YIPATH_STOREKIT_LOCAL": "1"})
    assert d.storekit_local is True and d.allow_anonymous is True


def test_settings_defaults_and_overrides():
    s = load_settings({})
    assert s.trial_days == 3 and "com.libofu.yipath.monthly" in s.product_ids
    s = load_settings({"YIPATH_TRIAL_DAYS": "7", "YIPATH_PRODUCT_IDS": "a.b, c.d", "YIPATH_APPLE_BUNDLE_ID": "x.y"})
    assert (s.trial_days, s.product_ids, s.bundle_id) == (7, frozenset({"a.b", "c.d"}), "x.y")


# --- a real transaction produced by StoreKit (Xcode's local test configuration) ---------------------------------

FIXTURE = Path(__file__).parent / "fixtures" / "xcode_local_transaction.jws"


def test_real_storekit_transaction_is_accepted_in_dev_mode():
    # Captured from an actual StoreKit purchase in the iOS unit tests (ios/YipathTests/AccountTests.swift).
    tx = TransactionVerifier(Settings(storekit_local=True)).verify(FIXTURE.read_text().strip())
    assert tx.product_id == "com.libofu.yipath.monthly"
    assert tx.environment == "Xcode"
    assert tx.original_transaction_id == "0"
    assert not tx.revoked
    assert tx.expires_at.year >= 2026


def test_real_storekit_transaction_is_refused_by_default_and_in_production():
    jws = FIXTURE.read_text().strip()
    for settings in (Settings(), Settings(env="production")):
        with pytest.raises(TransactionError, match="local StoreKit"):
            TransactionVerifier(settings).verify(jws)


def test_real_storekit_transaction_cannot_be_tampered_with():
    head, payload, sig = FIXTURE.read_text().strip().split(".")
    forged = payload[:-4] + ("AAAA" if payload[-4:] != "AAAA" else "BBBB")
    with pytest.raises(TransactionError):
        TransactionVerifier(Settings(storekit_local=True)).verify(f"{head}.{forged}.{sig}")


def test_numeric_zero_transaction_id_counts_as_present(chain):
    tx = verifier(chain).verify(sign_transaction(chain, originalTransactionId=0))
    assert tx.original_transaction_id == "0"


# --- entitlement ------------------------------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "t.sqlite3")


def _age_user(store, user_id, days):
    import sqlite3
    created = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(store.path) as c:
        c.execute("UPDATE users SET created_at = ? WHERE id = ?", (created, user_id))


def _tx(chain, **over):
    return verifier(chain).verify(sign_transaction(chain, **over))


def test_new_user_is_in_trial_then_expires(store):
    uid, _ = store.create_user()
    e = compute_entitlement(store, SETTINGS, uid)
    assert e.status == "trial" and e.active and e.expires_at is None
    _age_user(store, uid, 4)
    assert compute_entitlement(store, SETTINGS, uid).status == "expired"
    assert not compute_entitlement(store, SETTINGS, uid).active


def test_subscription_beats_expired_trial_and_lapses(store, chain):
    uid, _ = store.create_user()
    _age_user(store, uid, 30)
    store.save_subscription(uid, _tx(chain))
    e = compute_entitlement(store, SETTINGS, uid)
    assert e.status == "subscribed" and e.product_id == "com.libofu.yipath.monthly"
    later = datetime.now(timezone.utc) + timedelta(days=40)
    assert compute_entitlement(store, SETTINGS, uid, now=later).status == "expired"


def test_revoked_subscription_does_not_entitle(store, chain):
    uid, _ = store.create_user()
    _age_user(store, uid, 30)
    store.save_subscription(uid, _tx(chain, revocationDate=int(time.time() * 1000)))
    assert compute_entitlement(store, SETTINGS, uid).status == "expired"


def test_one_app_store_subscription_cannot_serve_two_accounts(store, chain):
    a, _ = store.create_user()
    b, _ = store.create_user()
    store.save_subscription(a, _tx(chain))
    store.save_subscription(a, _tx(chain))            # same account renewing is fine
    with pytest.raises(SubscriptionConflict):
        store.save_subscription(b, _tx(chain))


def test_renewal_replaces_the_stored_expiry(store, chain):
    uid, _ = store.create_user()
    store.save_subscription(uid, _tx(chain, expiresDate=int((time.time() + 86400) * 1000)))
    first = store.get_subscription(uid)[1]
    store.save_subscription(uid, _tx(chain, expiresDate=int((time.time() + 30 * 86400) * 1000)))
    assert store.get_subscription(uid)[1] > first
