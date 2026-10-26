"""Job status transitions with an audit trail."""
from __future__ import annotations

from sqlalchemy.orm import Session

from hunt.db import utcnow
from hunt.models import AuditLog, Job, JobStatus, Notification, RunLog, StatusEvent


def set_status(
    session: Session,
    job: Job,
    status: JobStatus | str,
    reason: str | None = None,
    actor: str = "system",
    run_id: int | None = None,
    next_action: str | None = None,
) -> None:
    new = status.value if isinstance(status, JobStatus) else status
    JobStatus(new)  # validate
    if next_action is not None:
        job.next_action = next_action or None
    if job.status == new:
        return
    session.add(StatusEvent(job_id=job.id, from_status=job.status, to_status=new,
                            reason=reason, actor=actor, run_id=run_id))
    job.status = new
    job.status_updated_at = utcnow()


def audit(session: Session, actor: str, action: str, entity: str | None = None,
          entity_id: str | int | None = None, **details) -> None:
    session.add(AuditLog(actor=actor, action=action, entity=entity,
                         entity_id=str(entity_id) if entity_id is not None else None,
                         details=details))


def notify(session: Session, kind: str, title: str, body: str | None = None,
           job_id: int | None = None) -> None:
    session.add(Notification(kind=kind, title=title, body=body, job_id=job_id))


def run_log(session: Session, run_id: int | None, level: str, message: str,
            stage: str | None = None, job_id: int | None = None) -> None:
    session.add(RunLog(run_id=run_id, level=level, stage=stage, job_id=job_id, message=message[:4000]))
