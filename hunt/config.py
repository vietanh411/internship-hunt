"""Process-level configuration (environment / .env). Runtime-editable automation
settings live in the database; see hunt.settings_store."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_prefix="HUNT_", extra="ignore")

    database_url: str = Field(
        default=f"sqlite:///{(ROOT / 'data' / 'hunt.db').as_posix()}",
        validation_alias=AliasChoices("HUNT_DATABASE_URL", "DATABASE_URL"),
    )
    data_dir: Path = ROOT / "data"
    config_dir: Path = ROOT / "config"
    seeds_dir: Path = ROOT / "seeds"
    frontend_dist: Path = ROOT / "frontend" / "dist"

    # Fernet key used to encrypt sensitive profile fields at rest. Generate with
    # `hunt keygen`. Without it, sensitive fields are stored unencrypted and a
    # warning is shown in the dashboard.
    secret_key: str | None = None

    timezone: str = "America/Chicago"
    schedule_hour: int = 9
    schedule_minute: int = 0
    scheduler_enabled: bool = True

    # Hard kill switch: unless true, the application engine never submits to a
    # real employer, regardless of dashboard mode. Mock/test targets are exempt.
    allow_real_submissions: bool = False
    headless: bool = True

    dashboard_password: str | None = None
    host: str = "127.0.0.1"
    port: int = 8000

    llm_model: str = "claude-opus-5-5"
    llm_enabled: bool = True

    imap_host: str = "imap.gmail.com"
    imap_user: str | None = None
    imap_password: str | None = None
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    notify_email: str | None = None

    enable_mock_ats: bool = False
    mock_ats_base: str = "http://127.0.0.1:8000/mock-ats"
    user_agent: str = "InternshipHunt/1.0 (personal internship search; low-volume)"

    @property
    def applications_dir(self) -> Path:
        return self.data_dir / "applications"

    @property
    def evidence_dir(self) -> Path:
        return self.data_dir / "evidence"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    for d in (s.data_dir, s.applications_dir, s.evidence_dir, s.reports_dir):
        d.mkdir(parents=True, exist_ok=True)
    return s
