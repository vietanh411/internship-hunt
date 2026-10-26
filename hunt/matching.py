"""Resume-to-job matching: requirement extraction, evidence ranking, and a 0-100
score with a factual explanation. Weights are configurable (settings_store)."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from hunt.db import utcnow
from hunt.discovery.normalize import hourly_equivalent, metro_of
from hunt.settings_store import DEFAULT_WEIGHTS
from hunt.taxonomy import IMPLIES, canonicalize, extract_skills, skill_kind

# ------------------------------------------------------------------ requirements

REQ_HEAD = re.compile(
    r"^\s*(?:#+\s*)?(?:basic|minimum|required|requirements|qualifications|what you(?:'| a)ll need|what we(?:'re| are) looking for|"
    r"you (?:have|bring|will have)|must[- ]haves?|who you are|about you|skills (?:and|&) experience|your background|"
    r"what you bring|requirements and qualifications|key qualifications)\b.*$", re.I)
PREF_HEAD = re.compile(
    r"^\s*(?:#+\s*)?(?:preferred|nice[- ]to[- ]haves?|bonus|pluses?|desired|additional qualifications|it(?:'s| is| would be) (?:a )?(?:plus|great|nice)|"
    r"extra credit|ideal(?:ly)?|we(?:'d| would) love)\b.*$", re.I)
OTHER_HEAD = re.compile(
    r"^\s*(?:#+\s*)?(?:responsibilities|what you(?:'| wi)ll do|about (?:the|us|our)|benefits|perks|compensation|pay|salary|"
    r"the role|role overview|job description|overview|who we are|why join|equal opportunity|our team|day to day|in this role)\b.*$", re.I)


@dataclass
class Requirements:
    required_lines: list[str] = field(default_factory=list)
    preferred_lines: list[str] = field(default_factory=list)
    required_skills: dict[str, int] = field(default_factory=dict)
    preferred_skills: dict[str, int] = field(default_factory=dict)
    all_skills: dict[str, int] = field(default_factory=dict)
    sectioned: bool = False


def extract_requirements(text: str) -> Requirements:
    req, pref = [], []
    mode = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        short = len(line) < 90
        if short and PREF_HEAD.match(line):
            mode = "pref"
            continue
        if short and REQ_HEAD.match(line):
            mode = "req"
            continue
        if short and OTHER_HEAD.match(line) and not line.startswith("-"):
            mode = None
            continue
        if mode == "req":
            req.append(line.lstrip("-• ").strip())
        elif mode == "pref":
            pref.append(line.lstrip("-• ").strip())
    r = Requirements(required_lines=req[:40], preferred_lines=pref[:30])
    r.sectioned = bool(req or pref)
    r.all_skills = extract_skills(text or "")
    r.required_skills = extract_skills("\n".join(req)) if req else {}
    r.preferred_skills = extract_skills("\n".join(pref)) if pref else {}
    return r


# ------------------------------------------------------------------ applicant evidence

@dataclass
class EvidenceUnit:
    entry_id: str
    entry_label: str
    kind: str  # experience / project
    bullet_id: str | None
    text: str
    skills: set[str]


@dataclass
class Applicant:
    skills: set[str]
    skills_listed: list[str]
    units: list[EvidenceUnit]
    degree_levels: set[str]
    fields: set[str]
    grad_date: datetime | None
    gpa: float | None


def _plain(t: str) -> str:
    return t.replace("**", "")


def build_applicant(master: dict, profile: dict) -> Applicant:
    listed: list[str] = []
    for group in master.get("skills", []):
        listed.extend(group["items"])
    listed.extend(profile.get("confirmed_extra_skills") or [])
    skills: set[str] = set()
    for item in listed:
        c = canonicalize(item)
        if c:
            skills.add(c)
    units: list[EvidenceUnit] = []
    for kind, section in (("experience", "experience"), ("project", "projects")):
        for e in master.get(section, []):
            label = e.get("title", "") + " @ " + e.get("org", "") if kind == "experience" else e.get("name", "")
            entry_skills = {c for c in (canonicalize(t) for t in e.get("tech", [])) if c}
            for b in e.get("bullets", []):
                bs = set(extract_skills(_plain(b["text"]))) | entry_skills
                bs |= {i for s_ in bs for i in IMPLIES.get(s_, [])}
                units.append(EvidenceUnit(e["id"], label, kind, b["id"], _plain(b["text"]), bs))
                skills |= set(extract_skills(_plain(b["text"])))
            skills |= entry_skills
    for s in list(skills):
        skills.update(IMPLIES.get(s, []))
    levels = {e.get("level") for e in master.get("education", []) if e.get("level")}
    fields_ = {(e.get("field") or "").lower() for e in master.get("education", [])}
    grad = None
    gd = (profile.get("education") or {}).get("expected_graduation_date")
    if gd:
        try:
            grad = datetime.fromisoformat(str(gd))
        except ValueError:
            grad = None
    gpa = None
    try:
        gpa = float((profile.get("education") or {}).get("current_gpa") or (profile.get("education") or {}).get("undergrad_gpa"))
    except (TypeError, ValueError):
        pass
    return Applicant(skills, listed, units, levels, fields_, grad, gpa)


# ------------------------------------------------------------------ text similarity

STOP = set("""a an and are as at be by for from has have in into is it its of on or that the this to was were will with you your
we our us they their them can may must should would could also more most other such than then these those through using use used
work working team teams role roles job jobs intern interns internship internships summer experience including include etc
ability able strong skills skill knowledge understanding new well across within help helps support supporting""".split())


def _tokens(text: str) -> list[str]:
    toks = re.findall(r"[a-z][a-z0-9+#./-]{1,}", text.lower())
    out = []
    for t in toks:
        t = t.strip("./-")
        if t in STOP or len(t) < 2:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if len(t) > 5 and t.endswith(suf):
                t = t[: -len(suf)]
                break
        out.append(t)
    return out


def cosine(a: str, b: str) -> float:
    ca, cb = Counter(_tokens(a)), Counter(_tokens(b))
    if not ca or not cb:
        return 0.0
    dot = sum(ca[t] * cb[t] for t in ca.keys() & cb.keys())
    na = math.sqrt(sum(v * v for v in ca.values()))
    nb = math.sqrt(sum(v * v for v in cb.values()))
    return dot / (na * nb)


# ------------------------------------------------------------------ education

PHD_REQ = re.compile(r"\b(?:currently )?(?:pursuing|enrolled in|candidates? (?:in|for))\s+(?:a\s+)?(?:ph\.?d|doctoral|doctorate)\b(?![^.]{0,40}\bor\b)", re.I)
MASTERS = re.compile(r"\b(?:master(?:'?s)?|ms|m\.s\.|graduate (?:students?|degrees?|programs?)|grad students?|advanced degrees?)\b", re.I)
BACHELOR_ONLY = re.compile(r"\b(?:rising (?:junior|senior|sophomore)s?|(?:full-time |current |enrolled )?undergraduate students?(?![^.]{0,80}(?:graduate|master))|undergraduate students? only|currently pursuing (?:a|an) (?:bachelor'?s|undergraduate) degree(?![^.]{0,60}(?:master|graduate)))\b", re.I)
FIELD_RE = re.compile(r"\b(computer science|data science|statistics|mathematics|math|applied math|engineering|information systems|"
                      r"information science|analytics|economics|operations research|physics|quantitative|related (?:technical )?field|stem)\b", re.I)
GRAD_WINDOW = re.compile(
    r"graduat\w*\s+(?:date\s+)?(?:between|from|in|by)?\s*(?:the\s+)?(?:(fall|spring|summer|winter|december|may|june|august|dec|jun|aug)\s+)?(20\d\d)"
    r"(?:\s*(?:-|–|to|and|through)\s*(?:(fall|spring|summer|winter|december|may|june|august|dec|jun|aug)\s+)?(20\d\d))?", re.I)
MONTH = {"fall": 12, "winter": 12, "december": 12, "dec": 12, "spring": 5, "may": 5, "june": 6, "jun": 6,
         "summer": 8, "august": 8, "aug": 8}


UNDERGRAD_TITLE = re.compile(r"\bundergrad(?:uate)?s?\b", re.I)
GRAD_IN_TITLE = re.compile(r"(?<!under)\bgrad(?:uate)?s?\b|\bmaster'?s?\b|\bm\.?s\.?\b|\bmba\b|\bph\.?d\b|\bgraduate\b", re.I)


RELATED_FIELDS = {"computer science", "data science", "statistics", "analytics", "engineering", "math", "mathematics"}


def is_grad_student(app: Applicant) -> bool:
    return bool(app.degree_levels & {"masters", "phd"})


def undergrad_only(title: str, text: str) -> bool:
    """An internship only for undergraduates (matters to Master's/PhD applicants): the title says
    'Undergraduate' without graduate/Master's students, or the description is written
    for undergraduates and never mentions Master's or graduate students."""
    t = re.sub(r"\bundergrad\w*", " ", title or "", flags=re.I)
    if UNDERGRAD_TITLE.search(title or "") and not GRAD_IN_TITLE.search(t):
        return True
    return bool(BACHELOR_ONLY.search(text or "")) and not MASTERS.search(text or "")


def education_fit(text: str, degrees_hint: list[str], app: Applicant, title: str = "") -> tuple[float, list[str], list[str], list[str]]:
    """Returns (score 0..1, strengths, gaps, gate_flags)."""
    strengths, gaps, gates = [], [], []
    score = 1.0
    t = text or ""
    if degrees_hint and set(degrees_hint) == {"PhD"} or PHD_REQ.search(t):
        gates.append("phd_required")
        gaps.append("Posting targets PhD students")
        score = 0.1
    elif is_grad_student(app) and undergrad_only(title, t):
        gates.append("undergrad_only")
        gaps.append("Undergraduate-only internship (you are a graduate student)")
        score = 0.1
    elif is_grad_student(app) and (degrees_hint and "Master's" not in degrees_hint and "Bachelor's" in degrees_hint
                                   or BACHELOR_ONLY.search(t)):
        gaps.append("Posting appears aimed at undergraduates (you are a graduate student)")
        score = 0.6
    elif is_grad_student(app) and (MASTERS.search(t) or "Master's" in (degrees_hint or [])):
        strengths.append("Graduate students are explicitly in scope")
    fields_req = {m.group(1).lower() for m in FIELD_RE.finditer(t)}
    if fields_req:
        ok = {"quantitative", "stem", "related field", "related technical field"} | app.fields
        if app.fields & RELATED_FIELDS:
            ok |= RELATED_FIELDS
        if fields_req & ok:
            strengths.append(f"Degree fields match ({', '.join(sorted(f.title() for f in app.fields if f))})")
        else:
            score *= 0.75
            gaps.append(f"Preferred fields: {', '.join(sorted(fields_req))}")
    m = GRAD_WINDOW.search(t)
    if m and app.grad_date:
        y1 = int(m.group(2))
        mo1 = MONTH.get((m.group(1) or "").lower(), 1)
        y2 = int(m.group(4)) if m.group(4) else None
        mo2 = MONTH.get((m.group(3) or "").lower(), 12)
        start = datetime(y1, mo1, 1)
        end = datetime(y2, mo2, 28) if y2 else datetime(y1, 12, 31)
        if not y2 and not m.group(1):
            start = datetime(y1, 1, 1)
        if start <= app.grad_date <= end:
            strengths.append(f"Graduation (Dec 2027) is inside the posting's window ({m.group(0).strip()})")
        elif y1 >= 2026:
            gaps.append(f"Graduation window '{m.group(0).strip()}' may not include Dec 2027")
            score *= 0.5
            gates.append("graduation_window")
    gm = re.search(r"\b(?:minimum|min\.?|at least|cumulative)\s+(?:a\s+)?(?:gpa\s+(?:of\s+)?)?([23]\.\d{1,2})", t, re.I)
    if gm and app.gpa:
        if app.gpa >= float(gm.group(1)):
            strengths.append(f"GPA {app.gpa} meets the {gm.group(1)} minimum")
        else:
            gaps.append(f"GPA minimum {gm.group(1)}")
            score *= 0.6
    return max(0.0, min(1.0, score)), strengths, gaps, gates


# ------------------------------------------------------------------ main scorer

WELL_KNOWN = {
    "google", "alphabet", "meta", "facebook", "amazon", "apple", "microsoft", "netflix", "nvidia", "tesla", "ibm", "intel",
    "oracle", "salesforce", "adobe", "uber", "lyft", "airbnb", "stripe", "linkedin", "twitter", "x", "snap", "spotify",
    "jpmorgan chase", "jpmorgan", "jp morgan", "goldman sachs", "morgan stanley", "bank of america", "citi", "citigroup",
    "wells fargo", "capital one", "american express", "blackrock", "citadel", "citadel securities", "jane street",
    "two sigma", "de shaw", "d e shaw", "hudson river trading", "jump trading", "optiver", "imc trading", "sig",
    "susquehanna international", "akuna capital", "drw", "virtu", "five rings", "palantir", "databricks", "snowflake",
    "openai", "anthropic", "deloitte", "pwc", "ey", "ernst and young", "kpmg", "accenture", "mckinsey", "bain",
    "boston consulting", "bcg", "booz allen hamilton", "lockheed martin", "boeing", "raytheon", "northrop grumman",
    "general motors", "ford", "walmart", "target", "costco", "home depot", "procter and gamble", "pepsico", "coca cola",
    "johnson and johnson", "pfizer", "merck", "abbott", "unitedhealth", "cvs health", "humana", "state farm", "allstate",
    "progressive", "geico", "visa", "mastercard", "paypal", "intuit", "cisco", "qualcomm", "amd", "texas instruments",
    "dell", "hp", "hewlett packard enterprise", "vmware", "servicenow", "workday", "atlassian", "shopify", "doordash",
    "instacart", "robinhood", "coinbase", "bloomberg", "at and t", "verizon", "t mobile", "comcast", "disney", "epic systems",
    "caterpillar", "john deere", "deere", "3m", "honeywell", "general electric", "ge", "siemens", "exxonmobil", "chevron",
    "american airlines", "southwest airlines", "delta air lines", "united airlines", "toyota", "nike", "starbucks",
    "mcdonald s", "kraft heinz", "mondelez", "boeing", "schwab", "charles schwab", "fidelity", "vanguard",
    "tiaa", "northwestern mutual", "lseg", "london stock exchange", "flex", "ingredion", "american family insurance",
    "exact sciences", "kohl s", "fiserv", "northern trust", "cme", "morningstar", "discover", "discover financial",
    "motorola solutions", "abbvie", "baxter", "walgreens", "mckesson", "cardinal health", "medtronic",
    "nationwide", "liberty mutual", "travelers", "the hartford", "hartford", "usaa", "prudential", "metlife",
    "aflac", "chubb", "aig", "marsh", "aon", "willis towers watson", "gartner", "s and p global", "moody s",
    "nasdaq", "ice", "intercontinental exchange", "ubs", "barclays", "hsbc", "deutsche bank", "bnp paribas",
    "pnc", "us bank", "u s bank", "truist", "fifth third", "huntington", "regions", "keybank", "ally",
    "synchrony", "sofi", "chime", "plaid", "brex", "ramp", "figma", "notion", "datadog", "mongodb", "cloudflare",
    "crowdstrike", "palo alto networks", "okta", "twilio", "zoom", "dropbox", "hubspot", "zillow", "expedia",
    "wayfair", "etsy", "ebay", "pinterest", "reddit", "roblox", "electronic arts", "sony", "samsung", "philips",
    "bosch", "lockheed", "general dynamics", "l3harris", "bae systems", "leidos", "saic", "caci", "booz allen",
    "honda", "nissan", "stellantis", "rivian", "lucid", "southwest", "fedex", "ups", "jb hunt", "union pacific",
    "bnsf", "capgemini", "cognizant", "infosys", "tata consultancy services", "wipro", "hp inc", "micron",
    "broadcom", "nxp", "analog devices", "applied materials", "lam research", "kla", "corning", "dow", "dupont",
    "cargill", "adm", "general mills", "kellanova", "conagra", "tyson", "hormel", "unilever", "nestle",
    "colgate palmolive", "kimberly clark", "estee lauder", "l oreal", "lowe s", "best buy", "kroger",
    "albertsons", "7 eleven", "at t", "charter", "paycom", "devon energy", "oneok", "love s",
    "love s travel stops", "expand energy", "jacobs", "fluor",
}


@dataclass
class MatchResult:
    score: float
    tier: str
    breakdown: dict
    explanation: dict
    priority: float
    gates: list[str]
    lesser_known: bool


def tier_for(score: float) -> str:
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "strong"
    if score >= 55:
        return "moderate"
    return "low"


def location_fit(locations: list[str], remote: str | None, settings: dict) -> tuple[float, str, str | None]:
    best, best_tier, best_metro = 0.0, "non_us", None
    prefs = [c.lower() for c in settings.get("preferred_cities", [])]
    for loc in locations or ["Unknown"]:
        metro, tier = metro_of(loc)
        if metro and metro.lower() not in prefs and tier == "preferred":
            tier = "nearby" if settings.get("include_nearby_metros", True) else "other"
        if tier == "other" and any(p.split(",")[0] in loc.lower() for p in prefs):
            tier = "preferred"
        val = {"preferred": 1.0, "nearby": 0.8 if settings.get("include_nearby_metros", True) else 0.4,
               "remote": 0.8 if settings.get("include_remote_us", True) else 0.0,
               "other": 0.4 if settings.get("include_other_us", True) else 0.0, "non_us": 0.0}[tier]
        if val > best:
            best, best_tier, best_metro = val, tier, metro
    if remote == "remote" and settings.get("include_remote_us", True) and best < 0.8:
        best, best_tier = 0.8, "remote"
    return best, best_tier, best_metro


def score_job(job, master: dict, profile: dict, settings: dict, app: Applicant | None = None,
              company_posting_counts: dict[str, int] | None = None, now: datetime | None = None) -> MatchResult:
    app = app or build_applicant(master, profile)
    weights = {**DEFAULT_WEIGHTS, **(settings.get("scoring_weights") or {})}
    now = now or utcnow()
    text = job.description_text or ""
    title = job.title or ""
    reqs = extract_requirements(text)

    # skills ----------------------------------------------------------------
    def core(d: dict) -> set[str]:
        return {s for s in d if skill_kind(s) != "soft"}

    req = core(reqs.required_skills) or core(reqs.all_skills)
    pref = core(reqs.preferred_skills) - req
    have_req = req & app.skills
    have_pref = pref & app.skills
    if req:
        cov_req = len(have_req) / len(req)
        cov_pref = len(have_pref) / len(pref) if pref else cov_req
        skills_score = 0.75 * cov_req + 0.25 * cov_pref
        # small credit for depth: the most frequently mentioned JD skills
        top = [s for s, _ in sorted(reqs.all_skills.items(), key=lambda kv: -kv[1]) if skill_kind(s) != "soft"][:5]
        if top:
            skills_score = 0.85 * skills_score + 0.15 * (len(set(top) & app.skills) / len(top))
    else:
        skills_score = 0.5 if not text else 0.55
    title_skills = core(extract_skills(title))
    if title_skills and title_skills <= app.skills:
        skills_score = min(1.0, skills_score + 0.05)

    # experience / projects -------------------------------------------------
    jd_skills = core(reqs.all_skills)
    jd_focus = text[:6000] + "\n" + title * 3
    unit_scores = []
    for u in app.units:
        overlap = len(u.skills & jd_skills) / max(3, min(len(jd_skills), 8)) if jd_skills else 0
        sim = cosine(u.text, jd_focus)
        unit_scores.append((min(1.0, overlap) * 0.6 + min(1.0, sim * 2.2) * 0.4, u))
    unit_scores.sort(key=lambda x: -x[0])
    tops = [s for s, _ in unit_scores[:3]] + [0, 0, 0]
    exp_score = 0.5 * tops[0] + 0.3 * tops[1] + 0.2 * tops[2]
    if any(u.kind == "experience" and s >= 0.45 for s, u in unit_scores[:4]):
        exp_score = min(1.0, exp_score + 0.08)
    if re.search(r"\b(data|analy|machine learning|scien)", title, re.I):
        exp_score = min(1.0, exp_score + 0.05)  # prior Data Science Intern title
    exp_score = min(1.0, exp_score * 1.15)

    # education ---------------------------------------------------------------
    edu_score, edu_strengths, edu_gaps, gates = education_fit(text, job.degrees or [], app, title)

    # location ----------------------------------------------------------------
    loc_score, loc_tier, loc_metro = location_fit(job.locations or [], job.remote_type, settings)

    # eligibility & timing ------------------------------------------------------
    elig = {"eligible": 1.0, "review": 0.5, "ineligible": 0.0}.get(job.eligibility, 0.5)
    terms = job.terms or []
    timing_state = (job.feed_flags or {}).get("term_status") or ("confirmed" if "Summer 2027" in terms else "unconfirmed")
    timing = {"confirmed": 1.0, "likely": 0.8, "unconfirmed": 0.5, "other_term": 0.0}.get(timing_state, 0.5)
    if timing_state == "other_term":
        gates.append("not_summer_2027")
    elig_timing = 0.6 * elig + 0.4 * timing

    # compensation --------------------------------------------------------------
    hourly = hourly_equivalent(job.salary_min, job.salary_max, job.salary_period)
    min_rate = (profile.get("preferences") or {}).get("min_hourly_rate") or 20
    if re.search(r"\bunpaid\b", text, re.I) and not hourly:
        comp = 0.0
    elif hourly is None:
        comp = 0.5
    else:
        comp = 1.0 if hourly >= float(min_rate) else 0.4

    comps = {"skills": skills_score, "experience": exp_score, "education": edu_score,
             "location": loc_score, "eligibility_timing": elig_timing, "compensation": comp}
    total_w = sum(weights.values()) or 1
    score = sum(weights[k] * comps[k] for k in comps) / total_w * 100

    if job.eligibility == "ineligible":
        gates.append("ineligible")
        score = min(score, 0.0)
    if loc_tier == "non_us":
        gates.append("non_us_location")

    # priority: score + recency + lesser-known boost + whitelist ---------------
    company_norm = job.company_norm or ""
    big_by_volume = (company_posting_counts or {}).get(company_norm, 0) >= 8
    lesser = not (company_norm in WELL_KNOWN or big_by_volume)
    priority = score
    if job.date_posted:
        age = (now - job.date_posted).days
        priority += 10 if age <= 1 else 6 if age <= 3 else 4 if age <= 7 else 2 if age <= 14 else 0 if age <= 30 else -3
    if lesser:
        priority += settings.get("lesser_known_boost", 0)
    if company_norm in {c.lower() for c in settings.get("whitelist", [])}:
        priority += 10

    # explanation -------------------------------------------------------------
    evidence = []
    for s, u in unit_scores[:4]:
        if s <= 0.05:
            continue
        evidence.append({"entry": u.entry_label, "bullet_id": u.bullet_id, "text": u.text,
                         "skills": sorted(u.skills & jd_skills), "relevance": round(s, 2)})
    strengths = []
    if have_req:
        strengths.append(f"Has {len(have_req)}/{len(req)} required skills: {', '.join(sorted(have_req))}")
    if have_pref:
        strengths.append(f"Has preferred skills: {', '.join(sorted(have_pref))}")
    if evidence:
        strengths.append(f"Most relevant evidence: {evidence[0]['entry']}")
    strengths += edu_strengths
    if loc_tier == "preferred":
        strengths.append(f"Location in a preferred metro ({loc_metro})")
    elif loc_tier in ("nearby", "remote"):
        strengths.append(f"Location: {loc_tier}{f' ({loc_metro})' if loc_metro else ''}")
    gaps = []
    missing_req = sorted(req - app.skills)
    missing_pref = sorted(pref - app.skills)
    if missing_req:
        gaps.append(f"Missing required skills: {', '.join(missing_req)}")
    if missing_pref:
        gaps.append(f"Missing preferred skills: {', '.join(missing_pref)}")
    gaps += edu_gaps
    if timing_state != "confirmed":
        gaps.append({"likely": "Summer 2027 likely but not stated", "unconfirmed": "Internship term not stated",
                     "other_term": "Posting is for a different term"}[timing_state])
    if job.eligibility == "review":
        gaps.append("Work-authorization language needs review")
    if hourly is None:
        gaps.append("Compensation not listed")

    breakdown = {k: {"score": round(v * 100, 1), "weight": weights[k],
                     "points": round(weights[k] * v / total_w * 100, 1)} for k, v in comps.items()}
    explanation = {
        "summary": f"{tier_for(score).title()} match ({score:.0f}/100)",
        "strengths": strengths, "gaps": gaps, "evidence": evidence,
        "required_skills": sorted(req), "preferred_skills": sorted(pref),
        "matched_skills": sorted((req | pref) & app.skills),
        "missing_required": missing_req, "missing_preferred": missing_pref,
        "location_tier": loc_tier, "timing": timing_state, "gates": gates,
        "requirements_sectioned": reqs.sectioned,
        "required_lines": reqs.required_lines[:15], "preferred_lines": reqs.preferred_lines[:10],
    }
    return MatchResult(round(score, 1), tier_for(score), breakdown, explanation, round(priority, 1), gates, lesser)
