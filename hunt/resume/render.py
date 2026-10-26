"""ATS-friendly PDF rendering that mirrors the applicant's LaTeX template (Jake's
resume): centered name/contact, small-caps section headings with a rule, bold
organisation / right-aligned location, italic title / right-aligned dates, en-dash
bullets. Single column, real text (base-14 Times fonts), no tables or images."""
from __future__ import annotations

import io
import re
from xml.sax.saxutils import escape

from pypdf import PdfReader
from reportlab.lib.colors import black
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer

FONT = "Times-Roman"
BOLD = "Times-Bold"
ITALIC = "Times-Italic"


def _md(text: str) -> str:
    """**bold** -> <b>bold</b>, with XML escaping."""
    parts = text.split("**")
    out = []
    for i, p in enumerate(parts):
        out.append(f"<b>{escape(p)}</b>" if i % 2 else escape(p))
    return "".join(out)


class HRule(Flowable):
    def __init__(self, width: float, thickness: float = 0.5, space_after: float = 3):
        super().__init__()
        self.width, self.thickness, self.space_after = width, thickness, space_after

    def wrap(self, aw, ah):
        return self.width, self.thickness + self.space_after

    def draw(self):
        self.canv.setStrokeColor(black)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, self.space_after, self.width, self.space_after)


class LeftRight(Flowable):
    """Left text (may wrap) and right text on the same baseline. Drawn as plain
    text runs (left first) so extraction order is left-then-right."""
    def __init__(self, left: str, right: str, lstyle: ParagraphStyle, rstyle: ParagraphStyle, width: float):
        super().__init__()
        self.lstyle, self.rstyle, self.width = lstyle, rstyle, width
        self.right_text = right
        self.rw = self._text_width(right, rstyle) if right else 0
        self.left = Paragraph(left, lstyle)
        self.right = Paragraph(escape(right), ParagraphStyle("r", parent=rstyle, alignment=TA_LEFT)) if right else None

    @staticmethod
    def _text_width(text: str, style: ParagraphStyle) -> float:
        from reportlab.pdfbase.pdfmetrics import stringWidth
        return stringWidth(text, style.fontName, style.fontSize)

    def wrap(self, aw, ah):
        lw, lh = self.left.wrap(self.width - self.rw - 8, ah)
        rh = self.right.wrap(self.rw + 2, ah)[1] if self.right else 0
        self.h = max(lh, rh)
        return self.width, self.h

    def draw(self):
        lw, lh = self.left.wrap(self.width - self.rw - 8, self.h)
        self.left.drawOn(self.canv, 0, self.h - lh)
        if self.right:
            rw, rh = self.right.wrap(self.rw + 2, self.h)
            self.right.drawOn(self.canv, self.width - self.rw, self.h - rh)


def _styles(scale: float) -> dict[str, ParagraphStyle]:
    s = scale
    return {
        "name": ParagraphStyle("name", fontName=BOLD, fontSize=20 * s, leading=24 * s, alignment=TA_CENTER),
        "contact": ParagraphStyle("contact", fontName=FONT, fontSize=10 * s, leading=12 * s, alignment=TA_CENTER),
        "section": ParagraphStyle("section", fontName=FONT, fontSize=12.5 * s, leading=14 * s, spaceBefore=5 * s),
        "org": ParagraphStyle("org", fontName=BOLD, fontSize=10.5 * s, leading=12.4 * s),
        "loc": ParagraphStyle("loc", fontName=FONT, fontSize=10.5 * s, leading=12.4 * s),
        "title": ParagraphStyle("title", fontName=ITALIC, fontSize=9.8 * s, leading=11.6 * s),
        "dates": ParagraphStyle("dates", fontName=ITALIC, fontSize=9.8 * s, leading=11.6 * s),
        "bullet": ParagraphStyle("bullet", fontName=FONT, fontSize=9.8 * s, leading=11.6 * s,
                                 leftIndent=0.38 * inch, bulletIndent=0.2 * inch, spaceAfter=0.6 * s),
        "proj": ParagraphStyle("proj", fontName=FONT, fontSize=9.8 * s, leading=11.8 * s),
        "skills": ParagraphStyle("skills", fontName=FONT, fontSize=9.8 * s, leading=12 * s, leftIndent=0.12 * inch),
    }


def _small_caps(title: str, size: float) -> str:
    out = []
    for word in title.split():
        out.append(f'<font size="{size:.1f}">{escape(word[0].upper())}</font>'
                   f'<font size="{size * 0.8:.1f}">{escape(word[1:].upper())}</font>')
    return " ".join(out)


def build_story(resume: dict, scale: float, width: float) -> list:
    st = _styles(scale)
    b = resume["basics"]
    story: list = [Paragraph(escape(b["name"]), st["name"])]
    contact = [escape(b.get("phone", ""))]
    if b.get("email"):
        contact.append(f'<a href="mailto:{escape(b["email"])}"><u>{escape(b["email"])}</u></a>')
    if b.get("linkedin_url"):
        contact.append(f'<a href="{escape(b["linkedin_url"])}"><u>{escape(b.get("linkedin_label") or b["linkedin_url"])}</u></a>')
    for key in ("github_url", "portfolio_url"):
        if b.get(key):
            contact.append(f'<a href="{escape(b[key])}"><u>{escape(re.sub(r"^https?://(www\.)?", "", b[key]))}</u></a>')
    story += [Paragraph(" | ".join(c for c in contact if c), st["contact"]), Spacer(1, 2 * scale)]

    def section(name: str):
        story.append(Paragraph(_small_caps(name, 12.5 * scale), st["section"]))
        story.append(HRule(width, 0.6, 3.5 * scale))

    section("Education")
    for e in resume["education"]:
        degree = e["degree"] + (f", GPA: {e['gpa']}" if e.get("gpa") else "")
        story.append(LeftRight(f"<b>{escape(e['school'])}</b>", e.get("location", ""), st["org"], st["loc"], width))
        story.append(LeftRight(f"<i>{escape(degree)}</i>", e.get("dates", ""), st["title"], st["dates"], width))
        story.append(Spacer(1, 1.5 * scale))

    section("Work Experience")
    for e in resume["experience"]:
        story.append(LeftRight(f"<b>{escape(e['org'])}</b>", e.get("location", ""), st["org"], st["loc"], width))
        story.append(LeftRight(f"<i>{escape(e['title'])}</i>", e.get("dates", ""), st["title"], st["dates"], width))
        for bl in e["bullets"]:
            story.append(Paragraph(_md(bl["text"]), st["bullet"], bulletText="–"))
        story.append(Spacer(1, 2 * scale))

    section("Projects")
    for p in resume["projects"]:
        head = f"<b>{escape(p['name'])}</b>"
        if p.get("context"):
            head += f" | <i>{escape(p['context'])}</i>"
        if p.get("tech"):
            head += " | " + escape(", ".join(t for t in p["tech"] if t not in ("NLP", "REST APIs", "Express", "Web Scraping")))
        story.append(Paragraph(head, st["proj"]))
        for bl in p["bullets"]:
            story.append(Paragraph(_md(bl["text"]), st["bullet"], bulletText="–"))
        story.append(Spacer(1, 1.5 * scale))

    section("Technical Skills")
    lines = [f"<b>{escape(g['category'])}</b>: {escape(', '.join(g['items']))}" for g in resume["skills"]]
    story.append(Paragraph("<br/>".join(lines), st["skills"]))
    return story


def render_pdf(resume: dict, scale: float = 1.0, title: str | None = None) -> bytes:
    buf = io.BytesIO()
    margin_x, margin_y = 0.5 * inch, 0.45 * inch
    doc = SimpleDocTemplate(
        buf, pagesize=letter, leftMargin=margin_x, rightMargin=margin_x, topMargin=margin_y, bottomMargin=margin_y,
        title=title or f"{resume['basics']['name']} – Resume", author=resume["basics"]["name"], subject="Resume",
        creator="InternshipHunt",
    )
    width = letter[0] - 2 * margin_x
    doc.build(build_story(resume, scale, width))
    return buf.getvalue()


def page_count(pdf: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf)).pages)


def render_fitted(resume: dict, one_page: bool = True) -> tuple[bytes, dict, list[str]]:
    """Render, shrinking slightly and then trimming the least relevant bullets
    (last bullets of the last projects) until it fits on one page."""
    import copy
    work = copy.deepcopy(resume)
    notes: list[str] = []
    for scale in (1.0, 0.97, 0.94, 0.91):
        pdf = render_pdf(work, scale)
        if not one_page or page_count(pdf) == 1:
            if scale != 1.0:
                notes.append(f"font scaled to {scale:.2f} to fit one page")
            return pdf, work, notes
    while True:
        trimmed = False
        for p in reversed(work["projects"]):
            if len(p["bullets"]) > 2:
                removed = p["bullets"].pop()
                notes.append(f"trimmed bullet {removed['id']} to fit one page")
                trimmed = True
                break
        if not trimmed and len(work["projects"]) > 2:
            removed = work["projects"].pop()
            notes.append(f"omitted project {removed['name']} to fit one page")
            trimmed = True
        if not trimmed:
            break
        pdf = render_pdf(work, 0.94)
        if page_count(pdf) == 1:
            return pdf, work, notes
    notes.append("could not fit on one page")
    return render_pdf(work, 0.91), work, notes
