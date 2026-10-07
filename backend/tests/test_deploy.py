import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.backup import backup_database
from app.config import Settings, load_settings
from app.preflight import production_problems
from app.store import Store

GOOD_ENV = {"YIPATH_ENV": "production", "DEEPSEEK_API_KEY": "k"}


# --- production preflight ----------------------------------------------------------------------

def test_a_complete_setup_has_no_problems(tmp_path):
    assert production_problems(load_settings(GOOD_ENV), GOOD_ENV, db_path=str(tmp_path / "db.sqlite3")) == []


def test_a_missing_ai_key_is_reported(tmp_path):
    env = {"YIPATH_ENV": "production"}
    problems = production_problems(load_settings(env), env, db_path=str(tmp_path / "db.sqlite3"))
    assert any("ANTHROPIC_API_KEY" in p for p in problems)      # no key at all: falls back to anthropic
    env = {"YIPATH_ENV": "production", "YIPATH_LLM": "deepseek"}
    assert any("DEEPSEEK_API_KEY" in p for p in production_problems(load_settings(env), env, db_path=str(tmp_path / "x")))
    env = {"YIPATH_ENV": "production", "YIPATH_LLM": "gpt"}
    assert any("not a known provider" in p for p in production_problems(load_settings(env), env, db_path=str(tmp_path / "x")))


def test_the_other_provider_works_with_its_own_key(tmp_path):
    env = {"YIPATH_ENV": "production", "YIPATH_LLM": "anthropic", "ANTHROPIC_API_KEY": "k"}
    assert production_problems(load_settings(env), env, db_path=str(tmp_path / "db.sqlite3")) == []


def test_a_missing_database_folder_is_reported(tmp_path):
    problems = production_problems(load_settings(GOOD_ENV), GOOD_ENV, db_path=str(tmp_path / "nope" / "db.sqlite3"))
    assert any("does not exist" in p for p in problems)


def test_an_unwritable_database_folder_is_reported(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        problems = production_problems(load_settings(GOOD_ENV), GOOD_ENV, db_path=str(locked / "db.sqlite3"))
    finally:
        locked.chmod(0o700)
    assert any("not writable" in p for p in problems)


def test_a_tampered_apple_root_certificate_is_reported(tmp_path, monkeypatch):
    import app.subscription as sub
    fake = tmp_path / "AppleRootCA-G3.cer"
    fake.write_bytes(b"not the real certificate")
    monkeypatch.setattr(sub, "ROOT_CERT_PATH", fake)
    problems = production_problems(load_settings(GOOD_ENV), GOOD_ENV, db_path=str(tmp_path / "db.sqlite3"))
    assert any("Apple root certificate" in p for p in problems)


def test_empty_products_are_reported(tmp_path):
    env = {**GOOD_ENV, "YIPATH_PRODUCT_IDS": " , "}
    s = Settings(env="production", product_ids=frozenset())
    assert any("PRODUCT_IDS" in p for p in production_problems(s, env, db_path=str(tmp_path / "db.sqlite3")))


# --- the server refuses to start when production is misconfigured -------------------------------------

def test_server_refuses_to_start_with_problems_in_production(monkeypatch, tmp_path):
    for var in ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "YIPATH_LLM"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("YIPATH_DB", str(tmp_path / "db.sqlite3"))
    monkeypatch.setattr(main, "get_settings", lambda: Settings(env="production"))
    with pytest.raises(RuntimeError, match="Refusing to start in production"):
        with TestClient(main.app):
            pass


def test_server_starts_when_production_is_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setenv("YIPATH_DB", str(tmp_path / "db.sqlite3"))
    monkeypatch.setattr(main, "get_settings", lambda: Settings(env="production"))
    with TestClient(main.app) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_dev_mode_never_blocks_startup(monkeypatch):
    for var in ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "YIPATH_LLM"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(main, "get_settings", lambda: Settings(env="dev"))
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200


# --- backups ------------------------------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    path = tmp_path / "live.sqlite3"
    store = Store(path)
    store.login_apple("someone")
    return path


def test_backup_is_a_complete_readable_copy(db, tmp_path):
    target = backup_database(db, tmp_path / "backups", now=datetime(2026, 10, 8, 3, 0, 0))
    assert target.name == "yipath-20261008-030000.sqlite3"
    with sqlite3.connect(target) as c:
        assert c.execute("SELECT apple_sub FROM users").fetchone() == ("someone",)
    assert Store(target).login_apple("someone")[2] is False    # opens as a normal yipath database


def test_old_backups_are_pruned_keeping_the_newest(db, tmp_path):
    out = tmp_path / "backups"
    start = datetime(2026, 10, 1, 3, 0, 0)
    for day in range(5):
        backup_database(db, out, keep=3, now=start + timedelta(days=day))
    names = sorted(p.name for p in out.glob("*.sqlite3"))
    assert names == ["yipath-20261003-030000.sqlite3", "yipath-20261004-030000.sqlite3", "yipath-20261005-030000.sqlite3"]


def test_backup_works_while_the_database_is_being_written(db, tmp_path):
    writer = sqlite3.connect(db)
    writer.execute("BEGIN")
    writer.execute("INSERT INTO users (apple_sub) VALUES ('uncommitted')")   # a write in flight
    target = backup_database(db, tmp_path / "backups")
    with sqlite3.connect(target) as c:
        subs = {r[0] for r in c.execute("SELECT apple_sub FROM users")}
    writer.rollback()
    writer.close()
    assert subs == {"someone"}      # the backup holds committed data only, never a half-written state


def test_backup_rejects_bad_input(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_database(tmp_path / "missing.sqlite3", tmp_path / "out")
    db = tmp_path / "x.sqlite3"
    Store(db)
    with pytest.raises(ValueError):
        backup_database(db, tmp_path / "out", keep=0)
