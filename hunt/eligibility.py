"""CPT/OPT work-authorization eligibility classifier.

Classifies a posting against the applicant's confirmed authorization (F-1 student,
authorized via CPT/OPT, will need employer sponsorship in the future). Uses the
exact posting language; every decision carries the sentence that triggered it.

Distinctions maintained (see master prompt section 4):
  cpt_opt_accepted          employer explicitly welcomes CPT/OPT / F-1 / offers sponsorship
  authorization_generic     "must be authorized to work in the US" (CPT/OPT satisfies this)
  no_sponsorship_current    "authorized to work without sponsorship" (no mention of future)
  no_future_sponsorship     employer states it does not sponsor visas / H-1B (policy statement)
  excludes_future_sponsorship  applicants needing sponsorship now or in future are excluded
  citizenship_required / permanent_residency_required / clearance_required /
  us_person_export / excludes_f1
  not_stated                posting says nothing about authorization
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

US = r"\b(?:us|usa|united states|american)\b"
SPONSOR = r"(?:(?:visa|employer|employment|immigration|work|h-?1-?b)\s+)*sponsor(?:ship|ed|ing)?"
FUTURE = r"(?:now or in the future|currently or in the future|current or future|present or future|now or future|at any (?:point|time)|in the future|future)"
F1 = r"\b(?:cpt|opt(?![- ]?(?:in|out)\b)|stem opt|f-?1|j-?1|student visas?|international students?|curricular practical training|optional practical training)\b"
NEG = r"(?:not|no|never|n't)"


@dataclass
class Rule:
    category: str
    verdict: str  # ineligible / review / eligible
    pattern: re.Pattern
    description: str


def _r(p: str) -> re.Pattern:
    return re.compile(p, re.I)


RULES: list[Rule] = [
    # --- explicit disqualifiers -------------------------------------------------
    Rule("citizenship_required", "ineligible",
         _r(rf"(?:must|required to|need to|should|will need to)\s+(?:be|hold|have|possess)\s+(?:an?\s+)?(?:active\s+)?{US}\s+citizen(?:ship)?"),
         "Requires U.S. citizenship"),
    Rule("citizenship_required", "ineligible",
         _r(rf"{US}\s+citizenship\s+(?:is\s+)?(?:required|mandatory|a (?:requirement|must))|requires?\s+{US}\s+citizenship|"
            rf"(?:only|exclusively)\s+(?:open\s+to\s+)?{US}\s+citizens|{US}\s+citizens\s+only|open\s+(?:only\s+)?to\s+{US}\s+citizens"),
         "Requires U.S. citizenship"),
    Rule("permanent_residency_required", "ineligible",
         _r(rf"(?:must|required to|need to)\s+be\s+(?:an?\s+)?{US}\s+(?:citizen|national)s?\s+(?:or|/)\s+(?:a\s+)?(?:lawful\s+)?permanent\s+resident|"
            rf"{US}\s+citizens?\s+(?:or|and|/)\s+(?:lawful\s+)?permanent\s+residents?\s+(?:only|are\s+eligible)|"
            rf"(?:green\s+card\s+holders?|permanent\s+residents?)\s+only|"
            rf"(?:must|required to)\s+(?:be|have)\s+(?:a\s+)?(?:green\s+card|permanent\s+resident)"),
         "Requires U.S. citizenship or permanent residency"),
    Rule("clearance_required", "ineligible",
         _r(r"(?:active|current|existing|interim)\s+(?:(?:dod|government|federal|security|secret|top\s+secret|ts/sci|ts)\s+)+clearance|"
            r"(?:ability|able|eligible|eligibility|must\s+be\s+able)\s+to\s+(?:obtain|get|acquire|receive)\s+(?:and\s+maintain\s+)?(?:an?\s+)?(?:active\s+)?(?:(?:u\.?s\.?|dod|government|federal|security|secret|top\s+secret|ts/sci)\s+)*(?:security\s+)?clearance|"
            r"(?:security|secret|ts/sci)\s+clearance\s+(?:is\s+)?(?:required|needed|mandatory)"),
         "Requires a security clearance (limited to U.S. citizens)"),
    Rule("us_person_export", "ineligible",
         _r(rf"(?:must|required to)\s+(?:be|qualify as)\s+(?:an?\s+)?{US}\s+person|"
            rf"(?:itar|export\s+control\w*)[^.]{{0,120}}(?:must|required|only)[^.]{{0,40}}{US}\s+persons?|"
            rf"{US}\s+persons?\s+(?:only|as\s+defined\s+(?:by|under)\s+(?:itar|22\s*c\.?f\.?r))"),
         "Restricted to U.S. persons under export-control rules"),
    Rule("excludes_f1", "ineligible",
         _r(rf"(?:not|unable to|cannot|can't|won't|will not|do not|does not)\s+(?:accept|consider|support|hire|allow)[^.]{{0,60}}{F1}|"
            rf"{F1}[^.]{{0,50}}(?:(?:are|is)\s+not\s+(?:eligible|accepted|considered|supported)|ineligible|not\s+be\s+considered)|"
            rf"not\s+(?:open|available)\s+to[^.]{{0,40}}{F1}|"
            rf"not\s+eligible\s+for\s+[^.]{{0,20}}{F1}"),
         "Explicitly excludes F-1 / CPT / OPT students"),
    Rule("excludes_future_sponsorship", "ineligible",
         _r(rf"(?:must|should|will)\s+not\s+(?:now\s+or\s+in\s+the\s+future\s+)?(?:require|need)\s+[^.]{{0,40}}{SPONSOR}|"
            rf"without\s+(?:the\s+need\s+for\s+|requiring\s+|needing\s+)?(?:any\s+)?{FUTURE}\s+[^.]{{0,20}}{SPONSOR}|"
            rf"(?:require|need)s?\s+[^.]{{0,30}}{SPONSOR}[^.]{{0,40}}{FUTURE}[^.]{{0,60}}(?:not\s+be\s+(?:considered|eligible)|ineligible|cannot\s+be\s+considered)|"
            rf"(?:candidates|applicants|individuals)\s+(?:who|that)\s+(?:will\s+)?(?:now\s+or\s+in\s+the\s+future\s+)?(?:require|need)[^.]{{0,40}}{SPONSOR}[^.]{{0,60}}(?:not|ineligible)|"
            rf"(?:not|no|unable to|cannot)\s+(?:be\s+)?(?:able\s+to\s+)?(?:consider|accept)\s+(?:candidates|applicants|individuals)[^.]{{0,60}}{SPONSOR}"),
         "Excludes applicants who will need sponsorship now or in the future"),

    # --- ambiguous / policy statements -----------------------------------------
    Rule("no_sponsorship_current", "review",
         _r(rf"(?:authorized|eligible|authorization|legally able)\s+to\s+work\s+(?:in\s+the\s+{US}\s+)?[^.]{{0,60}}without\s+(?:the\s+need\s+for\s+|requiring\s+|needing\s+)?(?:employer\s+|visa\s+|company\s+)?{SPONSOR}"),
         "Requires authorization to work without employer sponsorship (CPT/OPT is not employer sponsorship, but intent is unclear)"),
    Rule("no_future_sponsorship", "review",
         _r(rf"(?:do|does|will|are|is|can)\s*(?:not|n't)\s+(?:be\s+able\s+to\s+)?(?:offer|provide|sponsor|support)[^.]{{0,50}}(?:visa|h-?1-?b|{SPONSOR}|immigration)|"
            rf"(?:unable|not\s+able)\s+to\s+(?:offer|provide|sponsor|support)[^.]{{0,50}}(?:visa|h-?1-?b|{SPONSOR}|immigration)|"
            rf"no\s+(?:visa\s+|immigration\s+)?{SPONSOR}\s+(?:is\s+|will\s+be\s+)?(?:available|offered|provided)|"
            rf"{SPONSOR}\s+(?:is\s+|will\s+)?not\s+(?:be\s+)?(?:available|offered|provided|possible)|"
            rf"not\s+eligible\s+for\s+(?:visa\s+|immigration\s+)?{SPONSOR}"),
         "Employer states it does not offer visa / H-1B sponsorship"),

    # --- positive signals -------------------------------------------------------
    Rule("cpt_opt_accepted", "eligible",
         _r(rf"{F1}[^.]{{0,60}}(?:welcome|eligible|accepted|encouraged|considered|supported|are\s+able\s+to\s+apply|may\s+apply|can\s+apply)|"
            rf"(?:welcome|accept|consider|support|open\s+to|encourage)[^.]{{0,40}}{F1}|"
            rf"(?:will|do|does|can|are\s+able\s+to)\s+(?:offer|provide|sponsor)\s+(?:visa|h-?1-?b|immigration|{SPONSOR})|"
            rf"(?:visa\s+|h-?1-?b\s+)?{SPONSOR}\s+(?:is\s+)?(?:available|offered|provided)(?!\s+for\s+this)"),
         "Accepts CPT/OPT or offers sponsorship"),
    Rule("authorization_generic", "eligible",
         _r(rf"(?:must\s+be|be)\s+(?:legally\s+)?(?:authorized|eligible)\s+to\s+work\s+in\s+the\s+{US}|work\s+authorization\s+(?:in\s+the\s+{US}\s+)?(?:is\s+)?required"),
         "Requires U.S. work authorization (CPT/OPT satisfies this)"),
]

# Phrases that negate a citizenship / clearance match in the same sentence.
NEGATION = re.compile(rf"\b(?:does\s+not|do\s+not|is\s+not|not)\s+(?:require|required)|not\s+required|without\s+regard\s+to|regardless\s+of", re.I)
EEO_CONTEXT = re.compile(r"equal\s+(?:employment\s+)?opportunity|without\s+regard|regardless\s+of|discriminat|protected\s+(?:veteran|status)", re.I)

FEED_LABELS = {
    "U.S. Citizenship is Required": ("citizenship_required", "ineligible", "Feed label: U.S. citizenship is required"),
    "Does Not Offer Sponsorship": ("no_future_sponsorship", "review", "Feed label: does not offer sponsorship"),
    "Offers Sponsorship": ("cpt_opt_accepted", "eligible", "Feed label: offers sponsorship"),
}

SEVERITY = {"ineligible": 3, "review": 2, "eligible": 1}


@dataclass
class EligibilityResult:
    verdict: str
    category: str
    reasons: list[dict] = field(default_factory=list)
    snippets: list[str] = field(default_factory=list)


ABBREV = [(re.compile(r"\bU\.\s?S\.\s?A\.?", re.I), "USA"), (re.compile(r"\bU\.\s?S\.", re.I), "US"),
          (re.compile(r"\be\.g\.", re.I), "eg"), (re.compile(r"\bi\.e\.", re.I), "ie"),
          (re.compile(r"\b(Inc|Corp|Co|Ltd|No|St|Dr|Mr|Ms|Jr|Sr|vs)\.", re.I), r"\1")]


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text)
    for rx, rep in ABBREV:
        text = rx.sub(rep, text)
    return [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\s+-\s+|•", text) if s.strip()]


def classify(text: str, title: str = "", feed_sponsorship: str | None = None,
             policy: dict | None = None, profile_auth: dict | None = None) -> EligibilityResult:
    policy = policy or {}
    auth = profile_auth or {"requires_sponsorship_now_or_future": True, "us_citizen": False,
                            "permanent_resident": False, "security_clearance": False}
    hits: list[tuple[Rule, str]] = []
    for sent in _sentences(f"{title}. {text or ''}"):
        if len(sent) > 1200:
            sent = sent[:1200]
        for rule in RULES:
            m = rule.pattern.search(sent)
            if not m:
                continue
            if rule.category in ("citizenship_required", "permanent_residency_required", "clearance_required") and NEGATION.search(sent):
                continue
            if rule.category in ("citizenship_required", "permanent_residency_required") and EEO_CONTEXT.search(sent):
                continue
            if rule.category in ("citizenship_required", "permanent_residency_required") and re.search(F1, sent, re.I):
                # e.g. "U.S. citizens, permanent residents, or F-1 students on CPT/OPT"
                continue
            hits.append((rule, sent))

    reasons = [{"category": r.category, "verdict": r.verdict, "rule": r.description, "quote": s} for r, s in hits]
    if feed_sponsorship in FEED_LABELS:
        cat, verdict, desc = FEED_LABELS[feed_sponsorship]
        reasons.append({"category": cat, "verdict": verdict, "rule": desc, "quote": f"sponsorship: {feed_sponsorship}"})

    cats = {r["category"] for r in reasons}

    # Applicant-specific adjustments: if the applicant were a citizen etc. these
    # would not disqualify. Kept explicit so the logic follows the profile.
    disq = []
    if "citizenship_required" in cats and not auth.get("us_citizen"):
        disq.append("citizenship_required")
    if "permanent_residency_required" in cats and not (auth.get("us_citizen") or auth.get("permanent_resident")):
        disq.append("permanent_residency_required")
    if "clearance_required" in cats and not auth.get("security_clearance"):
        disq.append("clearance_required")
    if "us_person_export" in cats and not (auth.get("us_citizen") or auth.get("permanent_resident")):
        disq.append("us_person_export")
    if "excludes_f1" in cats:
        disq.append("excludes_f1")
    if "excludes_future_sponsorship" in cats and auth.get("requires_sponsorship_now_or_future"):
        disq.append("excludes_future_sponsorship")

    snippets = list(dict.fromkeys(r["quote"] for r in reasons))[:6]
    positive = "cpt_opt_accepted" in cats

    if disq:
        if disq == ["excludes_future_sponsorship"] and positive:
            return EligibilityResult("review", "conflicting_statements", reasons, snippets)
        return EligibilityResult("ineligible", disq[0], reasons, snippets)
    if "no_sponsorship_current" in cats:
        verdict = "eligible" if positive else policy.get("no_sponsorship_current_only", "review")
        return EligibilityResult(verdict, "no_sponsorship_current", reasons, snippets)
    if "no_future_sponsorship" in cats:
        verdict = "eligible" if positive else policy.get("no_visa_sponsorship_statement", "review")
        return EligibilityResult(verdict, "no_future_sponsorship", reasons, snippets)
    if positive:
        return EligibilityResult("eligible", "cpt_opt_accepted", reasons, snippets)
    if "authorization_generic" in cats:
        return EligibilityResult("eligible", "authorization_generic", reasons, snippets)
    return EligibilityResult(policy.get("unstated", "eligible"), "not_stated", reasons, snippets)
