"""ATS adapters: platform detection, form discovery, and form URLs.

Automatic (browser) submission is implemented for Greenhouse, Lever and Ashby
hosted forms and the local mock ATS. Workday, iCIMS, Oracle, SuccessFactors,
Taleo and unknown platforms require an applicant account or are unsupported, so
they get a prepared packet for manual submission."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from hunt.apply.answers import FormField
from hunt.discovery import ats
from hunt.discovery.normalize import parse_ats_url
from hunt.http import PoliteClient

# Sites whose hidden bot check rejects the system's (automation-controlled) browser even
# when you click Submit yourself ("There was an error verifying your application"). You
# apply in your own browser with the prepared resume and answer sheet; the window is
# never disguised to get past the check.
OWN_BROWSER_PLATFORMS = {"lever"}
AUTO_PLATFORMS = {"greenhouse", "ashby", "mock"}
# Platforms the "Finish application" window can fill for you (Workday: after you sign in).
ASSIST_PLATFORMS = AUTO_PLATFORMS | {"workday"}

MANUAL_REASONS = {
    "lever": "Lever's bot check rejects automated browser windows, so apply in your own browser.",
    "workday": "Workday requires creating an account on the employer's Workday site (with email verification).",
    "icims": "iCIMS requires an applicant account / login.",
    "oracle": "Oracle Recruiting Cloud requires an applicant profile with email verification.",
    "successfactors": "SAP SuccessFactors requires an applicant account.",
    "taleo": "Taleo requires an applicant account.",
    "eightfold": "Eightfold applications require an account / login.",
    "phenom": "Phenom career sites route to an account-based ATS.",
}

STANDARD_FIELDS = [
    FormField("first_name", "First Name", "text", True),
    FormField("last_name", "Last Name", "text", True),
    FormField("email", "Email", "text", True),
    FormField("phone", "Phone", "text", True),
    FormField("resume", "Resume/CV", "file", True),
    FormField("linkedin", "LinkedIn Profile", "text", False),
    FormField("authorized", "Are you legally authorized to work in the United States?", "select", True, ["Yes", "No"]),
    FormField("sponsorship", "Will you now or in the future require sponsorship for employment visa status?", "select", True, ["Yes", "No"]),
    FormField("school", "School", "text", False),
    FormField("degree", "Degree", "text", False),
    FormField("graduation", "Expected graduation date", "text", False),
    FormField("start", "Earliest start date", "text", False),
]


def platform_of(job) -> str:
    if job.is_test:
        return "workday" if job.ats_platform == "workday" else "mock"
    if job.ats_platform:
        return job.ats_platform
    return parse_ats_url(job.apply_url).platform or "other"


def manual_reason(platform: str) -> str:
    return MANUAL_REASONS.get(platform, "Application platform is not supported for automatic submission.")


def form_url(job) -> str:
    p = platform_of(job)
    if p == "greenhouse" and job.ats_board and job.ats_job_id:
        if "greenhouse.io" not in urlsplit(job.posting_url or job.apply_url or "").netloc:
            # the company shows this board on its own careers page (?gh_jid=…), so the hosted
            # page redirects there and the form sits in a frame; open the form itself instead
            return f"https://job-boards.greenhouse.io/embed/job_app?for={job.ats_board}&token={job.ats_job_id}"
        return f"https://job-boards.greenhouse.io/{job.ats_board}/jobs/{job.ats_job_id}"
    if p == "lever" and job.ats_board and job.ats_job_id:
        return f"https://jobs.lever.co/{job.ats_board}/{job.ats_job_id}/apply"
    if p == "ashby" and job.ats_board and job.ats_job_id:
        return f"https://jobs.ashbyhq.com/{job.ats_board}/{job.ats_job_id}/application"
    return job.apply_url or job.posting_url


_GH_TYPES = {"input_text": "text", "textarea": "textarea", "input_file": "file",
             "multi_value_single_select": "select", "multi_value_multi_select": "multi_select"}


def greenhouse_fields(form: dict) -> list[FormField]:
    out: list[FormField] = []
    for q in (form.get("questions") or []) + (form.get("location_questions") or []):
        for f in q.get("fields") or []:
            if f.get("type") == "input_hidden" or f.get("name") in ("resume_text", "cover_letter_text"):
                continue
            vals = f.get("values") or []
            out.append(FormField(name=f["name"], label=q.get("label", f["name"]), type=_GH_TYPES.get(f.get("type"), "text"),
                                 required=bool(q.get("required")), options=[v.get("label", "") for v in vals],
                                 option_values=[str(v.get("value")) for v in vals]))
    for sec in form.get("compliance") or []:
        for q in sec.get("questions") or []:
            for f in q.get("fields") or []:
                vals = f.get("values") or []
                out.append(FormField(name=f["name"], label=q.get("label", f["name"]), type=_GH_TYPES.get(f.get("type"), "select"),
                                     required=bool(q.get("required")), options=[v.get("label", "") for v in vals],
                                     option_values=[str(v.get("value")) for v in vals]))
    demo = form.get("demographic_questions") or {}
    for q in demo.get("questions") or []:
        opts = q.get("answer_options") or []
        out.append(FormField(name=f"demographic_{q.get('id')}", label=q.get("label", ""),
                             type="multi_select" if q.get("type") == "multi_value_multi_select" else "select",
                             required=bool(q.get("required")), options=[o.get("label", "") for o in opts],
                             option_values=[str(o.get("id")) for o in opts]))
    return out


def greenhouse_board(client: PoliteClient, job_id: str) -> str | None:
    """Board name for a Greenhouse job found only on a company's careers page (?gh_jid=…):
    Greenhouse's embed address redirects to one that names the board."""
    try:
        r = client.request("GET", f"https://boards.greenhouse.io/embed/job_app?token={job_id}", follow_redirects=False)
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"[?&]for=([A-Za-z0-9_-]+)", r.headers.get("location") or "")
    return m.group(1) if m else None


def fetch_form(job, client: PoliteClient, mock_base: str | None = None) -> tuple[list[FormField], dict | None, str]:
    """Returns (fields, raw_form, source). Read-only."""
    p = platform_of(job)
    if p == "mock":
        raw = client.get_json(f"{mock_base or job.apply_url.rsplit('/jobs/', 1)[0]}/api/jobs/{job.ats_job_id}")
        return greenhouse_fields(raw), raw, "mock_api"
    if p == "greenhouse" and job.ats_board and job.ats_job_id:
        _, raw = ats.greenhouse_job(client, job.ats_board, job.ats_job_id, job.company)
        return greenhouse_fields(raw), raw, "greenhouse_api"
    return list(STANDARD_FIELDS), None, "standard"
