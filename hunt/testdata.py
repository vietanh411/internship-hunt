"""Clearly-marked test jobs that point at the local mock ATS (is_test=True). They
exercise the submission path end to end; they are excluded from all dashboard
counts and can never reach a real employer."""
from __future__ import annotations

from sqlalchemy import select

from hunt.db import session_scope, utcnow
from hunt.models import Job, JobStatus

MOCK_JD = """Mock Analytics Co. (TEST FIXTURE – local mock ATS)

Summer 2027 Data Science Intern – Madison, WI

Responsibilities
- Build data pipelines and dashboards in SQL and Python
- Apply machine learning (regression, classification) to customer data
- Present insights to stakeholders

Requirements
- Pursuing a Bachelor's or Master's degree in Computer Science, Data Science, Statistics, or a related field
- Experience with Python, SQL, and Pandas
- Familiarity with scikit-learn and data visualization (Power BI or Tableau)

Preferred
- Experience with NLP or REST APIs
- Exposure to Docker and Git

Students on F-1 visas with CPT or OPT are welcome to apply.
Pay: $28 - $32 per hour.
"""

VARIANTS = [
    ("mock-standard", "TEST • Data Science Intern (Summer 2027) – standard form"),
    ("mock-captcha", "TEST • Data Analyst Intern (Summer 2027) – form with CAPTCHA"),
    ("mock-unknown", "TEST • ML Intern (Summer 2027) – form with an unverifiable question"),
]


def ensure_mock_jobs(base_url: str) -> list[int]:
    ids = []
    with session_scope() as s:
        for vid, title in VARIANTS:
            key = f"mock:test:{vid}"
            j = s.scalar(select(Job).where(Job.canonical_key == key))
            if j is not None and j.status not in (JobStatus.DISCOVERED.value,):
                # reset the fixture so every dry run exercises the full path
                s.delete(j)
                s.flush()
                j = None
            if j is None:
                import hashlib
                j = Job(uid=hashlib.sha1(key.encode()).hexdigest()[:16], canonical_key=key, company="Mock Analytics Co (TEST)",
                        company_norm="mock analytics test", title=title, ats_job_id=vid, ats_platform="mock", ats_board="mock",
                        location="Madison, WI", locations=["Madison, WI"], remote_type="onsite", salary_min=28, salary_max=32,
                        salary_period="hour", salary_text="$28 - $32 per hour", terms=["Summer 2027"], category="data_science",
                        description_text=MOCK_JD, posting_url=f"{base_url}/jobs/{vid}", apply_url=f"{base_url}/jobs/{vid}",
                        source="mock", sources=["mock"], date_posted=utcnow(), date_discovered=utcnow(),
                        verified_active=True, verified_at=utcnow(), verification_note="local mock ATS",
                        feed_flags={"term_status": "confirmed"}, is_test=True, status=JobStatus.DISCOVERED.value)
                s.add(j)
                s.flush()
            ids.append(j.id)
    return ids
