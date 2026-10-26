"""Screening-question answer engine.

Each form field is matched to a library rule. Rules produce one of:
  fixed       - a factual answer drawn from the verified applicant profile
  contextual  - text generated from the job + resume (fact-guarded)
  sensitive   - EEO / demographic; handled per the profile's EEO policy
  human       - legal, ambiguous, or unverifiable; requires the applicant
Unknown questions are always `human`. Nothing is guessed."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt.models import ScreeningAnswer


@dataclass
class FormField:
    name: str
    label: str
    type: str = "text"  # text / textarea / select / multi_select / radio / checkbox / file / date / combobox
    required: bool = False
    options: list[str] = field(default_factory=list)
    option_values: list[str] = field(default_factory=list)
    description: str = ""
    current: str = ""  # value already present on the page (autofill / account profile)
    entry: str = ""  # Workday repeatable entry the field belongs to: "work:2" / "edu:1"


@dataclass
class PlannedAnswer:
    name: str
    label: str
    type: str
    required: bool
    value: str | list[str] | None
    kind: str  # fixed / contextual / sensitive / file / human / skip
    rule: str | None = None
    reason: str | None = None
    options: list[str] = field(default_factory=list)
    option_values: list[str] = field(default_factory=list)
    fallbacks: list[str] = field(default_factory=list)  # truthful alternatives if the exact option is absent

    def to_dict(self) -> dict:
        return asdict(self)


def norm(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").replace("*", " ")).strip().lower()
    return s.rstrip(" ?:")


@dataclass
class Context:
    profile: dict
    master: dict
    job: object
    company: str
    settings: dict
    applicant_skills: set[str]
    contextual: Callable[[str, int], str | None] | None = None  # (question, max_words) -> text
    library: dict[str, ScreeningAnswer] = field(default_factory=dict)
    user_answers: list[ScreeningAnswer] = field(default_factory=list)
    test_mode: bool = False  # mock-ATS fixtures only: skips the onboarding confirmation gate


def _p(ctx: Context, path: str):
    cur = ctx.profile
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _yn(v) -> str | None:
    if v is True:
        return "Yes"
    if v is False:
        return "No"
    return None


def _fmt_date(d: str | None, f: FormField) -> str | None:
    if not d:
        return None
    try:
        dt = date.fromisoformat(str(d))
    except ValueError:
        return str(d)
    if f.type == "date":
        return dt.isoformat()
    return dt.strftime("%m/%d/%Y")


# --- rule table ------------------------------------------------------------------
# (key, label, regex on normalized question, kind, resolver, needs_wa_confirm, sensitive)
Resolver = Callable[[Context, FormField], "str | list[str] | None"]


def _city_state(ctx, f):
    c, s = _p(ctx, "contact.city"), _p(ctx, "contact.state")
    return f"{c}, {s}" if c and s else None


_SEASON_MONTH = {"spring": 5, "summer": 8, "fall": 12, "autumn": 12, "winter": 12}
_MONTH_NUM = {m.lower(): i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                                    "September", "October", "November", "December"], start=1)}


def _grad_window_yes_no(ctx, f) -> str | None:
    """'Will you graduate between May 2027 and June 2028?' -> Yes / No from the profile."""
    grad = str(_p(ctx, "education.expected_graduation_date") or "")
    if len(grad) < 7:
        return None
    gy, gm = int(grad[:4]), int(grad[5:7])
    pts = []
    for m in re.finditer(r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
                         r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|spring|summer|fall|autumn|winter)\.?\s*(?:of\s*)?(20\d\d)\b",
                         f.label, re.I):
        word, year = m.group(1).lower(), int(m.group(2))
        month = _SEASON_MONTH.get(word) or _MONTH_NUM.get(word) or next(
            (v for k, v in _MONTH_NUM.items() if k.startswith(word[:3])), None)
        if month:
            pts.append((year, month))
    if len(pts) < 2:
        return None
    lo, hi = min(pts), max(pts)
    return "Yes" if lo <= (gy, gm) <= hi else "No"


def _grad_option(ctx, f) -> str:
    """The listed option for the graduation term: the exact month first, then the
    season label schools use for it (Dec 2027 -> 'Fall/Winter 2027' or 'Winter 2027')."""
    g = str(_p(ctx, "education.expected_graduation_date") or "")
    if len(g) < 7:
        return _p(ctx, "education.expected_graduation")
    y, m = int(g[:4]), int(g[5:7])
    month = list(_MONTH_NUM)[m - 1].capitalize()
    seasons = {12: ["Fall/Winter", "Winter", "Fall"], 11: ["Fall/Winter", "Fall"], 10: ["Fall/Winter", "Fall"],
               9: ["Fall/Winter", "Fall"], 8: ["Spring/Summer", "Summer"], 7: ["Spring/Summer", "Summer"],
               6: ["Spring/Summer", "Summer"], 5: ["Spring/Summer", "Spring"], 4: ["Spring/Summer", "Spring"],
               3: ["Spring"], 2: ["Winter"], 1: ["Winter"]}[m]
    for cand in [f"{month} {y}", f"{month[:3]} {y}", f"{m:02d}/{y}", f"{m}/{y}"] + [f"{s} {y}" for s in seasons]:
        for o in f.options:
            if norm(o) == norm(cand):
                return o
    return f"{month} {y}"


US_STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
             "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
             "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
             "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
             "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
             "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
             "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
             "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
             "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"}


def _state(ctx, f):
    """Dropdowns list full state names ('Wisconsin'); a text box takes what the profile says."""
    v = str(_p(ctx, "contact.state") or "").strip()
    if not v:
        return None
    full = US_STATES.get(v.upper(), v)
    if f.type in ("wd_dropdown", "select", "combobox", "radio") or f.options:
        return (map_to_option(full, f) or map_to_option(v, f)) if f.options else full
    return v


def _grad(ctx, f):
    if f.type == "wd_date":
        g = str(_p(ctx, "education.expected_graduation_date") or "")
        return f"{g[5:7]}/{g[:4]}" if len(g) >= 7 else None
    if f.options and all(re.match(r"^(yes|no)\b", o.strip(), re.I) for o in f.options if o.strip()):
        return _grad_window_yes_no(ctx, f)
    if not f.options and re.match(r"^(will|are|do|is)\b", f.label.strip(), re.I):
        return _grad_window_yes_no(ctx, f)
    if f.options:
        return _grad_option(ctx, f)
    if re.search(r"\byear\b", f.label, re.I):
        return "2027"
    if f.type == "date":
        return str(_p(ctx, "education.expected_graduation_date"))
    if re.search(r"mm/yyyy|month", f.label, re.I):
        return "12/2027"
    return _p(ctx, "education.expected_graduation")


def _enrolled(ctx, f):
    lab = f.label.lower()
    if re.search(r"undergrad|bachelor|ph\.?d|doctoral", lab):
        return "No"  # currently enrolled in a master's program
    return "Yes"


def _gpa(ctx, f):
    lab = f.label.lower()
    if "undergrad" in lab or "bachelor" in lab:
        return _p(ctx, "education.undergrad_gpa")
    return _p(ctx, "education.current_gpa")


def _prev_employed(ctx, f):
    orgs = " ".join(e["org"].lower() for e in ctx.master.get("experience", []))
    from hunt.discovery.normalize import normalize_company
    cn = normalize_company(ctx.company)
    return "Yes" if cn and cn in orgs else "No"


def _languages(ctx, f):
    for g in ctx.master.get("skills", []):
        if g["category"].lower().startswith("language"):
            return ", ".join(g["items"])
    return None


def _visa_status(ctx, f):
    if f.options:
        return "F-1"
    return "F-1 student visa; authorized to work through CPT/OPT"


def _location_pref(ctx, f):
    prefs = [c.split(",")[0].lower() for c in ctx.settings.get("preferred_cities", [])]
    hits = [o for o in f.options if any(p in o.lower() for p in prefs)]
    if hits:
        return hits if f.type == "multi_select" else hits[0]
    return None


def _fields_of_study(ctx, f):
    """Data Science (the MS); if the form doesn't list it, Computer Science (the BS)."""
    if f.type == "multi_select":
        hits = [o for o in f.options if re.search(r"computer science|data science", o, re.I)]
        return hits or None
    for rx in (r"\bdata science\b", r"\bcomputer science\b"):
        hits = [o for o in f.options if re.search(rx, o, re.I)]
        if hits:
            return hits[0]
    return "Data Science" if not f.options else None


def _experience_with(ctx, f):
    from hunt.taxonomy import canonicalize, extract_skills
    if re.search(r"\b(years?|how many|how long|level)\b", f.label, re.I):
        return None  # quantities of experience are not verifiable from the resume
    if f.options and not all(o.strip().lower().startswith(("yes", "no")) for o in f.options[:2]):
        return None
    m = re.search(r"(?:experience|proficien\w*|familiar\w*|comfortable)\s+(?:with|in|using)\s+(.+)", f.label, re.I)
    if not m:
        return None
    skills = extract_skills(m.group(1))
    if not skills:
        c = canonicalize(m.group(1).strip(" ?."))
        skills = {c: 1} if c else {}
    if not skills:
        return None
    return "Yes" if all(s in ctx.applicant_skills for s in skills) else "No"


def _how_heard(ctx, f):
    if not f.options:
        return _p(ctx, "preferences.how_did_you_hear")
    # you chose: the company's own careers site wherever it is listed, else LinkedIn
    order = [r"careers? (site|page)", r"company (website|careers?)", r"website", r"linkedin", r"online", r"internet", r"job board", r"other"]
    for pat in order:
        hits = [o for o in f.options if re.search(pat, o, re.I)]
        if hits:
            return hits[0]
    return None


_GENDER_WORDS = {"male": {"male", "man"}, "female": {"female", "woman"}}


def _sensitive_option(key: str, own: str, f: FormField) -> str | None:
    """Your own self-identification mapped to the form's option, or None when the
    form's choices don't match it unambiguously (never a guess at a sub-group)."""
    if not f.options:
        return own
    v = norm(own)
    for o in f.options:
        if norm(o) == v:
            return o
    if key == "eeo_gender" and v in _GENDER_WORDS:
        want, other = _GENDER_WORDS[v], set().union(*_GENDER_WORDS.values()) - _GENDER_WORDS[v]
        hits = [o for o in f.options if (t := set(re.findall(r"[a-z]+", o.lower()))) & want and not t & other]
        return hits[0] if len(hits) == 1 else None
    if v in ("yes", "no"):  # 'I don't wish to answer' must not count as 'No'
        real = [o for o in f.options if not _DECLINE_RX.search(o)]
        return map_to_option(own, FormField(f.name, f.label, f.type, f.required, options=real))
    hits = [o for o in f.options if re.search(rf"\b{re.escape(v)}\b", norm(o))]
    if len(hits) > 1:  # e.g. 'Asian (...)' and 'Mixed (... White and Asian ...)'
        hits = [o for o in hits if norm(o).startswith(v)]
    return hits[0] if len(hits) == 1 else None


_DECLINE_RX = re.compile(r"decline|don.?t wish|do not wish|prefer not|not wish to|choose not|not to (?:answer|disclose|say)|"
                         r"i don.?t want|do not want to answer", re.I)


def _decline_option(f: FormField) -> str | None:
    for o in f.options:
        if _DECLINE_RX.search(o):
            return o
    return None


RULES: list[dict] = [
    # identity / contact
    dict(key="first_name", label="First name", rx=r"^(legal )?first name|^given name|^first$", kind="fixed", res=lambda c, f: _p(c, "identity.first_name")),
    dict(key="last_name", label="Last name", rx=r"^(legal )?last name|surname|family name|^last$", kind="fixed", res=lambda c, f: _p(c, "identity.last_name")),
    # "I have a preferred name" checkbox: the preferred name is the legal first name, so no
    dict(key="preferred_name", label="Preferred name", rx=r"preferred (first )?name|nickname", kind="fixed",
         res=lambda c, f: "No" if f.type == "checkbox" else _p(c, "identity.preferred_name")),
    dict(key="full_name", label="Full name", rx=r"^(full |legal |your )?name$|^full legal name|^(legal )?(first and last|first & last) (legal )?name$|^(full )?legal name$", kind="fixed",
         res=lambda c, f: f'{_p(c, "identity.first_name")} {_p(c, "identity.last_name")}'),
    dict(key="email", label="Email", rx=r"e-?mail", kind="fixed", res=lambda c, f: _p(c, "contact.email")),
    dict(key="phone_device_type", label="Phone device type", rx=r"phone device type|^device type$|phone type", kind="fixed",
         res=lambda c, f: "Mobile"),
    dict(key="country_phone_code", label="Country phone code", rx=r"country phone code|phone (country )?code|country code", kind="fixed",
         res=lambda c, f: "United States"),
    dict(key="phone_extension", label="Phone extension", rx=r"\bext(ension)?\b", kind="skip", res=None),  # never the phone number
    dict(key="phone", label="Phone", rx=r"\b(phone|mobile|cell)\b", kind="fixed", res=lambda c, f: _p(c, "contact.phone")),
    dict(key="linkedin", label="LinkedIn URL", rx=r"linkedin", kind="fixed", res=lambda c, f: _p(c, "contact.linkedin_url")),
    dict(key="github", label="GitHub URL", rx=r"github", kind="fixed", res=lambda c, f: _p(c, "contact.github_url")),
    dict(key="portfolio", label="Website / portfolio", rx=r"portfolio|personal (web)?site|^website|other website", kind="fixed", res=lambda c, f: _p(c, "contact.portfolio_url")),
    dict(key="current_location", label="Current location", rx=r"current (city|location)|where are you (currently )?(located|based)|^location( \(city.*\))?$|city,? state", kind="fixed", res=_city_state),
    dict(key="address_line2", label="Address line 2 (apartment / suite)", rx=r"address line 2|address 2\b|apartment|\bsuite\b|\bapt\b", kind="skip", res=None),
    dict(key="city", label="City", rx=r"^(current )?city( of residence)?$|^town/city$", kind="fixed", res=lambda c, f: _p(c, "contact.city")),
    dict(key="address", label="Street address", rx=r"street address|address line|^address$|mailing address", kind="fixed", res=lambda c, f: _p(c, "contact.address_line1")),
    dict(key="postal_code", label="ZIP / postal code", rx=r"zip|postal code", kind="fixed", res=lambda c, f: _p(c, "contact.postal_code")),
    dict(key="state", label="State", rx=r"^state( of residence)?$|^state/province|^(state ?/ ?)?region$|^state or region", kind="fixed", res=lambda c, f: _state(c, f)),
    dict(key="country", label="Country", rx=r"^country( of residence)?$", kind="fixed", res=lambda c, f: _p(c, "contact.country")),
    # work authorization (legal) - require profile confirmation
    dict(key="authorized_without_sponsorship", label="Authorized to work WITHOUT sponsorship (ambiguous for CPT/OPT)",
         rx=r"(authori[sz]ed|eligible|able) to work.*without.*sponsor|without (the need for )?(visa )?sponsorship.*(authori[sz]ed|eligible)", kind="human",
         res=lambda c, f: None, reason="Compound legal question: CPT/OPT authorizes work now, but you will need sponsorship later. Answer once and save it."),
    dict(key="currently_require_sponsorship", label="Currently require sponsorship (now only)",
         rx=r"((currently|right now|at this time|\bnow\b) (require|need)|(require|need)[^?]{0,40}\b(now|currently)\b)(?!.*future).*sponsor(?!.*future)|"
            r"sponsor[^?]*\b(for|during) (this|the) (internship|role|position|program)\b(?!.*future)", kind="human", res=lambda c, f: None,
         reason="Asks only about current sponsorship; CPT/OPT is not employer sponsorship. Decide how you want to answer."),
    dict(key="require_sponsorship", label="Will you require sponsorship now or in the future?",
         rx=r"(require|need|requir).*(sponsor|visa)|sponsor(ship)? .*(require|need)|h-?1-?b", kind="fixed",
         res=lambda c, f: _yn(_p(c, "work_authorization.requires_sponsorship_now_or_future")), wa=True),
    dict(key="visa_status", label="Current visa / employment eligibility status",
         rx=r"(visa|immigration|citizenship|employment eligibility|work authori[sz]ation) status|type of (visa|work authorization)|employment eligibility", kind="fixed",
         res=_visa_status, wa=True),
    dict(key="authorized_to_work", label="Are you authorized to work in the US?",
         rx=r"(legally )?(authori[sz]ed|eligible|permitted) to work|work authori[sz]ation|right to work|legally (able|allowed) to work|lawful(ly)? (authori[sz]ation|authori[sz]ed) to work|authori[sz]ation to work in", kind="fixed",
         res=lambda c, f: _yn(_p(c, "work_authorization.authorized_to_work_us")), wa=True),
    dict(key="cpt", label="Are you eligible for CPT?", rx=r"\bcpt\b|curricular practical", kind="fixed",
         res=lambda c, f: _yn(_p(c, "work_authorization.cpt_eligible")), wa=True),
    dict(key="opt", label="Will you use / are you eligible for OPT?", rx=r"\bopt\b|optional practical", kind="fixed",
         res=lambda c, f: _yn(_p(c, "work_authorization.will_use_opt")), wa=True),
    dict(key="us_citizen", label="Are you a U.S. citizen?", rx=r"(are you )?(a )?(u\.?s\.?|united states) citizen", kind="fixed",
         res=lambda c, f: _yn(_p(c, "work_authorization.us_citizen")), wa=True),
    dict(key="permanent_resident", label="Are you a permanent resident?", rx=r"permanent resident|green card", kind="fixed",
         res=lambda c, f: _yn(_p(c, "work_authorization.permanent_resident")), wa=True),
    dict(key="clearance_obtain", label="Able to obtain a security clearance?", rx=r"(able|eligible|willing) to (obtain|get).*clearance", kind="human",
         res=lambda c, f: None, reason="Clearance eligibility is a legal determination."),
    dict(key="clearance", label="Do you hold a security clearance?", rx=r"clearance", kind="fixed",
         res=lambda c, f: _yn(_p(c, "work_authorization.security_clearance"))),
    dict(key="export_control", label="Export control / U.S. person", rx=r"\bu\.?s\.? person\b|export control|\bitar\b|\bear\b controlled", kind="human",
         res=lambda c, f: None, reason="Export-control status is a legal declaration."),
    # education
    dict(key="gpa", label="GPA", rx=r"\bgpa\b|grade point", kind="fixed", res=_gpa),
    dict(key="graduation", label="Expected graduation", rx=r"(?<!under)(?<!post)graduat(ion|e)\b(?!\s+(program|student|school|degree|studies|level|coursework))|when (do|will) you (\w+ ){0,2}(graduat|complet|finish)\w*|completion date|(anticipated|expected) completion", kind="fixed", res=_grad),
    dict(key="degree_pursuing", label="Degree currently pursuing", rx=r"degree.*(pursu|current|seeking|working toward)|(pursu|current).*degree|level of (study|education)|highest (level of )?education|degree type|^degree$|academic (status|standing)", kind="fixed",
         res=lambda c, f: "Master's" if f.options else _p(c, "education.current_degree")),
    dict(key="school", label="School / university", rx=r"^(school|university|college|institution)( name)?$|(what|which) (school|university|college)|current (school|university)", kind="fixed",
         res=lambda c, f: _p(c, "education.current_school")),
    dict(key="major", label="Major / field of study", rx=r"^major|field of study|area of study|discipline|fields? .*study|concentration|^program of study", kind="fixed", res=_fields_of_study),
    dict(key="enrolled", label="Currently enrolled / returning to school", rx=r"(currently )?enrolled|returning to (school|university)|return to school|student status|^(are you )?(still|currently) (a )?student\b", kind="fixed",
         res=lambda c, f: _enrolled(c, f)),
    # availability
    dict(key="start_date", label="Earliest start date", rx=r"start date|when (can|could|would) you start|available to start|earliest (start|availability|date)|availability date", kind="fixed",
         res=lambda c, f: _fmt_date(_p(c, "availability.earliest_start_date"), f)),
    dict(key="end_date", label="Latest end date", rx=r"end date|available until|last day", kind="fixed",
         res=lambda c, f: _fmt_date(_p(c, "availability.latest_end_date"), f)),
    dict(key="summer_availability", label="Available for Summer 2027 internship", rx=r"available.*(summer|internship|full[- ]time).*(2027|weeks|duration)|(summer 2027|10-12 weeks|12 weeks).*available", kind="fixed",
         res=lambda c, f: "Yes" if _p(c, "availability.internship_term") == "Summer 2027" else None),
    dict(key="relocate", label="Willing to relocate?", rx=r"relocat", kind="fixed", res=lambda c, f: _yn(_p(c, "availability.willing_to_relocate"))),
    dict(key="location_preference", label="Office location preference", rx=r"location preference|preferred (office|location)|which (office|location)|office location", kind="fixed", res=_location_pref),
    dict(key="in_person", label="Able to work on-site / hybrid", rx=r"(able|willing) to (work|commute).*(on-?site|in[- ]person|office|hybrid)|commut", kind="fixed",
         res=lambda c, f: _yn(_p(c, "availability.willing_to_relocate"))),
    # attestations
    dict(key="over_18", label="At least 18 years old?", rx=r"18 years|at least 18|over 18|over the age|legal age", kind="fixed", res=lambda c, f: _yn(_p(c, "attestations.is_over_18"))),
    dict(key="previously_employed", label="Previously employed by this company?", rx=r"(previously|ever|formerly|currently|have you) (been )?(previously )?(employed|worked) (by|for|at|with)|former employee|current or former", kind="fixed", res=_prev_employed),
    dict(key="employee_id", label="Employee ID (if applicable)", rx=r"^employee (id|number)", kind="skip", res=None),
    dict(key="form_language", label="Language (of the form)", rx=r"^(preferred )?language$", kind="fixed", res=lambda c, f: "English"),
    dict(key="referral_code", label="Referral code", rx=r"referral code|referr\w* .*(code|name of|employee id)", kind="skip", res=None),  # never "No" in a code box
    dict(key="referral", label="Referred by an employee?", rx=r"referr(al|ed)|employee refer", kind="fixed", res=lambda c, f: "No"),
    dict(key="relatives", label="Relatives at the company?", rx=r"\brelatives?\b.*(work|employ|compan)|family members?.*(work|employ|compan)|related to (anyone|someone|an employee|a current)", kind="fixed", res=lambda c, f: _yn(_p(c, "attestations.has_relatives_at_employer"))),
    dict(key="noncompete", label="Subject to a non-compete?", rx=r"non-?compet|restrictive covenant|non-?solicit", kind="fixed", res=lambda c, f: _yn(_p(c, "attestations.subject_to_noncompete"))),
    dict(key="today_date", label="Today's date (self-identification forms)", rx=r"^date$|today'?s date|signature date|date signed", kind="fixed",
         res=lambda c, f: date.today().strftime("%m/%d/%Y") if f.type != "date" else date.today().isoformat()),
    dict(key="how_heard", label="How did you hear about us?", rx=r"how did you (first )?(hear|find|learn|connect)|where did you (hear|find|see)|^source$|how .* about (this|the) (job|role|position|opportunity)|what led you to apply", kind="fixed",
         res=_how_heard),
    dict(key="certify_accurate", label="Certify application information is accurate", rx=r"\bi (hereby )?certify|certify that|\battest\b|true and (complete|accurate)|accurate and complete|\bi acknowledge|acknowledge that", kind="fixed",
         res=lambda c, f: "Yes", approve_required=True),
    dict(key="privacy_consent", label="Consent to privacy policy / data processing", rx=r"privacy (policy|notice|statement)|data (processing|protection)|\bconsent to\b|\bgdpr\b|\bi agree\b|terms (of (use|service)|and conditions)", kind="fixed",
         res=lambda c, f: "Yes", approve_required=True),
    # declarations we never make on our own
    dict(key="salary_expectation", label="Salary / pay expectations", rx=r"salary|compensation (expectation|requirement)|desired (pay|rate|compensation)|expected (pay|salary|hourly)|pay expectation", kind="human",
         res=lambda c, f: None, reason="Pay expectation is a new declaration; save a standard answer to reuse it."),
    dict(key="outstanding_offers", label="Outstanding offers / deadlines", rx=r"outstanding offer|competing offer|offer deadline|deadlines?", kind="human",
         res=lambda c, f: None, reason="Depends on your current offers."),
    dict(key="criminal", label="Criminal history", rx=r"convicted|criminal|felony|misdemeanor", kind="human", res=lambda c, f: None, reason="Sensitive legal declaration.", sensitive=True),
    dict(key="years_experience", label="Years of experience", rx=r"years of (experience|professional)|how many years|how long have you", kind="human",
         res=lambda c, f: None, reason="Years of experience is not stated on the resume."),
    # EEO / demographics
    dict(key="eeo_gender", label="Gender", rx=r"^(please )?((select|indicate|choose) )?(your )?(gender|sex)\b(?!.*(orientation|transgender))|gender identity", kind="sensitive", res=lambda c, f: _p(c, "eeo.gender"), sensitive=True),
    dict(key="eeo_race", label="Race / ethnicity", rx=r"\brace\b|ethnicity", kind="sensitive", res=lambda c, f: _p(c, "eeo.race_ethnicity"), sensitive=True),
    dict(key="eeo_hispanic", label="Hispanic / Latino", rx=r"hispanic|latin[oax]", kind="sensitive", res=lambda c, f: _p(c, "eeo.hispanic_latino"), sensitive=True),
    dict(key="eeo_veteran", label="Veteran status", rx=r"veteran", kind="sensitive", res=lambda c, f: _p(c, "eeo.veteran_status"), sensitive=True),
    dict(key="eeo_disability", label="Disability status", rx=r"disabilit", kind="sensitive", res=lambda c, f: _p(c, "eeo.disability_status"), sensitive=True),
    dict(key="eeo_other", label="Sexual orientation / transgender / pronouns", rx=r"sexual orientation|transgender|lgbt|pronoun", kind="sensitive", res=lambda c, f: None, sensitive=True),
    # skills
    dict(key="programming_languages", label="Programming languages you know", rx=r"programming languages|languages (do you|are you|you).*(know|proficien|comfortable)|coding languages", kind="fixed", res=_languages),
    dict(key="experience_with", label="Experience with <technology>? (yes/no)", rx=r"(experience|proficien\w*|familiar\w*|comfortable) (with|in|using) ", kind="fixed", res=_experience_with),
    # contextual (generated)
    dict(key="why_interested", label="Why are you interested? (generated per job)", rx=r"why (are you|do you|would you)|what (interests|excites|draws) you|interest(ed)? in (this|the|our)|why .*\b(company|role|position|team|us)\b|motivat", kind="contextual", res=None),
    dict(key="tell_us", label="Describe a project / experience (generated per job)", rx=r"tell us about|describe (a|an|your)|share (a|an) (example|project)|walk us through|what (project|experience)", kind="contextual", res=None),
    dict(key="additional_info", label="Additional information (optional)", rx=r"additional information|anything else|other information|comments", kind="skip", res=None),
]

WA_KEYS = {r["key"] for r in RULES if r.get("wa")}


def _compiled_rules():
    return [(r, re.compile(r["rx"], re.I)) for r in RULES]


_RULES_C = _compiled_rules()


def match_rule(label: str) -> dict | None:
    q = norm(label)
    if len(q) > 250:  # a notice to acknowledge (it may mention an email address or a phone number)
        for r, rx in _RULES_C:
            if r["key"] in ("privacy_consent", "certify_accurate") and rx.search(q):
                return r
    for r, rx in _RULES_C:
        if rx.search(q):
            return r
    return None


def map_to_option(value: str, f: FormField) -> str | None:
    if not f.options:
        return value
    v = norm(value)
    opts = [(o, norm(o)) for o in f.options]
    for o, no in opts:
        if no == v:
            return o
    if re.fullmatch(r"\d+(\.\d+)?", v):  # a number into ranges: GPA 3.85 -> "3.81 - 3.9" / "3.75 - 4"
        for o, no in opts:
            m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)", no)
            if m and float(m.group(1)) <= float(v) <= float(m.group(2)):
                return o
    if v in ("yes", "no"):
        hits = [o for o, no in opts if re.match(rf"^{v}\b", no)]
        if len(hits) == 1:
            return hits[0]
        if v == "no":
            hits = [o for o, no in opts if re.match(r"^(no|i do not|i don.?t|i will not|i am not|not)\b", no)]
        else:
            hits = [o for o, no in opts if re.match(r"^(yes|i do|i will|i am|i have|(i )?(acknowledge|confirm|agree|accept|consent|understand))", no)
                    and not re.search(r"\bnot\b|n['’]t\b|\bdecline", no)]
        return hits[0] if len(hits) == 1 else None
    if v.startswith("f-1") or v == "f-1":
        hits = [o for o, no in opts if re.search(r"\bf-?1\b|student visa|cpt|opt", no)]
        return hits[0] if len(hits) == 1 else (hits[0] if hits else None)
    contains = [o for o, no in opts if v in no or (len(no) > 3 and no in v)]
    if len(contains) == 1:
        return contains[0]
    vt = set(re.findall(r"[a-z0-9']+", v))
    best, best_s = None, 0.0
    for o, no in opts:
        ot = set(re.findall(r"[a-z0-9']+", no))
        if not ot:
            continue
        s = len(vt & ot) / len(vt | ot)
        if s > best_s:
            best, best_s = o, s
    return best if best_s >= 0.5 else None


def load_library(session: Session) -> tuple[dict[str, ScreeningAnswer], list[ScreeningAnswer]]:
    rows = session.scalars(select(ScreeningAnswer)).all()
    lib = {r.key: r for r in rows}
    user = [r for r in rows if r.source == "user" and r.approved]
    return lib, user


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
EDU_FIELD = re.compile(r"^(school|degree|discipline|start-month|start-year|end-month|end-year)--(\d+)$")


def _education_block_answer(f: FormField, ctx: Context) -> dict | None:
    m = EDU_FIELD.match(f.name or "")
    if not m:
        return None
    part, idx = m.group(1), int(m.group(2))
    if idx > 0:  # only the first entry (current degree) is filled
        return {"value": None, "kind": "skip", "rule": "education_block", "reason": "Additional education entry left blank"}
    edu = (ctx.profile.get("education") or {})
    grad = str(edu.get("expected_graduation_date") or "")
    if part == "school":
        raw = edu.get("current_school")
    elif part == "degree":
        raw = "Master's"
    elif part == "discipline":
        raw = edu.get("current_major") or "Data Science"
    elif part in ("end-month", "end-year") and len(grad) >= 7:
        year, month = int(grad[:4]), int(grad[5:7])
        if part == "end-year":
            raw = str(year)
        else:
            raw = None
            for cand in (MONTHS[month - 1], MONTHS[month - 1][:3], str(month), f"{month:02d}"):
                if not f.options or map_to_option(cand, f):
                    raw = map_to_option(cand, f) if f.options else (MONTHS[month - 1] if f.type in ("combobox", "select") else str(month))
                    break
    elif part in ("start-month", "start-year") and len(str(edu.get("current_start_date") or "")) >= 7:
        sd = str(edu.get("current_start_date"))
        year, month = int(sd[:4]), int(sd[5:7])
        if part == "start-year":
            raw = str(year)
        else:
            raw = None
            for cand in (MONTHS[month - 1], MONTHS[month - 1][:3], str(month), f"{month:02d}"):
                if not f.options or map_to_option(cand, f):
                    raw = map_to_option(cand, f) if f.options else (MONTHS[month - 1] if f.type in ("combobox", "select") else str(month))
                    break
    else:  # start date of the MS program is not recorded on the resume
        if not f.required:
            return {"value": None, "kind": "skip", "rule": "education_block", "reason": "Program start date not on resume"}
        return {"value": None, "kind": "human", "rule": "education_block",
                "reason": "Add your MS start month (Profile → Onboarding: 'MS program start date')"}
    if not raw:
        return {"value": None, "kind": "human" if f.required else "skip", "rule": "education_block",
                "reason": "Could not map education value to the form's options"}
    value = map_to_option(str(raw), f) if f.options else raw
    if value is None and part == "discipline":  # Data Science not listed: Computer Science (the BS)
        value = map_to_option("Computer Science", f)
    if value is None:
        return {"value": None, "kind": "human" if f.required else "skip", "rule": "education_block",
                "reason": f"'{raw}' not among options {f.options[:6]}"}
    return {"value": value, "kind": "fixed", "rule": "education_block"}


def _ashby_education_answer(ctx: Context) -> dict:
    """One entry for the current degree, from the profile (same facts as the resume)."""
    edu = ctx.profile.get("education") or {}
    school = edu.get("current_school")
    if not school:
        return {"value": None, "kind": "human", "rule": "education_history", "reason": "Profile is missing: current school"}
    def ym(d):
        d = str(d or "")
        return [int(d[5:7]), int(d[:4])] if re.match(r"^\d{4}-\d{2}", d) else None
    degree = re.sub(r"\s+in\s+.*$", "", str(edu.get("current_degree") or "")) or None
    value = {"school": school, "degree": degree, "major": edu.get("current_major"),
             "start": ym(edu.get("current_start_date")), "end": ym(edu.get("expected_graduation_date")), "current": True}
    return {"value": json.dumps(value, ensure_ascii=False), "kind": "fixed", "rule": "education_history"}


_MON3 = {m[:3].lower(): i for i, m in enumerate(MONTHS, start=1)}


def _month_years(s: str) -> list[tuple[int | None, int]]:
    """'Jan 2026 – May 2026' -> [(1, 2026), (5, 2026)]; 'Expected Dec 2027' -> [(12, 2027)]."""
    return [(_MON3.get((m.group(1) or "").lower()), int(m.group(2)))
            for m in re.finditer(r"(?:\b([A-Za-z]{3})[a-z]*\.?\s+)?(\d{4})", s or "")]


def _plain(text: str) -> str:
    return re.sub(r"\*\*|__", "", text or "").strip()


DEGREE_ALTS = {"masters": ["Master of Science", "Master's Degree", "Masters", "Master of Science (MS)", "MS", "Master's"],
               "bachelors": ["Bachelor of Science", "Bachelor's Degree", "Bachelors", "Bachelor of Science (BS)", "BS", "Bachelor's"]}


def _entry_answer(f: FormField, ctx: Context) -> dict:
    """A field inside a Workday repeatable entry, answered from the same entry of your
    master resume (Work Experience n = experience n, Education n = education n)."""
    kind, _, idx = f.entry.partition(":")
    items = (ctx.master or {}).get("experience" if kind == "work" else "education") or []
    i = int(idx) - 1 if idx.isdigit() else -1
    if not 0 <= i < len(items):
        return {"value": None, "kind": "skip", "rule": "entry_extra", "reason": "Entry is not on your resume"}
    e, lab = items[i], norm(f.label)

    def ans(value, fallbacks=None) -> dict:
        if value in (None, ""):
            return {"value": None, "kind": "human" if f.required else "skip", "rule": f"{kind}_entry",
                    "reason": "Not on your resume"}
        return {"value": value, "kind": "fixed", "rule": f"{kind}_entry", "fallbacks": fallbacks or []}

    def date_value(t) -> str | None:
        if not t:
            return None
        return f"{t[0]:02d}/{t[1]}" if t[0] else str(t[1])

    if kind == "work":
        dates = _month_years(e.get("dates") or "")
        current = bool(re.search(r"present|current", e.get("dates") or "", re.I))
        if f.type == "checkbox" or re.search(r"currently work|i work here|current (job|position|role)", lab):
            return ans("Yes" if current else "No")
        if re.search(r"description|responsibilit|summary|duties|achievement", lab):
            return ans("\n".join("• " + _plain(b["text"] if isinstance(b, dict) else b) for b in e.get("bullets") or []))
        if re.search(r"job title|position|^title|^role$", lab):
            return ans(e.get("title"))
        if re.search(r"company|employer|organi[sz]ation", lab):
            return ans(e.get("org"))
        if re.search(r"location|city", lab):
            return ans(e.get("location"))
        if re.search(r"^from|start", lab):
            return ans(date_value(dates[0] if dates else None))
        if re.search(r"^to\b|^end|end date", lab):
            return ans(None if current else date_value(dates[1] if len(dates) > 1 else None))
    else:
        level = e.get("level") or ""
        edu = ctx.profile.get("education") or {}
        if re.search(r"school|university|college|institution", lab):
            return ans(e.get("school"), [e.get("school", "").replace("–", "-")])
        if re.search(r"degree", lab):
            alts = DEGREE_ALTS.get(level, [])
            return ans(alts[0] if alts and f.type != "text" else e.get("degree"), alts[1:])
        if re.search(r"field of study|major|discipline|area of study", lab):
            return ans(e.get("field"), ["Computer Science"] if e.get("field") == "Data Science" else [])
        if re.search(r"gpa|overall result|grade", lab):
            return ans(e.get("gpa"))
        ends = _month_years(e.get("dates") or "")
        if re.search(r"^from|start|first year", lab):
            start = str(edu.get("current_start_date") if level == "masters" else
                        edu.get("undergrad_start_date") if level == "bachelors" else "") or ""
            return ans(f"{start[5:7]}/{start[:4]}" if re.match(r"^\d{4}-\d{2}", start) else None)
        if re.search(r"^to\b|^end|last year|graduat|expected", lab):
            return ans(date_value(ends[-1] if ends else None))
    return ans(None)


def answer_field(f: FormField, ctx: Context) -> PlannedAnswer:
    base = dict(name=f.name, label=f.label, type=f.type, required=f.required, options=f.options, option_values=f.option_values)
    if f.type == "file":
        lab = norm(f.label + " " + f.name)
        if "cover" in lab:
            return PlannedAnswer(**base, value="cover_letter", kind="file", rule="cover_letter")
        if "resume" in lab or "cv" in lab.split() or lab.endswith("cv"):
            return PlannedAnswer(**base, value="resume", kind="file", rule="resume")
        if f.required:
            return PlannedAnswer(**base, value=None, kind="human", reason="Unknown required file upload")
        return PlannedAnswer(**base, value=None, kind="skip", reason="Optional upload")

    if f.type == "ashby_education":
        return PlannedAnswer(**base, **_ashby_education_answer(ctx))

    if f.entry:  # Workday "Work Experience 2" / "Education 1": from that resume entry, never general rules
        return PlannedAnswer(**base, **_entry_answer(f, ctx))

    # Greenhouse education block (school--0, degree--0, start-month--0, end-year--0 ...):
    # its "End date" is the degree's graduation date, not internship availability. These
    # come from the verified resume and take precedence over generic saved answers.
    edu = _education_block_answer(f, ctx)
    if edu is not None:
        if edu.get("rule") == "education_block" and (f.name or "").startswith("discipline--") and edu.get("kind") == "fixed":
            edu["fallbacks"] = ["Computer Science", "Other"]
        return PlannedAnswer(**base, **edu)

    # user-saved answers for this exact question (or their patterns) take precedence
    q = norm(f.label)
    for ua in ctx.user_answers:
        pats = ua.patterns or []
        if norm(ua.label) == q or any(re.search(p, q, re.I) for p in pats):
            if not f.options and norm(ua.answer or "") in ("yes", "no") and re.search(r"phone|mobile|e-?mail|\bname\b|address", q):
                continue  # never type "Yes" into a contact box that shares a consent question's label
            if "|" in (ua.answer or "") and f.options:
                alts = [x.strip() for x in ua.answer.split("|")]
                if f.type in ("multi_select", "wd_multiselect"):
                    picks = [o for o in (map_to_option(x, f) for x in alts) if o]  # "select all that apply"
                    if picks:
                        return PlannedAnswer(**base, value=list(dict.fromkeys(picks)), kind="fixed", rule=f"user:{ua.key}")
                else:  # one choice: the first alternative this form offers
                    pick = next((o for o in (map_to_option(x, f) for x in alts) if o), None)
                    if pick:
                        return PlannedAnswer(**base, value=pick, kind="fixed", rule=f"user:{ua.key}")
                continue
            val = map_to_option(ua.answer or "", f)
            if val is not None:
                return PlannedAnswer(**base, value=val, kind="fixed", rule=f"user:{ua.key}")

    rule = match_rule(f.label)
    if rule is None and f.options and f.type in ("multi_select", "radio", "select", "wd_dropdown"):
        # a heading like "Please check one of the boxes below" with choices that say what it is
        # ("Yes, I have a disability...", "Asian (United States of America)")
        by_opts = match_rule(" ".join(f.options))
        if by_opts and by_opts.get("kind") == "sensitive":
            rule = by_opts
    if rule is None:
        if not f.required:
            return PlannedAnswer(**base, value=None, kind="skip", reason="Optional question with no saved answer")
        return PlannedAnswer(**base, value=None, kind="human", reason="No verified answer for this question")

    key, kind = rule["key"], rule["kind"]
    lib_row = ctx.library.get(key)

    if kind == "skip":
        return PlannedAnswer(**base, value=None, kind="skip", rule=key)
    if kind == "human":
        return PlannedAnswer(**base, value=None, kind="human", rule=key, reason=rule.get("reason"))
    if rule.get("approve_required") and not (lib_row and lib_row.approved):
        if not f.required and f.type != "checkbox":
            return PlannedAnswer(**base, value=None, kind="skip", rule=key)
        return PlannedAnswer(**base, value=None, kind="human", rule=key,
                             reason="Approve this standard acknowledgement once in the answer library to reuse it")
    if rule.get("wa") and not (_p(ctx, "work_authorization.confirmed") or ctx.test_mode):
        return PlannedAnswer(**base, value=None, kind="human", rule=key,
                             reason="Work-authorization answers must be confirmed in Profile & Onboarding first")

    if kind == "sensitive":
        policy = _p(ctx, "eeo.policy") or "ask"
        own = rule["res"](ctx, f) if rule.get("res") else None
        if policy == "answer" and own:
            mapped = _sensitive_option(key, str(own), f)
            if mapped:
                return PlannedAnswer(**base, value=mapped, kind="sensitive", rule=key)
        if policy == "decline" or (policy == "answer" and not own):
            d = _decline_option(f)
            if d:
                return PlannedAnswer(**base, value=d, kind="sensitive", rule=key, reason="Declined per EEO policy")
            if not f.required:
                return PlannedAnswer(**base, value=None, kind="skip", rule=key)
        if not f.required:
            return PlannedAnswer(**base, value=None, kind="skip", rule=key, reason="Voluntary self-identification left blank")
        return PlannedAnswer(**base, value=None, kind="human", rule=key, reason="Required self-identification question (sensitive)")

    if kind == "contextual":
        if not ctx.settings.get("auto_contextual_answers", True) or ctx.contextual is None:
            if not f.required:
                return PlannedAnswer(**base, value=None, kind="skip", rule=key)
            return PlannedAnswer(**base, value=None, kind="human", rule=key, reason="Open-ended question; automatic answers disabled")
        if f.options:
            return PlannedAnswer(**base, value=None, kind="human", rule=key, reason="Open-ended question with fixed options")
        words = 80 if f.type == "text" else 150
        text = ctx.contextual(f.label, words)
        if not text:
            if not f.required:
                return PlannedAnswer(**base, value=None, kind="skip", rule=key)
            return PlannedAnswer(**base, value=None, kind="human", rule=key, reason="Could not generate a verifiable answer")
        return PlannedAnswer(**base, value=text, kind="contextual", rule=key)

    # fixed
    raw = rule["res"](ctx, f)
    if raw is None or raw == "":
        if not f.required:
            return PlannedAnswer(**base, value=None, kind="skip", rule=key, reason="Profile field not set")
        return PlannedAnswer(**base, value=None, kind="human", rule=key, reason=f"Profile is missing: {rule['label']}")
    if isinstance(raw, list):
        return PlannedAnswer(**base, value=raw, kind="fixed", rule=key)
    if not f.options and f.type in ("wd_dropdown", "wd_multiselect", "combobox"):
        alts = {"how_heard": ["Job Board", "Online Job Board", "Internet", "Company Website", "Website", "Other"],
                "country": ["United States of America", "USA"],
                "country_phone_code": ["United States of America (+1)", "United States (+1)", "+1"],
                "degree_pursuing": ["Master's Degree", "Masters", "Master of Science", "MS"],
                "major": ["Computer Science", "Other"],
                "phone_device_type": ["Mobile Phone", "Cell", "Personal Cell"]}.get(key, [])
        return PlannedAnswer(**base, value=str(raw), kind="fixed", rule=key, fallbacks=alts)
    mapped = map_to_option(str(raw), f)
    if mapped is None:
        return PlannedAnswer(**base, value=None, kind="human", rule=key,
                             reason=f"Answer '{raw}' does not match any option: {f.options[:8]}")
    return PlannedAnswer(**base, value=mapped, kind="fixed", rule=key)


EXPECTED_FACTS = {
    "require_sponsorship": ("work_authorization.requires_sponsorship_now_or_future", True),
    "authorized_to_work": ("work_authorization.authorized_to_work_us", True),
    "us_citizen": ("work_authorization.us_citizen", True),
    "permanent_resident": ("work_authorization.permanent_resident", True),
    "cpt": ("work_authorization.cpt_eligible", True),
    "opt": ("work_authorization.will_use_opt", True),
}


def check_contradictions(answers: list[PlannedAnswer], ctx: Context) -> list[str]:
    """Verify every work-authorization answer against the profile, and that the
    same rule was never answered two different ways in one application."""
    issues: list[str] = []
    seen: dict[str, str] = {}
    for a in answers:
        if a.kind not in ("fixed", "sensitive") or a.value is None or isinstance(a.value, list):
            continue
        if a.rule in EXPECTED_FACTS:
            path, _ = EXPECTED_FACTS[a.rule]
            expected = _yn(_p(ctx, path))
            first = norm(str(a.value)).split(" ")[0].strip(",")
            if expected and first in ("yes", "no") and first != expected.lower():
                issues.append(f"'{a.label}' answered '{a.value}' but profile says {expected}")
        if a.rule and not a.rule.startswith("user:") and a.rule not in ("experience_with", "certify_accurate", "privacy_consent", "education_block"):
            prev = seen.get(a.rule)
            v = norm(str(a.value))
            if prev is not None and prev != v and a.rule not in ("graduation", "start_date"):
                issues.append(f"Inconsistent answers for {a.rule}: '{prev}' vs '{v}'")
            seen[a.rule] = v
    return issues


def seed_library(session: Session, profile: dict) -> None:
    """Mirror the rule table into the DB so the dashboard can show and approve it."""
    existing = {r.key: r for r in session.scalars(select(ScreeningAnswer)).all()}
    wa_ok = bool((profile.get("work_authorization") or {}).get("confirmed"))
    dummy_ctx = Context(profile=profile, master={"experience": [], "skills": []}, job=None, company="",
                        settings={}, applicant_skills=set())
    for r in RULES:
        preview = None
        if r["kind"] == "fixed" and r.get("res") and r["key"] not in ("experience_with", "location_preference", "previously_employed"):
            try:
                v = r["res"](dummy_ctx, FormField(name=r["key"], label=r["label"]))
                preview = ", ".join(v) if isinstance(v, list) else (str(v) if v is not None else None)
            except Exception:
                preview = None
        approved = (wa_ok if r.get("wa") else not r.get("approve_required")) if r["kind"] in ("fixed", "sensitive") else r["kind"] == "contextual"
        row = existing.get(r["key"])
        if row is None:
            session.add(ScreeningAnswer(key=r["key"], label=r["label"], patterns=[r["rx"]], answer=preview, kind=r["kind"],
                                        sensitive=bool(r.get("sensitive")), approved=approved, source="profile" if r["kind"] == "fixed" else "seed"))
        else:
            row.label, row.patterns, row.kind, row.sensitive = r["label"], [r["rx"]], r["kind"], bool(r.get("sensitive"))
            row.answer = preview if row.source in ("profile", "seed") else row.answer
            if r.get("wa"):
                row.approved = wa_ok
    session.flush()
