"""Job-specific resume tailoring from the verified master resume.

What may change: bullet order within a role, project order/selection, skill
order (and inclusion of user-confirmed extra skills), and bullet wording — each
reworded bullet must pass the fact guard or the original text is kept. Employers,
titles, dates, degrees and GPA are copied verbatim from the master."""
from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field

from hunt.llm import LLM
from hunt.matching import cosine, extract_requirements
from hunt.resume.factguard import check_bullet
from hunt.taxonomy import IMPLIES, canonicalize, extract_skills, skill_kind

log = logging.getLogger(__name__)

# Long-form expansions applied when the posting uses the long form and the bullet
# uses the acronym (pure terminology alignment; never changes facts).
EXPANSIONS = [
    (r"\bNLP\b", "natural language processing", "natural language processing (NLP)"),
    (r"\bEDA\b", "exploratory data analysis", "exploratory data analysis (EDA)"),
    (r"\bETL pipelines\b", "extract, transform", "ETL (extract, transform, load) pipelines"),
    (r"\bREST APIs\b", "restful", "RESTful APIs"),
    (r"\bREST API endpoints\b", "restful", "RESTful API endpoints"),
    (r"\bCI/CD\b", "continuous integration", "CI/CD (continuous integration and delivery)"),
]


@dataclass
class TailorResult:
    resume: dict
    keywords: list[str]
    matched_keywords: list[str]
    changes: list[dict] = field(default_factory=list)
    factcheck: dict = field(default_factory=dict)
    llm_used: bool = False


def _plain(t: str) -> str:
    return t.replace("**", "")


def _bullet_relevance(text: str, entry_tech: list[str], jd_text: str, jd_skills: dict[str, int]) -> float:
    bs = set(extract_skills(_plain(text))) | {c for c in (canonicalize(t) for t in entry_tech) if c}
    implied = {i for s in bs for i in IMPLIES.get(s, [])} - bs
    overlap = (sum(min(jd_skills.get(s, 0), 3) for s in bs) + 0.6 * sum(min(jd_skills.get(s, 0), 3) for s in implied)) / 6.0
    score = min(1.0, overlap) * 0.6 + min(1.0, cosine(_plain(text), jd_text) * 2.2) * 0.4
    # Recruiters weight concrete evidence: a quantified bullet that names a posting skill
    # leads over a generic one with similar wording overlap.
    own = set(extract_skills(_plain(text)))
    if re.search(r"\d", text) and own & set(jd_skills):
        score += 0.12
    return score


def _expand_terms(text: str, jd_lower: str) -> tuple[str, list[str]]:
    applied = []
    for pattern, trigger, replacement in EXPANSIONS:
        if trigger in jd_lower and re.search(pattern, text) and replacement.lower() not in text.lower():
            # preserve bold markers around the acronym if present
            new = re.sub(r"\*\*" + pattern[2:-2] + r"\*\*", "**" + replacement + "**", text, count=1)
            if new == text:
                new = re.sub(pattern, replacement, text, count=1)
            if new != text:
                applied.append(pattern.replace(r"\b", "") + " → " + replacement)
                text = new
    return text, applied


REWRITE_SYSTEM = """You tailor resume bullet points to a specific job posting for an ATS-friendly resume.

Hard rules - violating any of them makes the bullet unusable:
- Use ONLY facts already present in the original bullet. Do not add numbers, percentages, tools, technologies, employers, team sizes, outcomes, or responsibilities that are not in the original bullet.
- Keep every number exactly as written in the original (e.g. "10M+", "30%").
- Do not add leadership words (led, managed, mentored, owned, spearheaded) unless the original has them.
- You may: reorder clauses, choose stronger accurate verbs, and swap a word for the posting's terminology when it means the same thing (e.g. "dashboards" -> "data visualizations" if the posting uses that term and it is accurate).
- Keep each bullet to one sentence, past tense, no first person, roughly the same length (never more than 30% longer).
- Wrap the numbers and tool names that the original bolded in **double asterisks**, as in the original.
- If a bullet cannot be improved truthfully for this posting, return it unchanged.
"""

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "bullets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "posting_terms_used": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "text", "posting_terms_used"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["bullets"],
    "additionalProperties": False,
}


def _llm_rewrite(llm: LLM, job, bullets: list[dict], keywords: list[str]) -> dict[str, str]:
    jd = (job.description_text or "")[:9000]
    lines = "\n".join(f'- id={b["id"]} | role/project: {b["context"]} | tech on that entry: {", ".join(b["tech"])}\n  original: {b["text"]}'
                      for b in bullets)
    user = (f"Job posting: {job.title} at {job.company}\n\nPosting keywords: {', '.join(keywords[:25])}\n\n"
            f"Posting text:\n<posting>\n{jd}\n</posting>\n\nRewrite these bullets for this posting following the rules:\n{lines}")
    data = llm.json(REWRITE_SYSTEM, user, REWRITE_SCHEMA, effort="medium", max_tokens=6000)
    if not data:
        return {}
    return {b["id"]: b["text"].strip() for b in data.get("bullets", []) if b.get("id") and b.get("text")}


def tailor_resume(master: dict, profile: dict, job, settings: dict, llm: LLM | None = None) -> TailorResult:
    rs = settings.get("resume", {})
    jd_text = (job.description_text or "") + "\n" + (job.title or "")
    jd_lower = jd_text.lower()
    reqs = extract_requirements(job.description_text or "")
    jd_skills = dict(reqs.all_skills)
    for s in reqs.required_skills:
        jd_skills[s] = jd_skills.get(s, 0) + 2
    for s in extract_skills(job.title or ""):
        jd_skills[s] = jd_skills.get(s, 0) + 3
    keywords = [s for s, _ in sorted(jd_skills.items(), key=lambda kv: -kv[1]) if skill_kind(s) != "soft"]

    out = copy.deepcopy(master)
    changes: list[dict] = []
    rejected: list[dict] = []
    llm_used = False

    # 1. bullets within each experience entry, by relevance (role order stays chronological)
    for e in out["experience"]:
        orig = [b["id"] for b in e["bullets"]]
        e["bullets"].sort(key=lambda b: -_bullet_relevance(b["text"], e.get("tech", []), jd_text, jd_skills))
        if [b["id"] for b in e["bullets"]] != orig:
            changes.append({"type": "reorder_bullets", "entry": e["org"],
                            "detail": f"Bullets reordered by relevance: {[b['id'] for b in e['bullets']]}"})

    # 2. projects by relevance, keep the top N
    def proj_score(p):
        scores = sorted((_bullet_relevance(b["text"], p.get("tech", []), jd_text, jd_skills) for b in p["bullets"]), reverse=True)
        tech = {c for c in (canonicalize(t) for t in p.get("tech", [])) if c}
        tech |= {i for s in tech for i in IMPLIES.get(s, [])}
        return sum(scores[:2]) + 0.5 * len(tech & set(jd_skills))
    orig_proj = [p["id"] for p in out["projects"]]
    out["projects"].sort(key=lambda p: -proj_score(p))
    for p in out["projects"]:
        p["bullets"].sort(key=lambda b: -_bullet_relevance(b["text"], p.get("tech", []), jd_text, jd_skills))
    max_proj = int(rs.get("max_projects", 3))
    if len(out["projects"]) > max_proj:
        dropped = out["projects"][max_proj:]
        out["projects"] = out["projects"][:max_proj]
        changes.append({"type": "drop_projects", "detail": f"Omitted least relevant: {[p['name'] for p in dropped]}"})
    if [p["id"] for p in out["projects"]] != orig_proj[: len(out["projects"])]:
        changes.append({"type": "reorder_projects", "detail": f"Project order: {[p['name'] for p in out['projects']]}"})

    # 3. skills: posting-relevant first; add user-confirmed extra skills the posting asks for
    matched: set[str] = set()
    for g in out["skills"]:
        before = list(g["items"])
        pos = {item: i for i, item in enumerate(before)}

        def key(item):
            c = canonicalize(item)
            return (-(jd_skills.get(c, 0) if c else 0), pos[item])
        g["items"].sort(key=key)
        matched |= {canonicalize(i) for i in g["items"] if canonicalize(i) in jd_skills}
        if g["items"] != before:
            changes.append({"type": "reorder_skills", "entry": g["category"],
                            "detail": f"Prioritized: {[i for i in g['items'] if canonicalize(i) in jd_skills]}"})
    extra = [s for s in (profile.get("confirmed_extra_skills") or []) if canonicalize(s) in jd_skills]
    if extra:
        target = out["skills"][-1]
        for s in extra:
            if s not in target["items"]:
                target["items"].insert(0, s)
                matched.add(canonicalize(s))
        changes.append({"type": "add_confirmed_skills", "detail": f"Added user-confirmed skills: {extra}"})

    # 4. wording
    if rs.get("reword_bullets", True):
        for section in ("experience", "projects"):
            for e in out[section]:
                for b in e["bullets"]:
                    new, applied = _expand_terms(b["text"], jd_lower)
                    if applied and check_bullet(b["text"], new, e.get("tech", [])).ok:
                        changes.append({"type": "terminology", "bullet": b["id"], "detail": "; ".join(applied),
                                        "before": _plain(b["text"]), "after": _plain(new)})
                        b["text"] = new
        if llm is not None and llm.available and rs.get("use_llm", True):
            candidates = []
            for section in ("experience", "projects"):
                for e in out[section]:
                    ctx = f'{e.get("title", "")} @ {e.get("org", "")}' if section == "experience" else f'{e["name"]} ({e.get("context", "")})'
                    for b in e["bullets"]:
                        candidates.append({"id": b["id"], "text": b["text"], "context": ctx, "tech": e.get("tech", []), "entry": e})
            rewrites = _llm_rewrite(llm, job, [{k: v for k, v in c.items() if k != "entry"} for c in candidates], keywords)
            if rewrites:
                llm_used = True
            for c in candidates:
                new = rewrites.get(c["id"])
                if not new or _plain(new) == _plain(c["text"]):
                    continue
                g = check_bullet(c["text"], new, c["tech"])
                if g.ok:
                    for b in c["entry"]["bullets"]:
                        if b["id"] == c["id"]:
                            changes.append({"type": "reworded", "bullet": c["id"], "before": _plain(b["text"]), "after": _plain(new)})
                            b["text"] = new
                else:
                    rejected.append({"bullet": c["id"], "proposed": _plain(new), "issues": g.issues})

    # 5. final verification: every bullet in the output must trace to a master bullet
    master_bullets = {b["id"]: b["text"] for s in ("experience", "projects") for e in master[s] for b in e["bullets"]}
    master_tech = {b["id"]: e.get("tech", []) for s in ("experience", "projects") for e in master[s] for b in e["bullets"]}
    violations = []
    for section in ("experience", "projects"):
        for e in out[section]:
            for b in e["bullets"]:
                if b["id"] not in master_bullets:
                    violations.append(f"unknown bullet {b['id']}")
                    continue
                g = check_bullet(master_bullets[b["id"]], b["text"], master_tech[b["id"]])
                if not g.ok and _plain(b["text"]) != _plain(master_bullets[b["id"]]):
                    violations.append(f"{b['id']}: {g.issues}")
                    b["text"] = master_bullets[b["id"]]
    for key_ in ("education", "basics"):
        if out[key_] != master[key_]:
            violations.append(f"{key_} altered")
            out[key_] = copy.deepcopy(master[key_])
    for i, e in enumerate(out["experience"]):
        m = next(x for x in master["experience"] if x["id"] == e["id"])
        for f in ("org", "title", "dates", "location"):
            if e[f] != m[f]:
                violations.append(f"experience {e['id']} {f} altered")
                e[f] = m[f]

    factcheck = {
        "passed": not violations,
        "violations_reverted": violations,
        "rejected_rewrites": rejected,
        "rules": ["numbers must appear in original bullet", "skills limited to original bullet + entry tech",
                  "no new leadership claims", "no new proper nouns", "employers/titles/dates/degrees verbatim"],
    }
    return TailorResult(out, keywords, sorted(m for m in matched if m), changes, factcheck, llm_used)
