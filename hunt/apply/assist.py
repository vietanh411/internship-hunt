"""Assisted finish: open a visible browser on this PC with the application already
filled in. The applicant reviews it, clicks Submit, and completes any human check
(an emailed verification code, a CAPTCHA). Nothing is submitted by this module:
it only records the outcome once the employer's confirmation page appears."""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from datetime import datetime
from typing import Callable

from hunt.apply import adapters
from hunt.apply.browser import (
    SUBMIT_SELECTORS,
    collect_fields,  # noqa: F401  (re-exported for tests)
    confirmation_since,
    fill_all,
    needs_email_verification,
    page_snapshot,
    wait_for_form,
)
from hunt.artifacts import save_artifact
from hunt.config import get_settings
from hunt.db import new_session, utcnow
from hunt.models import Job, JobStatus, POST_SUBMISSION
from hunt.workflow import audit, notify, set_status

log = logging.getLogger(__name__)

WATCH_MINUTES = 20

_lock = threading.Lock()
ACTIVE = ("starting", "filling", "waiting")
_state: dict = {"job_id": None, "company": None, "title": None, "state": "idle", "message": "",
                "started_at": None, "finished_at": None, "filled": 0, "left_for_you": [], "queue": None,
                "code": None}
_cancel = threading.Event()  # stop the session (and the Finish all queue)
_skip = threading.Event()    # Finish all: move on to the next application

BANNER_JS = r"""
({msg, queue}) => {
  const id = 'summer2027-hunt-banner';
  let b = document.getElementById(id);
  if (!b) {
    b = document.createElement('div'); b.id = id;
    b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;background:#4338ca;color:#fff;' +
      'font:600 14px/1.4 system-ui,sans-serif;padding:10px 16px;box-shadow:0 2px 8px rgba(0,0,0,.3);' +
      'display:flex;align-items:center;gap:12px';
    document.body.appendChild(b);
    document.body.style.marginTop = '56px';
  }
  b.textContent = '';
  const text = document.createElement('span'); text.style.flex = '1'; text.textContent = msg; b.appendChild(text);
  if (queue) {
    const prog = document.createElement('span'); prog.style.cssText = 'opacity:.85;white-space:nowrap';
    prog.textContent = `Application ${queue.position} of ${queue.total} · ${queue.submitted} submitted`;
    b.appendChild(prog);
    for (const [label, action] of [["Skip (don't apply)", 'skip'], ['Stop', 'stop']]) {
      const btn = document.createElement('button'); btn.type = 'button'; btn.textContent = label;
      btn.setAttribute('data-hunt-action', action);
      btn.style.cssText = 'padding:3px 10px;border-radius:6px;border:1px solid rgba(255,255,255,.7);background:transparent;' +
        'color:#fff;font:inherit;cursor:pointer;white-space:nowrap';
      btn.addEventListener('click', (e) => {
        e.preventDefault(); e.stopPropagation();
        if (window.summer2027HuntAction) window.summer2027HuntAction(action);
        btn.textContent = action === 'skip' ? 'Skipping…' : 'Stopping…';
      });
      b.appendChild(btn);
    }
  }
}
"""


class AssistBusy(Exception):
    pass


def status() -> dict:
    with _lock:
        out = dict(_state)
    for k in ("started_at", "finished_at"):
        if isinstance(out.get(k), datetime):
            out[k] = out[k].isoformat() + "Z"
    return out


def _set(**kw) -> None:
    with _lock:
        changed = kw.get("message") and kw.get("message") != _state.get("message")
        _state.update(kw)
    if changed:
        _rec_log(f"[{_state.get('company')}] {kw.get('state') or ''} {kw['message']}")


def cancel() -> bool:
    if status()["state"] in ACTIVE:
        _cancel.set()
        return True
    return False


def check_startable(job: Job) -> None:
    if job.status in {s.value for s in POST_SUBMISSION}:
        raise ValueError(f"Already {job.status}")
    if job.eligibility == "ineligible":
        raise ValueError("This job's work-authorization requirements exclude you")
    if adapters.platform_of(job) not in adapters.ASSIST_PLATFORMS:
        raise ValueError(adapters.manual_reason(adapters.platform_of(job)) + " Use the Apply link.")
    if not job.resume_versions:
        raise ValueError("No tailored resume yet")


def start(job_id: int, headless: bool = False, on_ready: Callable | None = None, wait: bool = False,
          hooks: dict | None = None) -> dict:
    """Start a session for one job in a background thread. `on_ready(page)` is a test
    hook that plays the applicant's part; production passes nothing."""
    return _launch([job_id], False, headless, on_ready, hooks, wait)


def start_queue(job_ids: list[int] | None = None, headless: bool = False, on_ready: Callable | None = None,
                wait: bool = False, hooks: dict | None = None, platform: str | None = None) -> dict:
    """Finish all: one browser window works through every prepared application in turn.
    You review and submit each one (or Skip it); the next opens once the employer's
    confirmation page appears. Closing the window or Stop ends the queue."""
    if job_ids is None:
        from hunt.pipeline.stages import finish_queue_jobs
        from hunt.settings_store import get_automation
        s = new_session()
        try:
            assisted = set(get_automation(s).get("assisted_only_platforms") or [])
            job_ids = [j.id for j in finish_queue_jobs(s, assisted, include_test=get_settings().enable_mock_ats)
                       if platform is None or (j.application and j.application.platform == platform)]
        finally:
            s.close()
    if not job_ids:
        raise ValueError("Nothing is waiting for Finish application")
    return _launch(list(job_ids), True, headless, on_ready, hooks, wait)


def skip() -> bool:
    """Finish all: leave the current application for later and open the next one."""
    st = status()
    if st["state"] in ACTIVE and st.get("queue"):
        _skip.set()
        return True
    return False


def _job_label(job_id: int) -> tuple[str, str] | None:
    """(company, title) if the job can be finished now, else None."""
    s = new_session()
    try:
        job = s.get(Job, job_id)
        if job is None:
            raise ValueError("Job not found")
        check_startable(job)
        return job.company, job.title.strip()
    finally:
        s.close()


def _launch(job_ids: list[int], queue: bool, headless: bool, on_ready, hooks, wait: bool) -> dict:
    with _lock:
        if _state["state"] in ACTIVE:
            raise AssistBusy(f"A session is already open for {_state['company']}")
        first = None
        for jid in job_ids:
            try:
                first = (jid, *_job_label(jid))
                break
            except ValueError:
                if not queue:
                    raise
        if first is None:
            raise ValueError("None of these applications can be finished now")
        _cancel.clear()
        _skip.clear()
        _state.update(job_id=first[0], company=first[1], title=first[2], state="starting", filled=0, left_for_you=[], code=None,
                      message="Opening a browser window…", started_at=utcnow(), finished_at=None,
                      queue={"total": len(job_ids), "position": 0, "submitted": 0, "skipped": 0} if queue else None)
    t = threading.Thread(target=_run_all, args=(job_ids, queue, headless, on_ready, hooks), name="assist", daemon=True)
    t.start()
    if wait:
        t.join()
    return status()


def _queue_update(**kw) -> None:
    with _lock:
        if _state.get("queue") is not None:
            _state["queue"] = {**_state["queue"], **kw}


REC: dict = {"dir": None, "n": 0}  # set while a recorded session runs


def _rec_log(line: str) -> None:
    d = REC.get("dir")
    if d:
        try:
            with open(d / "events.log", "a", encoding="utf-8") as fh:
                fh.write(f"{utcnow():%H:%M:%S} {line}\n")
        except OSError:
            pass


def _rec_shot(page, every: int = 3) -> None:
    """While recording: a viewport screenshot every few ticks (~4-5 s)."""
    d = REC.get("dir")
    if not d:
        return
    REC["n"] += 1
    if REC["n"] % every:
        return
    try:
        (d / "shots").mkdir(exist_ok=True)
        page.screenshot(path=str(d / "shots" / f"{REC['n']:04d}.png"))
    except Exception:  # noqa: BLE001
        pass


def _run_all(job_ids: list[int], queue: bool, headless: bool, on_ready, hooks) -> None:
    from playwright.sync_api import sync_playwright

    final, msg = "error", ""
    record = bool((hooks or {}).get("record"))
    try:
        with sync_playwright() as pw:
            # A persistent profile keeps you signed in to each employer's site between
            # sessions (and lets the browser's own password manager remember logins).
            profile_dir = get_settings().data_dir / "browser_profile"
            profile_dir.mkdir(parents=True, exist_ok=True)
            # headed: the page follows the window's size (a fixed viewport put the bottom of
            # long forms, with the Submit button, behind the taskbar on smaller screens)
            size = {"no_viewport": True, "args": ["--start-maximized"]} if not headless else {"viewport": {"width": 1280, "height": 1800}}
            if record:  # "record it so you see what goes wrong"
                REC.update(dir=get_settings().data_dir / "debug" / "recordings" / f"{utcnow():%Y%m%d-%H%M%S}", n=0)
                REC["dir"].mkdir(parents=True, exist_ok=True)
                size["record_video_dir"] = str(REC["dir"])
            ctx_b = pw.chromium.launch_persistent_context(str(profile_dir), headless=headless, locale="en-US", **size)
            if record:
                ctx_b.tracing.start(screenshots=True, snapshots=True)
                _rec_log(f"recording started: {len(job_ids)} application(s)")
            # the banner's Skip / Stop buttons (Finish all)
            ctx_b.expose_binding("summer2027HuntAction",
                                 lambda source, action: (_skip if action == "skip" else _cancel).set())
            page = ctx_b.pages[0] if ctx_b.pages else ctx_b.new_page()
            page.set_default_timeout(15000)
            submitted = skipped = 0
            for i, jid in enumerate(job_ids, start=1):
                if _cancel.is_set():
                    final, msg = "cancelled", "Stopped."
                    break
                if queue:
                    try:
                        label = _job_label(jid)
                    except ValueError:
                        label = None  # finished or changed since the queue was built
                    if label is None:
                        _queue_update(position=i)
                        continue
                    _skip.clear()
                    _set(job_id=jid, company=label[0], title=label[1], state="starting", filled=0, left_for_you=[],
                         message=f"Opening {label[0]}…", code=None)
                    _queue_update(position=i)
                final, msg = _run_one(page, jid, on_ready, hooks)
                if final == "confirmed":
                    submitted += 1
                elif final == "skipped":
                    skipped += 1
                _queue_update(submitted=submitted, skipped=skipped)
                if not queue:
                    break
                if final in ("closed", "cancelled") or not _alive(page):
                    break  # you closed the window or pressed Stop
                if final == "confirmed" and i < len(job_ids):
                    _banner(page, f"Submitted – recorded ({submitted} this session). Opening the next application…")
                    page.wait_for_timeout(2500)
            else:
                if queue:
                    final = "done"
            if queue:
                left = len(job_ids) - (status()["queue"] or {}).get("position", 0)
                msg = (f"Finish all {'ended' if final == 'done' else 'stopped'}: {submitted} submitted, "
                       f"{skipped} skipped" + (f", {left} not opened" if left > 0 else "") + ".")
                if final == "done":
                    _banner(page, msg)
                    page.wait_for_timeout(1500)
            if record:
                _rec_log(f"session ended: {final} {msg}")
                try:
                    ctx_b.tracing.stop(path=str(REC["dir"] / "trace.zip"))
                except Exception as e:  # noqa: BLE001
                    _rec_log(f"trace not saved: {e}")
            try:
                ctx_b.close()
            except Exception:
                pass
            REC["dir"] = None
    except Exception as e:  # noqa: BLE001
        log.exception("assisted session failed")
        _rec_log(f"session failed: {type(e).__name__}: {e}")
        REC["dir"] = None
        final, msg = "error", f"Could not open the browser window: {type(e).__name__}: {e}"
    _set(state=final, message=msg, finished_at=utcnow())


def _run_one(page, job_id: int, on_ready: Callable | None, hooks: dict | None) -> tuple[str, str]:
    """Fill one application in the open window and record what happened.
    Returns (outcome, message)."""
    from hunt.apply.engine import _ctx, _resolve_files, ensure_application, prepare_application
    from hunt.http import PoliteClient
    from hunt.llm import get_llm
    from hunt.matching import build_applicant
    from hunt.models import Artifact
    from hunt.profile_store import get_master_resume, get_profile
    from hunt.settings_store import get_automation

    session = new_session()
    outcome, confirmation, shot = "closed", None, None
    job = session.get(Job, job_id)
    prev_status, prev_next = job.status, job.next_action
    claimed = False
    try:
        profile, (mv, master), settings = get_profile(session), get_master_resume(session), get_automation(session)
        skills = build_applicant(master, profile).skills
        app = ensure_application(session, job)
        if not app.plan:
            cl = session.get(Artifact, app.cover_letter_artifact_id) if app.cover_letter_artifact_id else None
            prepare_application(session, job, profile=profile, master=master, settings=settings, applicant_skills=skills,
                                client=PoliteClient(), llm=get_llm(), cover_letter_artifact=cl)
        files = _resolve_files(session, job)
        if "resume" not in files:
            raise RuntimeError("Tailored resume file is missing; regenerate it first")
        # claim the job so the scheduled run never submits it at the same time
        app.attempt_token, app.last_attempt_at = uuid.uuid4().hex, utcnow()
        set_status(session, job, JobStatus.APPLYING, "Assisted finish: you are completing this application",
                   actor="user", next_action="Finish the application in the browser window")
        session.commit()
        claimed = True
        ctx = _ctx(session, job, profile, master, settings, skills, get_llm())
        if adapters.platform_of(job) == "workday":
            outcome, confirmation, shot = _drive_workday(page, job, app, ctx, files, hooks or {})
        else:
            outcome, confirmation, shot = _drive_simple(page, job, app, ctx, files, on_ready, hooks or {})
    except Exception as e:  # noqa: BLE001
        if type(e).__name__ == "TargetClosedError":  # you closed the window while the form was loading
            outcome = "closed"
        else:
            log.exception("assisted session failed for job %s", job_id)
            outcome = "error"
            _set(message=f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------ record outcome
    try:
        session.rollback()
        job = session.get(Job, job_id)
        app = job.application
        if app is not None:
            app.attempt_token = None
        if outcome == "confirmed":
            app.date_applied = utcnow()
            app.confirmation_text, app.confirmation_source = confirmation, "page (you submitted)"
            if shot:
                ev = save_artifact(session, job, "evidence", "submission_assisted.png", shot, "image/png")
                app.evidence_artifact_id = ev.id
            set_status(session, job, JobStatus.SUBMITTED, "Confirmation observed (assisted finish)", actor="user",
                       next_action="Wait for response; follow up in ~2 weeks")
            audit(session, "user", "assisted_submit", "job", job.id)
            notify(session, "submitted", f"Submitted: {job.company} – {job.title.strip()}", confirmation, job.id)
            msg = "Submitted – confirmation recorded."
        elif outcome == "expired" and (claimed or job.status == JobStatus.APPLYING.value):
            set_status(session, job, JobStatus.EXPIRED, "Employer page says the posting no longer exists (Finish all)",
                       actor="system", next_action="")
            job.verified_active, job.verified_at = False, utcnow()
            msg = "This posting has been taken down; removed from your queue."
        elif outcome == "skipped" and (claimed or job.status == JobStatus.APPLYING.value):
            set_status(session, job, JobStatus.SKIPPED, "Skipped by you in Finish all", actor="user",
                       next_action="Skipped – won't be offered again. To apply after all, use Change status → Ready to Apply.")
            audit(session, "user", "assisted_skip", "job", job.id)
            msg = "Skipped – this one won't be offered again."
        elif claimed or job.status == JobStatus.APPLYING.value:
            restore = prev_status if prev_status != JobStatus.APPLYING.value else JobStatus.BLOCKED.value
            reason = {"closed": "Browser window closed before a confirmation page appeared",
                      "timeout": f"No confirmation within {WATCH_MINUTES} minutes",
                      "cancelled": "Assisted session cancelled",
                      "error": "Assisted session failed"}.get(outcome, outcome)
            set_status(session, job, restore, reason, actor="user",
                       next_action=(prev_next if outcome == "cancelled" else
                                    "If you did submit, use Change status → Submitted with the confirmation details; otherwise try Finish application again."))
            msg = reason + ("" if outcome != "error" else f": {status()['message']}")
        else:
            msg = f"Could not open this application: {status()['message']}"
        session.commit()
    except Exception:  # noqa: BLE001
        log.exception("could not record assisted outcome")
        session.rollback()
        msg = "Could not record the outcome; check the job page."
    finally:
        session.close()
    _set(message=msg)
    return outcome, msg


# ===================================================================== drivers

def _alive(page) -> bool:
    try:
        return not page.is_closed() and bool(page.evaluate("1"))
    except Exception:
        return False


def _watch(page, baseline: tuple[str, str], on_tick=None) -> tuple[str, str | None, bytes | None]:
    """Wait for the employer's confirmation page; returns (outcome, text, screenshot)."""
    deadline = time.time() + WATCH_MINUTES * 60
    while time.time() < deadline:
        if _cancel.is_set():
            return "cancelled", None, None
        if _skip.is_set():
            return "skipped", None, None
        if not _alive(page):
            return "closed", None, None
        try:
            conf = confirmation_since(page, baseline[1], baseline[0])
        except Exception:
            return "closed", None, None
        if conf:
            try:
                shot = page.screenshot(full_page=True)
            except Exception:
                shot = None
            return "confirmed", conf, shot
        if on_tick is not None:
            try:
                on_tick()
            except Exception as e:  # noqa: BLE001
                log.exception("assist tick failed")
                _rec_log(f"tick failed: {type(e).__name__}: {str(e)[:300]}")
        _rec_shot(page)
        try:
            page.wait_for_timeout(1500)
        except Exception:
            return "closed", None, None
    return "timeout", None, None


def _banner(page, msg: str) -> None:
    try:
        page.evaluate(BANNER_JS, {"msg": msg, "queue": status().get("queue")})
    except Exception:
        pass


CODE_POLL_SECONDS = 6
CODE_CLOCK_SKEW = 20  # seconds of tolerance between this PC's clock and the email's Date header


def _code_helper(page, job, hooks: dict):
    """When the site asks for an emailed code, find it in your inbox and show it in the
    top bar and on the dashboard. You type it in: the system never fills the code box.
    Only codes sent after this application's form was opened in the window count (an
    earlier attempt's code is no longer valid), and a newer code replaces the shown one."""
    from datetime import timedelta

    from hunt.notify import email_monitor
    opened = utcnow() - timedelta(seconds=CODE_CLOCK_SKEW)
    st = {"seen": False, "last_poll": 0.0, "code": None, "received": None, "hooked": False}

    def tick() -> None:
        if not email_monitor.imap_configured():
            return
        if not st["seen"]:
            if not needs_email_verification(page):
                return
            st["seen"] = True
            _banner(page, f"{job.company} emailed you a code. Looking for the new one in your inbox…")
            _set(message="The site emailed you a code; looking for the new one in your inbox…")
        if time.time() - st["last_poll"] < CODE_POLL_SECONDS:
            return
        st["last_poll"] = time.time()
        try:
            found = email_monitor.find_verification_code(opened, job.company)
        except Exception as e:  # noqa: BLE001  (inbox trouble must not end the session)
            log.warning("verification code lookup failed: %s", e)
            return
        if not found:
            return
        code, subject, received = found[0], found[1], (found[2] if len(found) > 2 else None)
        if code == st["code"] or (st["received"] and received and received <= st["received"]):
            return  # nothing newer
        st["code"], st["received"] = code, received
        _banner(page, f"Your code: {code}  —  type it into the code box, then submit. (From: {subject[:80]})")
        _set(code=code, message=f"Your code is {code}: type it into the code box in the browser window, then submit.")
        if hooks.get("on_code") and not st["hooked"]:
            st["hooked"] = True
            hooks["on_code"](page, code)

    return tick


def _drive_simple(page, job, app, ctx, files, on_ready, hooks: dict | None = None):
    """Single-page forms (Greenhouse, Lever, Ashby): fill everything, you submit."""
    from hunt.apply.engine import live_replanner, plan_live_answers
    _set(state="filling", message="Filling in the form…")
    page.goto(adapters.form_url(job), wait_until="domcontentloaded")
    wait_for_form(page)
    if _posting_gone(page):
        return "expired", None, None
    answers, selectors = plan_live_answers(page, app, ctx, files)
    filled, unfilled = fill_all(page, answers, files, selectors, live_replanner(page, app, ctx, files))
    left = [a.label for a in answers if a.required and (a.kind == "human" or a.label in unfilled)]
    _banner(page, "Filled by your Summer 2027 Hunt. Review everything"
            + (f", complete {len(left)} field(s) left for you" if left else "")
            + ", then click Submit. If the site asks for an emailed code or a CAPTCHA, complete it. "
            + "This window records the confirmation automatically.")
    try:
        for sel in SUBMIT_SELECTORS:
            loc = page.locator(sel)
            if loc.count() and loc.first.is_visible():
                loc.first.scroll_into_view_if_needed()
                break
    except Exception:
        pass
    baseline = page_snapshot(page)
    _set(state="waiting", filled=len(filled), left_for_you=left,
         message=("Waiting for you to review and click Submit in the browser window"
                  + (f" ({len(left)} field(s) need you)" if left else "") + "."))
    if on_ready is not None:
        on_ready(page)
    return _watch(page, baseline, on_tick=_code_helper(page, job, hooks or {}))


WD_NEXT = ["[data-automation-id='bottom-navigation-next-button']", "[data-automation-id='pageFooterNextButton']",
           "button:has-text('Save and Continue')", "button:has-text('Continue')", "button:has-text('Next')"]
WD_HIGHLIGHT_JS = r"""
(sels) => { for (const s of sels) { try { const e = document.querySelector(s); if (e) { e.style.outline = '3px solid #f59e0b';
  e.style.outlineOffset = '2px'; } } catch (_) {} } }
"""


def _wd_step(page) -> str | None:
    try:
        loc = page.locator("[data-automation-id='progressBarActiveStep']")
        if not loc.count():
            return None
        t = loc.first.inner_text(timeout=1500)
    except Exception:
        return None
    import re as _re
    m = _re.search(r"step \d+ of \d+\s*(.*)$", " ".join(t.split()), _re.I)
    return (m.group(1) if m else t).strip() or None


def _wd_click_next(page) -> bool:
    for sel in WD_NEXT:
        loc = page.locator(sel)
        try:
            if loc.count() and loc.first.is_visible() and loc.first.is_enabled():
                txt = (loc.first.inner_text(timeout=1000) or "").strip().lower()
                if txt.startswith("submit"):
                    return False  # never press the final Submit
                loc.first.click()
                return True
        except Exception:
            continue
    return False


GONE_RE = re.compile(r"page you are looking for doesn.?t exist|job (posting )?(is )?no longer available|"
                     r"this job (has been|is) (closed|filled|removed)|position (has been|is) (closed|filled)|"
                     r"no longer accepting applications", re.I)


def _posting_gone(page) -> bool:
    """The employer took the posting down (Workday: 'The page you are looking for doesn't exist.')."""
    try:
        return bool(GONE_RE.search(page.inner_text("body", timeout=3000)[:4000]))
    except Exception:  # noqa: BLE001
        return False


def _wd_should_fill(f, a) -> bool:
    """Empty fields get your answer. A value already there (Workday's reading of the
    resume, or an old account profile) is replaced only when it contradicts a verified answer."""
    from hunt.apply.browser import same_option
    if not f.current:
        return True
    if a.kind not in ("fixed", "sensitive") or a.value in (None, ""):
        return False
    if f.type == "checkbox":
        return (f.current == "checked") != (str(a.value).lower() in ("yes", "true", "1", "on", "checked"))
    if f.type == "wd_date":
        cur, val = [int(x) for x in re.findall(r"\d+", f.current)], [int(x) for x in re.findall(r"\d+", str(a.value))]
        return (cur[-1:] != val[-1:]) if len(cur) == 1 else cur != val
    # "Masters of Science (MS)" already there = your "Master of Science": leave it
    return not any(same_option(f.current, str(c)) for c in [a.value, *a.fallbacks])


def _wd_clear_needed(f, ctx) -> bool:
    """A middle name Workday made up from 'Viet Anh' (your first name is two words), or a
    phone number put in the phone-extension box."""
    from hunt.apply.answers import norm
    lab = norm(f.label)
    if re.search(r"\bext(ension)?\b", lab):
        return len(re.sub(r"\D", "", f.current)) >= 7
    return bool(re.match(r"^middle (name|initial)", lab)) and not (ctx.profile.get("identity") or {}).get("middle_name")


WD_RESUME_JS = r"""
() => {
  const box = document.querySelector('[aria-labelledby="Resume/CV-section"], [aria-labelledby="Resume-section"], [data-automation-id="resumeSection"]');
  const inputs = Array.from((box || document).querySelectorAll('input[type=file]'));
  if (!inputs.length || (!box && inputs.length > 1)) return {has: false};
  const area = box || inputs[0].closest('[data-automation-id^="formField-"], [role="group"]') || document.body;
  const items = area.querySelectorAll('[data-automation-id^="file-upload-item"], [data-automation-id="file-upload-successful"]');
  return {has: true, attached: items.length > 0 || /successfully uploaded|\.pdf\b|\.docx?\b/i.test(area.innerText || '')};
}
"""


def _wd_attach_resume(page, files) -> bool:
    """Workday's Resume/CV upload box has no name or label the form reader can use:
    attach the tailored resume there when no file is attached yet."""
    if "resume" not in files:
        return False
    try:
        st = page.evaluate(WD_RESUME_JS)
        if not st.get("has") or st.get("attached"):
            return False
        sel = ('[aria-labelledby="Resume/CV-section"] input[type=file], [aria-labelledby="Resume-section"] input[type=file], '
               '[data-automation-id="resumeSection"] input[type=file], input[type=file]')
        page.locator(sel).first.set_input_files(str(files["resume"]))
        page.wait_for_timeout(2500)  # Workday uploads it in the background
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("could not attach the resume on this Workday step: %s", e)
        return False


# Workday "Work Experience" / "Education" sections: is it on the page, add an entry, delete entry n
WD_ENTRY_JS = r"""
([kind, action, n]) => {
  const txt = e => (e ? (e.innerText || e.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const name = kind === 'work' ? 'work experience' : 'education';
  const HEADS = 'h1, h2, h3, h4, h5, [role="heading"], legend';
  const titles = Array.from(document.querySelectorAll(HEADS)).filter(h => txt(h).toLowerCase() === name);
  const addRx = /^add( another)?$/i;
  const labelled = Array.from(document.querySelectorAll('button[aria-label]'))
    .filter(b => new RegExp('^add (another )?' + name + '$', 'i').test(b.getAttribute('aria-label')));
  if (action === 'has') return titles.length > 0 || labelled.length > 0;
  if (action === 'count') {  // entries shown: "Work Experience 2" headings, or Workday's per-entry input ids
    const heads = new Set(Array.from(document.querySelectorAll(HEADS)).map(txt).filter(t => new RegExp('^' + name + ' \\d+$', 'i').test(t)));
    const pre = kind === 'work' ? 'workExperience' : 'education';
    const ids = new Set(Array.from(document.querySelectorAll(`[id^="${pre}-"]`)).map(e => (e.id.match(/^(?:workExperience|education)-(\d+)--/) || [])[1]).filter(Boolean));
    const boxes = Array.from(document.querySelectorAll(`[data-automation-id^="${pre}-"]`)).filter(e => /-\d+$/.test(e.getAttribute('data-automation-id'))).length;
    return Math.max(heads.size, ids.size, boxes);
  }
  if (action === 'add') {
    if (labelled.length) { labelled[0].click(); return true; }
    for (const h of titles) {
      for (let a = h.parentElement, d = 0; a && d < 6; a = a.parentElement, d++) {
        const bs = Array.from(a.querySelectorAll('button')).filter(b => addRx.test(txt(b)));
        if (bs.length) { bs[bs.length - 1].click(); return true; }
      }
    }
    return false;
  }
  const byLabel = Array.from(document.querySelectorAll('button[aria-label]'))
    .find(b => new RegExp('^(delete|remove) ' + name + ' ' + n + '$', 'i').test(b.getAttribute('aria-label')));
  if (byLabel) { byLabel.click(); return true; }
  const head = new RegExp('^' + name + ' ' + n + '$', 'i');
  const boxes = Array.from(document.querySelectorAll(HEADS)).filter(h => head.test(txt(h))).map(h => h.parentElement)
    .concat(Array.from(document.querySelectorAll(`[data-automation-id="${kind === 'work' ? 'workExperience' : 'education'}-${n}"]`)));
  for (let box of boxes) {
    for (let d = 0; box && d < 5; box = box.parentElement, d++) {
      const del = box.querySelector('[data-automation-id="panel-set-delete-button"], button[aria-label^="Delete"], button[aria-label^="Remove"]')
        || Array.from(box.querySelectorAll('button')).find(b => /^(delete|remove)$/i.test(txt(b)));
      if (del) { del.click(); return true; }
    }
  }
  return false;
}
"""


def _wd_sync_entries(page, ctx) -> None:
    """Make the page show one Work Experience / Education entry per resume entry
    (adding missing ones, deleting extra ones Workday invented). Clicks only in one
    direction, at most the difference, and waits for each click to show on the page:
    Workday draws a new entry slowly, and counting too early made it add and delete
    entries back and forth."""
    for kind, key in (("work", "experience"), ("edu", "education")):
        try:
            if not page.evaluate(WD_ENTRY_JS, [kind, "has", 0]):
                continue
            want = len((ctx.master or {}).get(key) or [])
            start = page.evaluate(WD_ENTRY_JS, [kind, "count", 0])
            action = "add" if start < want else "delete"
            for _ in range(abs(want - start)):
                before = page.evaluate(WD_ENTRY_JS, [kind, "count", 0])
                if not page.evaluate(WD_ENTRY_JS, [kind, action, before]):
                    log.info("no %s button for %s entries; leaving them as they are", action, kind)
                    break
                for _ in range(15):  # up to ~6 s for Workday to draw / remove the entry
                    page.wait_for_timeout(400)
                    if page.evaluate(WD_ENTRY_JS, [kind, "count", 0]) != before:
                        break
                else:
                    log.warning("%s entry %s did not show up; not clicking again", kind, action)
                    break
            page.wait_for_timeout(600)  # let the last entry finish rendering
        except Exception as e:  # noqa: BLE001
            log.warning("could not adjust %s entries: %s", kind, e)


def _wd_wait_fields(page, timeout_s: float = 10.0) -> list:
    """Workday draws a step's fields a moment after its title: wait until they are
    there and their number stops changing (reading too early found no fields at all)."""
    from hunt.apply.browser import collect_fields
    deadline, last, fields = time.time() + timeout_s, -1, []
    while time.time() < deadline:
        fields = collect_fields(page)
        if fields and len(fields) == last:
            return fields
        last = len(fields)
        page.wait_for_timeout(700)
    return fields


def _wd_errors(page) -> list[str]:
    try:
        loc = page.locator("[data-automation-id='errorBanner']:visible, [data-automation-id='errorMessage']:visible, "
                           "[data-automation-id='inputAlert']:visible")
        return [t for t in (" ".join(loc.nth(i).inner_text(timeout=800).split()) for i in range(min(loc.count(), 8))) if t]
    except Exception:  # noqa: BLE001
        return []


WD_DUMP_JS = r"""
() => {
  const txt = e => (e ? (e.innerText || e.textContent || '') : '').replace(/\s+/g, ' ').trim().slice(0, 120);
  return {
    url: location.href,
    headings: Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, [role="heading"], legend')).map(txt).filter(Boolean).slice(0, 80),
    buttons: Array.from(document.querySelectorAll('button')).map(b => ({text: txt(b), aria: b.getAttribute('aria-label'),
      aid: b.getAttribute('data-automation-id'), id: b.id})).slice(0, 150),
    groups: Array.from(document.querySelectorAll('[role="group"], [data-automation-id^="workExperience-"], [data-automation-id^="education-"]'))
      .map(g => ({aid: g.getAttribute('data-automation-id'), labelledby: g.getAttribute('aria-labelledby'), id: g.id})).slice(0, 60),
  };
}
"""


def _wd_dump(page, job, step: str, fields) -> None:
    """Keep the structure of each Workday step (labels, entries, buttons; not your answers)
    under data/debug/workday so a site that behaves differently can be fixed quickly."""
    import json
    try:
        d = get_settings().data_dir / "debug" / "workday"
        d.mkdir(parents=True, exist_ok=True)
        info = page.evaluate(WD_DUMP_JS)
        info["errors"] = _wd_errors(page)
        info["fields"] = [{"name": f.name, "label": f.label, "type": f.type, "entry": f.entry, "required": f.required,
                           "has_value": bool(f.current), "selector": f.description} for f in fields]
        slug = re.sub(r"[^a-z0-9]+", "-", f"{job.company}-{step}".lower()).strip("-")[:80]
        (d / f"{slug}.json").write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.debug("workday dump failed: %s", e)


def _drive_workday(page, job, app, ctx, files, hooks: dict):
    """Workday wizard: you sign in (or create the account); the system uploads the
    tailored resume, fills each step and clicks Save and Continue; it stops at Review
    so you press Submit yourself."""
    from hunt.apply.answers import answer_field
    from hunt.apply.browser import collect_fields
    _set(state="filling", message=f"Opening {job.company}'s Workday posting…")
    page.goto(job.apply_url or job.posting_url, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    if _posting_gone(page):
        return "expired", None, None
    try:
        btn = page.locator("[data-automation-id='adventureButton']")
        if btn.count():
            btn.first.click()
            page.wait_for_timeout(1500)
            # Apply Manually: Workday's own reading of the resume gets names, companies and
            # descriptions wrong; every field is filled from your verified profile instead
            for aid in ("applyManually", "autofillWithResume"):
                opt = page.locator(f"[data-automation-id='{aid}']")
                if opt.count() and opt.first.is_visible():
                    opt.first.click()
                    break
            page.wait_for_timeout(2500)
    except Exception:  # noqa: BLE001
        log.info("Workday apply menu not found; you can click Apply yourself")
    baseline = page_snapshot(page)
    state = {"step": None, "filled_steps": set(), "signin_hook": False, "review_hook": False, "stuck": 0,
             "filled": 0, "left": [], "resume_up": False, "autofill_ticks": 0}

    def signin_open() -> bool:
        # Workday often shows the sign-in / create-account box on top of the "Autofill
        # with Resume" step, so the progress bar alone can't tell that you're not in yet
        try:
            return page.locator("input[type=password]:visible, [data-automation-id='signInSubmitButton']:visible, "
                                "[data-automation-id='createAccountSubmitButton']:visible").count() > 0
        except Exception:  # noqa: BLE001
            return False

    def autofill_tick(step: str) -> None:
        """Upload the tailored resume (retried until it is attached), then Continue."""
        if not state["resume_up"]:
            up = page.locator("[data-automation-id='file-upload-input-ref'], input[type=file]")
            if not (up.count() and "resume" in files):
                _banner(page, f"{step}: waiting for the resume upload box…")
                return
            up.first.set_input_files(str(files["resume"]))
            state["resume_up"], state["autofill_ticks"] = True, 0
            _banner(page, "Uploaded your tailored resume; Workday is reading it…")
            return
        state["autofill_ticks"] += 1
        if state["autofill_ticks"] in (3, 8, 14):  # ~4 s for Workday to parse it, then Continue (again if needed)
            _wd_click_next(page)
        if state["autofill_ticks"] == 14:
            _banner(page, f"{step}: your resume is uploaded. If the page didn't move on, click Continue.")

    def fill_step(step: str) -> bool:
        """Fill this step; False when its fields never appeared (try again on a later tick)."""
        from hunt.apply.browser import clear_wd_selection
        low = step.lower()
        _banner(page, f"{step}: filling in your answers…")
        fields = _wd_wait_fields(page, 4.0 if "review" in low else 10.0)
        _wd_dump(page, job, step, fields)  # saved before filling, so a step that gets stuck can still be checked
        if not fields and "review" not in low:
            return False
        if "experience" in low:
            _wd_sync_entries(page, ctx)  # as many work / education entries as on your resume
            fields = _wd_wait_fields(page)
        planned = [(f, answer_field(f, ctx)) for f in fields]
        for f, a in planned:
            if f.current and _wd_clear_needed(f, ctx):
                page.locator(f.description).first.fill("")
        todo = [(f, a) for f, a in planned if _wd_should_fill(f, a)]
        for f, a in todo:
            if f.current and f.type == "wd_multiselect":
                clear_wd_selection(page, f.description)  # remove the wrong pick before adding yours
        answers = [a for _, a in todo]
        selectors = {f.name: f.description for f, _ in todo}
        handled = {f.name for f in fields}

        def revealed(seen: set[str]):  # questions this step shows only after earlier answers
            new = [f for f in collect_fields(page) if not f.current and f.name not in seen and f.name not in handled]
            return [answer_field(f, ctx) for f in new], {f.name: f.description for f in new}

        filled, unfilled = fill_all(page, answers, files, selectors, revealed)
        if _wd_attach_resume(page, files):
            filled.append("Resume/CV")
        left = [(a.label, selectors.get(a.name)) for a in answers if a.required and (a.kind == "human" or a.label in unfilled)]
        state["filled"] += len(filled)
        state["left"] = [l for l, _ in left]
        _wd_dump(page, job, step, fields)
        if "review" in low:
            _banner(page, "Review: everything is filled in. Check it, then click Submit. "
                          "This window records the confirmation automatically.")
            return True
        if left:
            page.evaluate(WD_HIGHLIGHT_JS, [s for _, s in left if s])
            _banner(page, f"{step}: fill the {len(left)} highlighted field(s), then click Save and Continue.")
        else:
            _banner(page, f"{step}: filled. Continuing…")
            page.wait_for_timeout(800)
            _wd_click_next(page)
        return True

    def tick() -> None:
        step = _wd_step(page)
        if step is None and "autofillwithresume" in page.url.lower():
            step = "Autofill with Resume"  # some sites show no progress bar on this page
        if step is None:
            _set(state="waiting", message="Click Apply (then Apply Manually) in the browser window if it didn't open.")
            return
        low = step.lower()
        if "sign in" in low or "create account" in low or signin_open():
            _set(state="waiting", message=f"Sign in or create your {job.company} Workday account in the browser window.")
            _banner(page, f"Sign in or create your {job.company} account (your browser can remember it). "
                          "The application is filled in for you after you sign in.")
            if hooks.get("on_signin") and not state["signin_hook"]:
                state["signin_hook"] = True
                hooks["on_signin"](page)
            return
        if "autofill" in low or ("resume" in low and "experience" not in low):
            state["step"] = step
            autofill_tick(step)
            _set(state="filling", message=f"{step}: uploading your tailored resume…")
            return
        tries = state.setdefault("tries", {})
        if step != state["step"] or (step not in state["filled_steps"] and tries.get(step, 0) < 3):
            state["step"], state["stuck"] = step, 0
            page.wait_for_timeout(1500)  # let the step render
            if step not in state["filled_steps"]:
                tries[step] = tries.get(step, 0) + 1
                _set(state="filling", message=f"Filling: {step}")
                if fill_step(step):
                    state["filled_steps"].add(step)
        else:
            state["stuck"] += 1
            if state["stuck"] == 8 and "review" not in low:  # ~12 s on the same step after filling it
                errs = _wd_errors(page)
                _banner(page, f"{step}: Workday needs something on this page"
                        + (f" ({'; '.join(errs)[:200]})" if errs else "") + ". Fix the flagged fields, then click Save and Continue.")
                state["left"] = errs or state["left"]
                _wd_dump(page, job, step, collect_fields(page))
        _set(state="waiting", filled=state["filled"], left_for_you=state["left"],
             message=("Review everything, then click Submit in the browser window." if "review" in low
                      else f"On '{step}'" + (f": {len(state['left'])} field(s) need you" if state["left"] else "")))
        if "review" in low and hooks.get("on_review") and not state["review_hook"]:
            state["review_hook"] = True
            hooks["on_review"](page)

    _set(state="waiting", message=f"Sign in or create your {job.company} Workday account in the browser window.")
    return _watch(page, baseline, on_tick=tick)
