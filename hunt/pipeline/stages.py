"""Pipeline stages. Each stage selects its input from persistent state (job status,
queued tasks), commits per item, and can be re-run safely: re-running a stage
continues where a crashed or cancelled run stopped."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from hunt.apply import adapters
from hunt.apply.engine import (ensure_application, prepare_application, recover_interrupted, submission_gates,
                               submit_application, submitted_today)
from hunt.artifacts import save_artifact
from hunt.config import get_settings
from hunt.db import utcnow
from hunt.dedupe import upsert_posting
from hunt.discovery import ats, feeds
from hunt.discovery.base import RawPosting
from hunt.discovery.normalize import INTERN_RE, classify_category, html_to_text, is_us_location, metro_of, summer_2027_status
from hunt.discovery.registry import boards_to_poll, learn_boards, sync_seed_boards
from hunt.eligibility import classify
from hunt.http import PermanentHTTPError, PoliteClient, RobotsDisallowed, TransientHTTPError
from hunt.llm import LLM
from hunt.matching import Applicant, score_job
from hunt.models import (
    POST_SUBMISSION,
    TERMINAL,
    Application,
    Artifact,
    Board,
    Job,
    JobStatus,
    Lock,
    PendingQuestion,
    PipelineRun,
    RemovedListing,
    ResumeVersion,
    Task,
)
from hunt.pipeline import queue
from hunt.resume.ats_check import ats_check
from hunt.resume.cover_letter import generate_cover_letter, needs_cover_letter, render_cover_letter
from hunt.resume.render import render_fitted
from hunt.resume.tailor import tailor_resume
from hunt.workflow import notify, run_log, set_status

log = logging.getLogger(__name__)

RESUME_FILENAME = "Resume_VietAnhNguyen.pdf"
COVER_FILENAME = "CoverLetter_VietAnhNguyen.pdf"


class Cancelled(Exception):
    pass


@dataclass
class RunContext:
    session: Session
    run: PipelineRun
    dry_run: bool
    settings: dict
    profile: dict
    master: dict
    master_version: int
    applicant: Applicant
    client: PoliteClient
    llm: LLM
    deadline: datetime
    worker: str
    seeds_path: object = None
    browser_factory: Callable | None = None
    board_cache: dict = field(default_factory=dict)
    stage_deadline: datetime | None = None
    _browser: object = None

    def log(self, level: str, msg: str, stage: str | None = None, job_id: int | None = None) -> None:
        getattr(log, level if level != "warn" else "warning", log.info)(msg)
        run_log(self.session, self.run.id, level, msg, stage or self.run.current_stage, job_id)

    def heartbeat(self) -> None:
        """Committed immediately in its own short transaction: a pending write must
        never be flushed (and hold SQLite's write lock) across network calls."""
        now = utcnow()
        self.run.heartbeat_at = now
        lock = self.session.get(Lock, "pipeline")
        if lock is not None:
            lock.heartbeat_at = now
        self.session.commit()

    def should_stop(self) -> bool:
        self.session.refresh(self.run, attribute_names=["cancel_requested"])
        limit = min(self.deadline, self.stage_deadline) if self.stage_deadline else self.deadline
        return self.run.cancel_requested or utcnow() > limit

    def check_cancel(self) -> None:
        self.session.refresh(self.run, attribute_names=["cancel_requested"])
        if self.run.cancel_requested:
            raise Cancelled()

    def browser(self):
        if self._browser is None:
            if self.browser_factory is None:
                raise RuntimeError("Browser automation unavailable")
            self._browser = self.browser_factory()
            self._browser.__enter__()
        return self._browser

    def close(self) -> None:
        if self._browser is not None:
            try:
                self._browser.__exit__(None, None, None)
            finally:
                self._browser = None
        self.client.close()


def log_task_errors(rc: "RunContext", stage: str, retry: Callable[[Exception], bool] | None = None):
    def on_error(task: Task, e: Exception) -> bool:
        rc.log("error", f"{task.kind} task {task.id} ({task.payload}) failed: {type(e).__name__}: {e}", stage,
               task.payload.get("job_id"))
        return retry(e) if retry else True
    return on_error


def today_key() -> str:
    return utcnow().strftime("%Y-%m-%d")


# =================================================================== 1. discovery

def allowed_categories(settings: dict) -> set[str]:
    cats = {classify_category(r) for r in settings.get("target_roles", [])}
    cats.discard(None)
    if "data_analytics" in cats:
        cats.add("business_analytics")
    return cats


def qualifies(p: RawPosting, rc: RunContext, from_feed: bool) -> tuple[bool, str, str | None]:
    s = rc.settings
    if not p.company or not p.title:
        return False, "missing company/title", None
    if p.company.lower() in {c.lower() for c in s.get("blacklist", [])}:
        return False, "blacklisted company", None
    if not from_feed and not INTERN_RE.search(p.title):
        return False, "not an internship", None
    cat = classify_category(p.title, p.category_hint)
    if cat is None or cat not in allowed_categories(s):
        return False, "role outside target categories", cat
    if p.degrees and set(p.degrees) == {"PhD"}:
        return False, "PhD-only", cat
    if p.locations:
        us = [l for l in p.locations if is_us_location(l)]
        if not us:
            return False, "outside the United States", cat
        if not s.get("include_other_us", True):
            tiers = {metro_of(l)[1] for l in us}
            if not tiers & {"preferred", "nearby", "remote"}:
                return False, "outside preferred locations", cat
    status = summer_2027_status(p.title, p.description_text or "", p.terms or None)
    if status == "other_term":
        return False, "not a Summer 2027 term", cat
    if p.date_posted and p.date_posted < utcnow() - timedelta(days=int(s.get("max_posting_age_days", 75))):
        return False, "posting older than max age", cat
    return True, "ok", cat


def stage_discovery(rc: RunContext) -> dict:
    s, session = rc.settings, rc.session
    stats = Counter()
    skipped = Counter()
    sources = s.get("sources", {})
    if rc.seeds_path is not None:
        stats["seed_boards_added"] = sync_seed_boards(session, rc.seeds_path)
        session.commit()

    def ingest(p: RawPosting, from_feed: bool):
        ok, reason, _ = qualifies(p, rc, from_feed)
        if not ok:
            skipped[reason] += 1
            return
        r = upsert_posting(session, p)
        if r.removed:
            skipped["previously removed (too old / ineligible)"] += 1
            return
        if r.created:
            stats["new_jobs"] += 1
            if not from_feed:
                stats["new_from_direct_boards"] += 1
        elif r.merged_from_other_source:
            stats["merged_duplicates"] += 1
        else:
            stats["already_known"] += 1

    feed_postings: list[RawPosting] = []
    for name in feeds.FEEDS:
        if not sources.get(name, True):
            continue
        try:
            posts = feeds.fetch_feed(rc.client, name)
            stats[f"feed_{name}"] = len(posts)
            feed_postings += posts
            rc.log("info", f"Feed {name}: {len(posts)} active Summer 2027 listings", "discovery")
        except Exception as e:  # noqa: BLE001  (failure isolation per source)
            stats["feed_errors"] += 1
            rc.log("error", f"Feed {name} failed: {e}", "discovery")
    for i, p in enumerate(feed_postings):
        ingest(p, True)
        if i % 150 == 149:
            session.commit()  # short write transactions keep the dashboard responsive
    session.commit()
    if s.get("learn_boards_from_feeds", True):
        stats["boards_learned"] = learn_boards(session, feed_postings)
        session.commit()

    enabled = {k for k in ("greenhouse", "lever", "ashby", "smartrecruiters", "workday") if sources.get(k, True)}
    day = today_key()
    for b in boards_to_poll(session, enabled, int(s.get("max_learned_boards_per_run", 400))):
        if b.last_polled_at and b.last_polled_at > utcnow() - timedelta(hours=18):
            continue
        # curated (seed/user) boards jump ahead of leftover learned-board tasks
        queue.enqueue(session, "poll_board", f"poll:{b.id}:{day}", {"board_id": b.id}, rc.run.id, max_attempts=3,
                      priority_delay_s=-86400 if b.origin in ("seed", "user") else 0)
    session.commit()

    def handle(task: Task):
        rc.heartbeat()
        b = session.get(Board, task.payload["board_id"])
        if b is None or not b.active:
            return
        if b.last_polled_at and b.last_polled_at > utcnow() - timedelta(hours=18):
            return  # already polled (e.g. a leftover task from an earlier run)
        company = b.company
        kwargs = {}
        if b.platform in ("workday", "smartrecruiters"):
            cats = allowed_categories(s)
            kwargs["prefilter"] = lambda t: classify_category(t) in cats
            kwargs["known"] = set(session.scalars(select(Job.ats_job_id).where(
                Job.ats_platform == b.platform, Job.ats_board == b.token)).all())
        session.commit()  # no open transaction during network I/O
        # --- network only below this line until results are written ---
        if b.platform == "greenhouse" and not company:
            company = ats.greenhouse_company(rc.client, b.token) or b.token
        company = company or b.token
        posts = ats.LISTERS[b.platform](rc.client, b.token, company, **kwargs)
        b.company = b.company or company
        rc.board_cache[(b.platform, b.token)] = {p.ats_job_id: p for p in posts}
        for p in posts:
            p.board_metro = b.metro
            ingest(p, False)
        b.last_polled_at, b.jobs_found, b.consecutive_failures, b.last_error = utcnow(), len(posts), 0, None
        stats["boards_polled"] += 1

    def on_error(task: Task, e: Exception) -> bool:
        b = session.get(Board, task.payload["board_id"])
        if b is not None:
            b.consecutive_failures += 1
            b.last_error = str(e)[:500]
            b.last_polled_at = utcnow()
            if isinstance(e, PermanentHTTPError) and e.status in (404, 410) or b.consecutive_failures >= 5:
                b.active = False
                rc.log("warn", f"Deactivated board {b.platform}:{b.token} ({e})", "discovery")
                return False
        stats["board_errors"] += 1
        rc.log("warn", f"Board poll failed ({task.payload}): {type(e).__name__}: {e}", "discovery")
        return not isinstance(e, PermanentHTTPError)

    q = queue.drain(session, "poll_board", handle, rc.worker, rc.should_stop, on_error)
    stats["board_tasks_failed"] = q["failed"] + q["dead"]
    session.commit()
    out = dict(stats)
    out["skipped"] = dict(skipped.most_common())
    out["target"] = int(s.get("daily_discovery_target", 30))
    return out


# =================================================================== 2. verification

EXPIRED_RE = re.compile(r"no longer (available|accepting|open)|position has been filled|job (?:is |has been )?(closed|expired|removed)|"
                        r"this (job|position|posting) (is no longer|has expired|has been closed)|page (?:you are looking for )?(?:was )?not found|"
                        r"requisition (?:is )?(?:closed|no longer)", re.I)


def _merge_detail(job: Job, p: RawPosting) -> None:
    if p.description_text and len(p.description_text) > len(job.description_text or ""):
        job.description_text = p.description_text
    if job.salary_min is None and p.salary_min is not None:
        job.salary_min, job.salary_max, job.salary_period, job.salary_text = p.salary_min, p.salary_max, p.salary_period, p.salary_text
    if p.locations and not job.locations:
        job.locations, job.location = p.locations, "; ".join(p.locations[:4])
    if p.date_posted and not job.date_posted:
        job.date_posted = p.date_posted
    ts = summer_2027_status(job.title, job.description_text or "", job.terms if "Summer 2027" in (job.terms or []) else None)
    job.feed_flags = {**(job.feed_flags or {}), "term_status": ts}


def _expire(rc: RunContext, job: Job, why: str) -> None:
    job.verified_active, job.verified_at, job.verification_note = False, utcnow(), why
    if job.status not in {s.value for s in POST_SUBMISSION}:
        set_status(rc.session, job, JobStatus.EXPIRED, why, run_id=rc.run.id, next_action="")


def board_listing(rc: RunContext, platform: str, token: str, company: str, interns_only: bool = True) -> dict:
    key = (platform, token) if interns_only else (platform, token, "all")
    if key not in rc.board_cache:
        posts = ats.LISTERS[platform](rc.client, token, company, interns_only=interns_only)
        rc.board_cache[key] = {p.ats_job_id: p for p in posts}
    return rc.board_cache[key]


def verify_one(rc: RunContext, job: Job) -> str:
    plat, board, jid = job.ats_platform, job.ats_board, job.ats_job_id
    try:
        if plat in ("greenhouse", "lever", "ashby") and board and jid:
            p = board_listing(rc, plat, board, job.company).get(jid)
            if p is None:
                if plat == "greenhouse":
                    p, _ = ats.greenhouse_job(rc.client, board, jid, job.company)
                elif plat == "lever":
                    p = ats.lever_job(rc.client, board, jid, job.company)
                else:
                    p = board_listing(rc, plat, board, job.company, interns_only=False).get(jid)
                    if p is None:
                        raise ats.PostingGone(f"ashby {board}/{jid}")
            _merge_detail(job, p)
            job.verified_active, job.verification_note = True, f"Active on {plat} job board API"
        elif plat == "smartrecruiters" and board and jid:
            _merge_detail(job, ats.smartrecruiters_job(rc.client, board, jid, job.company))
            job.verified_active, job.verification_note = True, "Active on SmartRecruiters API"
        elif plat == "workday" and board and jid:
            _merge_detail(job, ats.workday_job(rc.client, board, jid, job.company))
            job.verified_active, job.verification_note = True, "Active on employer Workday site"
        else:
            url = job.posting_url or job.apply_url
            try:
                r = rc.client.request("GET", url, check_robots=True)
            except RobotsDisallowed:
                job.verified_active, job.verification_note = None, "robots.txt disallows automated verification"
                job.verified_at = utcnow()
                return "unverifiable"
            text = html_to_text(r.text)[:40000]
            if EXPIRED_RE.search(text[:6000]):
                _expire(rc, job, "Employer page says the posting is closed")
                return "expired"
            if len(text) > 800 and len(text) > len(job.description_text or ""):
                job.description_text = text
                job.feed_flags = {**(job.feed_flags or {}), "description_source": "page_text"}
            job.verified_active, job.verification_note = True, "Employer page reachable"
        job.verified_at = utcnow()
        if job.eligibility_category == "description_unavailable" and len(job.description_text or "") > 200                 and job.status == JobStatus.ELIGIBILITY_REVIEW.value:
            job.eligibility, job.eligibility_category = "unknown", None
            set_status(rc.session, job, JobStatus.DISCOVERED, "Posting text retrieved; re-checking eligibility", run_id=rc.run.id)
        return "active"
    except ats.PostingGone:
        _expire(rc, job, "Posting no longer exists on the employer's job board")
        return "expired"
    except PermanentHTTPError as e:
        if e.status in (404, 410):
            _expire(rc, job, f"Employer page returned HTTP {e.status}")
            return "expired"
        job.verified_active, job.verified_at, job.verification_note = None, utcnow(), f"HTTP {e.status} during verification"
        return "unverifiable"


def stage_verification(rc: RunContext) -> dict:
    session = rc.session
    day = today_key()
    stale = utcnow() - timedelta(days=3)
    jobs = session.scalars(select(Job).where(
        Job.status.notin_([s.value for s in TERMINAL]), Job.is_test.is_(False),
        (Job.verified_at.is_(None)) | (Job.verified_at < stale))).all()

    def prio(j: Job):
        tier = min((metro_of(l)[1] for l in (j.locations or ["x"])), key=lambda t: ["preferred", "nearby", "remote", "other", "non_us"].index(t))
        return (["preferred", "nearby", "remote", "other", "non_us"].index(tier), -(j.date_posted or datetime(2000, 1, 1)).timestamp())
    for j in sorted(jobs, key=prio):
        queue.enqueue(session, "verify_job", f"verify:{j.id}:{day}", {"job_id": j.id}, rc.run.id, max_attempts=4)
    session.commit()
    stats = Counter()

    def handle(task: Task):
        rc.heartbeat()
        job = session.get(Job, task.payload["job_id"])
        if job is None or job.status in {s.value for s in TERMINAL}:
            return
        stats[verify_one(rc, job)] += 1

    def on_error(task: Task, e: Exception) -> bool:
        stats["errors"] += 1
        return log_task_errors(rc, "verification", lambda ex: isinstance(ex, (TransientHTTPError, TimeoutError)))(task, e)

    q = queue.drain(session, "verify_job", handle, rc.worker, rc.should_stop, on_error)
    remaining = session.scalar(select(func.count(Task.id)).where(Task.kind == "verify_job", Task.status == "queued")) or 0
    return {**dict(stats), "queued_for_next_run": remaining, "task_failures": q["failed"] + q["dead"]}


# =================================================================== 3. deduplication (safety net)

def stage_deduplication(rc: RunContext) -> dict:
    """upsert_posting dedupes at insert time; this pass merges any remaining
    same-requisition rows created by later-arriving details (e.g. req ids found
    in descriptions)."""
    from hunt.dedupe import _loc_overlap
    from hunt.discovery.normalize import extract_req_id, normalize_title
    session = rc.session
    merged = 0
    rows = session.scalars(select(Job).where(Job.status.in_([JobStatus.DISCOVERED.value, JobStatus.ELIGIBILITY_REVIEW.value,
                                                                JobStatus.MATCHED.value]))).all()
    groups: dict[tuple, list[Job]] = {}
    for j in rows:
        groups.setdefault((j.company_norm, normalize_title(j.title)), []).append(j)
    for _, js in groups.items():
        if len(js) < 2:
            continue
        js.sort(key=lambda j: (0 if j.ats_platform in adapters.AUTO_PLATFORMS else 1, j.id))
        keep = js[0]
        for d in js[1:]:
            r1 = extract_req_id(keep.ats_job_id, keep.posting_url, keep.description_text[:3000] if keep.description_text else None)
            r2 = extract_req_id(d.ats_job_id, d.posting_url, d.description_text[:3000] if d.description_text else None)
            same = (r1 and r2 and r1 == r2) or (not (r1 and r2) and _loc_overlap(keep.locations or [], d.locations or []))
            if not same or d.application is not None or d.resume_versions:
                continue
            keep.sources = sorted(set((keep.sources or []) + (d.sources or [])))
            if len(d.description_text or "") > len(keep.description_text or ""):
                keep.description_text = d.description_text
            session.delete(d)
            merged += 1
    session.commit()
    return {"merged": merged}


# =================================================================== 4. eligibility

def purge_listings(rc: RunContext, ineligible_only: bool = False) -> Counter:
    """Remove listings older than max_posting_age_days (posting date, or first seen when
    the posting has none) and ineligible ones, with their prepared files. Anything you
    applied to, or may have applied to, is kept for your records."""
    session, s = rc.session, rc.settings
    days = int(s.get("max_posting_age_days", 30))
    cutoff = utcnow() - timedelta(days=days)
    keep = {x.value for x in POST_SUBMISSION} | {JobStatus.APPLYING.value}
    root = (get_settings().data_dir / "applications").resolve()
    known = set(session.scalars(select(RemovedListing.canonical_key)).all())
    stats: Counter = Counter()
    removed: set[int] = set()
    files: list[str] = []
    for job in session.scalars(select(Job).where(Job.is_test.is_(False), Job.status.notin_(list(keep)))).all():
        app = job.application
        if app is not None and (app.date_applied or "mark Submitted" in (job.next_action or "")):
            continue  # sent, or possibly sent (unconfirmed / interrupted)
        if job.status == JobStatus.INELIGIBLE.value or job.eligibility == "ineligible":
            reason = "ineligible"
        elif not ineligible_only and (job.date_posted or job.date_discovered or utcnow()) < cutoff:
            reason = f"older than {days} days"
        else:
            continue
        if job.canonical_key not in known:
            session.add(RemovedListing(canonical_key=job.canonical_key, company=job.company, title=(job.title or "")[:500],
                                       reason=reason))
            known.add(job.canonical_key)
        files.extend(a.path for a in job.artifacts if a.path)  # generated resumes / screenshots
        # clear references between this listing's own rows first, so the deletes can't
        # trip a foreign key (the application points at its resume and screenshot)
        if app is not None:
            app.resume_version_id = app.cover_letter_artifact_id = app.evidence_artifact_id = None
            session.flush()
        for rv in list(job.resume_versions):
            session.delete(rv)
        session.flush()
        session.expire(job, ["resume_versions"])  # already deleted; don't cascade to them again
        session.delete(job)
        session.flush()
        removed.add(job.id)
        stats[reason] += 1
        if len(removed) % 100 == 0:
            session.commit()
            _remove_files(files, root)  # only once the rows are really gone
            files.clear()
    if removed:
        for t in session.scalars(select(Task).where(Task.status == "queued")).all():
            if (t.payload or {}).get("job_id") in removed:
                t.status = "cancelled"
    session.commit()
    _remove_files(files, root)
    if removed:
        rc.log("info", "Cleanup: removed " + ", ".join(f"{n} {r}" for r, n in stats.items()), "cleanup")
    return stats


def _remove_files(paths: list[str], root: Path) -> None:
    """Delete generated files of removed listings (only inside data/applications)."""
    for p in paths:
        try:
            f = Path(p).resolve()
            if root in f.parents and f.is_file():
                f.unlink()
                d = f.parent
                while d != root and root in d.parents and not any(d.iterdir()):
                    d.rmdir()
                    d = d.parent
        except OSError:
            pass


def stage_cleanup(rc: RunContext) -> dict:
    """Every run starts by removing listings that are too old or ineligible."""
    stats = purge_listings(rc)
    return {"removed": sum(stats.values()), **{k.replace(" ", "_"): v for k, v in stats.items()},
            "max_age_days": int(rc.settings.get("max_posting_age_days", 30))}


def stage_eligibility(rc: RunContext) -> dict:
    session = rc.session
    stats = Counter()
    policy = rc.settings.get("eligibility", {})
    auth = rc.profile.get("work_authorization") or {}
    # Wait for verification: classifying before the full posting text is fetched
    # would park jobs in review on missing information.
    jobs = session.scalars(select(Job).where(Job.status == JobStatus.DISCOVERED.value,
                                             Job.eligibility == "unknown",
                                             (Job.verified_at.isnot(None)) | (Job.is_test.is_(True)))).all()
    for job in jobs:
        if rc.should_stop():
            stats["incomplete_time_budget_remaining"] = sum(1 for j in jobs if j.eligibility == "unknown")
            break
        text = job.description_text or ""
        res = classify(text, job.title, (job.feed_flags or {}).get("sponsorship"), policy, auth)
        verdict, category = res.verdict, res.category
        if not text.strip() and verdict == "eligible":
            verdict, category = "review", "description_unavailable"
            res.reasons.append({"category": category, "verdict": "review", "rule": "Full posting text could not be retrieved; check work-authorization terms on the employer site", "quote": ""})
        job.eligibility, job.eligibility_category, job.eligibility_reasons, job.work_auth_text = verdict, category, res.reasons, res.snippets
        term = (job.feed_flags or {}).get("term_status")
        if term == "other_term":
            set_status(session, job, JobStatus.INELIGIBLE, "Posting is for a different term than Summer 2027", run_id=rc.run.id)
            stats["wrong_term"] += 1
        elif verdict == "ineligible":
            set_status(session, job, JobStatus.INELIGIBLE, f"Work authorization: {category}", run_id=rc.run.id, next_action="")
        elif verdict == "review":
            set_status(session, job, JobStatus.ELIGIBILITY_REVIEW, f"Needs review: {category}", run_id=rc.run.id,
                       next_action="Review work-authorization language and approve or reject")
        stats[verdict] += 1
        stats[f"cat:{category}"] += 1
    rc.session.commit()
    gone = purge_listings(rc, ineligible_only=True)  # newly ineligible ones go in the same run
    if gone:
        stats["removed_ineligible"] += sum(gone.values())
    session.commit()
    return dict(stats)


# =================================================================== 5. matching

def scoring_version(rc: RunContext) -> str:
    s = rc.settings
    raw = json.dumps([rc.master_version, s.get("scoring_weights"), s.get("preferred_cities"), s.get("include_nearby_metros"),
                      s.get("include_remote_us"), s.get("include_other_us"), s.get("lesser_known_boost"), s.get("whitelist"),
                      rc.profile.get("confirmed_extra_skills"), 6], sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


def stage_matching(rc: RunContext) -> dict:
    session = rc.session
    v = scoring_version(rc)
    stats = Counter()
    counts = dict(session.execute(select(Job.company_norm, func.count(Job.id)).group_by(Job.company_norm)).all())
    # Later pre-submission stages are re-scored too (score only, no status change) so
    # the dashboard always reflects the current scoring logic and settings.
    jobs = session.scalars(select(Job).where(
        Job.status.in_([JobStatus.DISCOVERED.value, JobStatus.ELIGIBILITY_REVIEW.value, JobStatus.MATCHED.value,
                        JobStatus.RESUME_GENERATED.value, JobStatus.READY_TO_APPLY.value, JobStatus.BLOCKED.value,
                        JobStatus.FAILED.value]),
        Job.eligibility.in_(["eligible", "review"]))).all()
    black = {c.lower() for c in rc.settings.get("blacklist", [])}
    min_score = rc.settings.get("min_match_score", 55)
    for job in jobs:
        if job.company.lower() in black or job.company_norm in black:
            set_status(session, job, JobStatus.INELIGIBLE, "Blacklisted company", run_id=rc.run.id)
            continue
        sb = job.score_breakdown or {}
        fresh = sb.get("_v") == v and sb.get("_elig") == job.eligibility and job.match_score is not None
        if not fresh:  # eligibility is part of the score, so a changed verdict re-scores
            r = score_job(job, rc.master, rc.profile, rc.settings, rc.applicant, counts)
            job.match_score, job.match_tier, job.priority, job.lesser_known = r.score, r.tier, r.priority, r.lesser_known
            job.score_breakdown = {**r.breakdown, "_v": v, "_elig": job.eligibility}
            job.score_explanation = r.explanation
            stats[r.tier] += 1
        else:
            stats["unchanged"] += 1
        gates = (job.score_explanation or {}).get("gates", [])
        app = job.application
        if "undergrad_only" in gates and not (app and (app.date_applied or "mark Submitted" in (job.next_action or ""))):
            # you'll be an MS student, so undergraduate-only internships are removed like ineligible ones
            set_status(session, job, JobStatus.INELIGIBLE, "Undergraduate-only internship", run_id=rc.run.id,
                       next_action="Not applicable: undergraduate students only")
            stats["undergrad_only"] += 1
            continue
        if job.status == JobStatus.DISCOVERED.value:
            blocking = [g for g in gates if g in BLOCKING_GATES]
            nxt = (f"Not applicable: {', '.join(blocking)}" if blocking else
                   "Below minimum match score" if job.match_score < min_score else "Queued for resume tailoring")
            set_status(session, job, JobStatus.MATCHED, f"Scored {job.match_score}", run_id=rc.run.id, next_action=nxt)
    session.commit()
    if stats["undergrad_only"]:
        purge_listings(rc, ineligible_only=True)
    return dict(stats)


# =================================================================== 6. resume generation

def generated_today(session: Session) -> int:
    since = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return session.scalar(select(func.count(ResumeVersion.id)).join(Job).where(
        ResumeVersion.created_at >= since, Job.is_test.is_(False))) or 0


def tailor_job(rc: RunContext, job: Job) -> ResumeVersion:
    session = rc.session
    session.commit()  # LLM / form fetches below must not run inside a write transaction
    res = tailor_resume(rc.master, rc.profile, job, rc.settings, rc.llm)
    pdf, fitted, notes = render_fitted(res.resume, rc.settings.get("resume", {}).get("one_page", True))
    check = ats_check(pdf, fitted, res.matched_keywords, rc.settings.get("resume", {}).get("one_page", True), RESUME_FILENAME)
    policy = rc.settings.get("resume", {}).get("cover_letters", "when_required")
    form = None
    if adapters.platform_of(job) in ("greenhouse", "mock") and policy != "never":
        try:
            _, form, _ = adapters.fetch_form(job, rc.client)
        except Exception:  # noqa: BLE001
            form = None
    cover = None
    if needs_cover_letter(job, form, policy):
        paras, meta = generate_cover_letter(rc.master, rc.profile, job, job.score_explanation, rc.applicant.skills, rc.llm)
        cover = (render_cover_letter(paras, rc.master["basics"], job.company), meta)
    # --- database writes ---
    n = session.scalar(select(func.count(ResumeVersion.id)).where(ResumeVersion.job_id == job.id)) or 0
    version_id = f"rv-{job.uid}-{n + 1:03d}"
    art = save_artifact(session, job, "resume", RESUME_FILENAME, pdf, "application/pdf", version=version_id)
    changes = res.changes + [{"type": "layout", "detail": n_} for n_ in notes]
    if cover is not None:
        changes.append({"type": "cover_letter", "detail": f"Generated ({'LLM' if cover[1].get('llm_used') else 'template'}), fact-checked"})
    rv = ResumeVersion(version_id=version_id, job_id=job.id, artifact_id=art.id, master_version=rc.master_version,
                       keywords=res.keywords[:40], matched_keywords=res.matched_keywords, changes=changes,
                       factcheck=res.factcheck, ats_check=check, match_score=job.match_score, llm_used=res.llm_used,
                       content=fitted)
    session.add(rv)
    session.flush()
    if cover is not None:
        cl = save_artifact(session, job, "cover_letter", COVER_FILENAME, cover[0], "application/pdf", version=version_id)
        ensure_application(session, job).cover_letter_artifact_id = cl.id
    return rv


def stage_resumes(rc: RunContext) -> dict:
    session = rc.session
    s = rc.settings
    stats = Counter()
    cap = int(s.get("daily_resume_cap", 40)) - generated_today(session)
    if cap <= 0:
        return {"skipped": "daily resume cap reached"}
    min_score = s.get("min_match_score", 55)
    cands = session.scalars(select(Job).where(Job.status == JobStatus.MATCHED.value, Job.eligibility == "eligible",
                                              Job.match_score >= min_score).order_by(Job.priority.desc())).all()
    blocking = BLOCKING_GATES
    # the daily resume quota goes first to non-Workday postings from today / yesterday
    cands.sort(key=lambda j: (not fresh_non_workday(j), -(j.priority or 0)))
    picked = [j for j in cands if not (set((j.score_explanation or {}).get("gates", [])) & blocking)][:cap]
    for j in picked:
        queue.enqueue(session, "tailor", f"tailor:{j.id}:{rc.master_version}", {"job_id": j.id}, rc.run.id, max_attempts=3)
    session.commit()

    def handle(task: Task):
        rc.heartbeat()
        job = session.get(Job, task.payload["job_id"])
        if job is None or job.status != JobStatus.MATCHED.value:
            return
        rv = tailor_job(rc, job)
        set_status(session, job, JobStatus.RESUME_GENERATED, f"Resume {rv.version_id}", run_id=rc.run.id,
                   next_action="Preparing application")
        stats["generated"] += 1
        stats["llm_reworded"] += int(rv.llm_used)
        stats["ats_failed"] += int(not rv.ats_check.get("passed"))

    q = queue.drain(session, "tailor", handle, rc.worker, rc.should_stop, log_task_errors(rc, "resume_generation"))
    return {**dict(stats), "candidates": len(cands), "selected": len(picked), "task_failures": q["failed"] + q["dead"]}


# =================================================================== 7. applications

def stage_applications(rc: RunContext) -> dict:
    session = rc.session
    s = rc.settings
    stats = Counter()
    gate_reasons = Counter()
    stats["recovered_interrupted"] = recover_interrupted(session)
    session.commit()

    common = dict(profile=rc.profile, master=rc.master, settings=s, applicant_skills=rc.applicant.skills, llm=rc.llm)
    for job in session.scalars(select(Job).where(Job.status == JobStatus.RESUME_GENERATED.value)).all():
        if rc.should_stop():
            break
        app = job.application
        cl = session.get(Artifact, app.cover_letter_artifact_id) if app and app.cover_letter_artifact_id else None
        try:
            prepare_application(session, job, client=rc.client, run_id=rc.run.id, cover_letter_artifact=cl,
                                browser_getter=rc.browser if rc.browser_factory else None, **common)
            session.commit()
        except Exception as e:  # noqa: BLE001  (one bad posting must not stop the stage)
            session.rollback()
            stats["prepare_errors"] += 1
            rc.log("error", f"Preparing {job.company} failed: {type(e).__name__}: {str(e)[:200]}", "application", job.id)
            continue
        stats["prepared"] += 1
    # Re-check every application blocked on questions against the current profile and
    # saved answers: profile updates or answers given in the dashboard unblock it.
    # (CAPTCHA / login / unconfirmed-submission blocks have no unresolved questions and
    # are left for you to resolve.)
    for job in session.scalars(select(Job).where(Job.status == JobStatus.BLOCKED.value)).all():
        app = job.application
        if rc.should_stop():
            break
        if not app or not app.unresolved:
            continue
        cl = session.get(Artifact, app.cover_letter_artifact_id) if app.cover_letter_artifact_id else None
        try:
            prepare_application(session, job, client=rc.client, run_id=rc.run.id, cover_letter_artifact=cl,
                                browser_getter=rc.browser if rc.browser_factory else None, **common)
            session.commit()
        except Exception as e:  # noqa: BLE001
            session.rollback()
            stats["prepare_errors"] += 1
            rc.log("error", f"Re-checking {job.company} failed: {type(e).__name__}: {str(e)[:200]}", "application", job.id)
            continue
        stats["re_prepared"] += 1
        stats["unblocked"] += int(job.status == JobStatus.READY_TO_APPLY.value)

    cands = session.scalars(select(Job).join(Application).where(
        Job.status.in_([JobStatus.READY_TO_APPLY.value, JobStatus.FAILED.value]), Application.attempts < 3
    ).order_by(Job.is_test.desc(), Job.priority.desc())).all()
    if not get_settings().enable_mock_ats:  # mock fixtures only run with `hunt dry-run`
        cands = [j for j in cands if not j.is_test]
    for job in cands:
        gates = submission_gates(session, job, s, rc.profile, rc.dry_run)
        if not gates:
            queue.enqueue(session, "submit", f"submit:{job.id}:{job.application.attempts}", {"job_id": job.id}, rc.run.id, max_attempts=2)
        elif all(g.startswith("Dry run") for g in gates):
            stats["would_submit_if_live"] += 1
            rc.log("info", f"[dry run] would submit {job.company} – {job.title} via {job.application.platform}", "application", job.id)
        else:
            for g in gates:
                gate_reasons[g.split(":")[0]] += 1
    session.commit()

    def handle(task: Task):
        rc.heartbeat()
        job = session.get(Job, task.payload["job_id"])
        if job is None:
            return
        outcome = submit_application(session, job, browser=rc.browser(), dry_run=rc.dry_run, run_id=rc.run.id, **common)
        stats[f"outcome:{outcome.split(':')[0]}"] += 1
        rc.log("info", f"Submission {job.company} – {job.title}: {outcome}", "application", job.id)
        if outcome == "failed":
            raise RuntimeError(job.application.last_error or "submission failed")

    on_error = log_task_errors(rc, "application")

    if session.scalar(select(func.count(Task.id)).where(Task.kind == "submit", Task.status == "queued")):
        try:
            q = queue.drain(session, "submit", handle, rc.worker, rc.should_stop, on_error)
            stats["submit_task_failures"] = q["failed"] + q["dead"]
        except RuntimeError as e:
            rc.log("error", f"Browser automation unavailable: {e}", "application")
    out = dict(stats)
    out["not_submitted_reasons"] = dict(gate_reasons.most_common(10))
    return out


# =================================================================== 8. confirmation

def stage_confirmation(rc: RunContext) -> dict:
    from hunt.notify.email_monitor import check_inbox, imap_configured
    if not imap_configured():
        return {"skipped": "Gmail/IMAP not configured"}
    try:
        return check_inbox(rc.session, rc.run.id)
    except Exception as e:  # noqa: BLE001
        rc.log("error", f"Email monitor failed: {e}", "confirmation")
        return {"error": str(e)}


# =================================================================== 9. reporting

def stage_reporting(rc: RunContext) -> dict:
    from hunt.notify.report import build_report, deliver_report
    md, html_doc, summary = build_report(rc.session, rc.run)
    art = save_artifact(rc.session, None, "report", f"report_run{rc.run.id}.html", html_doc.encode("utf-8"), "text/html")
    rc.run.report_artifact_id = art.id
    notify(rc.session, "report", f"Daily report: {summary['headline']}", md[:4000])
    rc.session.commit()
    delivered = deliver_report(md, html_doc, summary)
    return {**summary, "emailed": delivered}


# =================================================================== 0. apply first

BLOCKING_GATES = {"phd_required", "not_summer_2027", "non_us_location", "graduation_window", "undergrad_only"}


def finish_queue_jobs(session: Session, assisted: set[str], include_test: bool = False) -> list[Job]:
    """Prepared applications waiting for you to click Finish application, in the order
    Finish all opens them: single-page forms first (quick), then Workday; newest first within each."""
    # Ashby too: its automatic submit nearly always meets a picture check, so you finish it
    finishable = (set(assisted or set()) | {"workday", "ashby"}) & adapters.ASSIST_PLATFORMS
    single_page = list(finishable - {"workday"})
    rows = session.scalars(select(Job).join(Application).where(
        Job.id.isnot(None) if include_test else Job.is_test.is_(False),
        or_(and_(Job.status == JobStatus.READY_TO_APPLY.value, Application.platform.in_(list(finishable))),
            # plus jobs stopped at an emailed code / CAPTCHA, which Finish application also completes
            and_(Job.status == JobStatus.BLOCKED.value, Application.apply_method == "browser",
                 Job.next_action.like("%Finish application%")),
            # and single-page forms waiting on questions only you can answer: the window fills
            # the rest and leaves those for you to answer in the form
            and_(Job.status == JobStatus.BLOCKED.value, Application.apply_method == "browser",
                 Application.platform.in_(single_page), Job.next_action.like("Answer %question%")),
        ))).all()
    # 1) non-Workday postings from today / yesterday, 2) other non-Workday, 3) Workday;
    # most recently posted first within each; best match breaks ties
    return sorted(rows, key=lambda j: (j.application.platform == "workday", not fresh_non_workday(j),
                                       -posted_at(j).timestamp(), -(j.match_score or 0), j.id))


FRESH_HOURS = 48  # "the day before or the day of searching"


def posted_at(job: Job) -> datetime:
    return job.date_posted or job.date_discovered or job.created_at


def fresh_non_workday(job: Job) -> bool:
    """A Greenhouse / Ashby / Lever / other non-Workday posting from today or yesterday."""
    platform = (job.application.platform if job.application else None) or job.ats_platform
    return platform != "workday" and posted_at(job) >= utcnow() - timedelta(hours=FRESH_HOURS)


def _finish_queue(session: Session, assisted: set[str]) -> int:
    """How many prepared applications are waiting for you to click Finish application."""
    return len(finish_queue_jobs(session, assisted))


def _apply_first_candidates(rc: RunContext, platforms: list[str], limit: int) -> list[Job]:
    if limit <= 0 or not platforms:
        return []
    s = rc.settings
    min_score = s.get("min_auto_apply_score", 70) if s.get("apply_mode") == "auto" else s.get("min_match_score", 55)
    rows = rc.session.scalars(select(Job).where(
        Job.status == JobStatus.MATCHED.value, Job.eligibility == "eligible",
        Job.is_test.is_(False) if not get_settings().enable_mock_ats else Job.id.isnot(None),
        Job.match_score >= min_score, Job.ats_platform.in_(platforms)).order_by(Job.priority.desc())).all()
    return [j for j in rows if not (set((j.score_explanation or {}).get("gates", [])) & BLOCKING_GATES)][:limit]


def _tailor_now(rc: RunContext, jobs: list[Job]) -> int:
    made = 0
    for job in jobs:
        if rc.should_stop():
            break
        rc.heartbeat()
        try:
            rv = tailor_job(rc, job)
        except Exception as e:  # noqa: BLE001  (one bad posting must not stop the loop)
            rc.session.rollback()
            rc.log("error", f"Tailoring failed for {job.company}: {type(e).__name__}: {e}", "apply_first", job.id)
            continue
        set_status(rc.session, job, JobStatus.RESUME_GENERATED, f"Resume {rv.version_id} (apply-first)", run_id=rc.run.id,
                   next_action="Preparing application")
        rc.session.commit()
        made += 1
    return made


def stage_apply_first(rc: RunContext) -> dict:
    """Submit before discovering: repeat (submit everything ready -> tailor the next best
    jobs) until today's confirmed submissions reach the target, candidates run out, or
    the loop's time budget ends. Sites that require you to confirm you're human are
    prepared for Finish application instead of being attempted."""
    s, session = rc.settings, rc.session
    target = int(s.get("daily_submission_target") or 0)
    if target <= 0:
        return {"skipped": "no daily submission target set"}
    if not s.get("automation_enabled", True) or s.get("paused"):
        return {"skipped": "automation disabled or paused"}
    goal = min(target, int(s.get("daily_application_cap") or target))
    loop_end = utcnow() + timedelta(minutes=int(s.get("apply_loop_max_minutes") or 120))
    rc.stage_deadline = min(rc.stage_deadline or rc.deadline, loop_end)
    assisted = set(s.get("assisted_only_platforms") or [])
    mock = get_settings().enable_mock_ats
    auto_platforms = sorted(p for p in adapters.AUTO_PLATFORMS if p not in assisted and (p != "mock" or mock))
    # sites you finish yourself; Workday always (it needs your sign-in)
    assisted_platforms = sorted({p for p in adapters.ASSIST_PLATFORMS if p in assisted} | {"workday"})
    stats: Counter = Counter()
    start = submitted_today(session, mock)
    stop_reason = None
    for round_no in range(1, 31):
        if rc.should_stop():
            stop_reason = "time budget reached"
            break
        if submitted_today(session, mock) >= goal:
            stop_reason = "target reached"
            break
        stats["rounds"] += 1
        res = stage_applications(rc)  # prepare tailored jobs, re-check blocked ones, submit everything ready
        for k, v in res.items():
            if isinstance(v, int) and v:
                stats[f"apply_{k}"] += v
        need = goal - submitted_today(session, mock)
        if need <= 0:
            stop_reason = "target reached"
            break
        if rc.dry_run:
            stop_reason = "dry run: one round only (nothing is submitted)"
            break
        batch = _apply_first_candidates(rc, auto_platforms, min(need, 10))
        if not batch:
            # no automatic candidates left: keep enough ready in your Finish queue
            want = need - _finish_queue(session, assisted)
            batch = _apply_first_candidates(rc, assisted_platforms, min(want, 10))
            if not batch:
                stop_reason = "no more candidates above your score threshold"
                break
            stats["tailored_for_finish"] += len(batch)
        made = _tailor_now(rc, batch)
        stats["tailored"] += made
        if made == 0:
            stop_reason = "could not tailor more candidates"
            break
    end = submitted_today(session, mock)
    out = dict(stats)
    out.update(submitted_now=end - start, submitted_today=end, goal=goal, target_reached=int(end >= goal),
               finish_queue=_finish_queue(session, assisted), stop_reason=stop_reason or "round limit")
    rc.log("info", f"Apply-first: {end}/{goal} submitted today ({end - start} this run); "
                   f"{out['finish_queue']} waiting for Finish application; stopped: {out['stop_reason']}", "apply_first")
    return out


STAGES: list[tuple[str, Callable[[RunContext], dict]]] = [
    ("cleanup", stage_cleanup),
    ("apply_first", stage_apply_first),
    ("discovery", stage_discovery),
    ("verification", stage_verification),
    ("deduplication", stage_deduplication),
    ("eligibility", stage_eligibility),
    ("matching", stage_matching),
    ("resume_generation", stage_resumes),
    ("application", stage_applications),
    ("confirmation", stage_confirmation),
    ("reporting", stage_reporting),
]
