"""Local mock applicant-tracking system used for tests and dry runs.

Mimics a Greenhouse job board: a questions API (GET /api/jobs/{id}) and a hosted
application form (GET /jobs/{id}) that posts to /jobs/{id}/submit and redirects to
a confirmation page. Job ids select variants:
  mock-standard  - normal form
  mock-captcha   - shows a CAPTCHA challenge frame (must be Blocked, never solved)
  mock-unknown   - includes a required question with no verified answer
  mock-silent    - accepts the submission but never shows a confirmation
  mock-verify    - asks for an emailed security code before accepting (like Greenhouse)
Submissions are stored in memory (and data/mock_ats/) for assertions."""
from __future__ import annotations

import html
import json
import secrets
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from hunt.config import get_settings

router = APIRouter()
SUBMISSIONS: list[dict] = []
PENDING: dict[str, dict] = {}  # mock-verify: submissions waiting for the emailed code
VERIFY_CODE = "NojgLEvQ"

BASE_QUESTIONS = [
    {"label": "First Name", "required": True, "fields": [{"name": "first_name", "type": "input_text", "values": []}]},
    {"label": "Last Name", "required": True, "fields": [{"name": "last_name", "type": "input_text", "values": []}]},
    {"label": "Email", "required": True, "fields": [{"name": "email", "type": "input_text", "values": []}]},
    {"label": "Phone", "required": True, "fields": [{"name": "phone", "type": "input_text", "values": []}]},
    {"label": "Resume/CV", "required": True, "fields": [{"name": "resume", "type": "input_file", "values": []},
                                                         {"name": "resume_text", "type": "textarea", "values": []}]},
    {"label": "Cover Letter", "required": False, "fields": [{"name": "cover_letter", "type": "input_file", "values": []}]},
    {"label": "LinkedIn Profile", "required": False, "fields": [{"name": "question_1001", "type": "input_text", "values": []}]},
    {"label": "Are you legally authorized to work in the United States?", "required": True,
     "fields": [{"name": "question_1002", "type": "multi_value_single_select", "values": [{"label": "Yes", "value": 1}, {"label": "No", "value": 0}]}]},
    {"label": "Will you now or in the future require sponsorship for employment visa status (e.g., H-1B visa status)?", "required": True,
     "fields": [{"name": "question_1003", "type": "multi_value_single_select", "values": [{"label": "Yes", "value": 1}, {"label": "No", "value": 0}]}]},
    {"label": "What is your expected graduation date?", "required": True, "fields": [{"name": "question_1004", "type": "input_text", "values": []}]},
    {"label": "Why are you interested in this internship?", "required": True, "fields": [{"name": "question_1005", "type": "textarea", "values": []}]},
    {"label": "How did you hear about this job?", "required": False,
     "fields": [{"name": "question_1006", "type": "multi_value_single_select",
                 "values": [{"label": "LinkedIn", "value": 1}, {"label": "Company Website", "value": 2}, {"label": "Job Board", "value": 3}, {"label": "Other", "value": 4}]}]},
]
UNKNOWN_Q = {"label": "What are your salary expectations for this internship?", "required": True,
             "fields": [{"name": "question_1099", "type": "input_text", "values": []}]}
COMPLIANCE = [{"type": "eeoc", "questions": [
    {"label": "Gender", "required": False, "fields": [{"name": "gender", "type": "multi_value_single_select",
     "values": [{"label": "Male", "value": 1}, {"label": "Female", "value": 2}, {"label": "Decline To Self Identify", "value": 3}]}]}]}]


RANDOM_ID_RADIOS = {"question_1002", "question_1003"}


def questions_for(job_id: str) -> list[dict]:
    q = list(BASE_QUESTIONS)
    if job_id == "mock-unknown":
        q.append(UNKNOWN_Q)
    return q


@router.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    return JSONResponse({"id": job_id, "title": "Data Science Intern (Summer 2027)", "questions": questions_for(job_id),
                         "location_questions": [], "compliance": COMPLIANCE, "demographic_questions": {}})


def _field_html(q: dict) -> str:
    out = []
    star = " *" if q["required"] else ""
    req = " required" if q["required"] else ""
    for f in q["fields"]:
        if f["name"] in ("resume_text",):
            continue
        name, label = html.escape(f["name"]), html.escape(q["label"])
        if f["type"] == "input_text":
            out.append(f'<div class="field"><label for="{name}">{label}{star}</label><input type="text" id="{name}" name="{name}"{req}></div>')
        elif f["type"] == "textarea":
            out.append(f'<div class="field"><label for="{name}">{label}{star}</label><textarea id="{name}" name="{name}"{req}></textarea></div>')
        elif f["type"] == "input_file":
            out.append(f'<div class="field"><label for="{name}">{label}{star}</label><input type="file" id="{name}" name="{name}"{req}></div>')
        elif f["name"] in RANDOM_ID_RADIOS:
            # like Ashby: radio names carry a prefix that changes on every page load
            rname = f"{secrets.token_hex(4)}__{name}"
            opts = "".join(f'<label><input type="radio" name="{rname}" id="{rname}-{i}" value="{html.escape(v["label"])}"{req}> '
                           f'{html.escape(v["label"])}</label>' for i, v in enumerate(f["values"]))
            out.append(f'<fieldset class="field"><legend>{label}{star}</legend>{opts}</fieldset>')
        else:
            opts = "".join(f'<option value="{html.escape(v["label"])}">{html.escape(v["label"])}</option>' for v in f["values"])
            out.append(f'<div class="field"><label for="{name}">{label}{star}</label><select id="{name}" name="{name}"{req}><option value="">Select...</option>{opts}</select></div>')
    return "".join(out)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_form(job_id: str):
    fields = "".join(_field_html(q) for q in questions_for(job_id) + COMPLIANCE[0]["questions"])
    captcha = ('<iframe title="reCAPTCHA" src="about:blank#recaptcha-challenge" width="304" height="78" '
               'style="border:1px solid #ccc"></iframe>') if job_id == "mock-captcha" else ""
    if job_id == "mock-invisible-captcha":  # like Ashby: hidden challenge frame always present
        captcha = ('<div style="visibility:hidden;position:absolute;top:-10000px"><iframe title="recaptcha challenge" '
                   'src="about:blank#recaptcha/enterprise/bframe" width="400" height="580"></iframe></div>')
    return f"""<!doctype html><html><head><title>Mock ATS – Apply</title>
<style>body{{font-family:sans-serif;max-width:720px;margin:2rem auto}}.field{{margin:.8rem 0;display:flex;flex-direction:column}}</style></head>
<body><h1>Data Science Intern (Summer 2027)</h1><p>Mock Analytics Co. – Madison, WI</p>
<form id="application_form" method="post" action="/mock-ats/jobs/{html.escape(job_id)}/submit" enctype="multipart/form-data">
{fields}{captcha}<button type="submit" id="submit_app">Submit Application</button></form></body></html>"""


@router.post("/jobs/{job_id}/submit")
async def submit(job_id: str, request: Request):
    form = await request.form()
    data, files = {}, {}
    for k, v in form.multi_items():
        if hasattr(v, "filename"):
            content = await v.read()
            if content:
                files[k] = {"filename": v.filename, "bytes": len(content), "is_pdf": content[:5] == b"%PDF-"}
        else:
            data[k.split("__")[-1]] = v
    missing = [f["name"] for q in questions_for(job_id) if q["required"] for f in q["fields"][:1]
               if f["name"] not in data and f["name"] not in files]
    if job_id == "mock-captcha":
        return HTMLResponse("<p>CAPTCHA verification failed.</p>", status_code=400)
    if job_id == "mock-verify" and not missing:  # like Greenhouse: an emailed security code first
        token = secrets.token_hex(6)
        PENDING[token] = {"job_id": job_id, "data": data, "files": files}
        return HTMLResponse(f"""<!doctype html><html><body><h1>Confirm you're a human</h1>
<p>A verification code has been sent to your email. Enter the 8-character code to finish your application.</p>
<form method="post" action="/mock-ats/jobs/mock-verify/verify"><input type="hidden" name="token" value="{token}">
<label for="security_code">Security code</label><input id="security_code" name="security_code">
<button type="submit" id="verify_btn">Submit application</button></form></body></html>""")
    if job_id == "mock-silent":  # accepts the post but shows no confirmation
        SUBMISSIONS.append({"job_id": job_id, "confirmation": None, "data": data, "files": files})
        return HTMLResponse("<p>Processing.</p>")
    if missing:
        return HTMLResponse(f"<p>Missing required fields: {', '.join(missing)}</p>", status_code=422)
    conf = "MOCK-" + secrets.token_hex(4).upper()
    rec = {"job_id": job_id, "confirmation": conf, "data": data, "files": files}
    SUBMISSIONS.append(rec)
    d = get_settings().data_dir / "mock_ats"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{conf}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return RedirectResponse(f"/mock-ats/jobs/{job_id}/confirmation?c={conf}", status_code=303)


@router.post("/jobs/mock-verify/verify")
async def verify(request: Request):
    form = await request.form()
    pending = PENDING.pop(str(form.get("token")), None)
    if pending is None or form.get("security_code") != VERIFY_CODE:
        return HTMLResponse("<p>That code is not correct.</p>", status_code=400)
    conf = "MOCK-" + secrets.token_hex(4).upper()
    SUBMISSIONS.append({**pending, "confirmation": conf})
    return RedirectResponse(f"/mock-ats/jobs/mock-verify/confirmation?c={conf}", status_code=303)


@router.get("/jobs/{job_id}/confirmation", response_class=HTMLResponse)
def confirmation(job_id: str, c: str = ""):
    return f"<!doctype html><html><body><h1>Thank you for applying!</h1><p>Your application has been received. Confirmation #{html.escape(c)}</p></body></html>"


ASHBY_UPLOAD_PAGE = """<!doctype html><html><head><title>Mock Ashby – Apply</title></head><body>
<h1>Software Engineering Intern</h1>
<form id="f">
<div class="ashby-application-form-field-entry" data-field-path="_systemfield_name">
  <label for="_systemfield_name" class="ashby-application-form-question-title _required_x">Name</label>
  <input id="_systemfield_name" name="_systemfield_name" required></div>
<div class="ashby-application-form-field-entry" data-field-path="_systemfield_resume">
  <label for="_systemfield_resume" class="ashby-application-form-question-title _required_x">Resume</label>
  <input type="file" id="_systemfield_resume" required
         style="position:absolute;width:1px;height:1px;clip:rect(0,0,0,0);overflow:hidden">
  <div id="item"></div></div>
<button type="submit" id="submit_app">Submit Application</button>
</form>
<script>
const VARIANT = "__VARIANT__";
let uploaded = null;
const inp = document.getElementById('_systemfield_resume'), item = document.getElementById('item');
inp.addEventListener('change', () => {
  const f = inp.files[0]; uploaded = null;
  item.innerHTML = '<p><svg class="loadingSvg" width="12" height="12"><circle cx="6" cy="6" r="5"/></svg><span>' + f.name + '</span></p>';
  if (VARIANT === 'stuck') return;
  setTimeout(() => { uploaded = f.name; item.innerHTML = '<p><span>' + f.name + '</span></p><button type="button" title="Delete file">x</button>'; }, 2500);
});
document.getElementById('f').addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = new FormData();
  body.append('_systemfield_name', document.getElementById('_systemfield_name').value);
  if (uploaded) body.append('resume_uploaded', uploaded);
  const r = await fetch('/mock-ats/ashby/' + VARIANT + '/submit', {method: 'POST', body});
  document.body.innerHTML = r.ok ? '<h1>Thank you for applying!</h1>' : '<p>Resume is required.</p>';
});
</script></body></html>"""


@router.get("/ashby/{variant}", response_class=HTMLResponse)
def ashby_form(variant: str):
    """Ashby-like form: the resume uploads in the background (2.5 s; 'stuck' never
    finishes) and a resume still uploading when Submit is clicked is dropped."""
    return ASHBY_UPLOAD_PAGE.replace("__VARIANT__", "stuck" if variant == "stuck" else "slow")


@router.post("/ashby/{variant}/submit")
async def ashby_submit(variant: str, request: Request):
    form = await request.form()
    data = {k: v for k, v in form.items() if not hasattr(v, "filename")}
    ok = bool(data.get("resume_uploaded"))
    SUBMISSIONS.append({"job_id": f"ashby-{variant}", "confirmation": "ASHBY-OK" if ok else None, "data": data,
                        "files": {"resume": {"filename": data["resume_uploaded"]}} if ok else {}})
    return JSONResponse({"ok": ok}, status_code=200 if ok else 422)


@router.get("/submissions")
def submissions():
    return SUBMISSIONS


def standalone_app() -> FastAPI:
    from hunt.mock_ats.workday import router as workday_router
    app = FastAPI(title="Mock ATS")
    app.include_router(workday_router, prefix="/mock-ats/workday")
    app.include_router(router, prefix="/mock-ats")
    return app
