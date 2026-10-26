"""Tailored cover letters built only from verified resume facts and the posting."""
from __future__ import annotations

import io
import re
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from hunt.llm import LLM
from hunt.resume.factguard import check_free_text


def _known_text(job) -> str:
    """Posting text the fact guard may treat as known (title + description)."""
    return f"{job.title}\n{job.description_text or ''}"

COVER_REQUIRED = re.compile(r"(cover letter (?:is )?(?:required|must|mandatory)|(?:include|submit|attach|upload|provide) (?:a |your )?cover letter|"
                            r"cover letters? (?:are|is) (?:required|strongly encouraged))", re.I)


def needs_cover_letter(job, form: dict | None, policy: str) -> bool:
    if policy == "never":
        return False
    if policy == "always":
        return True
    if form:
        for q in form.get("questions", []):
            for f in q.get("fields", []):
                if f.get("name") == "cover_letter" and q.get("required"):
                    return True
    return bool(COVER_REQUIRED.search(job.description_text or ""))


def _lower_first(s: str) -> str:
    s = s.replace("**", "").rstrip(".")
    return s[0].lower() + s[1:] if s and not s[:2].isupper() else s


def template_letter(master: dict, profile: dict, job, explanation: dict) -> list[str]:
    edu = master["education"]
    ms, bs = edu[0], edu[1]
    matched = (explanation or {}).get("matched_skills", [])[:4]
    evidence = (explanation or {}).get("evidence", [])
    by_id = {b["id"]: (e, kind) for kind in ("experience", "projects") for e in master[kind] for b in e["bullets"]}
    p1 = (f"I am applying for the {job.title} position at {job.company}. I am pursuing a {ms['degree']} at "
          f"{ms['school']} ({ms['dates'].replace('Expected ', 'expected ')}), after earning a {bs['degree']} at "
          f"{bs['school']} with a {bs.get('gpa')} GPA.")
    paras = [p1]
    used_entries = set()
    for ev in evidence:
        if len(paras) >= 3:
            break
        entry, kind = by_id.get(ev.get("bullet_id"), (None, None))
        if entry is None or entry["id"] in used_entries:
            continue
        used_entries.add(entry["id"])
        if kind == "experience":
            lead = f"As a {entry['title']} at {entry['org'].split(' (')[0]}, I {_lower_first(ev['text'])}."
        else:
            lead = f"In my {entry['name']} project, I {_lower_first(ev['text'])}."
        if len(paras) == 1 and matched:
            lead = f"Your posting emphasizes {', '.join(matched[:-1]) + ' and ' + matched[-1] if len(matched) > 1 else matched[0]}. " + lead
        paras.append(lead)
    avail = profile.get("availability") or {}
    start = avail.get("earliest_start_date")
    tail = "I am available for a Summer 2027 internship"
    if start:
        try:
            d = date.fromisoformat(str(start))
            tail += f" starting {d.strftime('%B')} {d.day}, {d.year}"
        except ValueError:
            pass
    if avail.get("willing_to_relocate"):
        tail += " and am willing to relocate"
    paras.append(tail + ". Thank you for considering my application.")
    return paras


COVER_SYSTEM = """You write concise, specific cover letters for internship applications.
Rules:
- Use only facts from the provided resume and profile. Never invent experiences, numbers, skills, awards, or familiarity with the company beyond what the job posting itself states.
- Do not claim skills the resume does not list. If the posting asks for a skill the applicant lacks, do not mention it.
- No generic filler ("I am passionate", "I believe I would be a great fit", "dream job"). Every sentence should carry a concrete fact.
- 3 or 4 short paragraphs, under 260 words total. No salutation or sign-off (added separately).
"""

COVER_SCHEMA = {
    "type": "object",
    "properties": {"paragraphs": {"type": "array", "items": {"type": "string"}}},
    "required": ["paragraphs"],
    "additionalProperties": False,
}


def generate_cover_letter(master: dict, profile: dict, job, explanation: dict, applicant_skills: set[str],
                          llm: LLM | None) -> tuple[list[str], dict]:
    meta = {"llm_used": False, "guard": None}
    if llm is not None and llm.available:
        import yaml
        resume_yaml = yaml.safe_dump({k: master[k] for k in ("education", "experience", "projects", "skills")},
                                     allow_unicode=True, sort_keys=False)
        user = (f"Applicant: {master['basics']['name']}\nAvailability: Summer 2027, start "
                f"{(profile.get('availability') or {}).get('earliest_start_date')}\n\nResume (verified facts):\n{resume_yaml}\n\n"
                f"Job: {job.title} at {job.company}\n<posting>\n{(job.description_text or '')[:8000]}\n</posting>")
        data = llm.json(COVER_SYSTEM, user, COVER_SCHEMA, effort="medium", max_tokens=3000)
        if data and data.get("paragraphs"):
            text = "\n\n".join(data["paragraphs"])
            g = check_free_text(text, master, profile, _known_text(job), job.company, applicant_skills)
            meta["guard"] = {"ok": g.ok, "issues": g.issues}
            if g.ok:
                meta["llm_used"] = True
                return data["paragraphs"], meta
    paras = template_letter(master, profile, job, explanation)
    g = check_free_text("\n\n".join(paras), master, profile, _known_text(job), job.company, applicant_skills)
    meta["template_guard"] = {"ok": g.ok, "issues": g.issues}
    return paras, meta


def render_cover_letter(paragraphs: list[str], basics: dict, company: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=inch, rightMargin=inch, topMargin=0.9 * inch,
                            bottomMargin=0.9 * inch, title=f"{basics['name']} – Cover Letter", author=basics["name"])
    body = ParagraphStyle("b", fontName="Times-Roman", fontSize=11, leading=15, spaceAfter=10)
    head = ParagraphStyle("h", fontName="Times-Bold", fontSize=16, leading=20)
    small = ParagraphStyle("s", fontName="Times-Roman", fontSize=10.5, leading=13)
    story = [Paragraph(escape(basics["name"]), head),
             Paragraph(escape(" | ".join(x for x in (basics.get("phone"), basics.get("email"), basics.get("linkedin_label")) if x)), small),
             Spacer(1, 18), Paragraph(date.today().strftime("%B %d, %Y").replace(" 0", " "), body),
             Paragraph(f"Dear {escape(company)} Hiring Team,", body)]
    story += [Paragraph(escape(p), body) for p in paragraphs]
    story += [Paragraph("Sincerely,", body), Paragraph(escape(basics["name"]), body)]
    doc.build(story)
    return buf.getvalue()
