import pytest

from hunt.eligibility import classify

CASES = [
    ("Candidates must be U.S. citizens due to contract requirements.", "ineligible", "citizenship_required"),
    ("U.S. citizenship is required for this position.", "ineligible", "citizenship_required"),
    ("This position does not require U.S. citizenship.", "eligible", None),
    ("We are an equal opportunity employer and consider applicants without regard to race, citizenship status, or national origin.", "eligible", "not_stated"),
    ("Applicants must be able to obtain and maintain a Secret security clearance.", "ineligible", "clearance_required"),
    ("Must be a U.S. Person as defined by ITAR.", "ineligible", "us_person_export"),
    ("Applicants must be authorized to work in the United States without the need for current or future visa sponsorship.", "ineligible", "excludes_future_sponsorship"),
    ("Candidates must not now or in the future require sponsorship for employment visa status.", "ineligible", "excludes_future_sponsorship"),
    ("You must be authorized to work in the U.S. without employer sponsorship.", "review", "no_sponsorship_current"),
    ("We are unable to sponsor H-1B visas for this role.", "review", "no_future_sponsorship"),
    ("Students on F-1 visas with CPT or OPT are welcome to apply.", "eligible", "cpt_opt_accepted"),
    ("International students eligible for CPT/OPT are encouraged to apply. We do not sponsor H-1B visas.", "eligible", None),
    ("This internship is not eligible for CPT or OPT.", "ineligible", "excludes_f1"),
    ("Must be legally authorized to work in the United States.", "eligible", "authorization_generic"),
    ("Open to U.S. citizens, permanent residents, and students with F-1 OPT/CPT authorization.", "eligible", None),
    ("Great internship building dashboards in SQL and Python.", "eligible", "not_stated"),
    ("Must be a U.S. citizen or permanent resident.", "ineligible", None),
    ("Visa sponsorship is not available for this position.", "review", "no_future_sponsorship"),
    ("You will optimize pipelines; adoption of new tools is encouraged.", "eligible", "not_stated"),
    ("Please contact us with questions. Students may opt-in to our newsletter.", "eligible", "not_stated"),
]


@pytest.mark.parametrize("text,verdict,category", CASES)
def test_classify(text, verdict, category):
    r = classify(text)
    assert r.verdict == verdict, (r.category, r.reasons)
    if category:
        assert r.category == category


def test_feed_label_citizenship():
    r = classify("Software intern building APIs.", feed_sponsorship="U.S. Citizenship is Required")
    assert r.verdict == "ineligible"


def test_policy_settings_change_review_to_eligible():
    text = "You must be authorized to work in the U.S. without employer sponsorship."
    r = classify(text, policy={"no_sponsorship_current_only": "eligible"})
    assert r.verdict == "eligible"


def test_unstated_policy_can_require_review():
    r = classify("Analyze data with SQL.", policy={"unstated": "review"})
    assert r.verdict == "review"


def test_reasons_quote_posting_language():
    r = classify("Requirements: Python. Candidates must be U.S. citizens due to contract requirements.")
    assert any("must be US citizens" in q for q in r.snippets)


def test_conflicting_statements_go_to_review():
    text = ("F-1 students on CPT are welcome to apply. "
            "Candidates must not require sponsorship now or in the future.")
    assert classify(text).verdict == "review"
