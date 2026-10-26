import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Fresh SQLite database with the schema, profile and master resume loaded."""
    monkeypatch.setenv("HUNT_DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("HUNT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HUNT_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("HUNT_SECRET_KEY", "")
    # never inherit live settings from the developer's .env
    monkeypatch.setenv("HUNT_ALLOW_REAL_SUBMISSIONS", "false")
    monkeypatch.setenv("HUNT_LLM_ENABLED", "false")
    monkeypatch.setenv("HUNT_IMAP_USER", "")
    monkeypatch.setenv("HUNT_SMTP_USER", "")
    monkeypatch.setenv("HUNT_DASHBOARD_PASSWORD", "")
    from hunt.llm import reset_llm
    reset_llm()
    from hunt import config, db as dbmod
    config.get_settings.cache_clear()
    dbmod.reset_engine()
    from hunt.bootstrap import init_db
    init_db(seed_boards=False)
    yield dbmod
    dbmod.reset_engine()
    config.get_settings.cache_clear()


@pytest.fixture()
def session(db):
    s = db.new_session()
    yield s
    s.close()
