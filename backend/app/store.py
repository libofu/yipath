"""SQLite storage: users, login sessions, subscriptions, and the readings cache."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.advice.schema import Profile, Reading

from .subscription import Transaction

DEFAULT_DB = Path(__file__).resolve().parent.parent / "yipath.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    apple_sub TEXT UNIQUE,            -- Sign in with Apple's stable id; NULL for anonymous dev users
    profile_json TEXT,                -- NULL until the user fills in the onboarding form
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,      -- only the hash of the login token is stored
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id INTEGER PRIMARY KEY,
    original_transaction_id TEXT NOT NULL UNIQUE,   -- one App Store subscription belongs to one account
    product_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,                       -- ISO 8601, UTC
    environment TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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


class SubscriptionConflict(Exception):
    """This App Store subscription is already linked to a different account."""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _parse_utc(text: str) -> datetime:
    """SQLite's CURRENT_TIMESTAMP ('YYYY-MM-DD HH:MM:SS', UTC) or an ISO 8601 string."""
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Store:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = str(path or os.environ.get("YIPATH_DB") or DEFAULT_DB)
        with self._conn() as c:
            self._migrate_old_users_table(c)
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _migrate_old_users_table(c: sqlite3.Connection) -> None:
        """Early dev databases had users(token_hash, profile_json NOT NULL). Move them over."""
        cols = [r[1] for r in c.execute("PRAGMA table_info(users)")]
        if not cols or "apple_sub" in cols:
            return
        c.execute("ALTER TABLE users RENAME TO users_old")
        c.executescript(_SCHEMA)
        c.execute("INSERT INTO users (id, profile_json, created_at) SELECT id, profile_json, created_at FROM users_old")
        c.execute("INSERT INTO sessions (token_hash, user_id) SELECT token_hash, id FROM users_old")
        c.execute("DROP TABLE users_old")

    # --- users and sessions -------------------------------------------------------------
    def _new_session(self, c: sqlite3.Connection, user_id: int) -> str:
        token = secrets.token_urlsafe(32)   # shown to the client once; only its hash is stored
        c.execute("INSERT INTO sessions (token_hash, user_id) VALUES (?, ?)", (_hash(token), user_id))
        return token

    def create_user(self, profile: Profile | None = None, apple_sub: str | None = None) -> tuple[int, str]:
        """Creates an account and a login session. Returns (user_id, token)."""
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO users (apple_sub, profile_json) VALUES (?, ?)",
                (apple_sub, profile.model_dump_json() if profile else None),
            )
            return cur.lastrowid, self._new_session(c, cur.lastrowid)

    def login_apple(self, apple_sub: str) -> tuple[int, str, bool]:
        """Finds or creates the account for this Apple ID and starts a session.
        Returns (user_id, token, has_profile)."""
        with self._conn() as c:
            row = c.execute("SELECT id, profile_json FROM users WHERE apple_sub = ?", (apple_sub,)).fetchone()
            if row is None:
                cur = c.execute("INSERT INTO users (apple_sub) VALUES (?)", (apple_sub,))
                user_id, has_profile = cur.lastrowid, False
            else:
                user_id, has_profile = row[0], row[1] is not None
            return user_id, self._new_session(c, user_id), has_profile

    def user_by_token(self, token: str) -> tuple[int, Profile | None] | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT u.id, u.profile_json FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
                (_hash(token),),
            ).fetchone()
        if row is None:
            return None
        return row[0], (Profile.model_validate_json(row[1]) if row[1] else None)

    def update_profile(self, user_id: int, profile: Profile) -> None:
        with self._conn() as c:
            c.execute("UPDATE users SET profile_json = ? WHERE id = ?", (profile.model_dump_json(), user_id))
            # A changed profile invalidates everything generated from the old one.
            c.execute("DELETE FROM readings WHERE user_id = ?", (user_id,))

    def get_profile(self, user_id: int) -> Profile | None:
        with self._conn() as c:
            row = c.execute("SELECT profile_json FROM users WHERE id = ?", (user_id,)).fetchone()
        return Profile.model_validate_json(row[0]) if row and row[0] else None

    def user_created_at(self, user_id: int) -> datetime:
        with self._conn() as c:
            row = c.execute("SELECT created_at FROM users WHERE id = ?", (user_id,)).fetchone()
        return _parse_utc(row[0])

    def delete_user(self, user_id: int) -> None:
        """Erases the account and everything stored about it."""
        with self._conn() as c:
            for table in ("readings", "subscriptions", "sessions"):
                c.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            c.execute("DELETE FROM users WHERE id = ?", (user_id,))

    # --- subscriptions ---------------------------------------------------------------------
    def save_subscription(self, user_id: int, tx: Transaction) -> None:
        """Records the latest transaction for this user. Raises SubscriptionConflict if the
        same App Store subscription is already attached to another account."""
        with self._conn() as c:
            owner = c.execute(
                "SELECT user_id FROM subscriptions WHERE original_transaction_id = ?", (tx.original_transaction_id,)
            ).fetchone()
            if owner and owner[0] != user_id:
                raise SubscriptionConflict()
            c.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
            c.execute(
                "INSERT INTO subscriptions (user_id, original_transaction_id, product_id, expires_at, environment, revoked) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, tx.original_transaction_id, tx.product_id, tx.expires_at.isoformat(), tx.environment, int(tx.revoked)),
            )

    def apply_notification(self, tx: Transaction) -> bool:
        """Applies what an App Store notification says about a subscription we already know.
        Returns False if no account has this subscription (nothing to update).

        Notifications can arrive late or out of order, so: a refund always wins and sticks; an
        ordinary update only ever moves the expiry forward, never back."""
        with self._conn() as c:
            row = c.execute(
                "SELECT expires_at, revoked FROM subscriptions WHERE original_transaction_id = ?",
                (tx.original_transaction_id,),
            ).fetchone()
            if row is None:
                return False
            stored_expiry, stored_revoked = _parse_utc(row[0]), bool(row[1])
            if tx.revoked:
                c.execute(
                    "UPDATE subscriptions SET revoked = 1, updated_at = CURRENT_TIMESTAMP WHERE original_transaction_id = ?",
                    (tx.original_transaction_id,),
                )
            elif not stored_revoked and tx.expires_at >= stored_expiry:
                c.execute(
                    "UPDATE subscriptions SET product_id = ?, expires_at = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE original_transaction_id = ?",
                    (tx.product_id, tx.expires_at.isoformat(), tx.original_transaction_id),
                )
            return True

    def get_subscription(self, user_id: int) -> tuple[str, datetime, bool] | None:
        """(product_id, expires_at, revoked) or None."""
        with self._conn() as c:
            row = c.execute(
                "SELECT product_id, expires_at, revoked FROM subscriptions WHERE user_id = ?", (user_id,)
            ).fetchone()
        return (row[0], _parse_utc(row[1]), bool(row[2])) if row else None

    # --- readings cache --------------------------------------------------------------------
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
