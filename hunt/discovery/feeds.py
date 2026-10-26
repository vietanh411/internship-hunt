"""Community-maintained Summer 2027 internship lists published as JSON on GitHub
(SimplifyJobs, vanshb03). Public data intended for reuse."""
from __future__ import annotations

from datetime import datetime, timezone

from hunt.discovery.base import RawPosting
from hunt.discovery.normalize import parse_ats_url
from hunt.http import PoliteClient

FEEDS = {
    "simplify": "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json",
    "vanshb03": "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/.github/scripts/listings.json",
}


def _ts(v) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromtimestamp(int(v), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None


def parse_feed(name: str, data: list[dict]) -> list[RawPosting]:
    out: list[RawPosting] = []
    for x in data:
        if not x.get("active") or not x.get("is_visible", True):
            continue
        terms = x.get("terms") or []
        season = x.get("season")
        if name == "vanshb03":
            if season and season != "Summer":
                continue
            terms = terms or ["Summer 2027"]
        if terms and "Summer 2027" not in terms:
            continue
        url = x.get("url") or ""
        ref = parse_ats_url(url)
        out.append(RawPosting(
            source=name,
            company=(x.get("company_name") or "").strip(),
            title=(x.get("title") or "").strip(),
            url=url,
            apply_url=url,
            ats_platform=ref.platform,
            ats_board=ref.board,
            ats_job_id=ref.job_id,
            locations=list(x.get("locations") or []),
            date_posted=_ts(x.get("date_posted")),
            terms=terms,
            degrees=list(x.get("degrees") or []),
            category_hint=x.get("category"),
            feed_flags={"sponsorship": x.get("sponsorship"), "feed_id": x.get("id")},
        ))
    return out


def fetch_feed(client: PoliteClient, name: str) -> list[RawPosting]:
    data = client.get_json(FEEDS[name])
    return parse_feed(name, data)
