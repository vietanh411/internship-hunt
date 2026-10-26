import copy
from types import SimpleNamespace

import yaml

from hunt.config import ROOT
from hunt.matching import build_applicant, extract_requirements, score_job
from hunt.resume.ats_check import ats_check
from hunt.resume.factguard import check_bullet, check_free_text, numbers_in
from hunt.resume.render import page_count, render_fitted
from hunt.resume.tailor import tailor_resume
from hunt.settings_store import DEFAULT_AUTOMATION

MASTER = yaml.safe_load(open(ROOT / "config" / "master_resume.yaml", encoding="utf-8"))
PROFILE = {"education": {"expected_graduation_date": "2027-12-15", "undergrad_gpa": "3.85"},
           "availability": {"earliest_start_date": "2027-05-30", "willing_to_relocate": True},
           "preferences": {"min_hourly_rate": 20}, "confirmed_extra_skills": []}

DS_JD = """About the role
You will analyze large datasets and build dashboards.

Requirements
- Pursuing a Master's degree in Data Science, Computer Science, or Statistics
- Proficiency in Python and SQL
- Experience with Pandas and scikit-learn
- Experience building ETL pipelines and Power BI dashboards

Preferred Qualifications
- NLP experience with spaCy
- Familiarity with Spark and AWS

Summer 2027 internship, 12 weeks. Pay $30/hour."""

ME_JD = """Requirements
- Pursuing a degree in Mechanical Engineering
- SolidWorks, GD&T, finite element analysis
- Experience machining parts
Summer 2027."""


def job(jd, title="Data Science Intern (Summer 2027)", eligibility="eligible", locations=("Madison, WI",), **kw):
    d = dict(title=title, company="Acme", company_norm="acme", description_text=jd, locations=list(locations),
             remote_type="onsite", eligibility=eligibility, terms=["Summer 2027"], feed_flags={"term_status": "confirmed"},
             salary_min=30, salary_max=30, salary_period="hour", degrees=[], date_posted=None)
    d.update(kw)
    return SimpleNamespace(**d)


def test_requirement_sections():
    r = extract_requirements(DS_JD)
    assert r.sectioned
    assert {"Python", "SQL", "Pandas", "scikit-learn"} <= set(r.required_skills)
    assert "Spark" in r.preferred_skills and "Spark" not in r.required_skills


def test_relevant_job_scores_higher_and_explains_gaps():
    app = build_applicant(MASTER, PROFILE)
    good = score_job(job(DS_JD), MASTER, PROFILE, DEFAULT_AUTOMATION, app)
    bad = score_job(job(ME_JD, title="Mechanical Engineering Intern"), MASTER, PROFILE, DEFAULT_AUTOMATION, app)
    assert good.score > 70 > bad.score
    assert good.tier in ("excellent", "strong")
    assert "Spark" in good.explanation["missing_preferred"]
    assert any("Python" in s for s in good.explanation["strengths"])
    assert good.explanation["evidence"], "explanation must cite resume evidence"


def test_location_and_eligibility_gate():
    app = build_applicant(MASTER, PROFILE)
    madison = score_job(job(DS_JD), MASTER, PROFILE, DEFAULT_AUTOMATION, app)
    austin = score_job(job(DS_JD, locations=["Austin, TX"]), MASTER, PROFILE, DEFAULT_AUTOMATION, app)
    assert madison.score > austin.score
    inel = score_job(job(DS_JD, eligibility="ineligible"), MASTER, PROFILE, DEFAULT_AUTOMATION, app)
    assert inel.score == 0 and "ineligible" in inel.gates


def test_weights_are_configurable():
    app = build_applicant(MASTER, PROFILE)
    s = copy.deepcopy(DEFAULT_AUTOMATION)
    s["scoring_weights"] = {"skills": 0, "experience": 0, "education": 0, "location": 100, "eligibility_timing": 0, "compensation": 0}
    r = score_job(job(DS_JD, locations=["Austin, TX"]), MASTER, PROFILE, s, app)
    assert abs(r.score - 40.0) < 0.01  # "other US" location = 0.4


def test_phd_posting_is_gated():
    app = build_applicant(MASTER, PROFILE)
    r = score_job(job("Requirements\n- Currently pursuing a PhD in Statistics\nSummer 2027"), MASTER, PROFILE, DEFAULT_AUTOMATION, app)
    assert "phd_required" in r.gates


# ---------------------------------------------------------------- fact guard

def test_factguard_rejects_new_numbers_skills_and_claims():
    orig = "Supported national internet policy research by processing and analyzing **10M+ DNS records** with **SQL** and exploratory data analysis."
    assert check_bullet(orig, "Analyzed **10M+ DNS records** with **SQL** and exploratory data analysis to support national internet policy research.", ["SQL", "EDA"]).ok
    assert not check_bullet(orig, "Analyzed **15M+ DNS records** with SQL.", ["SQL"]).ok           # changed number
    assert not check_bullet(orig, "Analyzed 10M+ DNS records with SQL and Spark.", ["SQL"]).ok       # new tool
    assert not check_bullet(orig, "Led a team analyzing 10M+ DNS records with SQL.", ["SQL"]).ok     # leadership claim
    assert not check_bullet(orig, "Analyzed 10M+ DNS records with SQL for Google.", ["SQL"]).ok      # new organisation
    assert not check_bullet(orig, "I analyzed 10M+ DNS records with SQL.", ["SQL"]).ok               # first person
    assert numbers_in("Cut load time by 30% for 100+ users and 3.5k rows") >= {"30%", "100", "3.5k"}


def test_free_text_guard():
    app = build_applicant(MASTER, PROFILE)
    ok = "At VNNIC I processed 10M+ DNS records with SQL. I am completing an MS in Data Science at University of Wisconsin–Madison."
    assert check_free_text(ok, MASTER, PROFILE, DS_JD, "Acme", app.skills).ok
    bad = "I built Kubernetes clusters that served 2 billion requests at Google."
    g = check_free_text(bad, MASTER, PROFILE, DS_JD, "Acme", app.skills)
    assert not g.ok and len(g.issues) >= 2


class FakeLLM:
    available = True
    calls = failures = 0

    def __init__(self, bullets):
        self._b = bullets

    def json(self, system, user, schema, **kw):
        return {"bullets": [{"id": k, "text": v, "posting_terms_used": []} for k, v in self._b.items()]}


def test_tailoring_accepts_truthful_rewrites_and_rejects_fabrication():
    llm = FakeLLM({
        "vn-1": "Analyzed **10M+ DNS records** with **SQL** and exploratory data analysis to support national internet policy research.",
        "vn-2": "Built **3+ ETL pipelines** in **Spark** that saved **$2M** annually.",          # fabricated tool + number
        "ou-2": "Led a thematic analysis of AI agent perceptions across **2 platforms**.",          # new leadership claim
        "js-1": "Collected **500+ job postings/day** for Microsoft using BeautifulSoup and Requests.",  # new org
    })
    res = tailor_resume(MASTER, PROFILE, job(DS_JD), DEFAULT_AUTOMATION, llm)
    texts = {b["id"]: b["text"] for s in ("experience", "projects") for e in res.resume[s] for b in e["bullets"]}
    assert texts["vn-1"].startswith("Analyzed **10M+")
    master_text = {b["id"]: b["text"] for s in ("experience", "projects") for e in MASTER[s] for b in e["bullets"]}
    for bid in ("vn-2", "ou-2", "js-1"):
        assert texts[bid] == master_text[bid] or "expl" in texts[bid].lower() or "ETL (extract" in texts[bid]
        assert "Spark" not in texts[bid] and "$2M" not in texts[bid] and "Microsoft" not in texts[bid] and not texts[bid].startswith("Led")
    rejected = {r["bullet"] for r in res.factcheck["rejected_rewrites"]}
    assert {"vn-2", "ou-2", "js-1"} <= rejected
    assert res.factcheck["passed"]
    assert res.resume["education"] == MASTER["education"] and res.resume["basics"] == MASTER["basics"]
    for e, m in zip(res.resume["experience"], MASTER["experience"]):
        assert (e["org"], e["title"], e["dates"]) == (m["org"], m["title"], m["dates"])
    assert res.llm_used


def test_tailoring_reorders_skills_toward_posting():
    res = tailor_resume(MASTER, PROFILE, job(DS_JD), DEFAULT_AUTOMATION, None)
    langs = next(g for g in res.resume["skills"] if g["category"] == "Languages")["items"]
    assert langs[:2] == ["Python", "SQL"] or langs[:2] == ["SQL", "Python"]
    all_master = {i for g in MASTER["skills"] for i in g["items"]}
    assert {i for g in res.resume["skills"] for i in g["items"]} == all_master  # nothing added


# ---------------------------------------------------------------- PDF

def test_pdf_is_one_page_and_ats_readable():
    res = tailor_resume(MASTER, PROFILE, job(DS_JD), DEFAULT_AUTOMATION, None)
    pdf, fitted, notes = render_fitted(res.resume, True)
    assert pdf[:5] == b"%PDF-"
    assert page_count(pdf) == 1
    check = ats_check(pdf, fitted, res.matched_keywords, True, "Resume_VietAnhNguyen.pdf")
    failed = [c for c in check["checks"] if not c["passed"]]
    assert check["passed"], failed
    assert check["keyword_coverage"]["ratio"] == 1.0


def test_undergraduate_only_internships_are_gated():
    from hunt.matching import undergrad_only
    # title says undergraduate (DFW Airport)
    assert undergrad_only("Undergraduate Internship - Environmental Technical Projects", "Summer 2027 internship.")
    assert undergrad_only("Undergrad Co-op – Interactive Developer", "")
    # description written only for undergraduates
    assert undergrad_only("Data Intern", "Requirements: rising senior working towards a bachelor’s degree in CS.")
    assert undergrad_only("Data Intern", "Currently pursuing a Bachelor's degree in Computer Science.")
    # graduate / Master's students are in scope: not gated
    assert not undergrad_only("Internship (Undergraduate / Master's)", "")
    assert not undergrad_only("Undergraduate or Graduate Data Intern", "")
    assert not undergrad_only("Biometrics Intern", "Master, doctoral or advanced undergraduate student in statistics.")
    assert not undergrad_only("Data Intern", "Open to rising seniors and graduate students.")
    assert not undergrad_only("Data Science Intern", "Pursuing a degree in data science or a related field.")
