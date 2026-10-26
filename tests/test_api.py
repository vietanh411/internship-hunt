import io
import zipfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(db):
    from hunt.api.app import create_app
    return TestClient(create_app(start_background=False))


def _seed_job(db):
    from hunt.dedupe import upsert_posting
    from hunt.discovery.base import RawPosting
    s = db.new_session()
    j = upsert_posting(s, RawPosting(source="greenhouse", company="Acme", title="Data Science Intern (Summer 2027)",
                                     url="https://job-boards.greenhouse.io/acme/jobs/9", ats_platform="greenhouse",
                                     ats_board="acme", ats_job_id="9", locations=["Madison, WI"],
                                     description_text="Python SQL Summer 2027 " * 20)).job
    s.commit()
    jid = j.id
    s.close()
    return jid


def test_status_overview_and_jobs(client, db):
    jid = _seed_job(db)
    st = client.get("/api/status").json()
    assert st["schedule"].startswith("Daily 09:00 America/Chicago") and st["next_run"]
    assert any("Real submissions are disabled" in w for w in st["warnings"])
    ov = client.get("/api/overview").json()
    assert ov["total_discovered"] == 1 and len(ov["series"]["days"]) == 14
    res = client.get("/api/jobs", params={"q": "data", "location": "madison"}).json()
    assert res["total"] == 1 and res["items"][0]["id"] == jid
    d = client.get(f"/api/jobs/{jid}").json()
    assert d["company"] == "Acme" and d["events"] == []
    assert client.get(f"/api/jobs/{jid}/resume").status_code == 404
    kb = client.get("/api/pipeline").json()
    assert kb["discovered"]["total"] == 1


def test_settings_validation_and_audit(client):
    assert client.patch("/api/settings", json={"apply_mode": "yolo"}).status_code == 400
    assert client.patch("/api/settings", json={"not_a_setting": 1}).status_code == 400
    r = client.patch("/api/settings", json={"apply_mode": "auto", "daily_application_cap": 10,
                                            "scoring_weights": {"location": 20}}).json()
    assert r["apply_mode"] == "auto" and r["scoring_weights"]["location"] == 20 and r["scoring_weights"]["skills"] == 30
    assert client.get("/api/audit").json()[0]["action"] == "update_settings"


def test_manual_submitted_requires_confirmation(client, db):
    jid = _seed_job(db)
    assert client.post(f"/api/jobs/{jid}/status", json={"status": "submitted"}).status_code == 400
    r = client.post(f"/api/jobs/{jid}/status", json={"status": "submitted", "confirmation": "Email: Thanks for applying (#123)"})
    assert r.status_code == 200 and r.json()["status"] == "submitted"
    d = client.get(f"/api/jobs/{jid}").json()
    assert d["application"]["confirmation_source"] == "user" and d["events"][-1]["actor"] == "user"


def test_profile_onboarding_and_answer_library(client):
    p = client.get("/api/profile").json()
    assert "Confirm work authorization answers" in p["auto_apply_blockers"]
    lib = {a["key"]: a for a in client.get("/api/answers").json()}
    assert lib["require_sponsorship"]["approved"] is False  # until confirmed
    assert client.patch("/api/answers/require_sponsorship", json={"approved": True}).status_code == 409
    client.patch("/api/profile", json={"work_authorization": {"confirmed": True}})
    lib = {a["key"]: a for a in client.get("/api/answers").json()}
    assert lib["require_sponsorship"]["approved"] is True and lib["require_sponsorship"]["answer"] == "Yes"
    assert client.patch("/api/answers/certify_accurate", json={"approved": True}).status_code == 200


def test_export_and_delete(client, db):
    _seed_job(db)
    r = client.get("/api/export")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert {"jobs.json", "profile.json", "master_resume.json", "answers.json"} <= set(z.namelist())
    assert client.post("/api/data/delete", json={"confirm": "nope"}).status_code == 400
    assert client.post("/api/data/delete", json={"confirm": "DELETE", "scope": "jobs"}).json()["ok"]
    assert client.get("/api/overview").json()["total_discovered"] == 0


def test_password_protection(db, monkeypatch):
    from hunt import config
    monkeypatch.setenv("HUNT_DASHBOARD_PASSWORD", "s3cret")
    config.get_settings.cache_clear()
    from hunt.api.app import create_app
    c = TestClient(create_app(start_background=False))
    assert c.get("/api/overview").status_code == 401
    assert c.get("/api/health").status_code == 200
    assert c.post("/api/login", json={"password": "wrong"}).status_code == 401
    assert c.post("/api/login", json={"password": "s3cret"}).status_code == 200
    assert c.get("/api/overview").status_code == 200


def test_answering_question_unblocks_application(client, db):
    from hunt.models import Application, Artifact, Job, JobStatus, PendingQuestion, ResumeVersion
    jid = _seed_job(db)
    s = db.new_session()
    j = s.get(Job, jid)
    j.status = JobStatus.BLOCKED.value
    art = Artifact(job_id=jid, kind="resume", filename="Resume_VietAnhNguyen.pdf", content_type="application/pdf",
                   content=b"%PDF-", sha256="x")
    s.add(art)
    s.flush()
    s.add(ResumeVersion(version_id="rv-test-001", job_id=jid, artifact_id=art.id, master_version=1))
    q = PendingQuestion(job_id=jid, question="What are your salary expectations?", field_name="q9", required=True)
    s.add(q)
    s.flush()
    s.add(Application(job_id=jid, idempotency_key="app:t", unresolved=[{"id": q.id, "question": q.question}]))
    s.commit()
    qid = q.id
    s.close()
    r = client.post(f"/api/questions/{qid}/answer", json={"answer": "Open to the posted range", "save_to_library": True})
    assert r.status_code == 200
    d = client.get(f"/api/jobs/{jid}").json()
    assert d["open_questions"] == 0 and d["status"] == "resume_generated"
    lib = {a["key"]: a for a in client.get("/api/answers").json()}
    assert lib[f"user_q{qid}"]["answer"] == "Open to the posted range" and lib[f"user_q{qid}"]["approved"]


def test_no_counts_as_an_answer_in_onboarding(client):
    client.patch("/api/profile", json={"attestations": {"has_relatives_at_employer": False}})
    items = {i["path"]: i for i in client.get("/api/profile").json()["onboarding"]}
    assert items["attestations.has_relatives_at_employer"]["complete"] is True
    assert items["work_authorization.confirmed"]["complete"] is False
