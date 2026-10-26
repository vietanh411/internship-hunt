"""Database migration and first-run initialisation."""
from __future__ import annotations

import logging

from alembic import command
from alembic.config import Config

from hunt.config import ROOT, get_settings
from hunt.db import get_engine, session_scope

log = logging.getLogger(__name__)


def alembic_config() -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.attributes["url"] = get_settings().database_url
    return cfg


def migrate() -> None:
    cfg = alembic_config()
    with get_engine().begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def init_db(seed_boards: bool = True) -> None:
    from hunt.apply.answers import seed_library
    from hunt.discovery.registry import sync_seed_boards
    from hunt.profile_store import bootstrap_profile, get_profile

    migrate()
    with session_scope() as s:
        bootstrap_profile(s)
        seed_library(s, get_profile(s))
        if seed_boards:
            n = sync_seed_boards(s, get_settings().seeds_dir / "companies.yaml")
            if n:
                log.info("Added %d seed boards", n)
