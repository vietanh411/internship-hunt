"""Pipeline run orchestration: single-run lock, per-stage records, failure
isolation, cancellation, and time budget."""
from __future__ import annotations

import logging
import os
import socket
import traceback
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from hunt.config import get_settings
from hunt.db import new_session, utcnow
from hunt.llm import get_llm
from hunt.matching import build_applicant
from hunt.models import Lock, PipelineRun, StageRun
from hunt.pipeline import queue
from hunt.pipeline.stages import STAGES, Cancelled, RunContext
from hunt.profile_store import get_master_resume, get_profile
from hunt.settings_store import get_automation
from hunt.workflow import notify, run_log
from hunt.http import PoliteClient

log = logging.getLogger(__name__)

LOCK_NAME = "pipeline"
# Fraction of the *remaining* run budget each network-heavy stage may use, so a slow
# source cannot starve later stages. Unfinished work stays queued for the next run.
STAGE_SHARE = {"apply_first": 0.65, "discovery": 0.35, "verification": 0.45, "resume_generation": 0.6}
LOCK_STALE_MIN = 20


class RunAlreadyActive(Exception):
    pass


def _owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def lock_owner(run_id: int) -> str:
    return f"{_owner()}#run{run_id}"


def acquire_lock(session, run_id: int) -> None:
    now = utcnow()
    lock = session.get(Lock, LOCK_NAME)
    if lock is not None:
        if lock.heartbeat_at > now - timedelta(minutes=LOCK_STALE_MIN):
            raise RunAlreadyActive(f"A pipeline run is already active ({lock.owner})")
        session.delete(lock)  # stale: previous process died without releasing
        session.flush()
    session.add(Lock(name=LOCK_NAME, owner=lock_owner(run_id), acquired_at=now, heartbeat_at=now))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise RunAlreadyActive("Another run acquired the lock")
    # We hold the exclusive lock, so any other run still marked running is orphaned.
    for old in session.scalars(select(PipelineRun).where(PipelineRun.status == "running", PipelineRun.id != run_id)).all():
        old.status, old.finished_at, old.error = "failed", now, "Abandoned (process stopped without finishing)"
    session.commit()


def release_lock(session, owner: str) -> None:
    """Only the process that acquired the lock may release it."""
    lock = session.get(Lock, LOCK_NAME)
    if lock is not None and lock.owner == owner:
        session.delete(lock)
        session.commit()


def active_run(session) -> PipelineRun | None:
    lock = session.get(Lock, LOCK_NAME)
    if lock is None or lock.heartbeat_at < utcnow() - timedelta(minutes=LOCK_STALE_MIN):
        return None
    return session.scalar(select(PipelineRun).where(PipelineRun.status == "running").order_by(PipelineRun.id.desc()))


def run_pipeline(trigger: str = "manual", dry_run: bool = False, only: list[str] | None = None,
                 max_minutes: int = 150, browser_factory=None) -> int:
    """Run the pipeline once. Returns the run id. Raises RunAlreadyActive."""
    s = get_settings()
    session = new_session()
    owner: str | None = None
    try:
        if active_run(session) is not None:
            raise RunAlreadyActive("A pipeline run is already active")
        settings = get_automation(session)
        run = PipelineRun(trigger=trigger, dry_run=dry_run, status="running", stats={})
        session.add(run)
        session.commit()
        try:
            acquire_lock(session, run.id)
            owner = lock_owner(run.id)
        except RunAlreadyActive:
            run.status, run.finished_at, run.error = "cancelled", utcnow(), "Another run is active"
            session.commit()
            raise
        if not settings.get("automation_enabled", True) and trigger == "schedule":
            run.status, run.finished_at, run.error = "cancelled", utcnow(), "Automation disabled"
            session.commit()
            return run.id
        if settings.get("paused") and trigger == "schedule":
            run.status, run.finished_at, run.error = "cancelled", utcnow(), "Automation paused"
            session.commit()
            return run.id

        profile = get_profile(session)
        master_version, master = get_master_resume(session)
        if browser_factory is None:
            from hunt.apply.browser import Browser, playwright_available
            if playwright_available():
                browser_factory = lambda: Browser(headless=s.headless)  # noqa: E731
        rc = RunContext(session=session, run=run, dry_run=dry_run, settings=settings, profile=profile, master=master,
                        master_version=master_version, applicant=build_applicant(master, profile), client=PoliteClient(),
                        llm=get_llm(), deadline=utcnow() + timedelta(minutes=max_minutes), worker=_owner(),
                        seeds_path=s.seeds_dir / "companies.yaml", browser_factory=browser_factory)
        # We hold the exclusive run lock, so any task still marked running belongs to a
        # process that died: put it back in the queue immediately.
        released = queue.release_stale(session, minutes=0)
        if released:
            run_log(session, run.id, "warn", f"Re-queued {released} task(s) left running by a previous process")
        session.commit()

        failures = 0
        cancelled = False
        for name, fn in STAGES:
            if only and name not in only:
                continue
            remaining = rc.deadline - utcnow()
            rc.stage_deadline = utcnow() + remaining * STAGE_SHARE.get(name, 1.0)
            sr = StageRun(run_id=run.id, stage=name, status="running")
            session.add(sr)
            run.current_stage = name
            run.heartbeat_at = utcnow()
            _heartbeat_lock(session)
            session.commit()
            try:
                rc.check_cancel()
                result = fn(rc) or {}
                sr.status = "succeeded"
                sr.checkpoint = result
                sr.processed = int(sum(v for k, v in result.items() if isinstance(v, int) and not k.startswith("target")))
                run.stats = {**(run.stats or {}), name: result}
            except Cancelled:
                session.rollback()
                sr.status, sr.error = "cancelled", "Cancelled by user"
                cancelled = True
            except Exception as e:  # noqa: BLE001  (failure isolation: continue with later stages)
                session.rollback()
                failures += 1
                sr.status, sr.error = "failed", f"{type(e).__name__}: {e}"
                run_log(session, run.id, "error", f"Stage {name} failed: {e}\n{traceback.format_exc()[-2500:]}", name)
                log.exception("stage %s failed", name)
            sr.finished_at = utcnow()
            session.commit()
            if cancelled:
                break
        run.status = "cancelled" if cancelled else ("partial" if failures else "succeeded")
        run.finished_at = utcnow()
        run.current_stage = None
        llm = rc.llm
        run.stats = {**(run.stats or {}), "_meta": {"http_requests": rc.client.request_count, "llm_calls": llm.calls,
                                                     "llm_failures": llm.failures, "llm_available": llm.available}}
        if failures:
            notify(session, "error", f"Run #{run.id} finished with {failures} failed stage(s)", None)
        session.commit()
        rc.close()
        return run.id
    finally:
        if owner is not None:
            try:
                release_lock(session, owner)
            except Exception:  # noqa: BLE001
                session.rollback()
        session.close()


def _heartbeat_lock(session) -> None:
    lock = session.get(Lock, LOCK_NAME)
    if lock:
        lock.heartbeat_at = utcnow()


def request_cancel() -> bool:
    session = new_session()
    try:
        run = active_run(session)
        if run is None:
            return False
        run.cancel_requested = True
        session.commit()
        return True
    finally:
        session.close()
