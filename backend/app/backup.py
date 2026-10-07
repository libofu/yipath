"""Consistent online backups of the SQLite database (safe while the server is running)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


def backup_database(db_path: str | Path, out_dir: str | Path, keep: int = 14, now: datetime | None = None) -> Path:
    """Copies the database to out_dir/yipath-YYYYmmdd-HHMMSS.sqlite3 using SQLite's backup API
    (which, unlike copying the file, is consistent even mid-write), then deletes all but the
    newest `keep` backups. Returns the new backup's path."""
    db_path, out_dir = Path(db_path), Path(out_dir)
    if not db_path.is_file():
        raise FileNotFoundError(f"database not found: {db_path}")
    if keep < 1:
        raise ValueError("keep must be at least 1")
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    target = out_dir / f"yipath-{stamp}.sqlite3"
    source = sqlite3.connect(db_path)
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()

    for old in sorted(out_dir.glob("yipath-*.sqlite3"))[:-keep]:   # names sort by time
        old.unlink()
    return target
