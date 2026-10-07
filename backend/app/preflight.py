"""Startup checks for production: refuse to boot when misconfigured, with a clear message,
instead of failing on the first customer's request."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from .config import Settings
from .store import DEFAULT_DB
from .subscription import load_pinned_root


def production_problems(settings: Settings, environ: Mapping[str, str] | None = None, db_path: str | None = None) -> list[str]:
    """Everything that is wrong with this production setup (empty list = good to go)."""
    env = os.environ if environ is None else environ
    problems: list[str] = []

    # 1. An AI provider with a key; otherwise every reading would fail with a 502.
    provider = env.get("YIPATH_LLM") or ("deepseek" if env.get("DEEPSEEK_API_KEY") else "anthropic")
    key_var = {"deepseek": "DEEPSEEK_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(provider)
    if key_var is None:
        problems.append(f"YIPATH_LLM={provider!r} is not a known provider (use deepseek or anthropic)")
    elif not env.get(key_var):
        problems.append(f"{key_var} is not set (needed for the {provider} provider)")

    # 2. A database location we can write to (it must be on persistent storage).
    path = Path(db_path or env.get("YIPATH_DB") or DEFAULT_DB)
    folder = path.parent
    if not folder.is_dir():
        problems.append(f"database folder {folder} does not exist (mount a volume there)")
    elif not os.access(folder, os.W_OK):
        problems.append(f"database folder {folder} is not writable")

    # 3. Apple's pinned root certificate must be intact: it is what purchases are trusted against.
    try:
        load_pinned_root()
    except Exception as e:
        problems.append(f"Apple root certificate check failed: {e}")

    # 4. Products and bundle id.
    if not settings.product_ids:
        problems.append("YIPATH_PRODUCT_IDS is empty")
    if not settings.bundle_id:
        problems.append("YIPATH_APPLE_BUNDLE_ID is empty")
    return problems
