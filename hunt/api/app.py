"""FastAPI application: REST API for the Summer 2027 Internship Command Center and
the static dashboard build."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
import re
import zipfile
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from hunt.api import serializers as ser
from hunt.config import get_settings
from hunt.db import new_session, utcnow
from hunt.models import (
    POST_SUBMISSION,
    Application,
    Artifact,
    AuditLog,
    Board,
    EmailMessage,
    Job,
    JobStatus,
    MasterResume,
    Notification,
    PendingQuestion,
    PipelineRun,
    ResumeVersion,
    RunLog,
    ScreeningAnswer,
    StageRun,
    StatusEvent,
    Task,
)
from hunt.profile_store import (
    auto_apply_blockers,
    get_master_resume,
    get_profile,
    import_master_resume,
    onboarding_status,
    update_profile,
)
from hunt.settings_store import DEFAULT_AUTOMATION, get_automation, update_automation
from hunt.workflow import audit, set_status

log = logging.getLogger(__name__)


def db():
    s = new_session()
    try:
        yield s
    finally:
        s.close()


# ------------------------------------------------------------------ auth

def _token() -> str | None:
    pw = get_settings().dashboard_password
    if not pw:
        return None
    key = (get_settings().secret_key or "hunt").encode()
    return hmac.new(key, pw.encode(), hashlib.sha256).hexdigest()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from hunt.bootstrap import init_db
    from hunt.pipeline.scheduler import start_scheduler, stop_scheduler
    init_db()
    start_scheduler()
    yield
    stop_scheduler()


def create_app(start_background: bool = True) -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Internship Hunt", version="1.0", lifespan=lifespan if start_background else None)

    @app.middleware("http")
    async def auth_mw(request: Request, call_next):
        tok = _token()
        path = request.url.path
        if tok and path.startswith("/api") and path not in ("/api/login", "/api/health"):
            if not hmac.compare_digest(request.cookies.get("hunt_session", ""), tok):
                return JSONResponse({"detail": "Login required"}, status_code=401)
        return await call_next(request)

    @app.post("/api/login")
    def login(response: Response, payload: dict = Body(...)):
        tok = _token()
        if tok is None:
            return {"ok": True, "auth": "disabled"}
        if not hmac.compare_digest(str(payload.get("password", "")), get_settings().dashboard_password or ""):
            raise HTTPException(401, "Wrong password")
        response.set_cookie("hunt_session", tok, httponly=True, samesite="strict", max_age=30 * 86400)
        return {"ok": True}

    @app.get("/api/health")
    def health():
        return {"ok": True, "time": utcnow().isoformat() + "Z"}

    _register_routes(app)

    if s.enable_mock_ats:
        from hunt.mock_ats.app import router as mock_router
        from hunt.mock_ats.workday import router as mock_wd_router
        app.include_router(mock_wd_router, prefix="/mock-ats/workday")
        app.include_router(mock_router, prefix="/mock-ats")

    dist = s.frontend_dist
    if (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = dist / path
            if path and f.is_file() and dist in f.resolve().parents:
                return FileResponse(f)
            # never cache the page shell: after an update it must point at the new bundle
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache, must-revalidate"})
    else:
        @app.get("/", include_in_schema=False)
        def no_ui():
            return HTMLResponse("<h1>Summer 2027 Hunt API</h1><p>Dashboard not built. Run <code>npm run build</code> in "
                                "<code>frontend/</code>. API docs at <a href='/docs'>/docs</a>.</p>")
    return app


# ------------------------------------------------------------------ routes

def _register_routes(app: FastAPI) -> None:  # noqa: C901
    # ---------------- status / overview
    @app.get("/api/status")
    def status(session: Session = Depends(db)):
        from hunt.apply.browser import playwright_available
        from hunt.llm import get_llm
        from hunt.notify.email_monitor import imap_configured
        from hunt.notify.report import smtp_configured
        from hunt.pipeline.runner import active_run
        from hunt.pipeline.scheduler import next_run_time, scheduler_running
        from hunt.security import encryption_enabled
        s = get_settings()
        prof = get_profile(session)
        last = session.scalar(select(PipelineRun).where(PipelineRun.status != "running").order_by(PipelineRun.id.desc()))
        act = active_run(session)
        nxt = next_run_time()
        warnings = []
        if not encryption_enabled():
            warnings.append("HUNT_SECRET_KEY not set: sensitive profile fields are stored unencrypted.")
        if not s.allow_real_submissions:
            warnings.append("Real submissions are disabled (HUNT_ALLOW_REAL_SUBMISSIONS=false). Applications are prepared but never sent.")
        if not get_llm().available:
            warnings.append("Claude API not configured: resume rewording and cover letters use deterministic templates.")
        blockers = auto_apply_blockers(prof)
        if blockers:
            warnings.append("Onboarding incomplete: " + ", ".join(blockers))
        if s.host not in ("127.0.0.1", "localhost") and not s.dashboard_password:
            warnings.append("Dashboard is exposed without a password (set HUNT_DASHBOARD_PASSWORD).")
        settings = get_automation(session)
        from hunt.apply.engine import submitted_today
        from hunt.pipeline.stages import _finish_queue
        return {
            "submitted_today": submitted_today(session),
            "daily_submission_target": settings.get("daily_submission_target"),
            "finish_queue": _finish_queue(session, set(settings.get("assisted_only_platforms") or [])),
            "scheduler_running": scheduler_running(), "schedule": f"Daily {s.schedule_hour:02d}:{s.schedule_minute:02d} {s.timezone}",
            "next_run": nxt.isoformat() if nxt else None, "last_run": ser.run(last) if last else None,
            "active_run": ser.run(act) if act else None, "automation_enabled": settings["automation_enabled"],
            "paused": settings["paused"], "apply_mode": settings["apply_mode"], "llm_available": get_llm().available,
            "llm_model": s.llm_model, "imap_configured": imap_configured(), "smtp_configured": smtp_configured(),
            "encryption_enabled": encryption_enabled(), "allow_real_submissions": s.allow_real_submissions,
            "playwright_available": playwright_available(), "onboarding_blockers": blockers, "warnings": warnings,
            "database": "postgresql" if s.database_url.startswith("postgres") else "sqlite",
        }

    @app.get("/api/overview")
    def overview(session: Session = Depends(db)):
        real = Job.is_test.is_(False)
        cnt = lambda *conds: session.scalar(select(func.count(Job.id)).where(real, *conds)) or 0  # noqa: E731
        status_counts = dict(session.execute(select(Job.status, func.count(Job.id)).where(real).group_by(Job.status)).all())
        submitted_like = sum(status_counts.get(s.value, 0) for s in POST_SUBMISSION)
        responded = sum(status_counts.get(s, 0) for s in ("assessment", "interview", "offer", "rejected"))
        awaiting = (session.scalar(select(func.count(Job.id)).join(Application).where(
            real, Job.status == JobStatus.READY_TO_APPLY.value, Application.approved.is_(False))) or 0)
        resumes = session.scalar(select(func.count(func.distinct(ResumeVersion.job_id))).join(Job).where(real)) or 0
        # daily series (last 14 days, UTC dates)
        since = utcnow() - timedelta(days=14)
        days = [(since + timedelta(days=i + 1)).date() for i in range(14)]
        def by_day(rows):
            c = Counter(r.date() for r in rows if r)
            return [c.get(d, 0) for d in days]
        disc = by_day(session.scalars(select(Job.date_discovered).where(real, Job.date_discovered >= since)).all())
        res = by_day(session.scalars(select(ResumeVersion.created_at).join(Job).where(real, ResumeVersion.created_at >= since)).all())
        sub = by_day(session.scalars(select(Application.date_applied).join(Job).where(real, Application.date_applied >= since)).all())
        top = session.scalars(select(Job).where(real, Job.eligibility == "eligible",
                                                Job.status.notin_(["expired", "ineligible", "rejected", "withdrawn"]))
                              .order_by(Job.priority.desc().nullslast()).limit(10)).all()
        return {
            "total_discovered": cnt(), "eligible": cnt(Job.eligibility == "eligible"),
            "eligibility_review": status_counts.get("eligibility_review", 0),
            "ineligible": cnt(Job.eligibility == "ineligible"),
            "high_match": cnt(Job.match_score >= 70, Job.eligibility == "eligible"),
            "resumes_generated": resumes, "applications_submitted": submitted_like, "awaiting_review": awaiting,
            "blocked": status_counts.get("blocked", 0), "failed": status_counts.get("failed", 0),
            "interviews": status_counts.get("interview", 0), "offers": status_counts.get("offer", 0),
            "response_rate": round(responded / submitted_like, 3) if submitted_like else None,
            "open_questions": session.scalar(select(func.count(PendingQuestion.id)).where(PendingQuestion.status == "open")) or 0,
            "status_counts": status_counts,
            "tier_counts": dict(session.execute(select(Job.match_tier, func.count(Job.id)).where(real, Job.match_tier.isnot(None)).group_by(Job.match_tier)).all()),
            "series": {"days": [d.isoformat() for d in days], "discovered": disc, "resumes": res, "submitted": sub},
            "week": {"discovered": sum(disc[-7:]), "resumes": sum(res[-7:]), "submitted": sum(sub[-7:])},
            "today": {"discovered": disc[-1], "resumes": res[-1], "submitted": sub[-1]},
            "top_opportunities": [ser.job_summary(j) for j in top],
        }

    # ---------------- jobs
    @app.get("/api/jobs")
    def list_jobs(session: Session = Depends(db), q: str | None = None, company: str | None = None, location: str | None = None,
                  category: str | None = None, min_score: float | None = None, max_score: float | None = None,
                  eligibility: str | None = None, status: str | None = None, salary_min: float | None = None,
                  posted_after: str | None = None, lesser_known: bool | None = None, has_resume: bool | None = None,
                  include_test: bool = False, sort: str = "priority", order: str = "desc",
                  page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500)):
        stmt = select(Job)
        if not include_test:
            stmt = stmt.where(Job.is_test.is_(False))
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(or_(func.lower(Job.title).like(like), func.lower(Job.company).like(like),
                                  func.lower(Job.description_text).like(like)))
        if company:
            stmt = stmt.where(func.lower(Job.company).like(f"%{company.lower()}%"))
        if location:
            stmt = stmt.where(func.lower(Job.location).like(f"%{location.lower()}%"))
        if category:
            stmt = stmt.where(Job.category.in_(category.split(",")))
        if min_score is not None:
            stmt = stmt.where(Job.match_score >= min_score)
        if max_score is not None:
            stmt = stmt.where(Job.match_score <= max_score)
        if eligibility:
            stmt = stmt.where(Job.eligibility.in_(eligibility.split(",")))
        if status:
            stmt = stmt.where(Job.status.in_(status.split(",")))
        if salary_min is not None:
            stmt = stmt.where(or_(Job.salary_max >= salary_min, Job.salary_min >= salary_min))
        if posted_after:
            try:
                stmt = stmt.where(Job.date_posted >= datetime.fromisoformat(posted_after.replace("Z", "")))
            except ValueError:
                raise HTTPException(400, "posted_after must be ISO date")
        if lesser_known is not None:
            stmt = stmt.where(Job.lesser_known.is_(lesser_known))
        if has_resume is not None:
            sub = select(ResumeVersion.job_id)
            stmt = stmt.where(Job.id.in_(sub) if has_resume else Job.id.notin_(sub))
        total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = {"priority": Job.priority, "score": Job.match_score, "posted": Job.date_posted, "discovered": Job.date_discovered,
               "company": Job.company, "title": Job.title, "status": Job.status, "salary": Job.salary_max}.get(sort, Job.priority)
        stmt = stmt.order_by(col.desc().nullslast() if order == "desc" else col.asc().nullslast(), Job.id.desc())
        rows = session.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
        facets = {
            "categories": dict(session.execute(select(Job.category, func.count(Job.id)).where(Job.is_test.is_(False)).group_by(Job.category)).all()),
            "statuses": dict(session.execute(select(Job.status, func.count(Job.id)).where(Job.is_test.is_(False)).group_by(Job.status)).all()),
            "eligibility": dict(session.execute(select(Job.eligibility, func.count(Job.id)).where(Job.is_test.is_(False)).group_by(Job.eligibility)).all()),
        }
        return {"items": [ser.job_summary(j) for j in rows], "total": total, "page": page, "page_size": page_size, "facets": facets}

    def _job(session: Session, job_id: int) -> Job:
        j = session.get(Job, job_id)
        if j is None:
            raise HTTPException(404, "Job not found")
        return j

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: int, session: Session = Depends(db)):
        j = _job(session, job_id)
        d = ser.job_detail(j)
        d["questions"] = [ser.question(q) for q in session.scalars(select(PendingQuestion).where(PendingQuestion.job_id == j.id)).all()]
        d["emails"] = [{"subject": e.subject, "sender": e.sender, "category": e.category, "received_at": ser.iso(e.received_at)}
                       for e in session.scalars(select(EmailMessage).where(EmailMessage.job_id == j.id)).all()]
        return d

    def _pdf(a: Artifact, filename: str | None = None, inline: bool = False) -> Response:
        disp = "inline" if inline else "attachment"
        return Response(a.content, media_type=a.content_type,
                        headers={"Content-Disposition": f'{disp}; filename="{filename or a.filename}"'})

    @app.get("/api/jobs/{job_id}/resume")
    def job_resume(job_id: int, inline: bool = False, session: Session = Depends(db)):
        j = _job(session, job_id)
        if not j.resume_versions:
            raise HTTPException(404, "No tailored resume yet")
        return _pdf(session.get(Artifact, j.resume_versions[-1].artifact_id), None, inline)

    @app.get("/api/resumes/{version_id}/pdf")
    def resume_pdf(version_id: str, inline: bool = False, session: Session = Depends(db)):
        rv = session.scalar(select(ResumeVersion).where(ResumeVersion.version_id == version_id))
        if rv is None:
            raise HTTPException(404)
        return _pdf(session.get(Artifact, rv.artifact_id), None, inline)

    @app.get("/api/jobs/{job_id}/cover-letter")
    def cover_letter(job_id: int, inline: bool = False, session: Session = Depends(db)):
        j = _job(session, job_id)
        if not j.application or not j.application.cover_letter_artifact_id:
            raise HTTPException(404, "No cover letter")
        return _pdf(session.get(Artifact, j.application.cover_letter_artifact_id), None, inline)

    @app.get("/api/artifacts/{artifact_id}")
    def artifact(artifact_id: int, inline: bool = True, session: Session = Depends(db)):
        a = session.get(Artifact, artifact_id)
        if a is None:
            raise HTTPException(404)
        return _pdf(a, None, inline)

    @app.post("/api/jobs/{job_id}/approve")
    def approve(job_id: int, session: Session = Depends(db)):
        j = _job(session, job_id)
        if j.application is None:
            raise HTTPException(409, "Application not prepared yet")
        j.application.approved, j.application.approved_at = True, utcnow()
        if j.status == JobStatus.READY_TO_APPLY.value:
            j.next_action = "Approved – will be submitted on the next run (or Submit now)"
        audit(session, "user", "approve_application", "job", j.id)
        session.commit()
        return ser.job_summary(j)

    @app.post("/api/jobs/{job_id}/eligibility")
    def set_eligibility(job_id: int, payload: dict = Body(...), session: Session = Depends(db)):
        j = _job(session, job_id)
        verdict = payload.get("verdict")
        if verdict not in ("eligible", "ineligible"):
            raise HTTPException(400, "verdict must be eligible or ineligible")
        prev = j.eligibility
        j.eligibility = verdict
        j.eligibility_reasons = (j.eligibility_reasons or []) + [{"category": "user_override", "verdict": verdict,
                                                                   "rule": "Reviewed by applicant", "quote": payload.get("note") or ""}]
        if verdict == "ineligible":
            set_status(session, j, JobStatus.INELIGIBLE, "Marked ineligible by user", actor="user", next_action="")
        elif j.status in (JobStatus.ELIGIBILITY_REVIEW.value, JobStatus.INELIGIBLE.value, JobStatus.DISCOVERED.value):
            set_status(session, j, JobStatus.MATCHED, "Eligibility approved by user", actor="user", next_action="Queued for resume tailoring")
            if j.application:
                j.application.approved = True
        audit(session, "user", "eligibility_override", "job", j.id, previous=prev, verdict=verdict, note=payload.get("note"))
        session.commit()
        return ser.job_summary(j)

    MANUAL_STATUSES = {"submitted", "assessment", "interview", "offer", "rejected", "withdrawn", "ready_to_apply", "expired", "matched",
                       "skipped"}

    @app.post("/api/jobs/{job_id}/status")
    def change_status(job_id: int, payload: dict = Body(...), session: Session = Depends(db)):
        j = _job(session, job_id)
        new = payload.get("status")
        if new not in MANUAL_STATUSES:
            raise HTTPException(400, f"status must be one of {sorted(MANUAL_STATUSES)}")
        note = payload.get("note") or ""
        if new == "submitted":
            conf = (payload.get("confirmation") or "").strip()
            if not conf:
                raise HTTPException(400, "Marking as submitted requires confirmation details (e.g. confirmation email subject or number)")
            from hunt.apply.engine import ensure_application
            app_ = ensure_application(session, j)
            app_.date_applied = app_.date_applied or utcnow()
            app_.confirmation_text, app_.confirmation_source = conf, "user"
        set_status(session, j, new, note or f"Set by user to {new}", actor="user",
                   next_action=payload.get("next_action", "" if new in ("rejected", "withdrawn", "expired") else
                                           "Skipped – won't be offered again" if new == "skipped" else None))
        audit(session, "user", "status_change", "job", j.id, status=new, note=note)
        session.commit()
        return ser.job_summary(j)

    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: int, session: Session = Depends(db)):
        j = _job(session, job_id)
        if j.status not in (JobStatus.BLOCKED.value, JobStatus.FAILED.value):
            raise HTTPException(409, f"Cannot retry from status {j.status}")
        if j.application:
            j.application.attempt_token = None
            j.application.attempts = min(j.application.attempts, 1)
            if j.application.unresolved:
                open_q = session.scalar(select(func.count(PendingQuestion.id)).where(PendingQuestion.job_id == j.id, PendingQuestion.status == "open"))
                if open_q:
                    raise HTTPException(409, "Answer the open questions first")
        target = JobStatus.RESUME_GENERATED if j.resume_versions else JobStatus.MATCHED
        set_status(session, j, target, "Retry requested by user (submission state verified by user)", actor="user",
                   next_action="Will be re-prepared on the next run")
        audit(session, "user", "retry", "job", j.id)
        session.commit()
        return ser.job_summary(j)

    @app.post("/api/jobs/{job_id}/regenerate-resume")
    def regenerate(job_id: int, session: Session = Depends(db)):
        from hunt.http import PoliteClient
        from hunt.llm import get_llm
        from hunt.matching import build_applicant
        from hunt.pipeline.stages import RunContext, tailor_job
        j = _job(session, job_id)
        if j.status in {s.value for s in POST_SUBMISSION}:
            raise HTTPException(409, "Already submitted; the submitted resume is preserved")
        profile = get_profile(session)
        mv, master = get_master_resume(session)
        run = PipelineRun(trigger="manual-resume", status="succeeded", finished_at=utcnow())
        session.add(run)
        session.flush()
        rc = RunContext(session=session, run=run, dry_run=True, settings=get_automation(session), profile=profile,
                        master=master, master_version=mv, applicant=build_applicant(master, profile), client=PoliteClient(),
                        llm=get_llm(), deadline=utcnow() + timedelta(minutes=5), worker="api")
        rv = tailor_job(rc, j)
        if j.status in (JobStatus.MATCHED.value, JobStatus.BLOCKED.value, JobStatus.FAILED.value, JobStatus.READY_TO_APPLY.value):
            set_status(session, j, JobStatus.RESUME_GENERATED, f"Resume regenerated {rv.version_id}", actor="user",
                       next_action="Preparing application")
        session.commit()
        rc.client.close()
        return ser.resume_version(rv)

    @app.post("/api/jobs/{job_id}/notes")
    def notes(job_id: int, payload: dict = Body(...), session: Session = Depends(db)):
        j = _job(session, job_id)
        j.notes = payload.get("notes")
        session.commit()
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/interview.ics")
    def ics(job_id: int, start: str, minutes: int = 45, location: str = "", session: Session = Depends(db)):
        from zoneinfo import ZoneInfo
        from hunt.notify.ics import interview_ics
        j = _job(session, job_id)
        try:
            dt = datetime.fromisoformat(start)
        except ValueError:
            raise HTTPException(400, "start must be ISO datetime")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(get_settings().timezone))
        body = interview_ics(f"{j.uid}-{int(dt.timestamp())}", j.company, j.title, dt, minutes, location,
                             f"{j.posting_url}\n{j.next_action or ''}")
        return Response(body, media_type="text/calendar",
                        headers={"Content-Disposition": f'attachment; filename="interview-{j.uid}.ics"'})

    # ---------------- assisted finish (visible browser on this PC; you submit)
    @app.post("/api/jobs/{job_id}/assist")
    def assist_start(job_id: int, session: Session = Depends(db)):
        from hunt.apply import assist
        _job(session, job_id)
        try:
            st = assist.start(job_id)
        except assist.AssistBusy as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
        audit(session, "user", "assist_start", "job", job_id)
        session.commit()
        return st

    @app.get("/api/assist")
    def assist_status():
        from hunt.apply import assist
        return assist.status()

    @app.post("/api/assist/cancel")
    def assist_cancel():
        from hunt.apply import assist
        return {"cancelled": assist.cancel()}

    @app.post("/api/assist/queue")
    def assist_queue_start(platform: str | None = None, record: bool = False, session: Session = Depends(db)):
        """Finish all: one window works through every application waiting for you.
        ?platform=workday limits it to one site; ?record=true saves a video, trace and
        screenshots under data/debug/recordings for troubleshooting."""
        from hunt.apply import assist
        try:
            st = assist.start_queue(platform=platform, hooks={"record": True} if record else None)
        except assist.AssistBusy as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
        audit(session, "user", "assist_queue_start", "job", None, total=(st.get("queue") or {}).get("total"))
        session.commit()
        return st

    @app.post("/api/assist/skip")
    def assist_skip():
        from hunt.apply import assist
        return {"skipped": assist.skip()}

    @app.post("/api/jobs/{job_id}/submit-now")
    def submit_now(job_id: int, session: Session = Depends(db)):
        from hunt.apply.engine import submission_gates
        j = _job(session, job_id)
        gates = submission_gates(session, j, get_automation(session), get_profile(session), dry_run=False)
        if gates:
            return JSONResponse({"submitted": False, "reasons": gates}, status_code=409)
        from hunt.pipeline.scheduler import run_in_background
        run_in_background(trigger="manual-submit", only=["application"], max_minutes=10)
        return {"submitted": "queued"}

    # ---------------- pipeline (kanban)
    @app.get("/api/pipeline")
    def pipeline(session: Session = Depends(db), limit: int = 60):
        cols = {}
        for st in JobStatus:
            rows = session.scalars(select(Job).where(Job.status == st.value, Job.is_test.is_(False))
                                   .order_by(Job.priority.desc().nullslast()).limit(limit)).all()
            total = session.scalar(select(func.count(Job.id)).where(Job.status == st.value, Job.is_test.is_(False))) or 0
            cols[st.value] = {"total": total, "items": [ser.job_summary(j) for j in rows]}
        return cols

    # ---------------- questions & answer library
    @app.get("/api/questions")
    def questions(status: str = "open", session: Session = Depends(db)):
        rows = session.scalars(select(PendingQuestion).where(PendingQuestion.status == status).order_by(PendingQuestion.id.desc())).all()
        return [ser.question(q, session.get(Job, q.job_id)) for q in rows]

    @app.post("/api/questions/{qid}/answer")
    def answer_question(qid: int, payload: dict = Body(...), session: Session = Depends(db)):
        q = session.get(PendingQuestion, qid)
        if q is None:
            raise HTTPException(404)
        ans = (payload.get("answer") or "").strip()
        if not ans:
            raise HTTPException(400, "answer required")
        q.answer, q.status, q.answered_at = ans, "answered", utcnow()
        # answers are always saved to the library (approved by the applicant) so the
        # application can be re-prepared; "reuse" controls whether other jobs match it.
        key = f"user_q{q.id}"
        from hunt.apply.answers import norm
        reuse = payload.get("save_to_library", True)
        pattern = payload.get("pattern") or ("^" + re.escape(norm(q.question)) + "$")
        row = session.scalar(select(ScreeningAnswer).where(ScreeningAnswer.key == key))
        if row is None:
            row = ScreeningAnswer(key=key, label=q.question, kind="fixed", source="user")
            session.add(row)
        row.answer, row.approved = ans, True
        row.patterns = [pattern] if reuse else ["^" + re.escape(norm(q.question)) + "$"]
        # identical open questions on other jobs are answered too when reuse is on
        if reuse:
            for other in session.scalars(select(PendingQuestion).where(PendingQuestion.status == "open",
                                                                       PendingQuestion.question == q.question)).all():
                other.answer, other.status, other.answered_at = ans, "answered", utcnow()
        _refresh_blocked(session, {q.job_id} | ({o.job_id for o in session.scalars(select(PendingQuestion).where(
            PendingQuestion.question == q.question, PendingQuestion.status == "answered")).all()} if reuse else set()))
        audit(session, "user", "answer_question", "question", q.id, reuse=reuse)
        session.commit()
        return ser.question(q)

    def _refresh_blocked(session: Session, job_ids: set[int]) -> None:
        """Drop answered questions from each application's unresolved list; once none
        remain, send the job back to be re-prepared on the next run."""
        for jid in job_ids:
            j = session.get(Job, jid)
            if j is None or j.application is None:
                continue
            open_ids = set(session.scalars(select(PendingQuestion.id).where(
                PendingQuestion.job_id == jid, PendingQuestion.status == "open")).all())
            j.application.unresolved = [u for u in (j.application.unresolved or []) if u.get("id") in open_ids]
            if not open_ids and j.status == JobStatus.BLOCKED.value and j.resume_versions:
                set_status(session, j, JobStatus.RESUME_GENERATED, "All questions answered", actor="user",
                           next_action="Questions answered – application will be re-prepared on the next run")

    @app.post("/api/questions/{qid}/dismiss")
    def dismiss_question(qid: int, session: Session = Depends(db)):
        q = session.get(PendingQuestion, qid)
        if q is None:
            raise HTTPException(404)
        q.status = "dismissed"
        _refresh_blocked(session, {q.job_id})
        session.commit()
        return ser.question(q)

    @app.get("/api/answers")
    def answers(session: Session = Depends(db)):
        rows = session.scalars(select(ScreeningAnswer).order_by(ScreeningAnswer.kind, ScreeningAnswer.id)).all()
        return [{"key": r.key, "label": r.label, "answer": r.answer, "kind": r.kind, "sensitive": r.sensitive,
                 "approved": r.approved, "source": r.source, "patterns": r.patterns, "updated_at": ser.iso(r.updated_at)} for r in rows]

    @app.patch("/api/answers/{key}")
    def patch_answer(key: str, payload: dict = Body(...), session: Session = Depends(db)):
        r = session.scalar(select(ScreeningAnswer).where(ScreeningAnswer.key == key))
        if r is None:
            raise HTTPException(404)
        if "answer" in payload:
            if r.source != "user":
                raise HTTPException(409, "Profile-derived answers are edited in Profile & Onboarding")
            r.answer = payload["answer"]
        if "approved" in payload:
            from hunt.apply.answers import WA_KEYS
            if r.key in WA_KEYS:
                raise HTTPException(409, "Work-authorization answers are approved by confirming them in Profile & Onboarding")
            r.approved = bool(payload["approved"])
        audit(session, "user", "update_answer", "answer", key, **{k: v for k, v in payload.items() if k != "answer"})
        session.commit()
        return {"ok": True}

    @app.delete("/api/answers/{key}")
    def delete_answer(key: str, session: Session = Depends(db)):
        r = session.scalar(select(ScreeningAnswer).where(ScreeningAnswer.key == key))
        if r is None or r.source != "user":
            raise HTTPException(409, "Only user-saved answers can be deleted")
        session.delete(r)
        session.commit()
        return {"ok": True}

    # ---------------- settings & automation controls
    @app.get("/api/settings")
    def get_settings_(session: Session = Depends(db)):
        return get_automation(session)

    @app.patch("/api/settings")
    def patch_settings(payload: dict = Body(...), session: Session = Depends(db)):
        unknown = set(payload) - set(DEFAULT_AUTOMATION)
        if unknown:
            raise HTTPException(400, f"Unknown settings: {sorted(unknown)}")
        if "apply_mode" in payload and payload["apply_mode"] not in ("auto", "review"):
            raise HTTPException(400, "apply_mode must be auto or review")
        for k in ("daily_discovery_target", "daily_application_cap", "daily_resume_cap", "min_match_score", "min_auto_apply_score"):
            if k in payload and not (isinstance(payload[k], (int, float)) and 0 <= payload[k] <= 1000):
                raise HTTPException(400, f"{k} must be a number between 0 and 1000")
        if "scoring_weights" in payload:
            w = payload["scoring_weights"]
            if not isinstance(w, dict) or any(not isinstance(v, (int, float)) or v < 0 for v in w.values()):
                raise HTTPException(400, "scoring_weights must be non-negative numbers")
        out = update_automation(session, payload)
        audit(session, "user", "update_settings", "settings", None, changed=sorted(payload))
        session.commit()
        return out

    @app.post("/api/automation/{action}")
    def automation(action: str, session: Session = Depends(db)):
        from hunt.pipeline.runner import request_cancel
        from hunt.pipeline.scheduler import run_in_background
        if action == "start":
            from hunt.pipeline.runner import active_run
            if active_run(session):
                raise HTTPException(409, "A run is already active")
            run_in_background(trigger="manual")
            return {"ok": True, "started": True}
        patches = {"pause": {"paused": True}, "resume": {"paused": False}, "enable": {"automation_enabled": True},
                   "disable": {"automation_enabled": False}}
        if action == "stop":
            return {"ok": True, "cancel_requested": request_cancel()}
        if action not in patches:
            raise HTTPException(400, "action must be start/stop/pause/resume/enable/disable")
        update_automation(session, patches[action])
        audit(session, "user", f"automation_{action}")
        session.commit()
        return {"ok": True, **get_automation(session)}

    # ---------------- runs
    @app.get("/api/runs")
    def runs(limit: int = 30, session: Session = Depends(db)):
        return [ser.run(r) for r in session.scalars(select(PipelineRun).order_by(PipelineRun.id.desc()).limit(limit)).all()]

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: int, session: Session = Depends(db)):
        r = session.get(PipelineRun, run_id)
        if r is None:
            raise HTTPException(404)
        return ser.run(r, with_stages=True)

    @app.get("/api/runs/{run_id}/logs")
    def run_logs(run_id: int, level: str | None = None, stage: str | None = None, limit: int = 500, session: Session = Depends(db)):
        stmt = select(RunLog).where(RunLog.run_id == run_id)
        if level:
            stmt = stmt.where(RunLog.level.in_(level.split(",")))
        if stage:
            stmt = stmt.where(RunLog.stage == stage)
        rows = session.scalars(stmt.order_by(RunLog.id.desc()).limit(limit)).all()
        return [{"id": l.id, "level": l.level, "stage": l.stage, "job_id": l.job_id, "message": l.message, "at": ser.iso(l.created_at)} for l in rows]

    @app.post("/api/runs")
    def start_run(payload: dict = Body(default={}), session: Session = Depends(db)):
        from hunt.pipeline.runner import active_run
        from hunt.pipeline.scheduler import run_in_background
        if active_run(session):
            raise HTTPException(409, "A run is already active")
        run_in_background(trigger="manual", dry_run=bool(payload.get("dry_run")), only=payload.get("stages"))
        return {"ok": True}

    @app.post("/api/runs/cancel")
    def cancel_run():
        from hunt.pipeline.runner import request_cancel
        return {"cancel_requested": request_cancel()}

    @app.get("/api/tasks")
    def tasks(status: str = "queued,dead", session: Session = Depends(db)):
        rows = session.scalars(select(Task).where(Task.status.in_(status.split(","))).order_by(Task.id.desc()).limit(300)).all()
        return [{"id": t.id, "kind": t.kind, "status": t.status, "attempts": t.attempts, "max_attempts": t.max_attempts,
                 "next_attempt_at": ser.iso(t.next_attempt_at), "last_error": t.last_error, "payload": t.payload} for t in rows]

    # ---------------- profile
    @app.get("/api/profile")
    def profile(session: Session = Depends(db)):
        p = get_profile(session)
        return {"profile": p, "onboarding": onboarding_status(p), "auto_apply_blockers": auto_apply_blockers(p)}

    @app.patch("/api/profile")
    def patch_profile(payload: dict = Body(...), session: Session = Depends(db)):
        from hunt.apply.answers import seed_library
        if "work_authorization" in payload and set(payload["work_authorization"]) - {"confirmed"}:
            audit(session, "user", "work_authorization_changed", "profile", 1, fields=sorted(payload["work_authorization"]))
        p = update_profile(session, payload)
        seed_library(session, p)
        audit(session, "user", "update_profile", "profile", 1, sections=sorted(payload))
        session.commit()
        return {"profile": p, "onboarding": onboarding_status(p), "auto_apply_blockers": auto_apply_blockers(p)}

    @app.get("/api/master-resume")
    def master_resume(session: Session = Depends(db)):
        v, data = get_master_resume(session)
        return {"version": v, "data": data}

    @app.put("/api/master-resume")
    def put_master_resume(payload: dict = Body(...), session: Session = Depends(db)):
        try:
            v = import_master_resume(session, payload, source="dashboard")
        except (ValueError, KeyError) as e:
            raise HTTPException(400, f"Invalid resume: {e}")
        audit(session, "user", "import_master_resume", "master_resume", v)
        session.commit()
        return {"version": v}

    # ---------------- boards
    @app.get("/api/boards")
    def boards(session: Session = Depends(db)):
        rows = session.scalars(select(Board).order_by(Board.origin, Board.platform, Board.company)).all()
        return [{"id": b.id, "platform": b.platform, "token": b.token, "company": b.company, "metro": b.metro,
                 "industry": b.industry, "origin": b.origin, "active": b.active, "last_polled_at": ser.iso(b.last_polled_at),
                 "last_error": b.last_error, "jobs_found": b.jobs_found} for b in rows]

    @app.post("/api/boards")
    def add_board(payload: dict = Body(...), session: Session = Depends(db)):
        plat, token = payload.get("platform"), (payload.get("token") or "").strip()
        if plat not in ("greenhouse", "lever", "ashby", "smartrecruiters", "workday") or not token:
            raise HTTPException(400, "platform and token required")
        b = Board(platform=plat, token=token, company=payload.get("company"), metro=payload.get("metro"), origin="user")
        session.add(b)
        session.commit()
        return {"id": b.id}

    @app.patch("/api/boards/{board_id}")
    def patch_board(board_id: int, payload: dict = Body(...), session: Session = Depends(db)):
        b = session.get(Board, board_id)
        if b is None:
            raise HTTPException(404)
        if "active" in payload:
            b.active = bool(payload["active"])
            b.consecutive_failures = 0
        session.commit()
        return {"ok": True}

    # ---------------- notifications & email
    @app.get("/api/notifications")
    def notifications(unread: bool = False, session: Session = Depends(db)):
        stmt = select(Notification).order_by(Notification.id.desc()).limit(100)
        if unread:
            stmt = stmt.where(Notification.read.is_(False))
        return [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "job_id": n.job_id, "read": n.read,
                 "created_at": ser.iso(n.created_at)} for n in session.scalars(stmt).all()]

    @app.post("/api/notifications/read-all")
    def read_all(session: Session = Depends(db)):
        for n in session.scalars(select(Notification).where(Notification.read.is_(False))).all():
            n.read = True
        session.commit()
        return {"ok": True}

    @app.get("/api/emails")
    def emails(session: Session = Depends(db)):
        rows = session.scalars(select(EmailMessage).order_by(EmailMessage.id.desc()).limit(200)).all()
        return [{"id": e.id, "sender": e.sender, "subject": e.subject, "category": e.category, "job_id": e.job_id,
                 "received_at": ser.iso(e.received_at), "applied_status": e.applied_status} for e in rows]

    @app.post("/api/email/check")
    def email_check(session: Session = Depends(db)):
        from hunt.notify.email_monitor import check_inbox, imap_configured
        if not imap_configured():
            raise HTTPException(409, "Set HUNT_IMAP_USER and HUNT_IMAP_PASSWORD (Gmail app password) to enable inbox monitoring")
        return check_inbox(session)

    # ---------------- data controls
    @app.get("/api/export")
    def export(session: Session = Depends(db)):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            jobs = session.scalars(select(Job)).all()
            z.writestr("jobs.json", json.dumps([ser.job_detail(j) for j in jobs], indent=1, default=str))
            z.writestr("profile.json", json.dumps(get_profile(session), indent=1, default=str))
            z.writestr("master_resume.json", json.dumps(get_master_resume(session)[1], indent=1))
            z.writestr("answers.json", json.dumps(answers(session), indent=1, default=str))
            z.writestr("audit_log.json", json.dumps([{"actor": a.actor, "action": a.action, "entity": a.entity, "entity_id": a.entity_id,
                                                        "details": a.details, "at": ser.iso(a.created_at)}
                                                       for a in session.scalars(select(AuditLog)).all()], indent=1, default=str))
            for rv in session.scalars(select(ResumeVersion)).all():
                a = session.get(Artifact, rv.artifact_id)
                j = session.get(Job, rv.job_id)
                z.writestr(f"resumes/{re.sub(r'[^A-Za-z0-9]+', '-', j.company)}/{rv.version_id}/{a.filename}", a.content)
        audit(session, "user", "export_data")
        session.commit()
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="summer2027-hunt-export-{utcnow():%Y%m%d}.zip"'})

    @app.post("/api/data/delete")
    def delete_data(payload: dict = Body(...), session: Session = Depends(db)):
        if payload.get("confirm") != "DELETE":
            raise HTTPException(400, 'Send {"confirm": "DELETE", "scope": "jobs"|"everything"}')
        scope = payload.get("scope", "jobs")
        for model in (PendingQuestion, EmailMessage, Notification, StatusEvent, Application, ResumeVersion, Artifact, Task, RunLog, StageRun):
            session.execute(delete(model))
        session.execute(delete(Job))
        if scope == "everything":
            from hunt.models import ProfileRow
            session.execute(delete(PipelineRun))
            session.execute(delete(ScreeningAnswer).where(ScreeningAnswer.source == "user"))
            session.execute(delete(ProfileRow))
        audit(session, "user", "delete_data", scope=scope)
        session.commit()
        if scope == "everything":
            from hunt.profile_store import bootstrap_profile
            bootstrap_profile(session)
            session.commit()
        return {"ok": True, "scope": scope}

    @app.get("/api/audit")
    def audit_log(limit: int = 200, session: Session = Depends(db)):
        return [{"actor": a.actor, "action": a.action, "entity": a.entity, "entity_id": a.entity_id, "details": a.details,
                 "at": ser.iso(a.created_at)} for a in session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()]


app = None


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
