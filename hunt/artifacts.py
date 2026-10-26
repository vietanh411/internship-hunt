"""Artifact storage: bytes in the database (portable across hosts) plus a copy at
data/applications/2027/<company>/<job_id>/<version>/<filename>."""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from hunt.config import get_settings
from hunt.models import Artifact, Job


def slug(s: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-").lower()
    return s[:maxlen] or "unknown"


def job_dir(job: Job) -> Path:
    jid = job.ats_job_id if job.ats_job_id and len(job.ats_job_id) <= 40 and "/" not in job.ats_job_id else job.uid
    return get_settings().applications_dir / "2027" / slug(job.company) / slug(jid, 50)


def save_artifact(session: Session, job: Job | None, kind: str, filename: str, content: bytes,
                  content_type: str, version: str | None = None) -> Artifact:
    path = None
    if job is not None:
        d = job_dir(job)
        target_dir = d / version if version else d
        target_dir.mkdir(parents=True, exist_ok=True)
        p = target_dir / filename
        p.write_bytes(content)
        if version:  # keep the latest version at the job folder root too
            shutil.copyfile(p, d / filename)
        path = str(p)
    a = Artifact(job_id=job.id if job else None, kind=kind, filename=filename, content_type=content_type,
                 content=content, sha256=hashlib.sha256(content).hexdigest(), path=path)
    session.add(a)
    session.flush()
    return a
