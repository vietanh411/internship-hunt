"""ATS readability validation: extract the PDF text the way a parser would and
confirm it is complete, ordered, and machine-readable."""
from __future__ import annotations

import io
import re

from pypdf import PdfReader


def _norm(s: str) -> str:
    s = s.replace("**", "").replace("–", "-").replace("—", "-").replace("­", "")
    s = re.sub(r"-\s*\n\s*", "-", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def extract_text(pdf: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf))
    return "\n".join(p.extract_text() or "" for p in reader.pages)


def ats_check(pdf: bytes, resume: dict, keywords: list[str] | None = None, one_page: bool = True,
              filename: str | None = None) -> dict:
    reader = PdfReader(io.BytesIO(pdf))
    text = extract_text(pdf)
    nt = _norm(text)
    checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "passed": bool(ok), "detail": detail})

    add("valid_pdf", len(reader.pages) >= 1, f"{len(reader.pages)} page(s)")
    if one_page:
        add("one_page", len(reader.pages) == 1, f"{len(reader.pages)} page(s)")
    if filename is not None:
        add("filename", bool(re.fullmatch(r"Resume_[A-Za-z0-9]+\.pdf", filename)), filename)
    add("selectable_text", len(nt) > 500, f"{len(nt)} characters extracted")
    add("no_garbled_glyphs", "(cid:" not in text and "�" not in text)
    b = resume["basics"]
    for label, val in (("name", b["name"]), ("email", b["email"]), ("phone", b.get("phone", ""))):
        add(f"contact_{label}", _norm(val) in nt, val)
    order = ["education", "work experience", "projects", "technical skills"]
    positions = [nt.find(h) for h in order]
    add("sections_present", all(p >= 0 for p in positions), str(dict(zip(order, positions))))
    add("section_order", all(p >= 0 for p in positions) and positions == sorted(positions))
    missing = []
    for section in ("experience", "projects"):
        for e in resume[section]:
            for bl in e["bullets"]:
                frag = _norm(bl["text"])[:70]
                if frag not in nt:
                    missing.append(bl["id"])
    add("all_bullets_extractable", not missing, f"missing: {missing}" if missing else "all bullets found")
    for e in resume["experience"]:
        add(f"dates_{e['id']}", _norm(e["dates"]) in nt, e["dates"])
    coverage = None
    if keywords:
        present = [k for k in keywords if _norm(k) in nt]
        coverage = {"present": present, "absent": [k for k in keywords if k not in present],
                    "ratio": round(len(present) / len(keywords), 2)}
    return {"passed": all(c["passed"] for c in checks), "checks": checks, "keyword_coverage": coverage,
            "text_preview": text[:600]}
