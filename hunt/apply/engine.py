"""Application preparation and submission with policy gates and idempotency."""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hunt.apply import adapters
from hunt.apply.answers import (
    Context,
    FormField,
    PlannedAnswer,
    answer_field,
    check_contradictions,
    load_library,
)
from hunt.apply.browser import SubmitResult, collect_fields, detect_captcha, requires_login, run_form, wait_for_form
from hunt.artifacts import save_artifact
from hunt.config import get_settings
from hunt.db import utcnow
from hunt.discovery.normalize import normalize_title
from hunt.llm import LLM
from hunt.models import Application, Artifact, Job, JobStatus, PendingQuestion, POST_SUBMISSION, ResumeVersion
from hunt.profile_store import auto_apply_blockers
from hunt.resume.factguard import check_free_text
from hunt.workflow import notify, set_status


def _known_text(job) -> str:
    """Posting text the fact guard may treat as known (title + description)."""
    return f"{job.title}\n{job.description_text or ''}"

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ contextual answers

ANSWER_SYSTEM = """You answer short open-ended internship application questions for one applicant.
Use only facts from the provided resume and the job posting. Do not invent experiences, numbers, skills, or company facts.
Be specific and plain; no filler such as "I am passionate" or "dream job". Write in first person. Stay under the word limit."""

ANSWER_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}


def make_contextual(master: dict, profile: dict, job: Job, explanation: dict, applicant_skills: set[str], llm: LLM | None):
    def lower_first(s: str) -> str:
        s = s.replace("**", "").rstrip(".")
        return s[0].lower() + s[1:] if s else s

    def template(question: str, words: int) -> str:
        ev = (explanation or {}).get("evidence") or []
        matched = (explanation or {}).get("matched_skills") or []
        ms = master["education"][0]
        if ev:
            e0 = ev[0]
            entry = e0["entry"]
            first = f"In my work on {entry.split(' @ ')[-1] if ' @ ' in entry else entry}, I {lower_first(e0['text'])}."
        else:
            first = ""
        q = question.lower()
        if any(k in q for k in ("describe", "tell us", "project", "walk us")):
            parts = [first] + ([f"I also {lower_first(ev[1]['text'])}."] if len(ev) > 1 else [])
            return " ".join(p for p in parts if p)
        skills = ", ".join(matched[:3]) if matched else "data analysis and software development"
        return (f"The {job.title} role at {job.company} matches the work I have done with {skills}. {first} "
                f"I am completing a {ms['degree']} at {ms['school']} ({ms['dates'].replace('Expected ', 'expected ')}) "
                f"and want a Summer 2027 internship where I can apply these skills to {job.company}'s projects.").strip()

    def generate(question: str, words: int) -> str | None:
        text = None
        if llm is not None and llm.available:
            import yaml
            resume = yaml.safe_dump({k: master[k] for k in ("education", "experience", "projects", "skills")}, allow_unicode=True, sort_keys=False)
            user = (f"Question: {question}\nWord limit: {words}\n\nResume:\n{resume}\n\nJob: {job.title} at {job.company}\n"
                    f"<posting>\n{(job.description_text or '')[:6000]}\n</posting>")
            data = llm.json(ANSWER_SYSTEM, user, ANSWER_SCHEMA, effort="medium", max_tokens=2000)
            if data and data.get("answer"):
                g = check_free_text(data["answer"], master, profile, _known_text(job), job.company, applicant_skills)
                if g.ok:
                    text = data["answer"].strip()
        if text is None:
            text = template(question, words)
            g = check_free_text(text, master, profile, _known_text(job), job.company, applicant_skills)
            if not g.ok:
                log.warning("template answer failed guard: %s", g.issues)
                return None
        w = text.split()
        if len(w) > words:
            text = " ".join(w[:words]).rstrip(",;") + "."
        return text

    return generate


# ------------------------------------------------------------------ preparation

def _ctx(session: Session, job: Job, profile: dict, master: dict, settings: dict, applicant_skills: set[str], llm: LLM | None) -> Context:
    lib, user = load_library(session)
    return Context(profile=profile, master=master, job=job, company=job.company, settings=settings,
                   applicant_skills=applicant_skills,
                   contextual=make_contextual(master, profile, job, job.score_explanation, applicant_skills, llm),
                   library=lib, user_answers=user, test_mode=bool(job.is_test))


def latest_resume(job: Job) -> ResumeVersion | None:
    return job.resume_versions[-1] if job.resume_versions else None


def application_key(canonical_key: str) -> str:
    """Idempotency key (max 120 chars). Long keys keep a readable prefix plus a hash of
    the whole key: plain truncation made distinct Workday postings collide."""
    key = f"app:{canonical_key}"
    if len(key) <= 120:
        return key
    return f"{key[:99]}#{hashlib.sha1(key.encode('utf-8')).hexdigest()[:20]}"


def ensure_application(session: Session, job: Job) -> Application:
    app = job.application
    if app is None:
        app = Application(job_id=job.id, idempotency_key=application_key(job.canonical_key))
        session.add(app)
        session.flush()
        session.refresh(job)
    return app


def sync_pending_questions(session: Session, job: Job, answers: list[PlannedAnswer],
                           authoritative: bool = False) -> list[PendingQuestion]:
    """authoritative=True when `answers` cover the employer's whole form (ATS API or
    live page): open questions that are no longer on it are closed as stale."""
    rows = session.scalars(select(PendingQuestion).where(PendingQuestion.job_id == job.id).order_by(PendingQuestion.id)).all()
    by_text: dict[str, PendingQuestion] = {}
    for q in rows:  # collapse duplicates created by earlier versions
        keep = by_text.get(q.question)
        if keep is None or (keep.status != "open" and q.status == "open"):
            if keep is not None and keep.status == "open":
                keep.status = "dismissed"
            by_text[q.question] = q
        elif q.status == "open" and keep.status == "open":
            q.status = "dismissed"
    out = []
    for a in answers:
        if a.kind != "human" or not a.required:
            continue
        q = by_text.get(a.label)
        if q is not None and q.field_name != a.name:
            q.field_name = a.name
        if q is None:
            q = PendingQuestion(job_id=job.id, question=a.label, field_name=a.name, field_type=a.type,
                                options=a.options, required=a.required, reason=a.reason)
            session.add(q)
        elif q.status == "dismissed":
            continue
        out.append(q)
    # Questions this plan can now answer (e.g. after you confirmed work authorization or
    # filled in your city) are resolved. Questions for fields outside this plan — such as
    # ones read from a live Lever/Ashby form at submission time — are left untouched.
    still_human = {a.label for a in answers if a.kind == "human" and a.required}
    planned = {a.name for a in answers}
    for q in list(by_text.values()):
        if q.status == "open" and q.question not in still_human and (q.field_name in planned or authoritative):
            q.status, q.answer, q.answered_at = "resolved", "Answered from your profile / saved answers", utcnow()
    session.flush()
    return [q for q in out if q.status == "open"]


def prepare_application(session: Session, job: Job, *, profile: dict, master: dict, settings: dict,
                        applicant_skills: set[str], client, llm: LLM | None, run_id: int | None = None,
                        cover_letter_artifact: Artifact | None = None, browser_getter=None) -> Application:
    app = ensure_application(session, job)
    platform = adapters.platform_of(job)
    app.platform = platform
    notes: list[str] = []
    if platform == "greenhouse" and not job.ats_board and job.ats_job_id and not job.is_test:
        job.ats_board = adapters.greenhouse_board(client, job.ats_job_id)
    try:
        fields, raw_form, source = adapters.fetch_form(job, client, get_settings().mock_ats_base if job.is_test else None)
    except Exception as e:  # noqa: BLE001
        fields, raw_form, source = list(adapters.STANDARD_FIELDS), None, "standard"
        notes.append(f"Could not fetch form definition ({e}); using standard fields")
    if platform in ("lever", "ashby"):
        # Lever/Ashby have no public form API: read the live form (no typing, no submit)
        # so its custom questions surface now rather than at submission time.
        live = None
        if browser_getter is not None:
            try:
                from hunt.apply.browser import inspect_form
                page = browser_getter().new_page()
                try:
                    live, _cap = inspect_form(page, adapters.form_url(job))
                finally:
                    page.context.close()
            except Exception as e:  # noqa: BLE001
                notes.append(f"Live form inspection failed ({type(e).__name__}); questions will be read at submission")
        if live:
            fields, source = live, "live_form"
        else:
            notes.append("Custom questions are read from the live form at submission; any unknown required question blocks submission.")
    ctx = _ctx(session, job, profile, master, settings, applicant_skills, llm)
    answers = [answer_field(f, ctx) for f in fields]
    if cover_letter_artifact is None:
        for a in answers:
            if a.rule == "cover_letter" and not a.required:
                a.kind, a.value, a.reason = "skip", None, "Optional cover letter not generated"
            elif a.rule == "cover_letter" and a.required:
                a.kind, a.value, a.reason = "human", None, "Cover letter required but not generated"
    contradictions = check_contradictions(answers, ctx)
    manual = platform not in adapters.AUTO_PLATFORMS
    # Manual platforms: you fill the employer's own form, so the answer sheet is
    # informational and its open items do not block the job.
    if manual:
        pending = []
    else:
        sync_pending_questions(session, job, answers, authoritative=source != "standard")
        # Every open question blocks, including ones read from the live form earlier that
        # this plan's field list may not contain (e.g. when the form fetch failed).
        pending = session.scalars(select(PendingQuestion).where(PendingQuestion.job_id == job.id,
                                                                PendingQuestion.status == "open")).all()
    rv = latest_resume(job)
    app.resume_version_id = rv.id if rv else None
    if cover_letter_artifact is not None:
        app.cover_letter_artifact_id = cover_letter_artifact.id
    app.apply_method = "browser" if platform in adapters.AUTO_PLATFORMS else "manual"
    app.plan = {
        "platform": platform, "form_url": adapters.form_url(job), "form_source": source,
        "answers": [a.to_dict() for a in answers], "notes": notes, "prepared_at": utcnow().isoformat(),
        "manual_reason": None if app.apply_method == "browser" else adapters.manual_reason(platform),
    }
    app.unresolved = [{"question": q.question, "reason": q.reason, "field": q.field_name, "id": q.id} for q in pending]
    app.contradictions = contradictions

    if manual and platform == "workday":
        set_status(session, job, JobStatus.READY_TO_APPLY, "Prepared for Finish application (Workday)", run_id=run_id,
                   next_action=(f"Ready – click Finish application: sign in to {job.company}'s Workday and the form is "
                                "filled in for you (you click Submit)"))
    elif manual:
        todo = [a.label for a in answers if a.kind == "human" and a.required]
        set_status(session, job, JobStatus.READY_TO_APPLY, "Packet prepared for manual submission", run_id=run_id,
                   next_action=f"Apply manually – {adapters.manual_reason(platform)} Resume + answer sheet ready"
                               + (f"; {len(todo)} item(s) on the sheet need you" if todo else "."))
    elif pending:
        set_status(session, job, JobStatus.BLOCKED, f"{len(pending)} question(s) need your answer", run_id=run_id,
                   next_action=f"Answer {len(pending)} question(s): " + "; ".join(q.question[:60] for q in pending[:3]))
        notify(session, "blocked", f"Input needed: {job.company} – {job.title}",
               "\n".join(f"- {q.question} ({q.reason})" for q in pending), job.id)
    elif contradictions:
        set_status(session, job, JobStatus.BLOCKED, "Answer contradictions detected", run_id=run_id,
                   next_action="Review contradictory answers: " + "; ".join(contradictions[:2]))
    else:
        if platform == "workday":
            nxt = (f"Ready – click Finish application: sign in to {job.company}'s Workday and the form is filled "
                   "in for you (you click Submit)")
        elif app.apply_method == "manual":
            nxt = f"Apply manually – {adapters.manual_reason(platform)} Packet ready."
        elif platform in set(settings.get("assisted_only_platforms") or []) and not job.is_test:
            nxt = "Ready – click Finish application (this site asks you to confirm you're human; ~30 seconds)"
        elif settings.get("apply_mode") == "auto" and job.eligibility == "eligible":
            nxt = "Queued for automatic submission"
        else:
            nxt = "Awaiting your approval to submit"
        set_status(session, job, JobStatus.READY_TO_APPLY, "Application prepared", run_id=run_id, next_action=nxt)
    session.flush()
    return app


# ------------------------------------------------------------------ gates

def chicago_today_bounds(tz: str = "America/Chicago") -> tuple[datetime, datetime]:
    z = ZoneInfo(tz)
    now = datetime.now(z)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    to_utc = lambda d: d.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return to_utc(start), to_utc(start + timedelta(days=1))


def submitted_today(session: Session, include_test: bool = False) -> int:
    """Confirmed submissions since midnight Central (automatic + ones you finished)."""
    a, b = chicago_today_bounds(get_settings().timezone)
    q = select(func.count(Application.id)).join(Job).where(Application.date_applied >= a, Application.date_applied < b)
    if not include_test:
        q = q.where(Job.is_test.is_(False))
    return session.scalar(q) or 0


def submission_gates(session: Session, job: Job, settings: dict, profile: dict, dry_run: bool) -> list[str]:
    """Reasons this job may NOT be auto-submitted right now (empty list = allowed)."""
    s = get_settings()
    app = job.application
    reasons = []
    if not settings.get("automation_enabled", True) or settings.get("paused"):
        reasons.append("Automation is disabled or paused")
    if app is None or not app.plan:
        reasons.append("Application not prepared")
        return reasons
    if job.status in {st.value for st in POST_SUBMISSION}:
        reasons.append(f"Already {job.status}")
    if job.status not in (JobStatus.READY_TO_APPLY.value, JobStatus.FAILED.value):
        reasons.append(f"Status is {job.status}")
    if app.apply_method != "browser":
        reasons.append(app.plan.get("manual_reason") or "Manual application platform")
    elif not job.is_test and app.platform in set(settings.get("assisted_only_platforms") or []):
        reasons.append("Finish application: this site makes you confirm you're human")
    if job.eligibility == "ineligible":
        reasons.append("Ineligible work-authorization requirements")
    if job.eligibility == "review" and not app.approved:
        reasons.append("Eligibility needs your review/approval")
    mode = settings.get("apply_mode", "review")
    # Mock-ATS fixtures (is_test) are pre-approved so dry runs exercise submission.
    if mode != "auto" and not app.approved and not job.is_test:
        reasons.append("Review mode: waiting for your approval")
    if mode == "auto" and not app.approved and (job.match_score or 0) < settings.get("min_auto_apply_score", 70):
        reasons.append(f"Score {job.match_score} below auto-apply minimum {settings.get('min_auto_apply_score')}")
    if app.unresolved:
        reasons.append("Unanswered required questions")
    if app.contradictions:
        reasons.append("Contradictory answers")
    blockers = auto_apply_blockers(profile)
    if blockers and not job.is_test:
        reasons.append("Onboarding incomplete: " + ", ".join(blockers))
    rv = latest_resume(job)
    if rv is None:
        reasons.append("No tailored resume")
    elif not (rv.ats_check or {}).get("passed") or not (rv.factcheck or {}).get("passed", True):
        reasons.append("Resume failed ATS or fact check")
    if not job.is_test:
        if dry_run:
            reasons.append("Dry run: real employers are never contacted")
        elif not s.allow_real_submissions:
            reasons.append("Real submissions disabled (set HUNT_ALLOW_REAL_SUBMISSIONS=true)")
        if submitted_today(session) >= int(settings.get("daily_application_cap", 15)):
            reasons.append("Daily application cap reached")
        dup = session.scalar(select(Job).join(Application).where(
            Job.id != job.id, Job.company_norm == job.company_norm,
            Job.status.in_([st.value for st in POST_SUBMISSION]), Application.date_applied >= utcnow() - timedelta(days=120)))
        if dup is not None and normalize_title(dup.title) == normalize_title(job.title):
            reasons.append(f"Possible duplicate of submitted application #{dup.id}")
    return reasons


# ------------------------------------------------------------------ submission

def recover_interrupted(session: Session, stale_minutes: int = 30) -> int:
    """Jobs left in APPLYING by a crash are never resubmitted automatically."""
    cutoff = utcnow() - timedelta(minutes=stale_minutes)
    n = 0
    for job in session.scalars(select(Job).where(Job.status == JobStatus.APPLYING.value)).all():
        app = job.application
        if app and app.last_attempt_at and app.last_attempt_at > cutoff:
            continue
        set_status(session, job, JobStatus.BLOCKED, "Submission was interrupted; outcome unknown",
                   next_action="Check your email / the employer portal, then mark Submitted or Retry")
        notify(session, "blocked", f"Verify submission: {job.company} – {job.title}",
               "A submission attempt was interrupted. It will not be retried automatically.", job.id)
        n += 1
    return n


def _resolve_files(session: Session, job: Job) -> dict[str, Path]:
    files: dict[str, Path] = {}
    rv = latest_resume(job)
    if rv:
        a = session.get(Artifact, rv.artifact_id)
        if a and a.path and Path(a.path).exists():
            files["resume"] = Path(a.path)
    app = job.application
    if app and app.cover_letter_artifact_id:
        a = session.get(Artifact, app.cover_letter_artifact_id)
        if a and a.path and Path(a.path).exists():
            files["cover_letter"] = Path(a.path)
    return files


def plan_live_answers(page, app: Application, ctx: Context, files: dict[str, Path],
                      skip_names: set[str] | None = None) -> tuple[list[PlannedAnswer], dict[str, str]]:
    """Read the open form page and compute the answer for every field on it (except
    `skip_names`, the fields already handled)."""
    dom_fields: list[FormField] = [f for f in collect_fields(page) if f.name not in (skip_names or set())]
    selectors = {f.name: f.description for f in dom_fields}
    # Searchable dropdowns expose no options in the DOM until opened; the ATS API
    # (Greenhouse) lists them, so the answer is mapped to an exact option.
    api_opts = {a["name"]: a.get("options") or [] for a in ((app.plan or {}).get("answers") or []) if a.get("options")}
    for f in dom_fields:
        if not f.options and api_opts.get(f.name):
            f.options = list(api_opts[f.name])
    answers = [answer_field(f, ctx) for f in dom_fields]
    for a in answers:
        if a.rule == "cover_letter" and "cover_letter" not in files:
            a.kind, a.value = ("human" if a.required else "skip"), None
    return answers, selectors


def live_replanner(page, app: Application, ctx: Context, files: dict[str, Path]):
    """For fill_all: plans the questions a form reveals only after earlier answers."""
    return lambda seen: plan_live_answers(page, app, ctx, files, skip_names=seen)


def submit_application(session: Session, job: Job, *, profile: dict, master: dict, settings: dict,
                       applicant_skills: set[str], llm: LLM | None, browser, dry_run: bool,
                       run_id: int | None = None) -> str:
    gates = submission_gates(session, job, settings, profile, dry_run)
    if gates:
        return "skipped: " + "; ".join(gates)
    app = job.application
    # claim (idempotency): one in-flight attempt per job
    app.attempt_token = uuid.uuid4().hex
    app.attempts += 1
    app.last_attempt_at = utcnow()
    set_status(session, job, JobStatus.APPLYING, f"Submission attempt {app.attempts}", run_id=run_id)
    session.commit()

    files = _resolve_files(session, job)
    if "resume" not in files:
        set_status(session, job, JobStatus.FAILED, "Resume file missing", run_id=run_id, next_action="Regenerate resume")
        session.commit()
        return "failed: resume missing"

    ctx = _ctx(session, job, profile, master, settings, applicant_skills, llm)
    url = app.plan.get("form_url")
    page = browser.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded")
        wait_for_form(page)
        if requires_login(page):
            result = SubmitResult("blocked", error="Application requires signing in", final_url=page.url)
        else:
            answers, selectors = plan_live_answers(page, app, ctx, files)
            contradictions = check_contradictions(answers, ctx)
            human = [a for a in answers if a.kind == "human" and a.required]
            if human or contradictions:
                pending = sync_pending_questions(session, job, answers, authoritative=True)
                app.unresolved = [{"question": q.question, "reason": q.reason, "field": q.field_name, "id": q.id} for q in pending]
                app.contradictions = contradictions
                result = SubmitResult("blocked", error="Live form has questions that need your answer: "
                                      + "; ".join(a.label[:60] for a in human[:4]) + ("; contradictions" if contradictions else ""),
                                      final_url=page.url)
            else:
                app.plan = {**app.plan, "live_answers": [a.to_dict() for a in answers]}
                cap = detect_captcha(page)
                if cap:
                    result = SubmitResult("blocked", error=f"CAPTCHA / bot check present ({cap})", final_url=page.url,
                                          screenshot=page.screenshot(full_page=True))
                else:
                    result = run_form(page, url, answers, files, submit=True, selectors=selectors, navigate=False,
                                      replan=live_replanner(page, app, ctx, files))
    except Exception as e:  # noqa: BLE001
        log.exception("submission error for job %s", job.id)
        result = SubmitResult("failed", error=f"{type(e).__name__}: {e}")
    finally:
        try:
            page.context.close()
        except Exception:
            pass

    if result.screenshot:
        ev = save_artifact(session, job, "evidence", f"submission_{app.attempts}.png", result.screenshot, "image/png")
        app.evidence_artifact_id = ev.id
    app.last_error = result.error
    if result.status == "submitted":
        app.date_applied = utcnow()
        app.confirmation_text = result.confirmation_text
        app.confirmation_source = "page"
        set_status(session, job, JobStatus.SUBMITTED, "Confirmation observed", run_id=run_id,
                   next_action="Wait for response; follow up in ~2 weeks")
    elif result.status == "blocked":
        err = result.error or ""
        if "verification code" in err:
            nxt = "Not submitted – this site asks you to confirm you're human (emailed code). Click Finish application."
        elif "CAPTCHA" in err:
            nxt = "Not submitted – this site asks you to confirm you're human (picture check). Click Finish application."
        elif "sign" in err.lower():
            nxt = "Not submitted – finish this application manually (sign-in required)"
        else:
            nxt = "Answer the pending questions, then retry"
        set_status(session, job, JobStatus.BLOCKED, err, run_id=run_id, next_action=nxt)
        notify(session, "blocked", f"Blocked: {job.company} – {job.title}", result.error, job.id)
    elif result.status == "unconfirmed" or result.submit_clicked:
        set_status(session, job, JobStatus.BLOCKED, "Submit clicked but no confirmation observed", run_id=run_id,
                   next_action="Check email/portal for a confirmation, then mark Submitted or Retry")
        notify(session, "blocked", f"Unconfirmed submission: {job.company} – {job.title}", result.error, job.id)
    else:
        set_status(session, job, JobStatus.FAILED, result.error, run_id=run_id, next_action="Will retry automatically")
    session.commit()
    return result.status
