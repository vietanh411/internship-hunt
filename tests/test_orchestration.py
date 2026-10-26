from datetime import timedelta

import pytest
from sqlalchemy import select

from hunt.db import utcnow
from hunt.models import Application, Job, JobStatus, Lock, PipelineRun, StageRun, Task
from hunt.pipeline import queue


def test_backoff_and_dead_letter(session):
    t = queue.enqueue(session, "x", "x:1", {}, max_attempts=3)
    session.commit()
    assert queue.enqueue(session, "x", "x:1", {}).id == t.id  # dedupe
    queue.fail(session, t, "boom")
    first = t.next_attempt_at
    assert t.status == "queued" and t.attempts == 1
    queue.fail(session, t, "boom")
    assert t.next_attempt_at - utcnow() > first - utcnow()  # exponential
    assert queue.backoff_seconds(1) == 60 and queue.backoff_seconds(3) == 240
    queue.fail(session, t, "boom")
    assert t.status == "dead"


def test_drain_retries_failures_and_stops(session):
    for i in range(3):
        queue.enqueue(session, "k", f"k:{i}", {"i": i})
    session.commit()
    seen = []

    def handler(task):
        seen.append(task.payload["i"])
        if task.payload["i"] == 1:
            raise ValueError("transient")
    stats = queue.drain(session, "k", handler, "w", lambda: False)
    assert stats == {"done": 2, "failed": 1, "dead": 0}
    failed = session.scalar(select(Task).where(Task.dedupe_key == "k:1"))
    assert failed.status == "queued" and failed.next_attempt_at > utcnow()  # will retry on a later run


def test_release_stale_running_tasks(session):
    t = queue.enqueue(session, "k", "k:s", {})
    t.status, t.locked_at = "running", utcnow() - timedelta(hours=2)
    session.commit()
    assert queue.release_stale(session) == 1 and t.status == "queued"


def test_run_lock_prevents_concurrent_runs(session):
    from hunt.pipeline.runner import RunAlreadyActive, acquire_lock, lock_owner, release_lock
    r1 = PipelineRun(trigger="t", status="running")
    session.add(r1)
    session.commit()
    acquire_lock(session, r1.id)
    with pytest.raises(RunAlreadyActive):
        acquire_lock(session, r1.id + 1)
    release_lock(session, "someone-else")          # a refused process cannot release it
    assert session.get(Lock, "pipeline") is not None
    # stale lock (process died) is taken over and the old run marked failed
    session.get(Lock, "pipeline").heartbeat_at = utcnow() - timedelta(hours=1)
    session.commit()
    r2 = PipelineRun(trigger="t", status="running")
    session.add(r2)
    session.commit()
    acquire_lock(session, r2.id)
    session.refresh(r1)
    assert r1.status == "failed"
    release_lock(session, lock_owner(r2.id))
    assert session.get(Lock, "pipeline") is None


def _job(session, status=JobStatus.READY_TO_APPLY, **kw):
    import uuid
    key = f"t:{uuid.uuid4().hex}"
    j = Job(uid=key[-16:], canonical_key=key, company="Acme", company_norm="acme", title=kw.pop("title", "Data Intern"),
            source="test", status=status.value, eligibility="eligible", match_score=90, **kw)
    session.add(j)
    session.flush()
    return j


def test_interrupted_submission_is_never_auto_resubmitted(session):
    from hunt.apply.engine import recover_interrupted, submission_gates
    from hunt.settings_store import get_automation
    j = _job(session, JobStatus.APPLYING)
    app = Application(job_id=j.id, idempotency_key=f"app:{j.canonical_key}", apply_method="browser",
                      plan={"form_url": "x"}, last_attempt_at=utcnow() - timedelta(hours=1), attempts=1)
    session.add(app)
    session.commit()
    assert recover_interrupted(session) == 1
    assert j.status == JobStatus.BLOCKED.value
    gates = submission_gates(session, j, {**get_automation(session), "apply_mode": "auto"}, {}, dry_run=False)
    assert any("Status is blocked" in g for g in gates)


def test_duplicate_submission_prevented(session):
    from hunt.apply.engine import submission_gates
    from hunt.settings_store import get_automation
    j = _job(session, JobStatus.SUBMITTED)
    session.add(Application(job_id=j.id, idempotency_key=f"app:{j.canonical_key}", apply_method="browser",
                            plan={"form_url": "x"}, date_applied=utcnow(), approved=True))
    j2 = _job(session, JobStatus.READY_TO_APPLY)  # same company + title, different listing
    session.add(Application(job_id=j2.id, idempotency_key=f"app:{j2.canonical_key}", apply_method="browser",
                            plan={"form_url": "x"}, approved=True))
    session.commit()
    s = {**get_automation(session), "apply_mode": "auto"}
    assert any("Already submitted" in g for g in submission_gates(session, j, s, {}, dry_run=False))
    assert any("Possible duplicate" in g for g in submission_gates(session, j2, s, {}, dry_run=False))
    # idempotency key is unique per requisition
    from sqlalchemy.exc import IntegrityError
    session.add(Application(job_id=_job(session).id, idempotency_key=f"app:{j.canonical_key}"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_real_submission_kill_switch_and_dry_run(session):
    from hunt.apply.engine import submission_gates
    from hunt.settings_store import get_automation
    j = _job(session)
    session.add(Application(job_id=j.id, idempotency_key=f"app:{j.canonical_key}", apply_method="browser",
                            plan={"form_url": "x"}, approved=True))
    session.commit()
    s = {**get_automation(session), "apply_mode": "auto"}
    assert any("Real submissions disabled" in g for g in submission_gates(session, j, s, {}, dry_run=False))
    assert any("Dry run" in g for g in submission_gates(session, j, s, {}, dry_run=True))


def test_stage_failure_is_isolated_and_cancel_works(db, monkeypatch):
    from hunt.pipeline import runner, stages

    def boom(rc):
        raise RuntimeError("source outage")
    calls = []
    fake = [("discovery", boom), ("matching", lambda rc: calls.append("matching") or {"ok": 1}),
            ("reporting", lambda rc: calls.append("reporting") or {})]
    monkeypatch.setattr(runner, "STAGES", fake)
    rid = runner.run_pipeline(trigger="test", dry_run=True, browser_factory=lambda: None)
    s = db.new_session()
    run = s.get(PipelineRun, rid)
    assert run.status == "partial" and calls == ["matching", "reporting"]
    st = {x.stage: x.status for x in s.scalars(select(StageRun).where(StageRun.run_id == rid)).all()}
    assert st == {"discovery": "failed", "matching": "succeeded", "reporting": "succeeded"}
    assert s.get(Lock, "pipeline") is None  # lock released

    def cancel_then(rc):
        rc.run.cancel_requested = True
        rc.session.commit()
        return {}
    monkeypatch.setattr(runner, "STAGES", [("discovery", cancel_then), ("matching", lambda rc: calls.append("after-cancel") or {})])
    rid2 = runner.run_pipeline(trigger="test", dry_run=True, browser_factory=lambda: None)
    s.expire_all()
    assert s.get(PipelineRun, rid2).status == "cancelled" and "after-cancel" not in calls
    s.close()


def test_matching_moves_previously_scored_jobs_and_rescores_on_eligibility_change(db):
    from hunt.pipeline import runner
    from hunt.pipeline.stages import stage_matching
    s = db.new_session()
    j = _job(s, JobStatus.ELIGIBILITY_REVIEW, description_text="Requirements\n- Python and SQL\nSummer 2027 internship.",
             locations=["Madison, WI"], terms=["Summer 2027"], feed_flags={"term_status": "confirmed"})
    j.eligibility = "review"
    s.commit()
    jid = j.id
    s.close()
    runner.run_pipeline(trigger="t", dry_run=True, only=["matching"], browser_factory=lambda: None)
    s = db.new_session()
    j = s.get(Job, jid)
    review_score = j.match_score
    assert review_score is not None and j.status == JobStatus.ELIGIBILITY_REVIEW.value
    j.eligibility, j.status = "eligible", JobStatus.DISCOVERED.value  # e.g. approved / re-classified
    s.commit()
    s.close()
    runner.run_pipeline(trigger="t", dry_run=True, only=["matching"], browser_factory=lambda: None)
    s = db.new_session()
    j = s.get(Job, jid)
    assert j.status == JobStatus.MATCHED.value and j.match_score > review_score
    s.close()


def test_profile_update_resolves_stale_pending_questions(session):
    from hunt.apply.answers import PlannedAnswer
    from hunt.apply.engine import sync_pending_questions
    j = _job(session, JobStatus.BLOCKED)
    wa = PlannedAnswer("q1", "Are you authorized to work in the US?", "select", True, None, "human",
                       reason="Work-authorization answers must be confirmed in Profile & Onboarding first")
    salary = PlannedAnswer("q2", "Salary expectations?", "text", True, None, "human", reason="new declaration")
    assert len(sync_pending_questions(session, j, [wa, salary])) == 2
    # after the applicant confirms work authorization, q1 is answerable; q2 still is not
    wa_ok = PlannedAnswer("q1", wa.label, "select", True, "Yes", "fixed", rule="authorized_to_work")
    live_only = PlannedAnswer("q3", "Live-form question", "text", True, None, "human")
    open_q = sync_pending_questions(session, j, [wa_ok, salary, live_only])
    assert {q.field_name for q in open_q} == {"q2", "q3"}
    from hunt.models import PendingQuestion
    q1 = session.scalar(select(PendingQuestion).where(PendingQuestion.field_name == "q1"))
    assert q1.status == "resolved"


def test_open_question_outside_plan_still_blocks(db, monkeypatch):
    from hunt.apply import adapters, engine
    from hunt.apply.answers import FormField
    from hunt.matching import build_applicant
    from hunt.models import Application, PendingQuestion
    from hunt.profile_store import get_master_resume, get_profile
    from hunt.settings_store import get_automation
    s = db.new_session()
    j = _job(s, JobStatus.BLOCKED, ats_platform="greenhouse", ats_board="acme", ats_job_id="1",
             apply_url="https://job-boards.greenhouse.io/acme/jobs/1")
    s.add(PendingQuestion(job_id=j.id, question="Live-form salary question", field_name="question_99", required=True))
    s.commit()
    # the form definition can't be fetched, so the generic field list is used; the
    # question read earlier from the live form must still block
    def broken(job, client, base=None):
        raise ConnectionError("form API down")
    monkeypatch.setattr(adapters, "fetch_form", broken)
    p = get_profile(s)
    v, m = get_master_resume(s)
    engine.prepare_application(s, j, profile=p, master=m, settings=get_automation(s),
                               applicant_skills=build_applicant(m, p).skills, client=None, llm=None)
    assert j.status == JobStatus.BLOCKED.value
    s.close()


def test_deleting_job_removes_its_application_resumes_and_files(session):
    from hunt.models import Artifact, PendingQuestion, ResumeVersion, StatusEvent
    from hunt.workflow import set_status
    j = _job(session, JobStatus.READY_TO_APPLY)
    art = Artifact(job_id=j.id, kind="resume", filename="Resume_VietAnhNguyen.pdf", content_type="application/pdf", content=b"%PDF", sha256="x")
    session.add(art)
    session.flush()
    session.add(ResumeVersion(version_id="rv-del-001", job_id=j.id, artifact_id=art.id, master_version=1))
    session.add(Application(job_id=j.id, idempotency_key="app:del", evidence_artifact_id=art.id))
    session.add(PendingQuestion(job_id=j.id, question="q"))
    set_status(session, j, JobStatus.BLOCKED, "x")
    session.commit()
    session.delete(j)
    session.commit()
    for model in (Application, ResumeVersion, Artifact, PendingQuestion, StatusEvent):
        assert session.scalar(select(func.count(model.id))) == 0, model


from sqlalchemy import func  # noqa: E402


def test_duplicate_pending_questions_collapse(session):
    from hunt.apply.answers import PlannedAnswer
    from hunt.apply.engine import sync_pending_questions
    from hunt.models import PendingQuestion
    j = _job(session, JobStatus.BLOCKED)
    session.add_all([PendingQuestion(job_id=j.id, question="Sponsor for this internship?", field_name="old_a"),
                     PendingQuestion(job_id=j.id, question="Sponsor for this internship?", field_name="old_b")])
    session.flush()
    ans = PlannedAnswer("new_name", "Sponsor for this internship?", "radio", True, None, "human")
    open_q = sync_pending_questions(session, j, [ans])
    assert len(open_q) == 1 and open_q[0].field_name == "new_name"
    assert session.scalar(select(func.count(PendingQuestion.id)).where(PendingQuestion.status == "open")) == 1


def test_long_workday_urls_get_distinct_application_keys():
    """Two GM Workday postings shared the first 120 characters; plain truncation
    gave both the same idempotency key and crashed the application stage."""
    from hunt.apply.engine import application_key
    base = ("workday:generalmotors.wd5.myworkdayjobs.com|generalmotors|careers_gm:/job/"
            "Sunnyvale-California-United-States-of-America/2027-Summer-Intern-")
    a, b = application_key(base + "Software-Engineering_JR-202512345"), application_key(base + "Data-Science_JR-202567890")
    assert a != b and len(a) <= 120 and len(b) <= 120
    assert application_key("greenhouse:acme:123") == "app:greenhouse:acme:123"  # short keys unchanged


def test_lever_is_applied_to_in_your_own_browser():
    """Lever's bot check rejects the automated window even when you click Submit, so
    Lever jobs get a resume + answer sheet for your own browser instead of Finish."""
    from hunt.apply import adapters
    assert "lever" in adapters.OWN_BROWSER_PLATFORMS
    assert "lever" not in adapters.AUTO_PLATFORMS and "lever" not in adapters.ASSIST_PLATFORMS
    assert "own browser" in adapters.manual_reason("lever")
