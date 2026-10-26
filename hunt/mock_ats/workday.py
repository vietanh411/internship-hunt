"""Mock Workday application wizard (tests only). Mirrors the real structure:
job page with an Apply menu (adventureButton / autofillWithResume / applyManually),
a progress bar naming the current step, Workday-style widgets (listbox dropdowns,
long lists that show only a few options until you type, multiselect prompts, date
segments, radio questions), a My Experience step with repeatable Work Experience /
Education entries (Add / Delete), values pre-filled wrongly the way Workday's resume
parsing does, and a final Submit that leads to an "Application Submitted" page."""
from __future__ import annotations

import html
import re

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()
STEPS = ["Create Account/Sign In", "Autofill with Resume", "My Information", "My Experience", "Application Questions", "Review"]
STATE: dict[str, dict] = {}
SUBMISSIONS: list[dict] = []
US_STATES = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida", "Georgia",
             "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland",
             "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire",
             "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania",
             "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
             "West Virginia", "Wisconsin", "Wyoming"]
DEGREES = ["Associates (AA)", "Bachelor of Arts (BA)", "Bachelor of Science (BS)", "Masters of Business Administration (MBA)",
           "Masters of Science (MS)", "Doctorate (PhD)"]  # as written on a real Workday site
FIELDS_OF_STUDY = ["Business", "Computer Science", "Data Science", "Statistics"]

# event delegation, so entries added with "Add" work like the rest of the page
WIDGET_JS = """
<script>
function showVirtual(lb, typed) {  // long Workday lists render only a few options at a time
  if (!lb.dataset.virtual) return; let shown = 0;
  lb.querySelectorAll('[role=option]').forEach(o => {
    const ok = shown < 8 && o.textContent.toLowerCase().startsWith(typed.toLowerCase());
    o.style.display = ok ? '' : 'none'; if (ok) shown++; });
}
function renumber() {
  for (const [list, name] of [['work-list', 'Work Experience'], ['edu-list', 'Education']]) {
    const el = document.getElementById(list); if (!el) continue;
    Array.from(el.children).forEach((g, i) => {
      g.querySelector('h4').textContent = name + ' ' + (i + 1);
      const d = g.querySelector('[data-automation-id=panel-set-delete-button]'); if (d) d.setAttribute('aria-label', 'Delete ' + name + ' ' + (i + 1));
    });
  }
}
let added = 0;
document.addEventListener('click', e => {
  const b = e.target.closest('button[aria-haspopup=listbox]');
  if (b) { e.preventDefault(); const lb = document.getElementById(b.dataset.listbox); lb.style.display = 'block';
           window.openLb = lb; window.typed = ''; showVirtual(lb, ''); return; }
  const o = e.target.closest('[role=listbox] [role=option]');
  if (o) { const lb = o.closest('[role=listbox]'); const btn = document.querySelector(`button[data-listbox="${lb.id}"]`);
           btn.textContent = o.textContent; document.querySelector(`input[name="${btn.dataset.target}"]`).value = o.textContent;
           lb.style.display = 'none'; window.openLb = null; return; }
  const p = e.target.closest('[data-automation-id=promptOption]');
  if (p) { const box = p.closest('[data-automation-id^=formField-]');
           box.querySelector('.chosen').innerHTML = `<div data-automation-id="selectedItem">${p.textContent}<span data-automation-id="DELETE_charm" role="button">x</span></div>`;
           box.querySelector('input[type=hidden]').value = p.textContent; p.parentElement.style.display = 'none'; return; }
  const x = e.target.closest('[data-automation-id=DELETE_charm]');
  if (x) { const box = x.closest('[data-automation-id^=formField-]'); x.closest('[data-automation-id=selectedItem]').remove();
           box.querySelector('input[type=hidden]').value = ''; return; }
  const add = e.target.closest('[data-mock-add]');
  if (add) { e.preventDefault(); const kind = add.dataset.mockAdd; const list = document.getElementById(kind + '-list');
             const uid = 'new' + (++added);
             setTimeout(() => {  // like Workday: the new entry is drawn a moment later
               list.insertAdjacentHTML('beforeend', document.getElementById('tpl-' + kind).innerHTML.replaceAll('__UID__', uid));
               renumber(); }, 1200);
             return; }
  const del = e.target.closest('[data-automation-id=panel-set-delete-button]');
  if (del) { e.preventDefault(); const g = del.closest('[role=group]'); setTimeout(() => { g.remove(); renumber(); }, 1200); return; }
  const nx = e.target.closest('[data-automation-id=bottom-navigation-next-button], [data-automation-id=pageFooterNextButton]');
  if (nx) { e.preventDefault(); nx.closest('form').submit(); }
});
document.addEventListener('input', e => {  // like Workday: two month digits move on to the year
  const t = e.target;
  if (t.matches && t.matches('[data-automation-id=dateSectionMonth-input]') && t.value.length >= 2) {
    const yr = t.parentElement.querySelector('[data-automation-id=dateSectionYear-input]');
    if (yr) { const extra = t.value.slice(2); t.value = t.value.slice(0, 2); yr.focus(); yr.value = extra; }
  }
});
document.addEventListener('focusin', e => {
  const ms = e.target.closest && e.target.closest('[data-automation-id=multiselectInputContainer]');
  if (ms && e.target.dataset.prompts) document.getElementById(e.target.dataset.prompts).style.display = 'block';
});
document.addEventListener('change', e => {
  if (e.target.matches && e.target.matches('[data-mock-resume] input[type=file]') && e.target.files.length) {
    const box = e.target.closest('[data-mock-resume]');
    box.querySelector('.uploaded').innerHTML = `<div data-automation-id="file-upload-item">${e.target.files[0].name}</div>`;
    box.querySelector('input[name=resume_uploaded]').value = e.target.files[0].name;
  }
});
document.addEventListener('keydown', e => {
  const ms = e.target.closest && e.target.closest('[data-automation-id=multiselectInputContainer]');
  if (ms && e.key === 'Enter') { e.preventDefault(); document.getElementById(e.target.dataset.prompts).style.display = 'block'; return; }
  const lb = window.openLb;
  if (lb && lb.dataset.virtual && e.key.length === 1) { window.typed += e.key; showVirtual(lb, window.typed); }
});
</script>"""


def _page(jid: str, n: int, body: str, error: str = "") -> HTMLResponse:
    # "-modal" jobs: like many real sites, sign-in is a box shown on the Autofill step
    active = 2 if n == 1 and jid.endswith("-modal") else n
    bar = "".join(
        f'<li data-automation-id="{"progressBarActiveStep" if i == active else "progressBarInactiveStep"}">'
        f'{"current step" if i == active else "step"} {i} of {len(STEPS)} {html.escape(s)}</li>'
        for i, s in enumerate(STEPS, start=1))
    err = f'<p data-automation-id="errorBanner" style="color:red">{html.escape(error)}</p>' if error else ""
    return HTMLResponse(f"""<!doctype html><html><head><title>Mock Workday</title></head><body>
<div data-automation-id="applyFlowPage"><h2 data-automation-id="jobTitleHeading">Data Analyst Intern (Summer 2027)</h2>
<ol data-automation-id="progressBar">{bar}</ol>{err}
<form method="post" action="/mock-ats/workday/job/{html.escape(jid)}/apply/{n}" enctype="multipart/form-data"><div id="step-root"></div></form>
<template id="step-body">{body}</template>
</div>{WIDGET_JS}
<script>  // like Workday: the step title shows first, its fields a moment later
setTimeout(() => document.getElementById('step-root').replaceWith(document.getElementById('step-body').content.cloneNode(true)), 2500);
</script></body></html>""")


def _req(required: bool) -> str:
    return '<abbr title="required">*</abbr>' if required else ""


def _text(aid: str, label: str, name: str, value: str = "", required: bool = True, field_name: str | None = None) -> str:
    # field_name: Workday gives the boxes in every entry the same name ("jobTitle"); ids differ
    return (f'<div data-automation-id="formField-{aid}"><label for="{name}">{label}{_req(required)}</label>'
            f'<input type="text" id="{name}" name="{field_name or name}" value="{html.escape(value)}"></div>')


def _dropdown(aid: str, label: str, name: str, options: list[str], current: str = "", virtual: bool = False) -> str:
    opts = "".join(f'<li role="option">{html.escape(o)}</li>' for o in options)
    return (f'<div data-automation-id="formField-{aid}"><label for="{name}-btn">{label}{_req(True)}</label>'
            f'<button type="button" id="{name}-btn" aria-haspopup="listbox" data-listbox="{name}-lb" data-target="{name}">'
            f'{html.escape(current) or "Select One"}</button><input type="hidden" name="{name}" value="{html.escape(current)}">'
            f'<ul role="listbox" id="{name}-lb" style="display:none"{" data-virtual=1" if virtual else ""}>{opts}</ul></div>')


def _date(aid: str, label: str, name: str, month: str | None = "", year: str = "", required: bool = True) -> str:
    m = (f'<input data-automation-id="dateSectionMonth-input" name="{name}_m" size="2" value="{month}">'
         if month is not None else "")
    return (f'<div data-automation-id="formField-{aid}"><label>{label}{_req(required)}</label>{m}'
            f'<input data-automation-id="dateSectionYear-input" name="{name}_y" size="4" value="{year}"></div>')


def _work(uid: str, k: int, v: dict) -> str:
    p = f"workExperience-{uid}--"
    chk = " checked" if v.get("current") else ""
    return (f'<div role="group" aria-labelledby="{p}heading"><h4 id="{p}heading">Work Experience {k}</h4>'
            f'<input type="hidden" name="work_uid" value="{uid}">'
            f'<button type="button" data-automation-id="panel-set-delete-button" aria-label="Delete Work Experience {k}">Delete</button>'
            + _text("jobTitle", "Job Title", p + "jobTitle", v.get("title", ""), field_name="jobTitle")
            + _text("companyName", "Company", p + "companyName", v.get("company", ""), field_name="companyName")
            + _text("location", "Location", p + "location", v.get("location", ""), required=False, field_name="location")
            + f'<div data-automation-id="formField-currentlyWorkHere"><input type="checkbox" id="{p}currentlyWorkHere" '
              f'name="currentlyWorkHere" value="{uid}"{chk}><label for="{p}currentlyWorkHere">I currently work here</label></div>'
            + _date("startDate", "From", p + "start", v.get("start_m", ""), v.get("start_y", ""))
            + _date("endDate", "To", p + "end", v.get("end_m", ""), v.get("end_y", ""), required=False)
            + f'<div data-automation-id="formField-roleDescription"><label for="{p}roleDescription">Role Description</label>'
              f'<textarea id="{p}roleDescription" name="{p}roleDescription">{html.escape(v.get("description", ""))}</textarea></div>'
            + "</div>")


def _edu(uid: str, k: int, v: dict) -> str:
    p = f"education-{uid}--"
    chosen = (f'<div data-automation-id="selectedItem">{html.escape(v["field"])}<span data-automation-id="DELETE_charm" role="button">x</span></div>'
              if v.get("field") else "")
    prompts = "".join(f'<div data-automation-id="promptOption">{html.escape(o)}</div>' for o in FIELDS_OF_STUDY)
    return (f'<div role="group" aria-labelledby="{p}heading"><h4 id="{p}heading">Education {k}</h4>'
            f'<input type="hidden" name="edu_uid" value="{uid}">'
            f'<button type="button" data-automation-id="panel-set-delete-button" aria-label="Delete Education {k}">Delete</button>'
            + _text("schoolName", "School or University", p + "schoolName", v.get("school", ""), field_name="schoolName")
            + _dropdown("degree", "Degree", p + "degree", DEGREES, v.get("degree", ""))
            + f'<div data-automation-id="formField-fieldOfStudy"><label for="{p}fieldOfStudy">Field of Study</label>'
              f'<div data-automation-id="multiselectInputContainer"><input id="{p}fieldOfStudy" data-prompts="{p}fos-p" type="text"></div>'
              f'<div class="chosen">{chosen}</div><input type="hidden" name="{p}fieldOfStudy" value="{html.escape(v.get("field", ""))}">'
              f'<div id="{p}fos-p" style="display:none">{prompts}</div></div>'
            + _text("gradeAverage", "Overall Result (GPA)", p + "gpa", v.get("gpa", ""), required=False, field_name="gradeAverage")
            + _date("firstYearAttended", "From", p + "from", None, v.get("from", ""), required=False)
            + _date("lastYearAttended", "To (Actual or Expected)", p + "to", None, v.get("to", ""), required=False)
            + "</div>")


# what Workday's resume parsing typically produces: wrong companies / dates, an invented entry
PARSED_WORK = [
    {"title": "Researcher Developer", "company": "Reddit GitHub", "current": True,
     "description": "Built a research corpus of 300K+ lines Reddit GitHub REST APIs Python"},
    {"title": "Data Science Intern", "company": "SQL EDA ETL", "start_m": "06", "start_y": "2023", "description": "Power BI"},
    {"title": "Python", "company": "Projects", "description": "Skills"},
]
PARSED_EDU = [{"school": "Norman", "degree": "Masters of Science (MS)", "field": "Business"}]


@router.get("/job/{jid}", response_class=HTMLResponse)
def job_page(jid: str):
    return HTMLResponse(f"""<!doctype html><html><body><div data-automation-id="jobPostingPage">
<h2 data-automation-id="jobPostingHeader">Data Analyst Intern (Summer 2027)</h2>
<a data-automation-id="adventureButton" href="#" onclick="document.getElementById('menu').style.display='block';return false">Apply</a>
<div id="menu" style="display:none">
 <a data-automation-id="autofillWithResume" href="/mock-ats/workday/job/{jid}/apply/1">Autofill with Resume</a>
 <a data-automation-id="applyManually" href="/mock-ats/workday/job/{jid}/apply/1">Apply Manually</a>
</div><div data-automation-id="jobPostingDescription">Thank you for your interest in Mock Workday Co.</div></div></body></html>""")


@router.get("/job/{jid}/apply/{n}", response_class=HTMLResponse)
def step(jid: str, n: int, error: str = ""):
    st = STATE.setdefault(jid, {})
    if n == 1:
        body = ('<label for="em">Email Address</label><input data-automation-id="email" id="em" name="email">'
                '<label for="pw">Password</label><input data-automation-id="password" id="pw" type="password" name="password">'
                '<button data-automation-id="signInSubmitButton" type="submit">Sign In</button>')
        if jid.endswith("-modal"):  # the upload area behind the sign-in box
            body += '<input type="file" data-automation-id="file-upload-input-ref" name="resume_behind" style="display:none">'
    elif n == 2:
        body = ('<p>Upload your resume to autofill your application.</p>'
                '<input type="file" data-automation-id="file-upload-input-ref" name="resume">'
                '<button data-automation-id="pageFooterNextButton" type="button">Continue</button>')
    elif n == 3:  # pre-filled the way resume parsing splits "Viet Anh Nguyen"
        body = (_text("legalNameSection_firstName", "First Name", "first_name", value="Viet")
                + _text("legalNameSection_middleName", "Middle Name", "middle_name", value="Anh", required=False)
                + _text("legalNameSection_lastName", "Last Name", "last_name", value=st.get("parsed_last", "Nguyen"))
                + _text("addressSection_addressLine1", "Address Line 1", "address1")
                + _text("addressSection_city", "City", "city")
                + _dropdown("addressSection_countryRegion", "State", "state", US_STATES, virtual=True)
                + _text("addressSection_postalCode", "Postal Code", "postal")
                + _dropdown("phone-device-type", "Phone Device Type", "phone_type", ["Landline", "Mobile"])
                + _text("phone-number", "Phone Number", "phone")
                + _text("phone-extension", "Phone Extension", "extension", value="(555) 010-0100", required=False)
                + '<div data-automation-id="formField-source"><label for="src">How Did You Hear About Us?<abbr title="required">*</abbr></label>'
                  '<div data-automation-id="multiselectInputContainer"><input id="src" data-prompts="src-p" type="text"></div>'
                  '<div class="chosen"></div><input type="hidden" name="source" value="">'
                  '<div id="src-p" style="display:none"><div data-automation-id="promptOption">Job Board</div>'
                  '<div data-automation-id="promptOption">LinkedIn</div><div data-automation-id="promptOption">Company Website</div>'
                  '<div data-automation-id="promptOption">Other</div></div></div>'
                + '<div data-automation-id="formField-candidateIsPreviousWorker"><label>Have you previously worked for Mock Workday Co?'
                  '<abbr title="required">*</abbr></label><input type="radio" id="pw-y" name="prev" value="Yes"><label for="pw-y">Yes</label>'
                  '<input type="radio" id="pw-n" name="prev" value="No"><label for="pw-n">No</label></div>'
                + '<button data-automation-id="bottom-navigation-next-button" type="button">Save and Continue</button>')
    elif n == 4:
        work = "".join(_work(f"p{i}", i, v) for i, v in enumerate(PARSED_WORK, start=1))
        edu = "".join(_edu(f"p{i}", i, v) for i, v in enumerate(PARSED_EDU, start=1))
        body = (f'<div data-automation-id="workExperienceSection"><h3>Work Experience</h3><div id="work-list">{work}</div>'
                '<button type="button" data-mock-add="work" aria-label="Add Work Experience">Add Another</button></div>'
                f'<div data-automation-id="educationSection"><h3>Education</h3><div id="edu-list">{edu}</div>'
                '<button type="button" data-mock-add="edu">Add Another</button></div>'
                f'<template id="tpl-work">{_work("__UID__", 0, {})}</template><template id="tpl-edu">{_edu("__UID__", 0, {})}</template>'
                # like Workday: a labelled section, a file input with no id / name, uploaded in the background
                '<div role="group" aria-labelledby="Resume/CV-section" data-mock-resume="1"><h3 id="Resume/CV-section">Resume/CV</h3>'
                '<p>Upload a file (5MB max)<abbr title="required">*</abbr></p><input type="file">'
                '<div class="uploaded"></div><input type="hidden" name="resume_uploaded" value=""></div>'
                '<button data-automation-id="bottom-navigation-next-button" type="button">Save and Continue</button>')
    elif n == 5:
        body = (_dropdown("q-auth", "Are you legally authorized to work in the United States?", "authorized", ["Yes", "No"])
                + _dropdown("q-sponsor", "Will you now or in the future require sponsorship for employment visa status?", "sponsorship", ["Yes", "No"])
                + '<div data-automation-id="formField-gradDate"><label>Expected graduation date<abbr title="required">*</abbr></label>'
                  '<input data-automation-id="dateSectionMonth-input" name="grad_m" size="2">'
                  '<input data-automation-id="dateSectionYear-input" name="grad_y" size="4"></div>'
                + '<button data-automation-id="bottom-navigation-next-button" type="button">Save and Continue</button>')
    elif n == 6:
        items = "".join(f"<li>{html.escape(k)}: {html.escape(str(v))}</li>" for k, v in st.items() if k != "resume_bytes")
        body = (f"<ul>{items}</ul>"
                '<button data-automation-id="bottom-navigation-next-button" type="button">Submit</button>')
    else:
        return HTMLResponse("not found", status_code=404)
    return _page(jid, n, body, error)


REQUIRED = {3: ["first_name", "last_name", "address1", "city", "state", "postal", "phone_type", "phone", "source", "prev"],
            5: ["authorized", "sponsorship", "grad_m", "grad_y"]}
ENTRY_KEY = re.compile(r"^(workExperience|education)-([^-]+)--(.+)$")


def _entries(form) -> tuple[list[dict], list[dict]]:
    """Work / education entries in page order, as the form submitted them. Boxes that
    share a name across entries ("jobTitle") come back in page order, one per entry."""
    found: dict[tuple[str, str], dict] = {}
    for k, v in form.multi_items():
        m = ENTRY_KEY.match(k)
        if m and not hasattr(v, "filename"):
            found.setdefault((m.group(1), m.group(2)), {})[m.group(3)] = v
    shared = {n: form.getlist(n) for n in ("jobTitle", "companyName", "location", "schoolName", "gradeAverage")}
    current = set(form.getlist("currentlyWorkHere"))
    work = []
    for i, uid in enumerate(form.getlist("work_uid")):
        e = found.get(("workExperience", uid), {})
        work.append({"title": shared["jobTitle"][i], "company": shared["companyName"][i], "location": shared["location"][i],
                     "current": uid in current, "start": f"{e.get('start_m', '')}/{e.get('start_y', '')}",
                     "end": f"{e.get('end_m', '')}/{e.get('end_y', '')}", "description": e.get("roleDescription", "")})
    edu = []
    for i, uid in enumerate(form.getlist("edu_uid")):
        e = found.get(("education", uid), {})
        edu.append({"school": shared["schoolName"][i], "degree": e.get("degree", ""), "field": e.get("fieldOfStudy", ""),
                    "gpa": shared["gradeAverage"][i], "from": e.get("from_y", ""), "to": e.get("to_y", "")})
    return work, edu


@router.post("/job/{jid}/apply/{n}")
async def post_step(jid: str, n: int, request: Request):
    st = STATE.setdefault(jid, {})
    form = await request.form()
    missing: list[str] = []
    if n == 2:
        f = form.get("resume")
        content = await f.read() if hasattr(f, "read") else b""
        st["resume_is_pdf"] = content[:5] == b"%PDF-"
        st["resume_name"] = getattr(f, "filename", "")
    elif n == 4:
        st["work"], st["edu"] = _entries(form)
        missing = [f"work {i}" for i, w in enumerate(st["work"], 1) if not (w["title"] and w["company"] and w["start"] != "/")]
        missing += [f"education {i}" for i, e in enumerate(st["edu"], 1) if not (e["school"] and e["degree"])]
        st["resume_cv"] = form.get("resume_uploaded") or ""
        missing += [] if st["resume_cv"] else ["Resume/CV"]
    else:
        for k, v in form.multi_items():
            if not hasattr(v, "filename") and k != "password":
                st[k] = v
    missing += [k for k in REQUIRED.get(n, []) if not st.get(k)]
    if missing:
        return RedirectResponse(f"/mock-ats/workday/job/{jid}/apply/{n}?error=Missing:+{','.join(missing)}", status_code=303)
    if n == 6:
        SUBMISSIONS.append({"job": jid, **st})
        return RedirectResponse(f"/mock-ats/workday/job/{jid}/done", status_code=303)
    return RedirectResponse(f"/mock-ats/workday/job/{jid}/apply/{n + 1}", status_code=303)


@router.get("/job/{jid}/done", response_class=HTMLResponse)
def done(jid: str):
    return HTMLResponse("<!doctype html><html><body><h2>Application Submitted</h2>"
                        "<p>Your application has been submitted. You can view it in your candidate home.</p></body></html>")
