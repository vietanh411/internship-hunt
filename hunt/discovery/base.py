from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawPosting:
    source: str
    company: str
    title: str
    url: str
    apply_url: str | None = None
    ats_platform: str | None = None
    ats_board: str | None = None
    ats_job_id: str | None = None
    locations: list[str] = field(default_factory=list)
    date_posted: datetime | None = None
    description_text: str | None = None
    terms: list[str] = field(default_factory=list)
    degrees: list[str] = field(default_factory=list)
    category_hint: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_period: str | None = None
    salary_text: str | None = None
    remote_hint: str | None = None
    deadline: datetime | None = None
    feed_flags: dict = field(default_factory=dict)
    board_metro: str | None = None

    @property
    def has_description(self) -> bool:
        return bool(self.description_text and len(self.description_text) > 200)


class SourceError(Exception):
    pass
