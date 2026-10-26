"""End-to-end: eligibility -> matching -> resume -> application prep -> real
browser submission, against the local mock ATS only (never a real employer)."""
import socket
import threading
import time

import pytest
from sqlalchemy import select

pytest.importorskip("playwright")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture()
def mock_ats(db, monkeypatch):
    import uvicorn
    from hunt import config
    from hunt.mock_ats import app as mock
    mock.SUBMISSIONS.clear()
    port = _free_port()
    base = f"http://127.0.0.1:{port}/mock-ats"
    monkeypatch.setenv("HUNT_MOCK_ATS_BASE", base)
    monkeypatch.setenv("HUNT_ENABLE_MOCK_ATS", "true")
    config.get_settings.cache_clear()
    server = uvicorn.Server(uvicorn.Config(mock.standalone_app(), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield base, mock.SUBMISSIONS
    server.should_exit = True
    t.join(timeout=5)


STAGES = ["eligibility", "matching", "resume_generation", "application"]


def test_full_pipeline_against_mock_ats(db, mock_ats):
    from hunt.models import Application, Job, JobStatus, PendingQuestion, ResumeVersion
    from hunt.pipeline.runner import run_pipeline
    from hunt.testdata import ensure_mock_jobs
    base, submissions = mock_ats
    ensure_mock_jobs(base)

    run_pipeline(trigger="test", dry_run=True, only=STAGES, max_minutes=5)
    s = db.new_session()
    jobs = {j.ats_job_id: j for j in s.scalars(select(Job).where(Job.is_test.is_(True))).all()}

    std = jobs["mock-standard"]
    assert std.eligibility == "eligible" and std.match_score >= 70
    assert std.status == JobStatus.SUBMITTED.value, (std.status, std.next_action, std.application.last_error)
    assert "Thank you for applying" in std.application.confirmation_text
    assert std.application.evidence_artifact_id
    rv = s.scalar(select(ResumeVersion).where(ResumeVersion.job_id == std.id))
    assert rv.ats_check["passed"] and rv.factcheck["passed"]

    assert len(submissions) == 1
    sub = submissions[0]
    assert sub["job_id"] == "mock-standard"
    assert sub["files"]["resume"]["is_pdf"] and sub["files"]["resume"]["filename"] == "Resume_VietAnhNguyen.pdf"
    assert sub["data"]["first_name"] == "Viet Anh" and sub["data"]["last_name"] == "Nguyen"
    assert sub["data"]["question_1002"] == "Yes"   # authorized to work
    assert sub["data"]["question_1003"] == "Yes"   # will require sponsorship
    assert sub["data"]["question_1004"] == "December 2027"
    assert "gender" not in sub["data"] or sub["data"]["gender"] == ""  # voluntary EEO left blank (policy: ask)

    cap = jobs["mock-captcha"]
    assert cap.status == JobStatus.BLOCKED.value and "CAPTCHA" in (cap.application.last_error or "")

    unk = jobs["mock-unknown"]
    assert unk.status == JobStatus.BLOCKED.value
    q = s.scalar(select(PendingQuestion).where(PendingQuestion.job_id == unk.id))
    assert "salary" in q.question.lower() and q.status == "open"
    s.close()

    # second run: nothing is submitted twice
    run_pipeline(trigger="test", dry_run=True, only=["application"], max_minutes=5)
    assert len(submissions) == 1

    # applicant answers the question -> the blocked application completes on the next run
    s = db.new_session()
    from hunt.apply.answers import norm
    from hunt.models import ScreeningAnswer
    q = s.get(PendingQuestion, q.id)
    q.answer, q.status = "Open to the posted range", "answered"
    import re
    s.add(ScreeningAnswer(key=f"user_q{q.id}", label=q.question, kind="fixed", source="user", approved=True,
                          answer=q.answer, patterns=["^" + re.escape(norm(q.question)) + "$"]))
    s.commit()
    s.close()
    run_pipeline(trigger="test", dry_run=True, only=["application"], max_minutes=5)
    assert [x["job_id"] for x in submissions] == ["mock-standard", "mock-unknown"]
    assert submissions[1]["data"]["question_1099"] == "Open to the posted range"


def test_no_confirmation_means_not_submitted(db, mock_ats):
    """A post that is accepted but shows no confirmation must end Blocked, not Submitted."""
    import hashlib
    from hunt.apply.browser import Browser
    from hunt.apply.engine import prepare_application, submit_application
    from hunt.db import utcnow
    from hunt.http import PoliteClient
    from hunt.matching import build_applicant
    from hunt.models import Job, JobStatus
    from hunt.pipeline.stages import tailor_job
    from hunt.profile_store import get_master_resume, get_profile
    from hunt.settings_store import get_automation
    from hunt.testdata import MOCK_JD
    from types import SimpleNamespace
    base, submissions = mock_ats
    s = db.new_session()
    j = Job(uid=hashlib.sha1(b"silent").hexdigest()[:16], canonical_key="mock:test:mock-silent", company="Mock Analytics Co (TEST)",
            company_norm="mock analytics test", title="TEST • Data Intern (Summer 2027)", ats_job_id="mock-silent",
            ats_platform="mock", location="Madison, WI", locations=["Madison, WI"], description_text=MOCK_JD,
            posting_url=f"{base}/jobs/mock-silent", apply_url=f"{base}/jobs/mock-silent", source="mock", sources=["mock"],
            is_test=True, status=JobStatus.MATCHED.value, eligibility="eligible", match_score=90, date_discovered=utcnow(),
            feed_flags={"term_status": "confirmed"}, score_explanation={"evidence": [], "matched_skills": ["Python"]})
    s.add(j)
    s.commit()
    profile = get_profile(s)
    mv, master = get_master_resume(s)
    settings = get_automation(s)
    from hunt.models import PipelineRun
    run = PipelineRun(trigger="t", status="running")
    s.add(run)
    s.flush()
    app_ = build_applicant(master, profile)
    rc = SimpleNamespace(session=s, run=run, master=master, profile=profile, settings=settings, llm=None,
                         client=PoliteClient(), master_version=mv, applicant=app_)
    tailor_job(rc, j)
    j.status = JobStatus.RESUME_GENERATED.value
    prepare_application(s, j, profile=profile, master=master, settings=settings, applicant_skills=app_.skills,
                        client=rc.client, llm=None)
    s.commit()
    assert j.status == JobStatus.READY_TO_APPLY.value, j.next_action
    with Browser() as b:
        out = submit_application(s, j, profile=profile, master=master, settings=settings, applicant_skills=app_.skills,
                                 llm=None, browser=b, dry_run=True)
    assert out == "unconfirmed"
    assert j.status == JobStatus.BLOCKED.value and j.application.date_applied is None
    assert submissions and submissions[-1]["job_id"] == "mock-silent"
    s.close()


def test_hidden_captcha_frame_does_not_block(db, mock_ats):
    """Invisible reCAPTCHA frames (always present on Ashby) must not be treated as a challenge."""
    from hunt.apply.browser import Browser, detect_captcha
    base, _ = mock_ats
    with Browser() as b:
        page = b.new_page()
        page.goto(f"{base}/jobs/mock-invisible-captcha")
        assert detect_captcha(page) is None
        page.goto(f"{base}/jobs/mock-captcha")
        assert detect_captcha(page) is not None


ASHBY_LIKE = """<!doctype html><html><body><form>
<div class="ashby-application-form-field-entry" data-field-path="q1">
  <label class="ashby-application-form-question-title _required_x">Would you need Acme to sponsor a visa for this internship?</label>
  <div><span><input type="radio" id="q1-0" name="q1" style="opacity:0;position:absolute"><label for="q1-0">Yes</label></span>
       <span><input type="radio" id="q1-1" name="q1" style="opacity:0;position:absolute"><label for="q1-1">No</label></span></div>
</div>
<div class="ashby-application-form-field-entry" data-field-path="q2">
  <label class="ashby-application-form-question-title _required_x">Are you authorized to work in the US?</label>
  <div><span><input type="radio" id="q2-0" name="q2"><label for="q2-0">Yes</label></span>
       <span><input type="radio" id="q2-1" name="q2"><label for="q2-1">No</label></span></div>
</div>
</form></body></html>"""


def test_ashby_style_radio_questions_are_read_and_filled(db):
    from hunt.apply.answers import PlannedAnswer
    from hunt.apply.browser import Browser, collect_fields, fill_answer
    with Browser() as b:
        page = b.new_page()
        page.set_content(ASHBY_LIKE)
        fields = {f.name: f for f in collect_fields(page)}
        assert fields["q1"].label.startswith("Would you need Acme to sponsor")
        assert fields["q1"].required and fields["q1"].options == ["Yes", "No"]
        assert fields["q2"].label == "Are you authorized to work in the US?"
        ans = PlannedAnswer("q2", fields["q2"].label, "radio", True, "Yes", "fixed", options=fields["q2"].options)
        assert fill_answer(page, ans, {}, fields["q2"].description)
        assert page.locator("#q2-0").is_checked()
        hidden = PlannedAnswer("q1", fields["q1"].label, "radio", True, "No", "fixed", options=fields["q1"].options)
        assert fill_answer(page, hidden, {}, fields["q1"].description)
        assert page.locator("#q1-1").is_checked()


ASHBY_CHECKBOXES = """<!doctype html><html><body><form>
<div class="ashby-application-form-field-entry" data-field-path="avail">
  <label class="ashby-application-form-question-title _required_x">Which months are you available?</label>
  <div><input type="checkbox" id="m5" name="avail_may"><label for="m5">May 2027</label>
       <input type="checkbox" id="m6" name="avail_jun"><label for="m6">June 2027</label>
       <input type="checkbox" id="m7" name="avail_jul"><label for="m7">July 2027</label></div>
</div></form></body></html>"""


def test_ashby_checkbox_group_is_one_question(db):
    from hunt.apply.browser import Browser, collect_fields
    with Browser() as b:
        page = b.new_page()
        page.set_content(ASHBY_CHECKBOXES)
        fields = collect_fields(page)
        assert len(fields) == 1
        f = fields[0]
        assert f.label == "Which months are you available?" and f.type == "multi_select" and f.required
        assert f.options == ["May 2027", "June 2027", "July 2027"]


def _assist_jobs(db, base, variants=("mock-standard",), next_action=None):
    """Mock jobs, tailored and prepared, as if Greenhouse had blocked them."""
    from types import SimpleNamespace
    from hunt.apply.engine import prepare_application
    from hunt.http import PoliteClient
    from hunt.matching import build_applicant
    from hunt.models import Job, JobStatus, PipelineRun
    from hunt.pipeline.stages import tailor_job
    from hunt.profile_store import get_master_resume, get_profile
    from hunt.settings_store import get_automation
    from hunt.testdata import ensure_mock_jobs
    ensure_mock_jobs(base)
    s = db.new_session()
    profile, (mv, master), settings = get_profile(s), get_master_resume(s), get_automation(s)
    run = PipelineRun(trigger="t", status="running")
    s.add(run)
    s.flush()
    ap = build_applicant(master, profile)
    out = []
    for n, vid in enumerate(variants):
        j = s.scalar(select(Job).where(Job.ats_job_id == vid))
        tailor_job(SimpleNamespace(session=s, run=run, master=master, profile=profile, settings=settings, llm=None,
                                   client=PoliteClient(), master_version=mv, applicant=ap), j)
        j.status, j.eligibility, j.match_score = JobStatus.RESUME_GENERATED.value, "eligible", 90 - n
        prepare_application(s, j, profile=profile, master=master, settings=settings, applicant_skills=ap.skills,
                            client=PoliteClient(), llm=None)
        j.status = JobStatus.BLOCKED.value  # e.g. stopped at an emailed verification code
        if next_action:
            j.next_action = next_action
        out.append(j.id)
    s.commit()
    s.close()
    return out


def _assist_job(db, base):
    return _assist_jobs(db, base)[0]


def test_assisted_finish_records_confirmation_after_you_submit(db, mock_ats):
    from hunt.apply import assist
    from hunt.models import Job, JobStatus
    base, submissions = mock_ats
    jid = _assist_job(db, base)
    clicked = []

    def applicant(page):  # plays your part: everything is pre-filled, you click Submit
        assert page.locator("#first_name").input_value() == "Viet Anh"
        assert page.locator("#summer2027-hunt-banner").count() == 1
        assert not submissions, "assist must never submit by itself"
        page.click("#submit_app")
        clicked.append(True)

    st = assist.start(jid, headless=True, on_ready=applicant, wait=True)
    assert clicked and st["state"] == "confirmed", st
    assert len(submissions) == 1 and submissions[0]["files"]["resume"]["is_pdf"]
    s = db.new_session()
    j = s.get(Job, jid)
    assert j.status == JobStatus.SUBMITTED.value
    assert j.application.confirmation_source == "page (you submitted)" and j.application.evidence_artifact_id
    s.close()
    try:
        assist.start(jid, headless=True, wait=True)
        raise AssertionError("must refuse an already-submitted job")
    except ValueError:
        pass


def test_assisted_finish_window_closed_without_submitting(db, mock_ats):
    from hunt.apply import assist
    from hunt.models import Job, JobStatus
    base, submissions = mock_ats
    jid = _assist_job(db, base)
    st = assist.start(jid, headless=True, on_ready=lambda page: page.close(), wait=True)
    assert st["state"] == "closed" and not submissions
    s = db.new_session()
    j = s.get(Job, jid)
    assert j.status == JobStatus.BLOCKED.value and j.application.date_applied is None
    s.close()


def test_confirmation_must_be_new_since_baseline(db):
    from hunt.apply.browser import Browser, confirmation_since, page_snapshot
    with Browser() as b:
        page = b.new_page()
        page.set_content("<p>About us... Thank you for your interest in our company!</p><button>Submit</button>")
        base = page_snapshot(page)
        assert confirmation_since(page, base[1], base[0]) is None
        page.set_content("<p>About us... Thank you for your interest in our company!</p><h1>Thank you for applying!</h1>")
        assert confirmation_since(page, base[1], base[0])


def test_apply_first_submits_until_target_then_stops(db, mock_ats):
    """Apply-first tailors, prepares and submits matched jobs before discovery runs,
    and stops once today's target is met."""
    from hunt.models import Job, JobStatus
    from hunt.pipeline import runner
    from hunt.settings_store import update_automation
    from hunt.testdata import ensure_mock_jobs
    base, submissions = mock_ats
    ids = ensure_mock_jobs(base)
    s = db.new_session()
    update_automation(s, {"daily_submission_target": 1, "apply_mode": "auto", "assisted_only_platforms": ["greenhouse", "lever"]})
    for i, jid in enumerate(ids):
        j = s.get(Job, jid)
        j.status, j.eligibility, j.match_score = JobStatus.MATCHED.value, "eligible", 90
        j.priority = 100 if j.ats_job_id == "mock-standard" else 50
        j.score_explanation = {"gates": [], "evidence": [], "matched_skills": ["Python", "SQL"]}
    s.commit()
    s.close()
    called = []
    monkey_stages = [(n, f) for n, f in runner.STAGES if n == "apply_first"] + [("discovery", lambda rc: called.append("discovery") or {})]
    import hunt.pipeline.runner as r
    orig = r.STAGES
    r.STAGES = monkey_stages
    try:
        rid = runner.run_pipeline(trigger="test", dry_run=False, max_minutes=10)
    finally:
        r.STAGES = orig
    s = db.new_session()
    from hunt.models import PipelineRun
    res = s.get(PipelineRun, rid).stats["apply_first"]
    assert res["target_reached"] == 1 and res["stop_reason"] == "target reached", res
    assert [x["job_id"] for x in submissions] == ["mock-standard"]
    assert called == ["discovery"]  # discovery ran after applying
    s.close()


def test_assisted_only_platform_is_never_auto_attempted(session):
    from hunt.apply.engine import submission_gates
    from hunt.models import Application, Job, JobStatus
    from hunt.settings_store import get_automation
    j = Job(uid="gh-assist-1", canonical_key="gh:assist:1", company="Acme", company_norm="acme", title="Data Intern",
            source="greenhouse", status=JobStatus.READY_TO_APPLY.value, eligibility="eligible", match_score=90,
            ats_platform="greenhouse")
    session.add(j)
    session.flush()
    session.add(Application(job_id=j.id, idempotency_key="app:gh:assist:1", apply_method="browser", platform="greenhouse",
                            plan={"form_url": "x"}, approved=True))
    session.commit()
    gates = submission_gates(session, j, {**get_automation(session), "apply_mode": "auto"}, {}, dry_run=False)
    assert any("Finish application" in g for g in gates)


@pytest.mark.parametrize("wid", ["wd-1", "wd-modal"])
def test_workday_finish_fills_each_step_after_you_sign_in(db, mock_ats, wid):
    """You sign in; the system uploads the resume, fills every Workday step and clicks
    Save and Continue; it stops at Review; you press Submit; the confirmation is recorded.
    wd-modal: the sign-in box is shown on top of the Autofill with Resume step."""
    import hashlib
    from types import SimpleNamespace
    from hunt.apply import assist
    from hunt.apply.engine import prepare_application
    from hunt.db import utcnow
    from hunt.http import PoliteClient
    from hunt.matching import build_applicant
    from hunt.mock_ats import workday as wd
    from hunt.models import Job, JobStatus, PipelineRun
    from hunt.pipeline.stages import tailor_job
    from hunt.profile_store import get_master_resume, get_profile, update_profile
    from hunt.settings_store import get_automation
    from hunt.testdata import MOCK_JD
    base, _ = mock_ats
    wd.SUBMISSIONS.clear()
    wd.STATE.clear()
    s = db.new_session()
    update_profile(s, {"contact": {"address_line1": "100 Test St", "city": "Madison", "state": "Wisconsin", "postal_code": "53703"}})
    j = Job(uid=hashlib.sha1(wid.encode()).hexdigest()[:16], canonical_key=f"mock:test:{wid}", company="Mock Workday Co (TEST)",
            company_norm="mock workday test", title="TEST • Data Analyst Intern (Summer 2027)", ats_job_id=wid,
            ats_platform="workday", ats_board="mock", location="Madison, WI", locations=["Madison, WI"], description_text=MOCK_JD,
            posting_url=f"{base}/workday/job/{wid}", apply_url=f"{base}/workday/job/{wid}", source="mock", sources=["mock"],
            is_test=True, status=JobStatus.MATCHED.value, eligibility="eligible", match_score=90, date_discovered=utcnow(),
            feed_flags={"term_status": "confirmed"}, score_explanation={"evidence": [], "matched_skills": ["SQL"]})
    s.add(j)
    s.commit()
    profile, (mv, master), settings = get_profile(s), get_master_resume(s), get_automation(s)
    run = PipelineRun(trigger="t", status="running")
    s.add(run)
    s.flush()
    ap = build_applicant(master, profile)
    tailor_job(SimpleNamespace(session=s, run=run, master=master, profile=profile, settings=settings, llm=None,
                               client=PoliteClient(), master_version=mv, applicant=ap), j)
    j.status = JobStatus.RESUME_GENERATED.value
    prepare_application(s, j, profile=profile, master=master, settings=settings, applicant_skills=ap.skills,
                        client=PoliteClient(), llm=None)
    s.commit()
    assert j.status == JobStatus.READY_TO_APPLY.value and "Finish application" in j.next_action
    jid = j.id
    s.close()

    def signin(page):  # your part: sign in (test-only credentials for the mock site)
        page.fill("[data-automation-id=email]", "applicant@example.com")
        page.fill("[data-automation-id=password]", "mock-only-password")
        page.click("[data-automation-id=signInSubmitButton]")

    def review(page):  # your part: press Submit on Review
        assert not wd.SUBMISSIONS, "must not submit by itself"
        page.click("[data-automation-id=bottom-navigation-next-button]")

    st = assist.start(jid, headless=True, wait=True, hooks={"on_signin": signin, "on_review": review})
    assert st["state"] == "confirmed", st
    rec = wd.SUBMISSIONS[-1]
    assert rec["resume_is_pdf"] and rec["resume_name"] == "Resume_VietAnhNguyen.pdf"
    # Workday pre-filled "Viet" / middle "Anh": corrected; the correct last name is kept
    assert (rec["first_name"], rec["middle_name"], rec["last_name"]) == ("Viet Anh", "", "Nguyen")
    # State is a long list that shows a few options at a time
    assert (rec["address1"], rec["city"], rec["state"], rec["postal"]) == ("100 Test St", "Madison", "Wisconsin", "53703")
    # My Experience: wrong parsed entries replaced from the resume, the invented one deleted, a missing one added
    exp, edu = master["experience"], master["education"]
    assert [(w["title"], w["company"], w["location"], w["current"]) for w in rec["work"]] == \
        [(e["title"], e["org"], e["location"], False) for e in exp]
    assert [(w["start"], w["end"]) for w in rec["work"]] == [("01/2026", "05/2026"), ("06/2024", "08/2024")]
    assert all(w["description"].startswith("• ") and "**" not in w["description"] for w in rec["work"])
    # degree already "Masters of Science (MS)" (= Master of Science) is kept; the added entry gets "(BS)"
    assert [(e["school"], e["degree"], e["field"], e["gpa"], e["to"]) for e in rec["edu"]] == [
        ("University of Wisconsin–Madison", "Masters of Science (MS)", "Data Science", "", "2027"),
        ("University of Oklahoma", "Bachelor of Science (BS)", "Computer Science", "3.85", "2026")]
    assert rec["resume_cv"] == "Resume_VietAnhNguyen.pdf"   # Workday's unnamed Resume/CV upload box
    assert rec["extension"] == ""                           # a phone number in Phone Extension is cleared
    assert (rec["phone_type"], rec["source"], rec["prev"]) == ("Mobile", "Job Board", "No")
    assert (rec["authorized"], rec["sponsorship"]) == ("Yes", "Yes")
    assert (rec["grad_m"], rec["grad_y"]) == ("12", "2027")
    s = db.new_session()
    assert s.get(Job, jid).status == JobStatus.SUBMITTED.value
    s.close()


def _upload_answers(tmp_path):
    from hunt.apply.answers import PlannedAnswer
    pdf = tmp_path / "Resume_VietAnhNguyen.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%mock resume\n")
    answers = [PlannedAnswer("_systemfield_name", "Name", "text", True, "Viet Anh Nguyen", "fixed"),
               PlannedAnswer("_systemfield_resume", "Resume", "file", True, "resume", "file")]
    return answers, {"resume": pdf}


def test_submit_waits_for_background_resume_upload(db, mock_ats, tmp_path):
    """Ashby uploads the resume in the background; clicking Submit before it finishes
    sends an application without a resume. The submit must wait for the upload."""
    from hunt.apply.browser import Browser, collect_fields, run_form
    base, submissions = mock_ats
    answers, files = _upload_answers(tmp_path)
    with Browser() as b:
        page = b.new_page()
        page.goto(f"{base}/ashby/slow")
        selectors = {f.name: f.description for f in collect_fields(page)}
        res = run_form(page, f"{base}/ashby/slow", answers, files, submit=True, selectors=selectors)
    assert res.status == "submitted", res.error
    assert submissions[-1]["job_id"] == "ashby-slow"
    assert submissions[-1]["files"]["resume"]["filename"] == "Resume_VietAnhNguyen.pdf"


def test_resume_that_never_finishes_uploading_is_not_submitted(db, mock_ats, tmp_path, monkeypatch):
    from hunt.apply import browser
    base, submissions = mock_ats
    monkeypatch.setattr(browser, "UPLOAD_TIMEOUT_S", 4.0)
    answers, files = _upload_answers(tmp_path)
    with browser.Browser() as b:
        page = b.new_page()
        page.goto(f"{base}/ashby/stuck")
        selectors = {f.name: f.description for f in browser.collect_fields(page)}
        res = browser.run_form(page, f"{base}/ashby/stuck", answers, files, submit=True, selectors=selectors)
    assert res.status == "failed" and "did not finish uploading" in res.error
    assert not res.submit_clicked
    assert not [s for s in submissions if s["job_id"] == "ashby-stuck"]


ASHBY_YESNO = """<!doctype html><html><body><form>
<div class="ashby-application-form-field-entry" data-field-path="gov">
  <label class="ashby-application-form-question-title _required_x" for="gov">Have you previously worked for Acme?</label>
  <div class="ashby-application-form-input-yesno">
    <button type="button" aria-pressed="false" data-option="yes">Yes</button>
    <button type="button" aria-pressed="false" data-option="no">No</button>
    <input type="checkbox" tabindex="-1" name="gov-uuid" style="position:absolute;opacity:0;width:1px;height:1px">
  </div>
</div>
<script>
document.querySelectorAll('.ashby-application-form-input-yesno button').forEach(b => b.addEventListener('click', () => {
  b.parentElement.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', 'false'));
  b.setAttribute('aria-pressed', 'true');
  b.parentElement.querySelector('input').checked = b.dataset.option === 'yes';
}));
</script>
</form></body></html>"""


def test_ashby_yes_no_buttons_are_read_and_filled(db):
    """Ashby renders Yes/No questions as two buttons over a hidden checkbox."""
    from hunt.apply.answers import PlannedAnswer
    from hunt.apply.browser import Browser, collect_fields, fill_answer
    with Browser() as b:
        page = b.new_page()
        page.set_content(ASHBY_YESNO)
        f = {x.name: x for x in collect_fields(page)}["gov-uuid"]
        assert f.type == "yesno" and f.required and f.options == ["Yes", "No"]
        assert f.label == "Have you previously worked for Acme?"
        ans = PlannedAnswer(f.name, f.label, "yesno", True, "No", "fixed", options=f.options)
        assert fill_answer(page, ans, {}, f.description)
        assert page.locator("button[data-option=no]").get_attribute("aria-pressed") == "true"
        assert not page.locator("input[name=gov-uuid]").is_checked()


ASHBY_EDUCATION = """<!doctype html><html><body><form>
<div class="ashby-application-form-field-entry" data-field-path="_systemfield_education_history">
 <label class="ashby-application-form-question-title _required_x" for="_systemfield_education_history">Education History</label>
 <div class="ashby-application-form-input-education-entry">
  <label class="ashby-application-form-question-title _required_x" for="_systemfield_education_history-school">School</label>
  <input class="ashby-application-form-input-autocomplete" role="combobox" placeholder="Search schools..." value="">
  <div id="lb" role="listbox"></div>
  <label for="_systemfield_education_history-degree">Degree</label><input id="_systemfield_education_history-degree" type="text">
  <label for="_systemfield_education_history-major">Field of Study</label><input id="_systemfield_education_history-major" type="text">
  <div id="_systemfield_education_history-startDate">
   <select><option value="">Month...</option><option value="8">August</option><option value="9">September</option></select>
   <select><option value="">Year...</option><option value="2027">2027</option><option value="2026">2026</option></select></div>
  <div id="_systemfield_education_history-endDate">
   <select><option value="">Month...</option><option value="5">May</option><option value="12">December</option></select>
   <select><option value="">Year...</option><option value="2027">2027</option><option value="2026">2026</option></select></div>
  <label><input type="checkbox" id="_systemfield_education_history-isCurrent">Still Student?</label>
 </div>
</div>
<script>
const SCHOOLS = ['University of Wisconsin System', 'University of Wisconsin–Oshkosh', 'University of Wisconsin–Madison'];
const box = document.querySelector('[role=combobox]'), lb = document.getElementById('lb');
box.addEventListener('input', () => {
  lb.innerHTML = SCHOOLS.filter(s => s.toLowerCase().includes(box.value.toLowerCase().slice(0, 10)))
    .map(s => `<div role="option">${s}<br>United States<br>example.edu</div>`).join('');
  lb.querySelectorAll('[role=option]').forEach(o => o.addEventListener('click', () => {
    box.value = o.childNodes[0].textContent; lb.innerHTML = ''; }));
});
</script></form></body></html>"""


def test_ashby_education_history_is_one_field_and_filled(db):
    import json
    from hunt.apply.answers import PlannedAnswer
    from hunt.apply.browser import Browser, collect_fields, fill_answer
    with Browser() as b:
        page = b.new_page()
        page.set_content(ASHBY_EDUCATION)
        fields = collect_fields(page)
        assert [(f.name, f.type, f.required) for f in fields] == [("_systemfield_education_history", "ashby_education", True)]
        value = json.dumps({"school": "University of Wisconsin–Madison", "degree": "Master of Science", "major": "Data Science",
                            "start": [9, 2026], "end": [12, 2027], "current": True}, ensure_ascii=False)
        ans = PlannedAnswer(fields[0].name, fields[0].label, "ashby_education", True, value, "fixed")
        assert fill_answer(page, ans, {}, fields[0].description)
        assert page.locator("[role=combobox]").input_value() == "University of Wisconsin–Madison"
        assert page.locator("#_systemfield_education_history-degree").input_value() == "Master of Science"
        assert page.locator("#_systemfield_education_history-major").input_value() == "Data Science"
        start = page.locator("#_systemfield_education_history-startDate select")
        end = page.locator("#_systemfield_education_history-endDate select")
        assert [start.nth(0).input_value(), start.nth(1).input_value()] == ["9", "2026"]
        assert [end.nth(0).input_value(), end.nth(1).input_value()] == ["12", "2027"]
        assert page.locator("#_systemfield_education_history-isCurrent").is_checked()


REVEALED_RACE = """<html><body><form>
<label for="gender">Gender</label><select id="gender" name="gender"><option value=""></option><option>Male</option><option>Female</option></select>
<label for="hispanic_ethnicity">Are you Hispanic/Latino?</label>
<select id="hispanic_ethnicity" name="hispanic_ethnicity"><option value=""></option><option>Yes</option><option>No</option></select>
<div id="more"></div>
<script>
document.getElementById('hispanic_ethnicity').addEventListener('change', (e) => {
  document.getElementById('more').innerHTML = e.target.value === 'No'
    ? '<label for="race">Please identify your race</label><select id="race" name="race"><option value=""></option>'
      + '<option>Asian</option><option>White</option><option>Decline To Self Identify</option></select>' : '';
});
</script></form></body></html>"""


def test_questions_revealed_by_an_answer_are_filled_too(db):
    """Greenhouse shows the race question only after 'Hispanic/Latino: No'."""
    from hunt.apply.answers import PlannedAnswer
    from hunt.apply.browser import Browser, collect_fields, fill_all
    eeo = {"Gender": "Male", "Are you Hispanic/Latino?": "No", "Please identify your race": "Asian"}

    def plan(fields):
        return ([PlannedAnswer(f.name, f.label, f.type, False, eeo[f.label], "sensitive") for f in fields],
                {f.name: f.description for f in fields})

    with Browser() as b:
        page = b.new_page()
        page.set_content(REVEALED_RACE)
        first = collect_fields(page)
        assert [f.name for f in first] == ["gender", "hispanic_ethnicity"]  # no race question yet
        answers, selectors = plan(first)
        filled, unfilled = fill_all(page, answers, {}, selectors,
                                    replan=lambda seen: plan([f for f in collect_fields(page) if f.name not in seen]))
        assert page.locator("#race").input_value() == "Asian"
        assert "Please identify your race" in filled and not unfilled
        assert [a.name for a in answers] == ["gender", "hispanic_ethnicity", "race"]


def test_finish_all_works_through_the_queue(db, mock_ats):
    """Finish all: one window, each prepared application in turn; you submit or skip each."""
    from hunt.apply import assist
    from hunt.models import Job, JobStatus
    base, submissions = mock_ats
    finish = "Not submitted – this site asks you to confirm you're human (emailed code). Click Finish application."
    std, cap, unk = _assist_jobs(db, base, ("mock-standard", "mock-captcha", "mock-unknown"), next_action=finish)
    from datetime import timedelta
    from hunt.db import utcnow
    s = db.new_session()
    for k, jid in enumerate((unk, std, cap)):  # posted: unk 3 days ago, std 2 days ago (older than "fresh"), cap today
        j = s.get(Job, jid)
        j.date_posted = j.date_discovered = utcnow() - timedelta(days=3 - k, hours=1 if k < 2 else 0)
    s.commit()
    s.close()
    seen = []

    def applicant(page):  # plays your part for whichever application is open
        jid = assist.status()["job_id"]
        seen.append(jid)
        assert page.locator("#summer2027-hunt-banner [data-hunt-action=skip]").count() == 1
        if jid == cap:
            page.click("#summer2027-hunt-banner [data-hunt-action=skip]")  # you don't want this one
            return
        if jid == unk:
            page.fill("#question_1099", "Open to the posted range")  # the field left for you
        page.click("#submit_app")

    st = assist.start_queue(headless=True, on_ready=applicant, wait=True)  # builds the queue itself
    assert seen == [cap, std, unk], seen  # fresh (today / yesterday) first, then most recently posted
    assert st["state"] == "done" and st["queue"]["submitted"] == 2 and st["queue"]["skipped"] == 1, st
    assert [x["job_id"] for x in submissions] == ["mock-standard", "mock-unknown"]
    s = db.new_session()
    assert s.get(Job, std).status == JobStatus.SUBMITTED.value
    assert s.get(Job, unk).status == JobStatus.SUBMITTED.value
    skipped = s.get(Job, cap)
    assert skipped.status == JobStatus.SKIPPED.value  # not offered again
    from hunt.pipeline.stages import finish_queue_jobs
    assert finish_queue_jobs(s, {"greenhouse", "mock"}, include_test=True) == []
    s.close()


def test_finish_all_stops_when_you_press_stop(db, mock_ats):
    from hunt.apply import assist
    from hunt.models import Job, JobStatus
    base, submissions = mock_ats
    finish = "Not submitted – Click Finish application."
    std, cap = _assist_jobs(db, base, ("mock-standard", "mock-captcha"), next_action=finish)

    st = assist.start_queue(headless=True, wait=True,
                            on_ready=lambda page: page.click("#summer2027-hunt-banner [data-hunt-action=stop]"))
    assert st["state"] == "cancelled" and st["queue"]["position"] == 1 and not submissions, st
    s = db.new_session()
    assert s.get(Job, std).status == JobStatus.BLOCKED.value and s.get(Job, std).next_action == finish
    assert s.get(Job, cap).status == JobStatus.BLOCKED.value
    s.close()


def test_finish_shows_the_emailed_code_and_you_type_it(db, mock_ats, monkeypatch):
    """Code helper: the site emails a security code; the system finds it in the inbox and
    shows it in the top bar. It never types it: the applicant does."""
    from hunt.apply import assist
    from hunt.mock_ats import app as mock
    from hunt.models import Job, JobStatus
    from hunt.notify import email_monitor
    base, submissions = mock_ats
    jid = _assist_jobs(db, base)[0]
    s = db.new_session()
    s.get(Job, jid).apply_url = f"{base}/jobs/mock-verify"
    s.commit()
    s.close()
    monkeypatch.setattr(email_monitor, "imap_configured", lambda: True)
    asked = []
    monkeypatch.setattr(email_monitor, "find_verification_code",
                        lambda since, company=None: asked.append(company) or (mock.VERIFY_CODE, "Security code for your application", None))
    monkeypatch.setattr(assist, "CODE_POLL_SECONDS", 0)
    typed = []

    def on_code(page, code):  # plays your part once the code is shown
        assert code in page.locator("#summer2027-hunt-banner").inner_text()
        assert page.locator("#security_code").input_value() == "", "the system must never type the code"
        assert not submissions, "nothing is submitted before you enter the code"
        page.fill("#security_code", code)
        page.click("#verify_btn")
        typed.append(code)

    st = assist.start(jid, headless=True, on_ready=lambda page: page.click("#submit_app"), hooks={"on_code": on_code}, wait=True)
    assert st["state"] == "confirmed" and st["code"] == mock.VERIFY_CODE, st
    assert typed == [mock.VERIFY_CODE] and asked and asked[0] == "Mock Analytics Co (TEST)"
    assert submissions[-1]["job_id"] == "mock-verify" and submissions[-1]["confirmation"]
    s = db.new_session()
    assert s.get(Job, jid).status == JobStatus.SUBMITTED.value
    s.close()


def test_code_helper_shows_only_the_newest_code(db, monkeypatch):
    """Codes from earlier attempts are ignored and a newer code replaces the shown one."""
    from datetime import timedelta
    from types import SimpleNamespace
    from hunt.apply import assist
    from hunt.apply.browser import Browser
    from hunt.db import utcnow
    from hunt.notify import email_monitor
    monkeypatch.setattr(email_monitor, "imap_configured", lambda: True)
    monkeypatch.setattr(assist, "CODE_POLL_SECONDS", 0)
    t0 = utcnow()
    inbox = [("NewCodeA1", "Security code for your application to Acme", t0 + timedelta(seconds=5))]
    since_seen = []
    monkeypatch.setattr(email_monitor, "find_verification_code",
                        lambda since, company=None: since_seen.append(since) or inbox[-1])
    with Browser() as b:
        page = b.new_page()
        page.set_content("<p>A verification code has been sent to your email.</p><input id='security_code'>")
        tick = assist._code_helper(page, SimpleNamespace(company="Acme"), {})
        tick()
        assert "NewCodeA1" in page.locator("#summer2027-hunt-banner").inner_text()
        assert since_seen[0] >= t0 - timedelta(seconds=assist.CODE_CLOCK_SKEW + 2)  # only codes sent after the form opened
        inbox.append(("NewerB22", "Security code for your application to Acme", t0 + timedelta(seconds=60)))  # "resend code"
        tick()
        assert "NewerB22" in page.locator("#summer2027-hunt-banner").inner_text() and assist.status()["code"] == "NewerB22"
        assert page.locator("#security_code").input_value() == ""


def test_workday_checkboxes_under_one_question_are_one_choice_list(db):
    """Tencent: 'Please select race/ethnicity' is a set of checkboxes in one Workday field."""
    from hunt.apply.answers import PlannedAnswer
    from hunt.apply.browser import Browser, collect_fields, fill_answer
    html = """<html><body><div data-automation-id="formField-race"><legend>Please select race/ethnicity:<abbr title="required">*</abbr></legend>
    <input type="checkbox" id="r1"><label for="r1">Asian (United States of America)</label>
    <input type="checkbox" id="r2"><label for="r2">Hispanic or Latino (United States of America)</label>
    <input type="checkbox" id="r3"><label for="r3">White (United States of America)</label></div></body></html>"""
    with Browser() as b:
        page = b.new_page()
        page.set_content(html)
        fields = collect_fields(page)
        assert [(f.label, f.type, len(f.options)) for f in fields] == [("Please select race/ethnicity:", "multi_select", 3)]
        f = fields[0]
        assert fill_answer(page, PlannedAnswer(f.name, f.label, f.type, True, ["Asian (United States of America)"], "sensitive",
                                               options=f.options), {}, f.description)
        assert page.locator("#r1").is_checked() and not page.locator("#r2").is_checked()
