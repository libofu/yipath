from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from app.advice.schema import Profile, Reading
from app.advice.service import AdviceService, ReadingError, make_llm
from app.auth import AppleVerifier, AuthError
from app.config import Settings, load_settings
from app.entitlement import Entitlement, compute_entitlement
from app.store import Store, SubscriptionConflict
from app.subscription import TransactionError, TransactionVerifier


def _load_dotenv() -> None:
    """Tiny .env loader (KEY=VALUE lines) so we don't need another dependency."""
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


# --- request / response shapes ----------------------------------------------------------------

class SessionCreated(BaseModel):
    user_id: int
    token: str
    has_profile: bool = False


class AppleSignIn(BaseModel):
    identity_token: str
    nonce: str        # the raw nonce; Apple's token carries its SHA-256


class SignedTransaction(BaseModel):
    signed_transaction: str


class AppleNotification(BaseModel):
    signedPayload: str   # Apple's field name


class EntitlementOut(BaseModel):
    status: str                       # "subscribed" | "trial" | "expired"
    trial_ends_at: datetime
    expires_at: datetime | None = None
    product_id: str | None = None

    @classmethod
    def of(cls, e: Entitlement) -> EntitlementOut:
        return cls(status=e.status, trial_ends_at=e.trial_ends_at, expires_at=e.expires_at, product_id=e.product_id)


@dataclass
class CurrentUser:
    id: int
    profile: Profile | None


# --- shared objects (tests replace these through `app.dependency_overrides`) --------------------------

_settings: Settings | None = None
_store: Store | None = None
_service: AdviceService | None = None
_apple: AppleVerifier | None = None
_tx_verifier: TransactionVerifier | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _load_dotenv()
        _settings = load_settings()
    return _settings


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def get_service() -> AdviceService:
    global _service
    if _service is None:
        _load_dotenv()
        _service = AdviceService(get_store(), make_llm())
    return _service


def get_apple_verifier(settings: Settings = Depends(get_settings)) -> AppleVerifier:
    global _apple
    if _apple is None:
        _apple = AppleVerifier(audience=settings.bundle_id)
    return _apple


def get_tx_verifier(settings: Settings = Depends(get_settings)) -> TransactionVerifier:
    global _tx_verifier
    if _tx_verifier is None:
        _tx_verifier = TransactionVerifier(settings)
    return _tx_verifier


def current_user(authorization: str = Header(default=""), store: Store = Depends(get_store)) -> CurrentUser:
    scheme, _, token = authorization.partition(" ")
    found = store.user_by_token(token) if scheme.lower() == "bearer" and token else None
    if found is None:
        raise HTTPException(status_code=401, detail="invalid or missing token")
    return CurrentUser(id=found[0], profile=found[1])


def _today_default() -> date:
    # The audience is Chinese-speaking; clients may pass ?date= to override.
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


app = FastAPI(title="yipath")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# --- accounts ----------------------------------------------------------------------------------------

@app.post("/auth/apple", response_model=SessionCreated)
def sign_in_with_apple(
    body: AppleSignIn,
    store: Store = Depends(get_store),
    verifier: AppleVerifier = Depends(get_apple_verifier),
) -> SessionCreated:
    try:
        apple_sub = verifier.verify(body.identity_token, body.nonce)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    user_id, token, has_profile = store.login_apple(apple_sub)
    return SessionCreated(user_id=user_id, token=token, has_profile=has_profile)


@app.post("/profile", response_model=SessionCreated)
def create_anonymous_profile(
    profile: Profile, store: Store = Depends(get_store), settings: Settings = Depends(get_settings)
) -> SessionCreated:
    """Developer shortcut: an account with no sign-in. Switched off in production."""
    if not settings.allow_anonymous:
        raise HTTPException(status_code=404)
    user_id, token = store.create_user(profile)
    return SessionCreated(user_id=user_id, token=token, has_profile=True)


@app.get("/profile", response_model=Profile)
def read_profile(user: CurrentUser = Depends(current_user)) -> Profile:
    if user.profile is None:
        raise HTTPException(status_code=404, detail="no profile yet")
    return user.profile


@app.put("/profile", status_code=204)
def save_profile(profile: Profile, user: CurrentUser = Depends(current_user), store: Store = Depends(get_store)) -> None:
    store.update_profile(user.id, profile)


@app.delete("/account", status_code=204)
def delete_account(user: CurrentUser = Depends(current_user), store: Store = Depends(get_store)) -> None:
    """Required by the App Store for apps that create accounts: erase everything we hold."""
    store.delete_user(user.id)


# --- subscription ------------------------------------------------------------------------------------

@app.get("/subscription", response_model=EntitlementOut)
def subscription_status(
    user: CurrentUser = Depends(current_user),
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> EntitlementOut:
    return EntitlementOut.of(compute_entitlement(store, settings, user.id))


@app.post("/subscription/verify", response_model=EntitlementOut)
def verify_subscription(
    body: SignedTransaction,
    user: CurrentUser = Depends(current_user),
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
    verifier: TransactionVerifier = Depends(get_tx_verifier),
) -> EntitlementOut:
    """The app sends the signed transaction StoreKit gave it; we check Apple signed it."""
    try:
        tx = verifier.verify(body.signed_transaction)
    except TransactionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        store.save_subscription(user.id, tx)
    except SubscriptionConflict:
        raise HTTPException(status_code=409, detail="this subscription belongs to another account")
    return EntitlementOut.of(compute_entitlement(store, settings, user.id))


@app.post("/apple/notifications")
def apple_notifications(
    body: AppleNotification,
    store: Store = Depends(get_store),
    verifier: TransactionVerifier = Depends(get_tx_verifier),
) -> dict[str, bool]:
    """App Store Server Notifications V2: Apple calls this when a subscription renews, expires or
    is refunded, so access stays right even if the user never reopens the app.

    There is no login here; the request is trusted only if Apple's signature checks out. Set this
    URL in App Store Connect (App Information > App Store Server Notifications)."""
    try:
        notification = verifier.verify_notification(body.signedPayload)
    except TransactionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    handled = store.apply_notification(notification.transaction) if notification.transaction else False
    return {"handled": handled}


# --- readings (need a profile and an active trial/subscription) -----------------------------------------

def reader(
    user: CurrentUser = Depends(current_user),
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    if user.profile is None:
        raise HTTPException(status_code=409, detail="profile required")
    if not compute_entitlement(store, settings, user.id).active:
        raise HTTPException(status_code=402, detail="subscription required")
    return user


def _reading(period: str, on: date | None, user: CurrentUser, service: AdviceService) -> Reading:
    try:
        return service.get(user.id, user.profile, period, on or _today_default())  # type: ignore[arg-type]
    except ReadingError:
        raise HTTPException(status_code=502, detail="could not generate a reading, please retry")


@app.get("/reading/today", response_model=Reading)
def reading_today(
    date_: date | None = Query(default=None, alias="date"),
    user: CurrentUser = Depends(reader),
    service: AdviceService = Depends(get_service),
) -> Reading:
    return _reading("today", date_, user, service)


@app.get("/reading/week", response_model=Reading)
def reading_week(
    date_: date | None = Query(default=None, alias="date"),
    user: CurrentUser = Depends(reader),
    service: AdviceService = Depends(get_service),
) -> Reading:
    return _reading("week", date_, user, service)
