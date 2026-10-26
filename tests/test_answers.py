import copy
from types import SimpleNamespace

import yaml

from hunt.apply.answers import Context, FormField, answer_field, check_contradictions, map_to_option
from hunt.config import ROOT
from hunt.profile_store import _jsonable

MASTER = yaml.safe_load(open(ROOT / "tests" / "fixtures" / "master_resume.yaml", encoding="utf-8"))
BASE_PROFILE = _jsonable(yaml.safe_load(open(ROOT / "tests" / "fixtures" / "profile.yaml", encoding="utf-8")))


def ctx(confirmed=True, eeo="ask", **profile_patch):
    p = copy.deepcopy(BASE_PROFILE)
    p["work_authorization"]["confirmed"] = confirmed
    p["eeo"]["policy"] = eeo
    p["contact"]["city"], p["contact"]["state"] = "Madison", "WI"
    p["attestations"]["is_over_18"] = True
    for k, v in profile_patch.items():
        p[k].update(v)
    job = SimpleNamespace(source="greenhouse", title="Data Intern", company="Acme", description_text="")
    return Context(profile=p, master=MASTER, job=job, company="Acme",
                   settings={"preferred_cities": ["Madison, WI", "Chicago, IL"], "auto_contextual_answers": True},
                   applicant_skills={"Python", "SQL", "Pandas"},
                   contextual=lambda q, n: "I processed 10M+ DNS records with SQL at VNNIC.")


YN = ["Yes", "No"]


def a(label, type_="select", options=YN, required=True, c=None):
    return answer_field(FormField("f", label, type_, required, list(options or [])), c or ctx())


def test_work_authorization_answers_follow_profile():
    assert a("Are you legally authorized to work in the United States?").value == "Yes"
    assert a("Will you now or in the future require sponsorship for employment visa status (e.g., H-1B)?").value == "Yes"
    assert a("Are you a U.S. citizen?").value == "No"
    assert a("Are you eligible for CPT?").value == "Yes"
    assert a("Do you have a green card / permanent residency?").value == "No"


def test_unconfirmed_work_authorization_requires_human():
    r = a("Are you legally authorized to work in the United States?", c=ctx(confirmed=False))
    assert r.kind == "human" and "confirm" in r.reason.lower()


def test_ambiguous_legal_questions_require_human():
    assert a("Are you authorized to work in the US without the need for visa sponsorship?").kind == "human"
    assert a("Do you currently require visa sponsorship?").kind == "human"
    assert a("Are you able to obtain a security clearance?").kind == "human"
    assert a("Are you a U.S. person under ITAR?").kind == "human"


def test_unverifiable_declarations_never_guessed():
    assert a("What are your salary expectations?", "text", []).kind == "human"
    assert a("How many years of Python experience do you have?", "text", []).kind == "human"
    assert a("Do you have any outstanding offers with deadlines?", "text", []).kind == "human"
    assert a("Describe your favorite quantum annealer", "select", ["A", "B"]).kind == "human"
    r = a("Some brand new required question we have never seen", "text", [])
    assert r.kind == "human" and r.reason == "No verified answer for this question"
    assert a("Optional unknown question", "text", [], required=False).kind == "skip"


def test_fixed_facts_and_formats():
    assert a("First Name", "text", []).value == "Viet Anh"
    assert a("Last Name", "text", []).value == "Nguyen"
    assert a("Email", "text", []).value == BASE_PROFILE["contact"]["email"]
    assert a("What is your expected graduation date?", "text", []).value == "December 2027"
    assert a("Expected graduation year", "text", []).value == "2027"
    assert a("Earliest start date", "text", []).value == "05/30/2027"
    assert a("Are you willing to relocate?").value == "Yes"
    assert a("Have you previously worked for Acme?").value == "No"
    assert a("Location preference", "select", ["London", "Chicago", "New York"]).value == "Chicago"
    assert a("What programming languages do you know?", "text", []).value.startswith("Python, SQL")
    assert a("Do you have experience with SQL?").value == "Yes"
    assert a("Do you have experience with Spark?").value == "No"


def test_gpa_ambiguity():
    assert a("Undergraduate GPA", "text", []).value == "3.85"
    assert a("Current GPA", "text", []).kind == "human"  # MS GPA not provided


def test_eeo_policy():
    assert a("Gender", "select", ["Male", "Female", "Decline To Self Identify"], required=False).kind == "skip"
    r = a("Gender", "select", ["Male", "Female", "Decline To Self Identify"], required=True)
    assert r.kind == "human"
    r = a("Gender", "select", ["Male", "Female", "Decline To Self Identify"], required=True, c=ctx(eeo="decline"))
    assert r.value == "Decline To Self Identify"
    r = a("Veteran status", "select", ["I am a protected veteran", "I am not a protected veteran", "I don't wish to answer"],
          required=True, c=ctx(eeo="decline"))
    assert r.value == "I don't wish to answer"


def test_attestations_need_approval():
    r = a("I certify that the information provided is true and complete", "checkbox", [])
    assert r.kind == "human"


def test_option_mapping():
    f = FormField("x", "q", "select", True, ["Yes, I will require sponsorship", "No, I will not require sponsorship"])
    assert map_to_option("Yes", f) == "Yes, I will require sponsorship"
    assert map_to_option("No", f) == "No, I will not require sponsorship"
    f2 = FormField("x", "q", "select", True, ["U.S. Citizen", "Permanent Resident", "F-1 Student (CPT/OPT)", "H-1B"])
    assert map_to_option("F-1", f2) == "F-1 Student (CPT/OPT)"
    f3 = FormField("x", "q", "select", True, ["Option A", "Option B"])
    assert map_to_option("Yes", f3) is None


def test_contextual_answers_and_files():
    assert a("Why are you interested in this role?", "textarea", []).kind == "contextual"
    assert answer_field(FormField("resume", "Resume/CV", "file", True), ctx()).value == "resume"
    assert answer_field(FormField("cover_letter", "Cover Letter", "file", False), ctx()).value == "cover_letter"


def test_contradiction_check_catches_profile_mismatch():
    c = ctx()
    ans = [answer_field(FormField("q1", "Will you require sponsorship now or in the future?", "select", True, YN), c)]
    assert check_contradictions(ans, c) == []
    ans[0].value = "No"
    assert check_contradictions(ans, c)


def test_greenhouse_education_end_date_is_graduation_not_availability():
    from hunt.models import ScreeningAnswer
    c = ctx()
    # a saved generic answer (e.g. internship end month) must not leak into the education block
    c.user_answers = [ScreeningAnswer(key="user_q1", label="End date month", answer="9", approved=True, source="user",
                                      patterns=["^end date month$"], kind="fixed")]
    month = answer_field(FormField("end-month--0", "End date month", "select", True, MONTHS_OPTS), c)
    year = answer_field(FormField("end-year--0", "End date year", "text", True, []), c)
    assert (month.value, year.value) == ("December", "2027")
    assert answer_field(FormField("end-month--0", "End date month", "combobox", True, []), c).value == "December"
    assert answer_field(FormField("school--0", "School", "combobox", True, []), c).value == "University of Wisconsin–Madison"
    assert answer_field(FormField("degree--0", "Degree", "select", True, ["Bachelor's Degree", "Master's Degree", "Doctorate"]), c).value == "Master's Degree"
    assert answer_field(FormField("start-month--0", "Start date month", "select", False, MONTHS_OPTS), c).kind == "skip"
    assert answer_field(FormField("end-year--1", "End date year", "text", False, []), c).kind == "skip"


MONTHS_OPTS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def test_rule_patterns_do_not_match_inside_other_words():
    assert a("Military or Veteran", "checkbox", [], required=False).rule != "export_control"
    assert a("Do you have any certifications?", "text", []).rule != "certify_accurate"
    assert a("Describe an excellent project you built", "textarea", []).rule != "phone"
    assert a("How do you embrace ambiguity?", "textarea", []).rule != "eeo_race"
    assert a("Do you have experience related to SQL?").rule != "relatives"
    assert a("Do you have relatives who work at Acme?").rule == "relatives"
    assert a("Are you currently enrolled in an undergraduate program?").value == "No"
    assert a("Are you currently enrolled in a graduate program?").value == "Yes"


def test_graduation_window_yes_no():
    assert a("Will you graduate from January 2028-Summer 2028?").value == "No"
    assert a("Will you graduate between May 2027 and June 2028?").value == "Yes"
    assert a("Do you expect to graduate between Fall 2027 and Spring 2028?").value == "Yes"


def test_education_start_date_from_profile():
    c = ctx(education={"current_start_date": "2026-09"})
    assert answer_field(FormField("start-month--0", "Start date month", "select", True, MONTHS_OPTS), c).value == "September"
    assert answer_field(FormField("start-year--0", "Start date year", "text", True, []), c).value == "2026"
    r = answer_field(FormField("start-year--0", "Start date year", "text", True, []), ctx())
    assert r.kind == "human" and "start" in r.reason.lower()


def test_education_block_is_not_a_contradiction():
    c = ctx()
    fields = [FormField("school--0", "School", "combobox", True, []), FormField("degree--0", "Degree", "combobox", True, []),
              FormField("end-month--0", "End date month", "combobox", True, []), FormField("end-year--0", "End date year", "text", True, [])]
    assert check_contradictions([answer_field(f, c) for f in fields], c) == []


def test_combobox_option_similarity():
    from hunt.apply.browser import _similarity
    assert _similarity("University of Wisconsin–Madison", "University of Wisconsin - Madison") >= 0.9
    assert _similarity("Master's", "Master's Degree") >= 0.6
    assert _similarity("University of Wisconsin–Madison", "University of Wisconsin - Milwaukee") < 0.9
    assert _similarity("Data Science", "Political Science") < 0.6


def test_address_line2_city_and_lever_markers():
    assert a("Address Line 2", "text", [], required=False).kind == "skip"
    assert a("City", "text", []).value == "Madison"
    assert a("Location (City)", "combobox", []).value == "Madison, WI"
    r = a("Are you legally authorized to work in the country where this position is located?", "radio", ["Yes", "No"])
    assert r.value == "Yes"


def test_sponsorship_now_or_this_internship_is_your_decision():
    assert a("Do you now require sponsorship for employment visa status to work legally in the United States?").kind == "human"
    assert a("Would you need Cyvl to sponsor a visa for this internship?").kind == "human"
    assert a("Will you in the future require sponsorship for employment visa status?").value == "Yes"
    assert a("Will you now or in the future require sponsorship for employment visa status?").value == "Yes"


def test_legal_name_and_discipline_fallback():
    assert a("First and Last Legal Name", "text", []).value == "Viet Anh Nguyen"
    r = answer_field(FormField("discipline--0", "Discipline", "combobox", True, []), ctx())
    assert r.value == "Data Science" and r.fallbacks == ["Computer Science", "Other"]


def test_lawful_authorization_phrasing():
    assert a("Do you have lawful authorization to work in the U.S.?").value == "Yes"


def test_ashby_education_history_comes_from_profile():
    import json
    c = ctx(education={"current_start_date": "2026-09-02"})
    a = answer_field(FormField("_systemfield_education_history", "Education History", "ashby_education", True), c)
    assert a.kind == "fixed" and a.rule == "education_history"
    v = json.loads(a.value)
    assert v["school"] == BASE_PROFILE["education"]["current_school"]
    assert v["degree"] == "Master of Science" and v["major"] == "Data Science"
    assert v["start"] == [9, 2026] and v["end"] == [12, 2027] and v["current"] is True


def test_still_student_and_legal_first_last_name():
    c = ctx()
    assert answer_field(FormField("s", "Still Student?", "checkbox", False), c).value in ("Yes", "checked")
    assert answer_field(FormField("n", "Legal First and Last Name", "text", True), c).value == "Viet Anh Nguyen"


def test_graduation_term_maps_to_season_options():
    c = ctx()
    helion = FormField("g1", "What is your expected graduation date? (MM/YYYY)", "radio", True,
                       options=["Spring/Summer 2027", "Fall/Winter 2027", "Spring/Summer 2028"])
    assert answer_field(helion, c).value == "Fall/Winter 2027"
    grow = FormField("g2", "When is your expected graduation date?", "radio", True,
                     options=["Winter 2027", "Spring 2028", "Winter 2028", "I have already graduated"])
    assert answer_field(grow, c).value == "Winter 2027"
    months = FormField("g3", "Expected graduation", "select", True, options=["May 2027", "December 2027", "May 2028"])
    assert answer_field(months, c).value == "December 2027"


def _eeo_ctx():
    c = ctx(eeo="answer")
    c.profile["eeo"].update(gender="Male", hispanic_latino="No", race_ethnicity="Asian", veteran_status="No", disability_status="No")
    return c


def test_self_identification_uses_your_answers_without_guessing():
    c = _eeo_ctx()
    gender = lambda opts: answer_field(FormField("g", "Gender", "radio", True, options=opts), c).value  # noqa: E731
    assert gender(["Male", "Female", "Decline to self-identify"]) == "Male"
    assert gender(["Woman", "Man", "Non-binary", "Prefer not to say"]) == "Man"
    assert gender(["Female", "Male (he/him)", "Prefer not to say"]) == "Male (he/him)"
    race = lambda opts: answer_field(FormField("r", "Race", "radio", True, options=opts), c)  # noqa: E731
    us = ["Hispanic or Latino", "White (Not Hispanic or Latino)", "Asian (Not Hispanic or Latino)", "Decline to self-identify"]
    assert race(us).value == "Asian (Not Hispanic or Latino)"
    uk = ["White (English, German or any other White background)", "Mixed or Multiple ethnic groups (White and Asian, ...)",
          "Asian (Indian, Pakistani, Vietnamese, Korean, Chinese, or any other Asian background)", "Prefer not to say"]
    assert race(uk).value.startswith("Asian (Indian")
    granular = race(["East Asian", "South Asian", "Southeast Asian", "White", "Prefer not to say"])
    assert granular.value != "East Asian" and granular.kind in ("human", "sensitive")  # never guesses a sub-group
    hisp = answer_field(FormField("h", "Are you Hispanic/Latino?", "radio", True,
                                  options=["Hispanic or Latino", "Not Hispanic or Latino", "Decline"]), c)
    assert hisp.value == "Not Hispanic or Latino"
    vet = answer_field(FormField("v", "Veteran Status", "radio", True,
                                 options=["I am a protected veteran", "I am not a protected veteran", "I decline to self-identify"]), c)
    assert vet.value == "I am not a protected veteran"  # 'No', and never the decline option
    gecko = answer_field(FormField("v2", "Veteran Status", "radio", False, options=[
        "I identify as one or more of the classifications of protected veteran listed above",
        "I am not a protected veteran", "I decline to self-identify for protected veteran status"]), c)
    assert gecko.value == "I am not a protected veteran"
    dis = answer_field(FormField("d", "Disability Status", "radio", True, options=[
        "Yes, I have a disability (or previously had a disability)",
        "No, I do not have a disability and have not had one in the past", "I do not want to answer"]), c)
    assert dis.value.startswith("No, I do not have a disability")
    c.profile["eeo"]["disability_status"] = None
    assert answer_field(FormField("d", "Disability Status", "radio", True, options=[
        "Yes, I have a disability", "No, I do not have a disability", "I do not want to answer"]), c).value == "I do not want to answer"


def test_field_of_study_falls_back_to_computer_science():
    c = ctx()
    major = lambda opts: answer_field(FormField("m", "Field of study", "select", True, options=opts), c).value  # noqa: E731
    assert major(["Business", "Computer Science", "Data Science"]) == "Data Science"
    assert major(["Business", "Computer Science", "Mathematics"]) == "Computer Science"
    gh = answer_field(FormField("discipline--0", "Discipline", "select", True, options=["Business", "Computer Science", "Other"]), c)
    assert gh.value == "Computer Science"


def test_long_notice_degree_status_and_completion_term():
    """Acadian-style questions: a long privacy notice that mentions an email address,
    'academic status' as sentences, and 'anticipate completing' with season options."""
    c = ctx()
    c.library = {"privacy_consent": SimpleNamespace(approved=True)}
    notice = ("We collect information such as your contact details and work history to process your application. "
              "Personal data is handled under the Data Protection Act; contact us by emailing recruiting@example.com. "
              "You may have rights to access, update, or request deletion of your personal information. " * 2)
    r = a(notice, options=["Acknowledge/Confirm"], c=c)
    assert (r.value, r.rule) == ("Acknowledge/Confirm", "privacy_consent")
    status = ["I am currently enrolled in a PhD program", "I am currently enrolled or recently graduated from a Master's program",
              "I am currently enrolled or recently graduated from an Undergraduate program", "I am a current full-time employee"]
    assert a("Please select the option that best describes your current academic status:", options=status).value == status[1]
    terms = ["I have already completed my degree", "Winter 2026", "Spring/Summer 2026", "Winter 2027", "Spring/Summer 2027", "2029 and beyond"]
    assert a("When do you anticipate completing your current degree program?", options=terms).value == "Winter 2027"
    assert map_to_option("Yes", FormField("f", "Consent", "select", True, ["I do not consent", "I consent"])) == "I consent"


def test_saved_answers_ranges_alternatives_and_contact_guard():
    from types import SimpleNamespace as NS
    c = ctx()
    c.user_answers = [NS(key="gpa", label="GPA", patterns=[r"what is your gpa"], answer="3.85"),
                      NS(key="office", label="Office", patterns=[r"which (us )?hub"], answer="I am open to working in any office | Either"),
                      NS(key="langs", label="Langs", patterns=[r"programming languages"], answer="Python | Java | Rust"),
                      NS(key="texts", label="Mobile Number", patterns=[], answer="Yes")]
    assert a("What is your GPA?", options=["3.5 - 3.74", "3.75 - 4", "4+"], c=c).value == "3.75 - 4"
    assert a("What is your GPA?", options=["3.71 - 3.8", "3.81 - 3.9", "3.91 - 4.0"], c=c).value == "3.81 - 3.9"
    assert a("From which US hub do you prefer to work?", options=["San Francisco", "New York", "Either"], c=c).value == "Either"
    assert a("Which programming languages do you know?", "multi_select", ["Java", "C++", "Python"], c=c).value == ["Python", "Java"]
    assert a("Mobile Number", options=["Yes - I consent to texts", "No - I do not consent"], c=c).value == "Yes - I consent to texts"
    assert a("Mobile Number", "text", [], c=c).value != "Yes"   # a phone box never gets "Yes"


def test_workday_tencent_wordings():
    c = ctx(eeo="answer")
    c.profile["eeo"]["gender"] = "Male"
    assert a("Region", "wd_dropdown", [], c=c).value == "Wisconsin"            # Workday's address "Region" = state
    assert a("If you were referred by a Campus Ambassador, please enter the referral code:", "textarea", [], required=False).kind == "skip"
    assert a("Have you been previously employed with Tencent or any subsidiaries of Tencent?").value == "No"
    assert a("Are you subject to a non-competition or other agreement that would preclude you from working here?",
             c=ctx(attestations={"subject_to_noncompete": False})).value == "No"
    g = a("Please select gender.", options=["Male", "Female", "I do not wish to answer."], c=c)
    assert g.value == "Male"
    assert a("Sexual orientation", options=["Straight", "Gay"], c=c).rule != "eeo_gender"
