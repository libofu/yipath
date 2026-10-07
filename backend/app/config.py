"""Settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_PRODUCT_IDS = ("com.libofu.yipath.monthly", "com.libofu.yipath.yearly")


@dataclass(frozen=True)
class Settings:
    # "production" turns off the developer shortcuts below. Anything else is a dev setup.
    env: str = "dev"
    # Must equal the iOS app's bundle id: Apple puts it in sign-in tokens and transactions.
    bundle_id: str = "com.libofu.yipath"
    # Everyone gets this many free days from signup before a subscription is required.
    trial_days: int = 3
    # Subscription products the app sells. Anything else is rejected.
    product_ids: frozenset[str] = frozenset(DEFAULT_PRODUCT_IDS)
    # Accept transactions made with Xcode's *local* StoreKit test configuration. These are
    # signed by a throwaway local certificate, not by Apple, so this is never allowed in production.
    storekit_local: bool = False

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def allow_anonymous(self) -> bool:
        """`POST /profile` creates an account with no sign-in; handy for local development."""
        return not self.is_production


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    app_env = env.get("YIPATH_ENV", "dev")
    products = env.get("YIPATH_PRODUCT_IDS")
    return Settings(
        env=app_env,
        bundle_id=env.get("YIPATH_APPLE_BUNDLE_ID", "com.libofu.yipath"),
        trial_days=int(env.get("YIPATH_TRIAL_DAYS", "3")),
        product_ids=frozenset(p.strip() for p in products.split(",") if p.strip()) if products else frozenset(DEFAULT_PRODUCT_IDS),
        # never honoured in production, whatever the variable says
        storekit_local=env.get("YIPATH_STOREKIT_LOCAL") == "1" and app_env != "production",
    )
