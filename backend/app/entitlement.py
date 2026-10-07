"""Who may read? Anyone in their free trial, or with an active, unrevoked subscription."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import Settings
from .store import Store


@dataclass(frozen=True)
class Entitlement:
    status: str                    # "subscribed" | "trial" | "expired"
    trial_ends_at: datetime
    expires_at: datetime | None    # when the subscription lapses (None if never subscribed)
    product_id: str | None

    @property
    def active(self) -> bool:
        return self.status in ("subscribed", "trial")


def compute_entitlement(store: Store, settings: Settings, user_id: int, now: datetime | None = None) -> Entitlement:
    now = now or datetime.now(timezone.utc)
    trial_ends = store.user_created_at(user_id) + timedelta(days=settings.trial_days)
    sub = store.get_subscription(user_id)
    product_id, expires_at = (sub[0], sub[1]) if sub else (None, None)

    if sub and not sub[2] and sub[1] > now:
        status = "subscribed"
    elif now < trial_ends:
        status = "trial"
    else:
        status = "expired"
    return Entitlement(status, trial_ends, expires_at, product_id)
