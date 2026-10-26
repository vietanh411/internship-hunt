"""Registry of company job boards polled directly: curated seeds (regional,
lesser-known employers) plus boards learned from community feed URLs."""
from __future__ import annotations

import logging
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt.discovery.base import RawPosting
from hunt.models import Board

log = logging.getLogger(__name__)

POLLABLE = {"greenhouse", "lever", "ashby", "smartrecruiters", "workday"}


def load_seed_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for platform, entries in data.items():
        if platform not in POLLABLE or not entries:
            continue
        for e in entries:
            if platform == "workday":
                token = f"{e['host']}|{e['tenant']}|{e['site']}"
            else:
                token = str(e["token"])
            out.append({"platform": platform, "token": token, "company": e.get("company"),
                        "metro": e.get("metro"), "industry": e.get("industry")})
    return out


def sync_seed_boards(session: Session, path: Path) -> int:
    added = 0
    for e in load_seed_file(path):
        b = session.scalar(select(Board).where(Board.platform == e["platform"], Board.token == e["token"]))
        if b is None:
            session.add(Board(origin="seed", **e))
            added += 1
        else:
            b.company = b.company or e["company"]
            b.metro = e["metro"] or b.metro
            b.industry = e["industry"] or b.industry
            if b.origin == "learned":
                b.origin = "seed"
    session.flush()
    return added


def learn_boards(session: Session, postings: list[RawPosting]) -> int:
    existing = {(b.platform, b.token) for b in session.scalars(select(Board)).all()}
    added = 0
    for p in postings:
        if p.ats_platform in POLLABLE and p.ats_board and (p.ats_platform, p.ats_board) not in existing:
            session.add(Board(platform=p.ats_platform, token=p.ats_board, company=p.company, origin="learned"))
            existing.add((p.ats_platform, p.ats_board))
            added += 1
    session.flush()
    return added


def boards_to_poll(session: Session, enabled_platforms: set[str], max_learned: int) -> list[Board]:
    """All active seed/user boards, plus the least-recently polled learned boards."""
    rows = session.scalars(
        select(Board).where(Board.active.is_(True), Board.platform.in_(enabled_platforms))
    ).all()
    primary = [b for b in rows if b.origin in ("seed", "user")]
    learned = sorted((b for b in rows if b.origin == "learned"),
                     key=lambda b: (b.last_polled_at is not None, b.last_polled_at or 0))
    # Greenhouse / Ashby / Lever / SmartRecruiters first: their fresh postings are the
    # quickest to finish, so they must be found even when a run runs short of time
    return sorted(primary + learned[:max_learned], key=lambda b: b.platform == "workday")
