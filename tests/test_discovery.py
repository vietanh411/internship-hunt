from datetime import datetime, timedelta

import pytest

from hunt.discovery.base import RawPosting
from hunt.discovery.feeds import parse_feed
from hunt.discovery.normalize import (
    classify_category,
    is_us_location,
    metro_of,
    parse_ats_url,
    parse_salary,
    summer_2027_status,
)


def test_parse_ats_urls():
    r = parse_ats_url("https://job-boards.greenhouse.io/figma/jobs/6131089004")
    assert (r.platform, r.board, r.job_id) == ("greenhouse", "figma", "6131089004")
    r = parse_ats_url("https://boards.greenhouse.io/embed/job_app?for=acme&token=123")
    assert (r.platform, r.board, r.job_id) == ("greenhouse", "acme", "123")
    r = parse_ats_url("https://jobs.lever.co/palantir/d5486403-c050/apply")
    assert (r.platform, r.board, r.job_id) == ("lever", "palantir", "d5486403-c050")
    r = parse_ats_url("https://jobs.ashbyhq.com/ellipsislabs/02136b22")
    assert (r.platform, r.board) == ("ashby", "ellipsislabs")
    r = parse_ats_url("https://marmon.wd501.myworkdayjobs.com/en-US/Marmon_MSIP_Internships/job/Milwaukee-WI/Data-Engineering-Intern_JR0000037453")
    assert r.platform == "workday"
    assert r.board == "marmon.wd501.myworkdayjobs.com|marmon|Marmon_MSIP_Internships"
    assert r.job_id == "/job/Milwaukee-WI/Data-Engineering-Intern_JR0000037453"
    assert parse_ats_url("https://careers.example.com/job?gh_jid=42").job_id == "42"
    assert parse_ats_url("https://example.com/careers").platform is None


def test_feed_parsing_keeps_only_active_summer_2027():
    data = [
        {"active": True, "is_visible": True, "terms": ["Summer 2027"], "company_name": "A", "title": "Data Intern",
         "url": "https://jobs.lever.co/a/1", "locations": ["Chicago, IL"], "date_posted": 1791849600, "sponsorship": "Other"},
        {"active": False, "is_visible": True, "terms": ["Summer 2027"], "company_name": "B", "title": "x", "url": "u"},
        {"active": True, "is_visible": True, "terms": ["Fall 2026"], "company_name": "C", "title": "x", "url": "u"},
        {"active": True, "is_visible": False, "terms": ["Summer 2027"], "company_name": "D", "title": "x", "url": "u"},
    ]
    out = parse_feed("simplify", data)
    assert [p.company for p in out] == ["A"]
    assert out[0].ats_platform == "lever" and out[0].feed_flags["sponsorship"] == "Other"


def test_location_helpers():
    assert metro_of("Plano, TX")[0] == "Dallas, TX"
    assert metro_of("Middleton, WI") == ("Madison, WI", "preferred")
    assert metro_of("Milwaukee, WI")[1] == "nearby"
    assert metro_of("Remote in USA")[1] == "remote"
    assert metro_of("Austin, TX")[1] == "other"
    assert not is_us_location("Toronto, ON, Canada")
    assert is_us_location("New York, NY")


def test_term_detection():
    assert summer_2027_status("Data Science Intern (Summer 2027)", "") == "confirmed"
    assert summer_2027_status("Data Science Intern", "Join us for summer 2027 from May to August") == "confirmed"
    assert summer_2027_status("Software Intern - Fall 2026", "") == "other_term"
    assert summer_2027_status("Summer Analyst", "") == "likely"
    assert summer_2027_status("Data Intern", "") == "unconfirmed"
    assert summer_2027_status("x", "", ["Summer 2027", "Fall 2027"]) == "confirmed"


def test_category_classification():
    assert classify_category("Data Science Intern") == "data_science"
    assert classify_category("Software Engineering Intern") == "software"
    assert classify_category("Quantitative Research Intern") == "quant"
    assert classify_category("Mechanical Engineering Intern") is None
    assert classify_category("Marketing Intern") is None
    assert classify_category("Marketing Analytics Intern") == "data_analytics"


def test_salary_parsing():
    assert parse_salary("Pay range: $25 - $32 per hour")[:3] == (25.0, 32.0, "hour")
    assert parse_salary("$10,000/month stipend")[2] == "month"
    assert parse_salary("$80,000 - $95,000 annually")[2] == "year"
    assert parse_salary("No pay info")[0] is None


def _posting(**kw):
    base = dict(source="greenhouse", company="Acme Analytics", title="Data Science Intern (Summer 2027)",
                url="https://job-boards.greenhouse.io/acme/jobs/1", ats_platform="greenhouse", ats_board="acme",
                ats_job_id="1", locations=["Chicago, IL"], date_posted=datetime.utcnow(),
                description_text="Summer 2027 internship. Python and SQL required. " * 10)
    base.update(kw)
    return RawPosting(**base)


def test_discovery_filter(session):
    from types import SimpleNamespace
    from hunt.pipeline.stages import qualifies
    from hunt.settings_store import get_automation
    rc = SimpleNamespace(settings=get_automation(session))
    assert qualifies(_posting(), rc, False)[0]
    assert qualifies(_posting(title="Mechanical Engineering Intern"), rc, False)[1] == "role outside target categories"
    assert qualifies(_posting(locations=["London, UK"]), rc, False)[1] == "outside the United States"
    assert qualifies(_posting(title="Data Science Intern - Fall 2026", description_text="Fall 2026 co-op"), rc, False)[1] == "not a Summer 2027 term"
    assert qualifies(_posting(date_posted=datetime.utcnow() - timedelta(days=200)), rc, False)[1] == "posting older than max age"
    assert qualifies(_posting(title="Senior Data Scientist"), rc, False)[1] == "not an internship"
    assert qualifies(_posting(degrees=["PhD"]), rc, True)[1] == "PhD-only"
