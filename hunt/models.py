from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hunt.db import Base, utcnow


class JobStatus(str, enum.Enum):
    DISCOVERED = "discovered"
    ELIGIBILITY_REVIEW = "eligibility_review"
    MATCHED = "matched"
    RESUME_GENERATED = "resume_generated"
    READY_TO_APPLY = "ready_to_apply"
    APPLYING = "applying"
    SUBMITTED = "submitted"
    ASSESSMENT = "assessment"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    BLOCKED = "blocked"
    FAILED = "failed"
    EXPIRED = "expired"
    INELIGIBLE = "ineligible"
    SKIPPED = "skipped"  # you chose not to apply (Skip in Finish all); never offered again


# States from which the pipeline must never auto-advance or re-submit.
POST_SUBMISSION = {
    JobStatus.SUBMITTED, JobStatus.ASSESSMENT, JobStatus.INTERVIEW,
    JobStatus.OFFER, JobStatus.REJECTED, JobStatus.WITHDRAWN,
}
TERMINAL = POST_SUBMISSION | {JobStatus.EXPIRED, JobStatus.INELIGIBLE, JobStatus.SKIPPED}


class Eligibility(str, enum.Enum):
    UNKNOWN = "unknown"
    ELIGIBLE = "eligible"
    REVIEW = "review"
    INELIGIBLE = "ineligible"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    canonical_key: Mapped[str] = mapped_column(String(400), index=True)
    company: Mapped[str] = mapped_column(String(300))
    company_norm: Mapped[str] = mapped_column(String(300), index=True)
    title: Mapped[str] = mapped_column(String(500))
    ats_job_id: Mapped[str | None] = mapped_column(String(200))
    ats_platform: Mapped[str | None] = mapped_column(String(40), index=True)
    ats_board: Mapped[str | None] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(500))
    locations: Mapped[list] = mapped_column(JSON, default=list)
    remote_type: Mapped[str | None] = mapped_column(String(20))  # remote / hybrid / onsite / unknown
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    salary_period: Mapped[str | None] = mapped_column(String(20))  # hour / year / month
    salary_text: Mapped[str | None] = mapped_column(String(300))
    terms: Mapped[list] = mapped_column(JSON, default=list)
    internship_dates: Mapped[str | None] = mapped_column(String(200))
    degrees: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[str | None] = mapped_column(String(60), index=True)
    required_quals: Mapped[list] = mapped_column(JSON, default=list)
    preferred_quals: Mapped[list] = mapped_column(JSON, default=list)
    description_text: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[datetime | None] = mapped_column(DateTime)
    posting_url: Mapped[str | None] = mapped_column(String(1000))
    apply_url: Mapped[str | None] = mapped_column(String(1000))
    source: Mapped[str] = mapped_column(String(60))
    sources: Mapped[list] = mapped_column(JSON, default=list)
    date_posted: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    date_discovered: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    verified_active: Mapped[bool | None] = mapped_column(Boolean)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    verification_note: Mapped[str | None] = mapped_column(String(500))
    feed_flags: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. feed sponsorship label

    eligibility: Mapped[str] = mapped_column(String(20), default=Eligibility.UNKNOWN.value, index=True)
    eligibility_category: Mapped[str | None] = mapped_column(String(60))
    eligibility_reasons: Mapped[list] = mapped_column(JSON, default=list)
    work_auth_text: Mapped[list] = mapped_column(JSON, default=list)

    match_score: Mapped[float | None] = mapped_column(Float, index=True)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    score_explanation: Mapped[dict] = mapped_column(JSON, default=dict)
    match_tier: Mapped[str | None] = mapped_column(String(20))
    priority: Mapped[float | None] = mapped_column(Float, index=True)
    lesser_known: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[str] = mapped_column(String(30), default=JobStatus.DISCOVERED.value, index=True)
    status_updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    next_action: Mapped[str | None] = mapped_column(String(500))
    last_error: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    application: Mapped["Application | None"] = relationship(back_populates="job", uselist=False,
                                                             cascade="all, delete-orphan")
    resume_versions: Mapped[list["ResumeVersion"]] = relationship(back_populates="job", order_by="ResumeVersion.id",
                                                                  cascade="all, delete-orphan")
    events: Mapped[list["StatusEvent"]] = relationship(back_populates="job", order_by="StatusEvent.id",
                                                       cascade="all, delete-orphan")
    # artifacts, pending questions, emails, notifications: removed by ON DELETE CASCADE / SET NULL
    artifacts: Mapped[list["Artifact"]] = relationship(cascade="all, delete-orphan", passive_deletes=True,
                                                       foreign_keys="Artifact.job_id")
    questions: Mapped[list["PendingQuestion"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)

    __table_args__ = (Index("ix_jobs_status_score", "status", "match_score"),)


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    apply_method: Mapped[str] = mapped_column(String(30), default="unknown")  # browser / manual / email
    platform: Mapped[str | None] = mapped_column(String(40))
    resume_version_id: Mapped[int | None] = mapped_column(ForeignKey("resume_versions.id"))
    cover_letter_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id"))
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    unresolved: Mapped[list] = mapped_column(JSON, default=list)
    contradictions: Mapped[list] = mapped_column(JSON, default=list)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    attempt_token: Mapped[str | None] = mapped_column(String(64))
    date_applied: Mapped[datetime | None] = mapped_column(DateTime)
    confirmation_text: Mapped[str | None] = mapped_column(Text)
    confirmation_source: Mapped[str | None] = mapped_column(String(40))  # page / email / user
    evidence_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id"))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    job: Mapped[Job] = relationship(back_populates="application")


class Artifact(Base):
    """Binary files (resumes, cover letters, screenshots) stored in the database
    so the system works on hosts without persistent disks. A copy is also written
    under data/applications for convenience."""
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # resume / cover_letter / evidence / packet
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(100))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    sha256: Mapped[str] = mapped_column(String(64))
    path: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[str] = mapped_column(String(80), unique=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id"))
    master_version: Mapped[int] = mapped_column(Integer)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    matched_keywords: Mapped[list] = mapped_column(JSON, default=list)
    changes: Mapped[list] = mapped_column(JSON, default=list)
    factcheck: Mapped[dict] = mapped_column(JSON, default=dict)
    ats_check: Mapped[dict] = mapped_column(JSON, default=dict)
    match_score: Mapped[float | None] = mapped_column(Float)
    llm_used: Mapped[bool] = mapped_column(Boolean, default=False)
    content: Mapped[dict] = mapped_column(JSON, default=dict)  # the tailored structured resume
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    job: Mapped[Job] = relationship(back_populates="resume_versions")


class StatusEvent(Base):
    __tablename__ = "status_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(40), default="system")
    run_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    job: Mapped[Job] = relationship(back_populates="events")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trigger: Mapped[str] = mapped_column(String(30))  # schedule / manual / cli / github
    status: Mapped[str] = mapped_column(String(20), default="running")  # running / succeeded / partial / failed / cancelled
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    current_stage: Mapped[str | None] = mapped_column(String(40))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    report_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id"))

    stages: Mapped[list["StageRun"]] = relationship(back_populates="run", order_by="StageRun.id")


class StageRun(Base):
    __tablename__ = "stage_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)

    run: Mapped[PipelineRun] = relationship(back_populates="stages")


class RunLog(Base):
    __tablename__ = "run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    level: Mapped[str] = mapped_column(String(10))
    stage: Mapped[str | None] = mapped_column(String(40))
    job_id: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Task(Base):
    """Durable work queue item. Stages enqueue tasks and drain them; failed tasks
    are retried with exponential backoff across runs."""
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(300), unique=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued / running / done / dead / cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    locked_by: Mapped[str | None] = mapped_column(String(80))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Lock(Base):
    __tablename__ = "locks"

    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner: Mapped[str] = mapped_column(String(120))
    acquired_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SettingRow(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ProfileRow(Base):
    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    secret_blob: Mapped[str | None] = mapped_column(Text)  # Fernet token of sensitive JSON
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MasterResume(Base):
    __tablename__ = "master_resumes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    data: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ScreeningAnswer(Base):
    __tablename__ = "screening_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    label: Mapped[str] = mapped_column(String(300))
    patterns: Mapped[list] = mapped_column(JSON, default=list)
    answer: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))  # fixed / contextual / human
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(40), default="seed")  # seed / profile / user
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PendingQuestion(Base):
    __tablename__ = "pending_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    field_name: Mapped[str | None] = mapped_column(String(200))
    field_type: Mapped[str | None] = mapped_column(String(40))
    options: Mapped[list] = mapped_column(JSON, default=list)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str | None] = mapped_column(String(300))
    answer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open / answered / dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime)


class Board(Base):
    """A company job board on a supported ATS, polled directly by discovery."""
    __tablename__ = "boards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(30))
    token: Mapped[str] = mapped_column(String(300))  # board token, or host|tenant|site for workday
    company: Mapped[str | None] = mapped_column(String(300))
    metro: Mapped[str | None] = mapped_column(String(60))
    industry: Mapped[str | None] = mapped_column(String(80))
    origin: Mapped[str] = mapped_column(String(20), default="seed")  # seed / learned / user
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("platform", "token", name="uq_board_platform_token"),)


class EmailMessage(Base):
    __tablename__ = "email_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(String(500), unique=True)
    sender: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(1000))
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    category: Mapped[str] = mapped_column(String(40))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    snippet: Mapped[str | None] = mapped_column(Text)
    applied_status: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RemovedListing(Base):
    """A listing the cleanup step removed (too old / ineligible). Discovery skips it so it
    is not re-added later (a posting without a date would otherwise look new again)."""
    __tablename__ = "removed_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_key: Mapped[str] = mapped_column(String(400), unique=True)
    company: Mapped[str | None] = mapped_column(String(300))
    title: Mapped[str | None] = mapped_column(String(500))
    reason: Mapped[str] = mapped_column(String(40))
    removed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))  # blocked / report / email / error / offer
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
