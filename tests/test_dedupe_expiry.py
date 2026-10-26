from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import func, select

from hunt.dedupe import upsert_posting
from hunt.discovery import ats
from hunt.discovery.base import RawPosting
from hunt.models import Job, JobStatus


def P(**kw):
    base = dict(source="simplify", company="Acme Analytics, Inc.", title="Data Science Intern (Summer 2027)",
                url="https://job-boards.greenhouse.io/acme/jobs/555", ats_platform="greenhouse", ats_board="acme",
                ats_job_id="555", locations=["Chicago, IL"], date_posted=datetime(2026, 10, 1))
    base.update(kw)
    return RawPosting(**base)


def test_same_requisition_from_two_sources_is_one_job(session):
    r1 = upsert_posting(session, P())
    r2 = upsert_posting(session, P(source="greenhouse", company="Acme Analytics", description_text="Full JD " * 50))
    session.commit()
    assert r1.created and not r2.created and r2.merged_from_other_source
    assert session.scalar(select(func.count(Job.id))) == 1
    job = r1.job
    assert set(job.sources) == {"simplify", "greenhouse"}
    assert job.source == "greenhouse"  # direct ATS source preferred
    assert "Full JD" in job.description_text


def test_company_hosted_copy_matches_by_company_title_location(session):
    upsert_posting(session, P())
    r = upsert_posting(session, P(source="vanshb03", url="https://careers.acme.com/jobs/data-science-intern",
                                  ats_platform=None, ats_board=None, ats_job_id=None))
    session.commit()
    assert not r.created
    assert session.scalar(select(func.count(Job.id))) == 1


def test_same_title_different_cities_are_different_jobs(session):
    upsert_posting(session, P(url="u1", ats_platform=None, ats_board=None, ats_job_id=None, locations=["Chicago, IL"]))
    r = upsert_posting(session, P(url="u2", ats_platform=None, ats_board=None, ats_job_id=None, locations=["Dallas, TX"]))
    session.commit()
    assert r.created
    assert session.scalar(select(func.count(Job.id))) == 2


def test_requisition_ids_distinguish_postings(session):
    upsert_posting(session, P(url="https://x.com/a", ats_platform=None, ats_board=None, ats_job_id=None, title="Data Intern R12345"))
    r = upsert_posting(session, P(url="https://x.com/b", ats_platform=None, ats_board=None, ats_job_id=None, title="Data Intern R99999"))
    session.commit()
    assert r.created


def _rc(session):
    from hunt.pipeline.stages import RunContext  # noqa: F401
    from hunt.models import PipelineRun
    run = PipelineRun(trigger="test", status="running")
    session.add(run)
    session.flush()
    return SimpleNamespace(session=session, run=run, client=None, board_cache={})


def test_expired_when_ats_reports_gone(session, monkeypatch):
    from hunt.pipeline import stages
    job = upsert_posting(session, P(source="greenhouse")).job
    session.commit()
    rc = _rc(session)
    rc.board_cache[("greenhouse", "acme")] = {}  # board listing no longer contains the job

    def gone(*a, **k):
        raise ats.PostingGone("gone")
    monkeypatch.setattr(ats, "greenhouse_job", gone)
    assert stages.verify_one(rc, job) == "expired"
    assert job.status == JobStatus.EXPIRED.value and job.verified_active is False


def test_active_job_gets_details_merged(session, monkeypatch):
    from hunt.pipeline import stages
    job = upsert_posting(session, P()).job
    session.commit()
    rc = _rc(session)
    rc.board_cache[("greenhouse", "acme")] = {"555": P(source="greenhouse", description_text="Summer 2027. Python SQL. " * 30,
                                                       salary_min=30, salary_max=35, salary_period="hour", salary_text="$30-35/hr")}
    assert stages.verify_one(rc, job) == "active"
    assert job.verified_active and job.salary_min == 30 and job.description_text.startswith("Summer 2027")


def test_closed_page_text_marks_expired(session):
    from hunt.pipeline import stages
    job = upsert_posting(session, P(url="https://careers.example.com/job/9", ats_platform=None, ats_board=None, ats_job_id=None)).job
    session.commit()
    rc = _rc(session)

    class FakeClient:
        def request(self, method, url, **kw):
            return SimpleNamespace(text="<html><body><h1>Sorry, this position has been filled.</h1></body></html>")
    rc.client = FakeClient()
    assert stages.verify_one(rc, job) == "expired"


def test_cleanup_removes_old_and_ineligible_listings_but_keeps_your_applications(session, tmp_path):
    """Every run: listings older than 30 days (posting date, else first seen) and
    ineligible ones are removed; anything applied to (or maybe applied to) is kept;
    removed listings are not re-added by discovery."""
    from datetime import timedelta
    from hunt.db import utcnow
    from hunt.models import Application, RemovedListing
    from hunt.pipeline.stages import purge_listings
    now = utcnow()
    tmp = tmp_path

    def job(n, status, posted_days=None, seen_days=0, eligibility="eligible", applied=False, next_action=None):
        j = upsert_posting(session, P(url=f"https://job-boards.greenhouse.io/acme/jobs/{n}", ats_job_id=str(n),
                                      title=f"Data Science Intern {n} (Summer 2027)",
                                      date_posted=(now - timedelta(days=posted_days)) if posted_days is not None else None)).job
        j.status, j.eligibility, j.next_action = status.value, eligibility, next_action
        j.date_discovered = now - timedelta(days=seen_days)
        if applied or next_action or n == 2:
            a = Application(job_id=j.id, idempotency_key=f"app:{n}", date_applied=now if applied else None, attempts=1)
            session.add(a)
            session.flush()
            if n == 2:  # a prepared application pointing at its resume + screenshot (the real-data case)
                from hunt.models import Artifact, ResumeVersion
                art = Artifact(job_id=j.id, kind="resume", filename="r.pdf", path=str(tmp / "r.pdf"), content_type="application/pdf", content=b"%PDF", sha256="0" * 64)
                session.add(art)
                session.flush()
                rv = ResumeVersion(job_id=j.id, version_id=f"rv-{n}", artifact_id=art.id, master_version=1)
                session.add(rv)
                session.flush()
                a.resume_version_id, a.evidence_artifact_id = rv.id, art.id
        return j

    fresh = job(1, JobStatus.READY_TO_APPLY, posted_days=5)
    old = job(2, JobStatus.READY_TO_APPLY, posted_days=45)
    undated_old = job(3, JobStatus.MATCHED, posted_days=None, seen_days=40)
    inel = job(4, JobStatus.INELIGIBLE, posted_days=2, eligibility="ineligible")
    sent_old = job(5, JobStatus.SUBMITTED, posted_days=60, applied=True)
    maybe_sent = job(6, JobStatus.BLOCKED, posted_days=60, next_action="Check email/portal for a confirmation, then mark Submitted or Retry")
    session.commit()
    keys = {j.id: j.canonical_key for j in (old, undated_old, inel)}
    kept_ids = {fresh.id, sent_old.id, maybe_sent.id}

    rc = SimpleNamespace(session=session, settings={"max_posting_age_days": 30}, log=lambda *a, **k: None)
    stats = purge_listings(rc)
    assert stats == {"older than 30 days": 2, "ineligible": 1}
    assert set(session.scalars(select(Job.id)).all()) == kept_ids
    assert set(session.scalars(select(RemovedListing.canonical_key)).all()) == set(keys.values())
    # discovery does not bring a removed listing back
    again = upsert_posting(session, P(url="https://job-boards.greenhouse.io/acme/jobs/3", ats_job_id="3",
                                      title="Data Science Intern 3 (Summer 2027)", date_posted=None))
    assert again.removed and again.job is None and not again.created
