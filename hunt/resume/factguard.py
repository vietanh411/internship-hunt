"""Factual-consistency guard for generated text.

A reworded bullet may change phrasing and emphasis, but it may not introduce:
  - a number that is not in the original bullet,
  - a skill / tool that is not in the original bullet or that entry's tech list,
  - a leadership or ownership claim absent from the original,
  - an unknown proper noun (employer, product, certification ...),
  - first-person voice, or substantially more length.
Free text (cover letters, contextual answers) is checked against the whole
master resume + profile + job description instead of a single bullet."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from hunt.taxonomy import SKILLS, extract_skills

NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
                "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15",
                "twenty": "20", "thirty": "30", "fifty": "50", "hundred": "100", "thousand": "1000",
                "million": "1000000", "dozen": "12", "dozens": "12", "hundreds": "100", "thousands": "1000",
                "millions": "1000000", "double": "2x", "doubled": "2x", "triple": "3x", "tripled": "3x", "half": "50%"}

LEADERSHIP = re.compile(r"\b(led|lead|leading|managed|manage|managing|supervis\w+|mentor\w*|direct(?:ed|ing)|headed|"
                        r"oversaw|oversee\w*|spearhead\w*|owned|chaired|founded|co-founded|launched|pioneered|"
                        r"award\w*|patent\w*|published|certified|certification)\b", re.I)
FIRST_PERSON = re.compile(r"\b(I|me|my|mine|myself|we|our)\b")

COMMON_CAPS = set("""A An The And Or For With By To Of In On At From Into Across Through Using Via Built Designed Developed
Delivered Created Automated Improved Reduced Increased Supported Enabled Collected Produced Tracked Centralized Cut Uncovered
Analyzed Processed Engineered Implemented Optimized Streamlined Synthesized Identified Applied Leveraged Conducted Performed
Prepared Cleaned Transformed Deployed Containerized Modeled Evaluated Visualized Researched Investigated Integrated
Architected Wrote Maintained Partnered Collaborated Presented Documented Ran Running Scraped Indexed Served Exposed
Data Science Machine Learning AI Agents Research API APIs REST ETL SQL NLP EDA DNS Python US Internet National""".split())


def _plain(t: str) -> str:
    return t.replace("**", "")


def numbers_in(text: str) -> set[str]:
    t = _plain(text).lower().replace(",", "")
    nums = set()
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(k|m|b|x|%)?(?![a-z])", t):
        nums.add(m.group(1) + (m.group(2) or ""))
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(k|m|b)\b", t):
        nums.add(m.group(1) + m.group(2))
    for w, d in NUMBER_WORDS.items():
        if re.search(rf"\b{w}\b", t):
            nums.add(d)
    return nums


def proper_nouns(text: str) -> set[str]:
    out = set()
    sentences = re.split(r"(?<=[.!?])\s+", _plain(text))
    for s in sentences:
        words = re.findall(r"[A-Za-z][A-Za-z0-9&.+#/-]*", s)
        for i, w in enumerate(words):
            if i == 0:
                continue
            if w[0].isupper() and w.strip(".") not in COMMON_CAPS and not w.isupper() or (w.isupper() and len(w) >= 2 and w not in COMMON_CAPS):
                out.add(w.strip(".,"))
    return out


def _skill_alias_words() -> set[str]:
    words = set()
    for canon in SKILLS:
        for part in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]*", canon):
            words.add(part.lower())
    return words


_ALIAS_WORDS = _skill_alias_words()


@dataclass
class GuardResult:
    ok: bool
    issues: list[str] = field(default_factory=list)


def check_bullet(original: str, rewritten: str, entry_tech: list[str] | None = None,
                 extra_allowed_skills: set[str] | None = None) -> GuardResult:
    issues: list[str] = []
    o, r = _plain(original), _plain(rewritten)
    new_nums = numbers_in(r) - numbers_in(o)
    if new_nums:
        issues.append(f"new numbers: {sorted(new_nums)}")
    allowed = set(extract_skills(o))
    for t in entry_tech or []:
        allowed |= set(extract_skills(t)) | {t}
    allowed |= extra_allowed_skills or set()
    new_skills = set(extract_skills(r)) - allowed
    # soft-skill mentions (communication, collaboration) are rewording, not new facts
    new_skills = {s for s in new_skills if SKILLS.get(s, ("",))[0] not in ("soft",)}
    if new_skills:
        issues.append(f"new skills/tools: {sorted(new_skills)}")
    lead_new = {m.lower() for m in LEADERSHIP.findall(r)} - {m.lower() for m in LEADERSHIP.findall(o)}
    if lead_new:
        issues.append(f"new leadership/ownership claims: {sorted(lead_new)}")
    nouns_new = {n for n in proper_nouns(r) - proper_nouns(o)
                 if n.lower() not in o.lower() and n.lower() not in _ALIAS_WORDS}
    if nouns_new:
        issues.append(f"new proper nouns: {sorted(nouns_new)}")
    if FIRST_PERSON.search(r):
        issues.append("first-person voice")
    if len(r) > max(len(o) * 1.3, len(o) + 45):
        issues.append("too long")
    if len(r) < 25:
        issues.append("too short")
    return GuardResult(not issues, issues)


LEARNING = re.compile(r"\b(learn|learning|grow|growing|develop my|expand my|eager to|excited to (?:build|deepen))\b", re.I)


def check_free_text(text: str, master: dict, profile: dict, job_text: str, company: str,
                    applicant_skills: set[str]) -> GuardResult:
    """For cover letters and contextual answers."""
    issues: list[str] = []
    corpus = _master_corpus(master, profile)
    allowed_nums = numbers_in(corpus) | numbers_in(job_text or "") | {"2026", "2027", "2028"}
    new_nums = numbers_in(text) - allowed_nums
    if new_nums:
        issues.append(f"numbers not in resume/profile/posting: {sorted(new_nums)}")
    for sent in re.split(r"(?<=[.!?])\s+", text):
        missing = {s for s in set(extract_skills(sent)) - applicant_skills if s.lower() not in company.lower()}
        missing = {s for s in missing if SKILLS.get(s, ("",))[0] != "soft"}
        if missing and not LEARNING.search(sent):
            issues.append(f"claims skills not on resume: {sorted(missing)} in: {sent[:120]}")
    known = (corpus + " " + (job_text or "") + " " + company).lower()
    unknown = {n for n in proper_nouns(text) if n.lower() not in known and n.lower() not in _ALIAS_WORDS
               and n not in ("Dear", "Sincerely", "Hiring", "Team", "Manager", "Summer", "Fall", "Spring")}
    if unknown:
        issues.append(f"unverified names: {sorted(unknown)[:8]}")
    lead = {m.lower() for m in LEADERSHIP.findall(text)} - {m.lower() for m in LEADERSHIP.findall(corpus)}
    lead -= {"launched"} if "launched" in (job_text or "").lower() else set()
    if lead:
        issues.append(f"leadership/award claims not on resume: {sorted(lead)}")
    return GuardResult(not issues, issues)


def _master_corpus(master: dict, profile: dict) -> str:
    parts = [master["basics"].get("name", "")]
    for e in master.get("education", []):
        parts += [e.get("school", ""), e.get("degree", ""), e.get("dates", ""), str(e.get("gpa") or ""), e.get("location", "")]
    for section in ("experience", "projects"):
        for e in master.get(section, []):
            parts += [e.get("org", ""), e.get("title", ""), e.get("name", ""), e.get("context", ""), e.get("dates", ""),
                      e.get("location", ""), " ".join(e.get("tech", []))]
            parts += [_plain(b["text"]) for b in e.get("bullets", [])]
    for g in master.get("skills", []):
        parts.append(" ".join(g["items"]))
    edu = profile.get("education") or {}
    parts += [str(v) for v in edu.values() if v]
    parts += profile.get("confirmed_extra_skills") or []
    return "\n".join(p for p in parts if p)
