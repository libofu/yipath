"""SQLite storage: users (profile + hashed token) and the readings cache."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.advice.schema import Profile, Reading

DEFAULT_DB = Path(__file__).resolve().parent.parent / "yipath.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS readings (
    user_id INTEGER NOT NULL,
    period TEXT NOT NULL,
    period_key TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    reading_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, period, period_key, prompt_version)
);
"""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = str(path or os.environ.get("YIPATH_DB") or DEFAULT_DB)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- users -------------------------------------------------------------
    def create_user(self, profile: Profile) -> tuple[int, str]:
        """Returns (user_id, token). The token is shown once; only its hash is stored."""
        token = secrets.token_urlsafe(32)
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO users (token_hash, profile_json) VALUES (?, ?)",
                (_hash(token), profile.model_dump_json()),
            )
            return cur.lastrowid, token

    def user_by_token(self, token: str) -> tuple[int, Profile] | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT id, profile_json FROM users WHERE token_hash = ?", (_hash(token),)
            ).fetchone()
        if row is None:
            return None
        return row[0], Profile.model_validate_json(row[1])

    def update_profile(self, user_id: int, profile: Profile) -> None:
        with self._conn() as c:
            c.execute("UPDATE users SET profile_json = ? WHERE id = ?", (profile.model_dump_json(), user_id))
            # A changed profile invalidates everything generated from the old one.
            c.execute("DELETE FROM readings WHERE user_id = ?", (user_id,))

    # --- readings cache ----------------------------------------------------
    def get_reading(self, user_id: int, period: str, period_key: str, version: str) -> Reading | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT reading_json FROM readings WHERE user_id=? AND period=? AND period_key=? AND prompt_version=?",
                (user_id, period, period_key, version),
            ).fetchone()
        return Reading.model_validate(json.loads(row[0])) if row else None

    def put_reading(self, user_id: int, period: str, period_key: str, version: str, reading: Reading) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO readings (user_id, period, period_key, prompt_version, reading_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, period, period_key, version, reading.model_dump_json()),
            )
