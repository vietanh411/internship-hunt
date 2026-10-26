"""Upsert discovered postings into the jobs table with cross-source
deduplication, so one requisition is one Job no matter how many sites list it."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt.db import utcnow
from hunt.discovery.base import RawPosting
from hunt.discovery.normalize import (
    classify_category,
    detect_terms,
    extract_req_id,
    metro_of,
    normalize_company,
    normalize_title,
    parse_salary,
    remote_type,
    summer_2027_status,
)
from hunt.models import Job, JobStatus

# Prefer direct ATS sources over aggregators when choosing the canonical record.
SOURCE_RANK = {"greenhouse": 0, "lever": 0, "ashby": 0, "smartrecruiters": 0, "workday": 0,
               "simplify": 2, "vanshb03": 3}


def normalize_url(url: str) -> str:
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url
    path = re.sub(r"/(apply|application)/?$", "", p.path.rstrip("/"))
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, "", ""))


def canonical_key(p: RawPosting) -> str:
    if p.ats_platform and p.ats_board and p.ats_job_id:
        return f"{p.ats_platform}:{p.ats_board.lower()}:{p.ats_job_id}"
    if p.ats_platform == "greenhouse" and p.ats_job_id:
        return f"greenhouse:*:{p.ats_job_id}"
    return f"url:{normalize_url(p.url)}"


def uid_for(key: str) -> str:
    return hashlib.sha1(key.encode()).hexdigest()[:16]


@dataclass
class UpsertResult:
    job: Job | None
    created: bool
    merged_from_other_source: bool
    removed: bool = False  # previously removed by cleanup; not re-added


def _loc_overlap(a: list[str], b: list[str]) -> bool:
    if not a or not b:
        return True
    ma = {metro_of(x)[0] or x.lower().split(",")[0].strip() for x in a}
    mb = {metro_of(x)[0] or x.lower().split(",")[0].strip() for x in b}
    return bool(ma & mb)


def find_existing(session: Session, p: RawPosting, key: str, company_norm: str) -> Job | None:
    job = session.scalar(select(Job).where(Job.canonical_key == key))
    if job:
        return job
    if p.ats_platform and p.ats_job_id:
        job = session.scalar(select(Job).where(Job.ats_platform == p.ats_platform, Job.ats_job_id == p.ats_job_id))
        if job:
            return job
    title_n = normalize_title(p.title)
    req_id = extract_req_id(p.ats_job_id, p.url, p.title)
    for cand in session.scalars(select(Job).where(Job.company_norm == company_norm)).all():
        if normalize_title(cand.title) != title_n:
            continue
        cand_req = extract_req_id(cand.ats_job_id, cand.posting_url, cand.title)
        if req_id and cand_req:
            if req_id == cand_req:
                return cand
            continue
        if _loc_overlap(p.locations, cand.locations or []):
            return cand
    return None


def upsert_posting(session: Session, p: RawPosting) -> UpsertResult:
    key = canonical_key(p)
    company_norm = normalize_company(p.company)
    now = utcnow()
    job = find_existing(session, p, key, company_norm)
    text = p.description_text or ""
    if job is None:
        from hunt.models import RemovedListing
        if session.scalar(select(RemovedListing.id).where(RemovedListing.canonical_key == key)):
            return UpsertResult(None, False, False, removed=True)
        lo, hi, period, stxt = (p.salary_min, p.salary_max, p.salary_period, p.salary_text)
        if lo is None and text:
            lo, hi, period, stxt = parse_salary(text)
        term_status = summer_2027_status(p.title, text, p.terms or None)
        terms = p.terms or detect_terms(p.title, text[:6000])
        job = Job(
            uid=uid_for(key), canonical_key=key, company=p.company, company_norm=company_norm,
            title=p.title, category=classify_category(p.title, p.category_hint), ats_job_id=p.ats_job_id, ats_platform=p.ats_platform, ats_board=p.ats_board,
            location="; ".join(p.locations[:4]) if p.locations else None, locations=p.locations,
            remote_type=remote_type(p.locations, text, p.remote_hint),
            salary_min=lo, salary_max=hi, salary_period=period, salary_text=stxt,
            terms=terms, degrees=p.degrees, description_text=text or None, deadline=p.deadline,
            posting_url=p.url, apply_url=p.apply_url or p.url, source=p.source, sources=[p.source],
            date_posted=p.date_posted, date_discovered=now, last_seen_at=now,
            feed_flags={**p.feed_flags, "term_status": term_status, "category_hint": p.category_hint,
                        "board_metro": p.board_metro},
            status=JobStatus.DISCOVERED.value, status_updated_at=now,
        )
        session.add(job)
        session.flush()
        return UpsertResult(job, True, False)

    merged = p.source not in (job.sources or [])
    if merged:
        job.sources = list(job.sources or []) + [p.source]
    job.last_seen_at = now
    if p.description_text and len(p.description_text) > len(job.description_text or ""):
        job.description_text = p.description_text
        if (job.feed_flags or {}).get("term_status") in (None, "unconfirmed", "likely"):
            job.feed_flags = {**(job.feed_flags or {}),
                              "term_status": summer_2027_status(job.title, p.description_text, job.terms or None)}
    if SOURCE_RANK.get(p.source, 5) < SOURCE_RANK.get(job.source, 5):
        job.source = p.source
        job.apply_url = p.apply_url or job.apply_url
        if p.ats_platform and not job.ats_platform:
            job.ats_platform, job.ats_board, job.ats_job_id = p.ats_platform, p.ats_board, p.ats_job_id
    if p.date_posted and (job.date_posted is None or p.date_posted < job.date_posted):
        job.date_posted = p.date_posted
    if job.salary_min is None and p.salary_min is not None:
        job.salary_min, job.salary_max, job.salary_period, job.salary_text = (
            p.salary_min, p.salary_max, p.salary_period, p.salary_text)
    if p.feed_flags.get("sponsorship") and not (job.feed_flags or {}).get("sponsorship"):
        job.feed_flags = {**(job.feed_flags or {}), "sponsorship": p.feed_flags["sponsorship"]}
    if p.degrees and not job.degrees:
        job.degrees = p.degrees
    return UpsertResult(job, False, merged)
