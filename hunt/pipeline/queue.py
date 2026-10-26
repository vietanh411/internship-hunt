"""Durable DB-backed task queue with exponential backoff."""
from __future__ import annotations

from datetime import timedelta
from typing import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hunt.db import utcnow
from hunt.models import Task

BASE_BACKOFF_S = 60
MAX_BACKOFF_S = 6 * 3600


def backoff_seconds(attempts: int) -> int:
    return min(BASE_BACKOFF_S * 2 ** max(0, attempts - 1), MAX_BACKOFF_S)


def enqueue(session: Session, kind: str, dedupe_key: str, payload: dict | None = None, run_id: int | None = None,
            max_attempts: int = 5, priority_delay_s: int = 0) -> Task:
    existing = session.scalar(select(Task).where(Task.dedupe_key == dedupe_key))
    if existing is not None:
        return existing
    t = Task(kind=kind, dedupe_key=dedupe_key, payload=payload or {}, run_id=run_id, max_attempts=max_attempts,
             next_attempt_at=utcnow() + timedelta(seconds=priority_delay_s))
    session.add(t)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return session.scalar(select(Task).where(Task.dedupe_key == dedupe_key))
    return t


def claim(session: Session, kind: str, worker: str, limit: int = 1) -> list[Task]:
    q = (select(Task).where(Task.kind == kind, Task.status == "queued", Task.next_attempt_at <= utcnow())
         .order_by(Task.next_attempt_at, Task.id).limit(limit))
    if session.get_bind().dialect.name == "postgresql":
        q = q.with_for_update(skip_locked=True)
    tasks = session.scalars(q).all()
    now = utcnow()
    for t in tasks:
        t.status, t.locked_by, t.locked_at = "running", worker, now
    session.flush()
    return tasks


def complete(session: Session, task: Task) -> None:
    task.status = "done"
    task.locked_by = None
    task.last_error = None


def fail(session: Session, task: Task, error: str, retryable: bool = True) -> None:
    task.attempts += 1
    task.last_error = error[:4000]
    task.locked_by = None
    if retryable and task.attempts < task.max_attempts:
        task.status = "queued"
        task.next_attempt_at = utcnow() + timedelta(seconds=backoff_seconds(task.attempts))
    else:
        task.status = "dead"


def release_stale(session: Session, minutes: int = 30) -> int:
    cutoff = utcnow() - timedelta(minutes=minutes)
    n = 0
    for t in session.scalars(select(Task).where(Task.status == "running", Task.locked_at < cutoff)).all():
        t.status, t.locked_by = "queued", None
        n += 1
    return n


def drain(session: Session, kind: str, handler: Callable[[Task], None], worker: str,
          should_stop: Callable[[], bool], on_error: Callable[[Task, Exception], bool] | None = None) -> dict:
    """Process due tasks of one kind until none remain or should_stop() is true.
    handler raises to signal failure; on_error returns whether to retry."""
    stats = {"done": 0, "failed": 0, "dead": 0}
    while not should_stop():
        tasks = claim(session, kind, worker, limit=1)
        session.commit()
        if not tasks:
            break
        t = tasks[0]
        try:
            handler(t)
            complete(session, t)
            stats["done"] += 1
        except Exception as e:  # noqa: BLE001
            session.rollback()
            t = session.get(Task, t.id)
            retry = on_error(t, e) if on_error else True
            fail(session, t, f"{type(e).__name__}: {e}", retryable=retry)
            stats["dead" if t.status == "dead" else "failed"] += 1
        session.commit()
    return stats
