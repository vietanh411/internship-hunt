"""Playwright form automation shared by ATS adapters.

Never attempts to solve or bypass CAPTCHAs, bot checks, logins, or MFA: when one
is detected the application is marked Blocked for the applicant to finish."""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from hunt.apply.answers import FormField, PlannedAnswer

log = logging.getLogger(__name__)

COLLECT_JS = r"""
() => {
  const visible = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return (r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none') || el.type === 'file'; };
  const txt = el => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const LABELISH = '.application-label, legend, label, .label, [class*="label"], [class*="question-title"], [class*="questionTitle"]';
  const labelFor = el => {
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = lb.split(/\s+/).map(id => txt(document.getElementById(id))).join(' ').trim(); if (t) return t; }
    // Lever: <label class="application-question"><div class="application-label">Q</div><div class="application-field"><input>
    const lq = el.closest('.application-question');
    if (lq) { const l = lq.querySelector('.application-label'); if (l && txt(l)) return txt(l); }
    if (el.labels && el.labels.length) {
      const own = el.labels[0];
      const t = txt(own);
      if (t && !own.contains(el)) return t;
      const inner = own.querySelector(LABELISH);
      if (inner && txt(inner)) return txt(inner);
      if (t) return t;
    }
    const al = el.getAttribute('aria-label'); if (al) return al;
    // walk up a few ancestors; use the first label-like element that is not wrapping the input
    let a = el.parentElement;
    for (let depth = 0; a && depth < 6; depth++, a = a.parentElement) {
      for (const l of a.querySelectorAll(LABELISH)) {
        if (!l.contains(el) && txt(l)) return txt(l);
      }
    }
    return el.getAttribute('placeholder') || el.name || el.id || '';
  };
  // the text of one radio/checkbox choice (not the question it belongs to)
  const optionLabelFor = el => {
    const l = el.closest('label');
    if (l && l.querySelectorAll('input').length === 1 && !l.querySelector('.application-label')) {
      const t = txt(l); if (t) return t;
    }
    if (el.id) { const f = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (f && txt(f)) return txt(f); }
    const sib = el.nextElementSibling; if (sib && txt(sib)) return txt(sib);
    return el.value || '';
  };
  const ashbyTitle = el => {
    const fe = el.closest('.ashby-application-form-field-entry, [data-field-path]') || el.closest('fieldset');
    if (!fe) return null;
    const t = fe.querySelector('.ashby-application-form-question-title');
    return t ? {text: txt(t), required: /required/i.test(t.className) || /\*\s*$/.test(txt(t))} : null;
  };
  const groupLabel = el => {
    const at = ashbyTitle(el); if (at && at.text) return at.text;
    const lq = el.closest('.application-question');
    if (lq) { const l = lq.querySelector('.application-label'); if (l && txt(l)) return txt(l); }
    const fs = el.closest('fieldset'); if (fs) { const lg = fs.querySelector('legend'); if (lg) return txt(lg); }
    const c = el.closest('.application-question, .field, .question, [class*="question"], [role="radiogroup"], [role="group"]');
    if (c) { const l = c.querySelector('.application-label, .text, legend, label, [class*="label"]'); if (l) return txt(l); }
    return el.name || '';
  };
  // Workday: each question sits in [data-automation-id^="formField-"] with a <label>/<legend>
  const wdField = el => el.closest('[data-automation-id^="formField-"]');
  const wdLabel = el => {
    const ff = wdField(el); if (!ff) return null;
    const l = ff.querySelector('label, legend');
    const t = l ? txt(l) : '';
    return {text: t, required: !!ff.querySelector('abbr[title="required"], [aria-required="true"], [required]') || /[*✱＊]\s*$/.test(t)};
  };
  const isWdSegment = el => /^dateSection/.test(el.getAttribute('data-automation-id') || '') || !!el.closest('[data-automation-id="multiselectInputContainer"]');
  // Workday repeatable entries ("Work Experience 2", "Education 1"): the entry a field is in
  const ENTRY_RX = /^(work experience|education)\s+(\d+)\b/i;
  const entryKind = s => (/^edu/i.test(s) ? 'edu' : 'work');
  const entryOf = el => {
    for (let a = el.parentElement, d = 0; a && a !== document.body && d < 14; a = a.parentElement, d++) {
      const m1 = (a.getAttribute('data-automation-id') || '').match(/^(workExperience|education)-(\d+)$/);
      if (m1) return entryKind(m1[1]) + ':' + m1[2];
      const lb = a.getAttribute('aria-labelledby');
      const m2 = (lb ? lb.split(/\s+/).map(id => txt(document.getElementById(id))).join(' ') : '').match(ENTRY_RX);
      if (m2) return entryKind(m2[1]) + ':' + m2[2];
      if (a.getAttribute('role') === 'group') {
        const h = a.querySelector('h1, h2, h3, h4, h5, [role="heading"]');
        const m3 = h ? txt(h).match(ENTRY_RX) : null;
        if (m3) return entryKind(m3[1]) + ':' + m3[2];
      }
    }
    const m4 = (el.id || '').match(/^(workExperience|education)-(\d+)--/);  // internal id: ordered in Python
    return m4 ? entryKind(m4[1]) + '#' + m4[2] : '';
  };
  // a stable handle for widgets with no unique id (the same date field repeats in every entry)
  const huntId = el => el.getAttribute('data-hunt-id') || (el.setAttribute('data-hunt-id', 'h' + Math.random().toString(36).slice(2, 9)), el.getAttribute('data-hunt-id'));
  const out = []; const groups = {};
  const els = document.querySelectorAll('input, select, textarea');
  for (const el of els) {
    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search'].includes(type)) continue;
    if (isWdSegment(el)) continue;  // handled as Workday date / multiselect widgets below
    if (el.closest('.ashby-application-form-input-education-entry')) continue;  // composite field below
    const yesno = el.closest('.ashby-application-form-input-yesno');
    if (yesno && el.name) {  // Ashby Yes/No: buttons backed by a hidden checkbox
      const at = ashbyTitle(el);
      const pressed = yesno.querySelector('button[aria-pressed="true"]');
      out.push({name: el.name, selector: `[name="${el.name}"]`, label: (at && at.text) || el.name, type: 'yesno',
                required: !!(at && at.required), options: ['Yes', 'No'], option_values: ['yes', 'no'],
                current: pressed ? txt(pressed) : ''});
      continue;
    }
    if (!visible(el) && type !== 'file') continue;
    const req = el.required || el.getAttribute('aria-required') === 'true';
    let sel = el.id ? '#' + CSS.escape(el.id) : (el.name ? `[name="${el.name}"]` : null);
    // Workday repeats name="jobTitle" in every Work Experience entry; its ids are unique
    const wdEntry = entryOf(el);
    let fname = (wdEntry && el.id) ? el.id : (el.name || el.id);
    if (type === 'radio' && !el.name) continue;
    if (!sel) {
      const box = el.closest('.ashby-application-form-field-entry, [data-field-path], fieldset');
      const title = box && box.querySelector('.ashby-application-form-question-title[for]');
      const path = box && box.getAttribute('data-field-path');
      const only = box && box.querySelectorAll('input:not([type=hidden]), select, textarea').length === 1;
      if (only && path) { sel = `[data-field-path="${path}"] input`; fname = path; }
      else if (only && title) { fname = title.getAttribute('for'); sel = `label[for="${fname}"] ~ div input`; }
    }
    if (!sel) continue;
    const entry = el.closest('.ashby-application-form-field-entry, [data-field-path]');
    const ashbyGroup = type === 'checkbox' && entry && entry.querySelectorAll('input[type=checkbox]').length > 1;
    // Workday: several checkboxes under one question ("Please select race/ethnicity") are one choice list
    const wff = wdField(el);
    const wdGroup = type === 'checkbox' && !ashbyGroup && wff && !wdEntry && wff.querySelectorAll('input[type=checkbox]').length > 1;
    // (one "I currently work here" box per Workday entry, all with the same name: each stands alone)
    if (type === 'radio' || ashbyGroup || wdGroup || (type === 'checkbox' && el.name && !wdEntry && document.querySelectorAll(`input[type=checkbox][name="${el.name}"]`).length > 1)) {
      const key = ashbyGroup ? 'entry:' + (entry.getAttribute('data-field-path') || entry.getAttribute('data-field-entry-id') || el.name)
        : wdGroup ? 'wd:' + huntId(wff) : el.name;
      const sel = ashbyGroup ? `[data-field-path="${entry.getAttribute('data-field-path')}"] input[type=checkbox]`
        : wdGroup ? `[data-hunt-id="${huntId(wff)}"] input[type=checkbox]` : `input[name="${el.name}"]`;
      const g = groups[key] || (groups[key] = {name: key, selector: sel, label: wdGroup ? ((wdLabel(el) || {}).text || groupLabel(el)) : groupLabel(el),
                 type: type === 'radio' ? 'radio' : 'multi_select', required: false, options: [], option_values: [], entry: entryOf(el)});
      const at = ashbyTitle(el);
      const wl = wdLabel(el);
      if (wl && wl.text && (!g.label || g.label === el.name)) g.label = wl.text;
      g.required = g.required || req || !!(at && at.required) || !!(wl && wl.required);
      g.options.push(optionLabelFor(el)); g.option_values.push(el.value);
      if (el.checked) g.current = optionLabelFor(el);
      continue;
    }
    let ftype = type;
    if (el.tagName === 'SELECT') ftype = el.multiple ? 'multi_select' : 'select';
    else if (el.tagName === 'TEXTAREA') ftype = 'textarea';
    else if (el.getAttribute('role') === 'combobox') ftype = 'combobox';
    else if (['email', 'tel', 'url', 'number', 'text'].includes(type)) ftype = 'text';
    const at = ashbyTitle(el);
    const wl = wdLabel(el);
    let label = (at && at.text && type !== 'checkbox') ? at.text : labelFor(el);
    if (wl && wl.text && (!label || label === el.id || label === el.name)) label = wl.text;
    const options = el.tagName === 'SELECT' ? Array.from(el.options).filter(o => o.value !== '').map(o => txt(o)) : [];
    const current = type === 'checkbox' ? (el.checked ? 'checked' : '') : (type === 'file' ? (el.files && el.files.length ? 'file' : '') : (el.value || ''));
    out.push({name: fname, selector: sel, label, type: ftype,
              required: req || !!(at && at.required) || !!(wl && wl.required) || /[*✱＊]\s*$/.test(label), options, option_values: [], current,
              entry: entryOf(el)});
  }
  // Ashby education history: school search + degree + field of study + dates + still-student box
  for (const fe of document.querySelectorAll('.ashby-application-form-field-entry[data-field-path]')) {
    if (!fe.querySelector('.ashby-application-form-input-education-entry')) continue;
    const path = fe.getAttribute('data-field-path');
    const t = fe.querySelector('.ashby-application-form-question-title');
    const school = fe.querySelector('input[role="combobox"]');
    out.push({name: path, selector: `[data-field-path="${path}"]`, label: t ? txt(t) : 'Education History',
              type: 'ashby_education', required: !!(t && /required/i.test(t.className)), options: [], option_values: [],
              current: school ? school.value : ''});
  }
  // Workday dropdowns: <button aria-haspopup="listbox"> showing the selected value ("Select One" = empty)
  for (const b of document.querySelectorAll('button[aria-haspopup="listbox"]')) {
    if (!visible(b)) continue;
    const wl = wdLabel(b);
    const label = (wl && wl.text) || (b.getAttribute('aria-label') || '').replace(/\s*(Select One|Required)\s*/g, ' ').trim();
    if (!label) continue;
    const sel = b.id ? '#' + CSS.escape(b.id) : `[data-hunt-id="${huntId(b)}"]`;
    const val = txt(b);
    out.push({name: b.id || sel, selector: sel, label, type: 'wd_dropdown', required: !!(wl && wl.required) || /Required/.test(b.getAttribute('aria-label') || ''),
              options: [], option_values: [], current: /^select one$/i.test(val) ? '' : val, entry: entryOf(b)});
  }
  // Workday multiselect "prompt" inputs (type to search, pick an option)
  for (const inp of document.querySelectorAll('[data-automation-id="multiselectInputContainer"] input')) {
    if (!visible(inp)) continue;
    const wl = wdLabel(inp); if (!wl || !wl.text) continue;
    const ff = wdField(inp);
    const chosen = ff ? Array.from(ff.querySelectorAll('[data-automation-id="selectedItem"]')).map(txt).join(', ') : '';
    const sel = inp.id ? '#' + CSS.escape(inp.id) : `[data-hunt-id="${huntId(inp)}"]`;
    out.push({name: inp.id || sel, selector: sel, label: wl.text, type: 'wd_multiselect', required: wl.required, options: [], option_values: [],
              current: chosen, entry: entryOf(inp)});
  }
  // Workday dates: month/(day)/year segments inside one form field
  for (const m of document.querySelectorAll('[data-automation-id="dateSectionMonth-input"], [data-automation-id="dateSectionYear-input"]')) {
    const ff = wdField(m); if (!ff || ff.dataset.huntSeen) continue;
    ff.dataset.huntSeen = '1';
    const wl = wdLabel(m) || {text: '', required: false};
    const aid = ff.getAttribute('data-automation-id');
    const segs = Array.from(ff.querySelectorAll('[data-automation-id^="dateSection"][data-automation-id$="-input"]'));
    const entry = entryOf(ff);  // the same date field repeats in every entry: address each one
    out.push({name: entry ? entry + ':' + aid : aid, selector: entry ? `[data-hunt-id="${huntId(ff)}"]` : `[data-automation-id="${aid}"]`,
              label: wl.text, type: 'wd_date', required: wl.required, entry,
              options: [], option_values: [], current: segs.every(s => s.value) ? segs.map(s => s.value).join('/') : ''});
  }
  document.querySelectorAll('[data-hunt-seen]').forEach(e => delete e.dataset.huntSeen);
  return out.concat(Object.values(groups));
}
"""

CAPTCHA_JS = r"""
() => {
  // Invisible reCAPTCHA / hCaptcha keep a challenge frame in the DOM that is hidden
  // (visibility:hidden, opacity 0, or moved off-screen); only a shown challenge counts.
  const shown = el => {
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0) return false;
    }
    const r = el.getBoundingClientRect();
    return r.width > 100 && r.height > 60 && r.bottom > 0 && r.right > 0 &&
           r.top < (window.innerHeight * 4) && r.left < window.innerWidth;
  };
  const frames = Array.from(document.querySelectorAll('iframe'));
  for (const f of frames) {
    const src = (f.src || '') + ' ' + (f.title || '');
    if (!/recaptcha|hcaptcha|turnstile|challenges\.cloudflare|captcha/i.test(src)) continue;
    // the reCAPTCHA v2 checkbox ("anchor", ~304x78) or a visible challenge ("bframe")
    if (shown(f) && !/recaptcha\/(api2|enterprise)\/anchor.*size=invisible/i.test(f.src || '')) return src.slice(0, 120);
  }
  const t = document.body ? document.body.innerText : '';
  if (/verify (that )?you('| a)re (a )?human|are you a robot|complete the captcha|checking your browser/i.test(t)) return 'text-challenge';
  return null;
}
"""

CONFIRM_RE = re.compile(r"thank you for (applying|your application|your interest|submitting)|application (has been |was )?(successfully )?(submitted|received)|"
                        r"we('ve| have) received your application|successfully submitted|thanks for applying", re.I)


@dataclass
class SubmitResult:
    status: str  # submitted / blocked / failed / unconfirmed / dry_run
    confirmation_text: str | None = None
    final_url: str | None = None
    screenshot: bytes | None = None
    error: str | None = None
    submit_clicked: bool = False
    filled: list[str] = field(default_factory=list)
    unfilled: list[str] = field(default_factory=list)


class Browser:
    """Context manager around a Playwright Chromium instance."""
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw = None
        self.browser = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=self.headless)
        return self

    def __exit__(self, *exc):
        try:
            if self.browser:
                self.browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def new_page(self):
        ctx = self.browser.new_context(viewport={"width": 1280, "height": 1800}, locale="en-US")
        page = ctx.new_page()
        page.set_default_timeout(15000)
        return page


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def collect_fields(page) -> list[FormField]:
    try:
        raw = page.evaluate(COLLECT_JS)
    except Exception as e:  # noqa: BLE001
        if "context was destroyed" not in str(e) and "navigat" not in str(e):
            raise
        page.wait_for_timeout(1200)  # the site moved to its next page while we were reading: read that one
        page.wait_for_load_state("domcontentloaded")
        raw = page.evaluate(COLLECT_JS)
    out = []
    seen = set()
    for r in raw:
        key = (r["name"], r["type"])
        if key in seen:
            continue
        seen.add(key)
        label = re.sub(r"\s*([*✱＊]|\(required\)|required)\s*$", "", (r["label"] or r["name"]).strip(), flags=re.I).strip()
        r["options"] = [re.sub(r"\s*[*✱＊]\s*$", "", o or "").strip() for o in (r.get("options") or [])]
        f = FormField(name=r["name"], label=label, type=r["type"], required=bool(r["required"]),
                      options=r.get("options") or [], option_values=r.get("option_values") or [],
                      current=str(r.get("current") or ""), entry=str(r.get("entry") or ""))
        f.description = r["selector"]  # carry the selector
        out.append(f)
    order: dict[str, dict[str, int]] = {}
    for f in out:  # "work#12" (Workday's internal id) -> "work:1" by order on the page
        if "#" in f.entry:
            kind, internal = f.entry.split("#", 1)
            seen_kind = order.setdefault(kind, {})
            f.entry = f"{kind}:{seen_kind.setdefault(internal, len(seen_kind) + 1)}"
    return out


def detect_captcha(page) -> str | None:
    try:
        return page.evaluate(CAPTCHA_JS)
    except Exception:
        return None


def requires_login(page) -> bool:
    try:
        return page.locator("input[type=password]:visible").count() > 0
    except Exception:
        return False


def _locate(page, a: PlannedAnswer, selector: str | None):
    cands = []
    if selector:
        cands.append(selector)
    if a.name:
        cands += [f"#{a.name}" if re.fullmatch(r"[A-Za-z][\w-]*", a.name) else None, f'[name="{a.name}"]']
    for c in cands:
        if not c:
            continue
        loc = page.locator(c)
        try:
            if loc.count() > 0:
                return loc
        except Exception:
            continue
    try:
        loc = page.get_by_label(a.label, exact=False)
        if loc.count() > 0:
            return loc
    except Exception:
        pass
    return None


def fill_answer(page, a: PlannedAnswer, files: dict[str, Path], selector: str | None = None) -> bool:
    loc = _locate(page, a, selector)
    if loc is None:
        return False
    first = loc.first
    t = a.type
    if t == "file":
        path = files.get(str(a.value))
        if not path:
            return False
        first.set_input_files(str(path))
        return True
    if t in ("text", "textarea", "date", "email", "tel", "url", "number"):
        first.fill(str(a.value))
        return True
    if t == "select":
        try:
            first.select_option(label=str(a.value))
        except Exception:
            first.select_option(value=str(a.value))
        return True
    if t == "multi_select" and loc.count() > 1:  # checkbox group
        values = a.value if isinstance(a.value, list) else [a.value]
        for i in range(loc.count()):
            el = loc.nth(i)
            lab = (a.options[i] if i < len(a.options) else "") or ""
            if any(str(v).lower() == lab.lower() for v in values):
                el.check()
        return True
    if t == "multi_select":
        values = a.value if isinstance(a.value, list) else [a.value]
        first.select_option(label=[str(v) for v in values])
        return True
    if t == "radio":
        for i in range(loc.count()):
            lab = a.options[i] if i < len(a.options) else ""
            if lab.strip().lower() == str(a.value).strip().lower():
                el = loc.nth(i)
                try:
                    el.check(timeout=4000)
                except Exception:
                    el.check(force=True, timeout=4000)
                return el.is_checked()
        return False
    if t == "checkbox":
        if str(a.value).lower() in ("yes", "true", "1", "on", "checked"):
            try:
                first.check(timeout=4000)
            except Exception:  # noqa: BLE001  (styled checkboxes hide the real input)
                first.check(force=True, timeout=4000)
            return first.is_checked()
        if str(a.value).lower() in ("no", "false", "0", "off") and first.is_checked():  # e.g. a wrong "I currently work here"
            try:
                first.uncheck(timeout=4000)
            except Exception:  # noqa: BLE001
                first.uncheck(force=True, timeout=4000)
            return not first.is_checked()
        return True
    if t == "ashby_education":
        return _fill_ashby_education(page, first, str(a.value))
    if t == "yesno":
        opt = "yes" if str(a.value).strip().lower().startswith("y") else "no"
        btn = first.locator("xpath=ancestor::*[contains(@class, 'ashby-application-form-input-yesno')][1]").locator(f'button[data-option="{opt}"]')
        btn.click(timeout=4000)
        return btn.get_attribute("aria-pressed") == "true"
    if t == "wd_dropdown":
        return _pick_from_listbox(page, first, a.value, getattr(a, "fallbacks", []) or [])
    if t == "wd_multiselect":
        values = a.value if isinstance(a.value, list) else [a.value]
        ok = False
        for v in values:
            ok = _pick_multiselect(page, first, v, getattr(a, "fallbacks", []) or []) or ok
        return ok
    if t == "wd_date":
        return _fill_wd_date(first, str(a.value))
    if t == "combobox":
        for v in [str(a.value)] + list(getattr(a, "fallbacks", []) or []):
            if _fill_combobox(page, first, v):
                return True
        return False
    first.fill(str(a.value))
    return True


def _norm_opt(s: str) -> str:
    s = s.lower().replace("–", "-").replace("—", "-").replace("’", "'")
    s = re.sub(r"[^a-z0-9' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _similarity(a: str, b: str) -> float:
    na, nb = _norm_opt(a), _norm_opt(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    jacc = len(ta & tb) / len(ta | tb)
    prefix = 0.15 if nb.startswith(na) or na.startswith(nb) else 0.0
    return min(1.0, jacc + prefix)


def _fill_combobox(page, box, value: str, min_score: float = 0.6) -> bool:
    """Searchable dropdown (react-select etc.): type a short query, then click the
    listed option most similar to the intended value. Returns False (field left
    unfilled, so the form is not submitted) when no option is a close match."""
    words = _norm_opt(value).split()
    queries = [value, " ".join(words[:3]), " ".join(words[:2]), words[0] if words else value]
    for q in dict.fromkeys(qq for qq in queries if qq):
        box.click()
        box.fill("")
        box.type(q, delay=25)
        page.wait_for_timeout(900)
        opts = page.get_by_role("option")
        try:
            texts = [opts.nth(i).inner_text(timeout=1000) for i in range(min(opts.count(), 40))]
        except Exception:
            texts = []
        if not texts:
            continue
        def score(t: str) -> float:
            return max(_similarity(value, t), _similarity(value, t.splitlines()[0] if t.strip() else t))
        best_i, best = max(enumerate(texts), key=lambda it: score(it[1]))
        if score(best) >= min_score:
            opts.nth(best_i).click(timeout=4000)
            return True
    try:
        box.fill("")
        box.press("Escape")
    except Exception:
        pass
    return False


def _fill_ashby_education(page, box, value: str) -> bool:
    """Ashby education entry: school (searchable), degree, field of study, start/end
    month+year dropdowns, Still Student? box. value is the JSON from the answer engine."""
    v = json.loads(value)
    if not _fill_combobox(page, box.locator('input[role="combobox"]').first, v["school"]):
        return False
    for key, suffix in (("degree", "degree"), ("major", "major")):
        inp = box.locator(f'input[id$="-{suffix}"]')
        if v.get(key) and inp.count():
            inp.first.fill(v[key])
    for key, suffix in (("start", "startDate"), ("end", "endDate")):
        sels = box.locator(f'[id$="-{suffix}"] select')
        if v.get(key) and sels.count() >= 2:
            sels.nth(0).select_option(value=str(v[key][0]))
            sels.nth(1).select_option(value=str(v[key][1]))
    cb = box.locator('input[type="checkbox"][id$="-isCurrent"]')
    if v.get("current") and cb.count() and not cb.first.is_checked():
        try:
            cb.first.check(timeout=4000)
        except Exception:  # noqa: BLE001
            cb.first.check(force=True, timeout=4000)
    return True


def _listbox_options(page):
    opts = page.locator("[role='listbox'] [role='option']:visible, [data-automation-id='promptOption']:visible")
    try:
        return opts, [opts.nth(i).inner_text(timeout=800).strip() for i in range(min(opts.count(), 300))]
    except Exception:
        return opts, []


def stem_opt(s: str) -> str:
    """'Masters of Science (MS)' and 'Master of Science' -> 'master of science'."""
    s = re.sub(r"\([^)]*\)", " ", s or "")
    words = [w[:-2] if w.endswith("'s") else (w[:-1] if w.endswith("s") and len(w) > 3 else w) for w in _norm_opt(s).split()]
    return " ".join(w for w in words if w not in ("degree",))


def same_option(a: str, b: str) -> bool:
    return bool(a) and bool(b) and (_norm_opt(a) == _norm_opt(b) or stem_opt(a) == stem_opt(b))


def _best_index(value: str, texts: list[str], min_score: float = 0.6) -> int | None:
    if not texts:
        return None
    v = _norm_opt(value)
    for i, t in enumerate(texts):  # exact (case/punctuation-insensitive) wins
        if _norm_opt(t) == v:
            return i
    for i, t in enumerate(texts):  # then the same words up to plurals / abbreviations in brackets
        if same_option(t, value):
            return i
    if v in ("yes", "no"):
        hits = [i for i, t in enumerate(texts) if _norm_opt(t).split(" ")[:1] == [v]]
        return hits[0] if len(hits) == 1 else None
    best = max(range(len(texts)), key=lambda i: _similarity(value, texts[i]))
    return best if _similarity(value, texts[best]) >= min_score else None


def _first_match(candidates: list[str], texts: list[str]) -> int | None:
    for c in candidates:  # your answer first, then its truthful alternatives
        i = _best_index(c, texts)
        if i is not None:
            return i
    return None


def _pick_from_listbox(page, button, value, fallbacks=()) -> bool:
    """Workday dropdown: open the list once and click the option matching the answer
    (or one of its alternatives). Re-opening it for every alternative made the page jump."""
    candidates = [str(value)] + [str(f) for f in fallbacks or [] if f]
    try:
        button.click()
        page.wait_for_timeout(700)
        opts, texts = _listbox_options(page)
        i = _first_match(candidates, texts)
        if i is None and candidates[0]:
            # long lists (US states) only show a few options at a time; typing jumps to the match
            page.keyboard.type(candidates[0][:12], delay=60)
            page.wait_for_timeout(700)
            opts, texts = _listbox_options(page)
            i = _first_match(candidates, texts)
        if i is None:
            page.keyboard.press("Escape")
            return False
        opts.nth(i).click(timeout=4000)
        page.wait_for_timeout(300)
        return True
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False


CLEAR_WD_SELECTION_JS = r"""
(sel) => {
  const inp = document.querySelector(sel); if (!inp) return 0;
  const ff = inp.closest('[data-automation-id^="formField-"]') || inp.parentElement;
  let n = 0;
  for (const it of Array.from(ff.querySelectorAll('[data-automation-id="selectedItem"]'))) {
    const x = it.querySelector('[data-automation-id="DELETE_charm"], [data-automation-id="deleteButton"], [aria-label^="Delete"], [aria-label^="Remove"], button, [role="button"]');
    if (x) { x.click(); n++; }
  }
  return n;
}
"""


def clear_wd_selection(page, selector: str) -> int:
    """Remove what a Workday multiselect already holds (a wrong pick from resume parsing)."""
    try:
        n = page.evaluate(CLEAR_WD_SELECTION_JS, selector)
        page.wait_for_timeout(300)
        return n
    except Exception:  # noqa: BLE001
        return 0


def _pick_multiselect(page, inp, value, fallbacks=()) -> bool:
    """Workday prompt: open it (some list their first options right away), else search
    for the answer and then its alternatives, and click the matching option."""
    candidates = [str(value)] + [str(f) for f in fallbacks or [] if f]
    try:
        inp.click()
        page.wait_for_timeout(600)
        opts, texts = _listbox_options(page)
        i = _first_match(candidates, texts)
        for query in candidates[:2] if i is None else []:
            inp.fill(query)
            inp.press("Enter")
            page.wait_for_timeout(1200)
            opts, texts = _listbox_options(page)
            i = _first_match(candidates, texts)
            if i is not None:
                break
        if i is None:
            inp.fill("")
            page.keyboard.press("Escape")
            return False
        opts.nth(i).click(timeout=4000)
        page.wait_for_timeout(500)
        return True
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False


def _fill_wd_date(container, value: str) -> bool:
    """value: MM/YYYY, MM/DD/YYYY or YYYY-MM(-DD)."""
    m = re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$", value) or None
    if m:
        year, month, day = m.group(1), m.group(2), m.group(3)
    else:
        parts = value.split("/")
        if len(parts) == 1 and re.fullmatch(r"\d{4}", parts[0]):
            month, day, year = None, None, parts[0]
        elif len(parts) == 2:
            month, day, year = parts[0], None, parts[1]
        elif len(parts) == 3:
            month, day, year = parts
        else:
            return False
    want = {"dateSectionMonth-input": month, "dateSectionDay-input": day, "dateSectionYear-input": year}
    page = container.page
    present = {k: v for k, v in want.items() if v and container.locator(f"[data-automation-id='{k}']").count()}
    if not present:
        return False
    digits = "".join(str(v).zfill(2) if k != "dateSectionYear-input" else str(v) for k, v in present.items())

    def close_popup() -> None:
        try:
            page.keyboard.press("Escape")  # a month calendar may have opened; it covers the next box
        except Exception:  # noqa: BLE001
            pass

    try:
        # Workday's date box ("MM/YYYY") moves from month to year by itself: click it once
        # and type the whole date in one run, then close the calendar it may have opened
        first_seg = container.locator("[data-automation-id^='dateSection'][data-automation-id$='-input']").first
        first_seg.click(timeout=2500)
        page.keyboard.press("Control+A")
        page.keyboard.type(digits, delay=70)
        close_popup()
        page.wait_for_timeout(250)
        if _wd_date_ok(container, want):
            return True
        # older sites: separate month / day / year inputs
        for aid, val in present.items():
            seg = container.locator(f"[data-automation-id='{aid}']").first
            seg.click(timeout=2500)
            try:
                seg.fill("", timeout=1500)  # replace a wrong value instead of typing after it
            except Exception:  # noqa: BLE001
                pass
            seg.type(str(val).zfill(2) if aid != "dateSectionYear-input" else str(val), delay=40)
            close_popup()
        if _wd_date_ok(container, want):
            return True
        if _wd_date_calendar(container, month, year) and _wd_date_ok(container, want):
            return True
    except Exception:  # noqa: BLE001
        pass
    close_popup()
    _dump_widget(container, "wd-date")
    return False


def _wd_date_ok(container, want: dict) -> bool:
    """The date segments now hold the intended month / day / year."""
    try:
        got = container.evaluate("""el => Object.fromEntries(Array.from(el.querySelectorAll(
            '[data-automation-id^="dateSection"][data-automation-id$="-input"]')).map(i =>
            [i.getAttribute('data-automation-id'), (i.value || i.getAttribute('aria-valuetext') || '').trim()]))""")
    except Exception:  # noqa: BLE001
        return False
    for k, v in want.items():
        if v and k in got and not (got[k].lstrip("0") == str(v).lstrip("0")):
            return False
    return bool(got)


def _wd_date_calendar(container, month: str | None, year: str) -> bool:
    """Pick the date in Workday's month calendar: step the year header to the target
    year with its arrows, then click the month."""
    page = container.page
    try:
        icon = container.locator("[data-automation-id='dateIcon'], button[aria-label*='alendar'], [data-automation-id*='datePicker'] button")
        (icon.first if icon.count() else container.locator("[data-automation-id^='dateSection'][data-automation-id$='-input']").first).click()
        page.wait_for_timeout(500)
        for _ in range(30):
            header = page.locator(f"text=/^{year}$/").filter(has_not=page.locator("input"))
            if header.count() and header.first.is_visible():
                break
            shown = page.locator("text=/^20\\d\\d$/")
            cur = next((int(shown.nth(i).inner_text()) for i in range(min(shown.count(), 6)) if shown.nth(i).is_visible()), None)
            if cur is None:
                return False
            arrow = page.locator("button[aria-label*='revious'], [data-automation-id*='revious']" if cur > int(year)
                                 else "button[aria-label*='ext'], [data-automation-id*='ext']")
            vis = [arrow.nth(i) for i in range(min(arrow.count(), 6)) if arrow.nth(i).is_visible()]
            if not vis:
                return False
            vis[0].click()
            page.wait_for_timeout(250)
        if month:
            abbr = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][int(month) - 1]
            cell = page.locator(f"text=/^{abbr}/")
            vis = [cell.nth(i) for i in range(min(cell.count(), 6)) if cell.nth(i).is_visible()]
            if not vis:
                return False
            vis[0].click()
        page.wait_for_timeout(300)
        return True
    except Exception:  # noqa: BLE001
        return False


def _dump_widget(container, kind: str) -> None:
    """Save a widget's HTML when filling it failed, so the site's markup can be checked."""
    try:
        from hunt.config import get_settings
        d = get_settings().data_dir / "debug" / "widgets"
        d.mkdir(parents=True, exist_ok=True)
        html = container.evaluate("el => el.outerHTML")[:20000]
        (d / f"{kind}-{int(time.time())}.html").write_text(html, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


SUBMIT_SELECTORS = [
    "button[type=submit]",
    "input[type=submit]",
    "button:has-text('Submit application')",
    "button:has-text('Submit Application')",
    "button:has-text('Submit')",
    "#btn-submit",
]


def click_submit(page) -> bool:
    for sel in SUBMIT_SELECTORS:
        loc = page.locator(sel)
        try:
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click()
                return True
        except Exception:
            continue
    return False


VERIFY_RE = re.compile(r"verification code (was|has been) sent|enter the \d+-character code|confirm you'?re a human|"
                       r"security code|check your email for a (code|verification)", re.I)


def needs_email_verification(page) -> bool:
    try:
        return bool(VERIFY_RE.search(page.inner_text("body", timeout=3000) or ""))
    except Exception:
        return False


CONFIRM_URL_RE = re.compile(r"/(confirmation|thanks|thank-you|success|submitted)\b", re.I)


def page_snapshot(page) -> tuple[str, str]:
    try:
        return page.url, page.inner_text("body", timeout=3000) or ""
    except Exception:
        return "", ""


def confirmation_since(page, baseline_text: str, baseline_url: str) -> str | None:
    """A confirmation only counts if it is new since the baseline: job descriptions
    often contain phrases like "thank you for your interest" before anything is sent."""
    url, body = page_snapshot(page)
    if len(CONFIRM_RE.findall(body)) > len(CONFIRM_RE.findall(baseline_text or "")):
        matches = list(CONFIRM_RE.finditer(body))
        base_n = len(CONFIRM_RE.findall(baseline_text or ""))
        m = matches[base_n] if base_n < len(matches) else matches[-1]
        start = max(0, m.start() - 80)
        return re.sub(r"\s+", " ", body[start:m.end() + 200]).strip()
    if url and url != baseline_url and CONFIRM_URL_RE.search(url) and not CONFIRM_URL_RE.search(baseline_url or ""):
        return f"Confirmation page reached: {url}"
    return None


def wait_for_confirmation(page, timeout_s: float = 25.0, baseline: tuple[str, str] = ("", "")) -> str | None:
    import time
    base_url, base_text = baseline
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        conf = confirmation_since(page, base_text, base_url)
        if conf:
            return conf
        page.wait_for_timeout(700)
    return None


def fill_all(page, answers: list[PlannedAnswer], files: dict[str, Path],
             selectors: dict[str, str] | None = None, replan=None) -> tuple[list[str], list[str]]:
    """Fill every planned answer. `replan(seen_names)` returns (answers, selectors) for
    questions the form revealed in response (e.g. race appears after 'Hispanic/Latino:
    No'); those are filled too and appended to `answers`."""
    selectors = selectors if selectors is not None else {}
    filled, unfilled = [], []

    def fill(batch: list[PlannedAnswer]) -> None:
        for a in batch:
            if a.kind in ("skip", "human") or a.value in (None, ""):
                continue
            try:
                ok = fill_answer(page, a, files, selectors.get(a.name))
            except Exception as e:  # noqa: BLE001
                log.warning("fill failed for %s: %s", a.label, e)
                ok = False
            (filled if ok else unfilled).append(a.label)

    # one box that can't be reached (covered by a pop-up calendar, say) must not stall the
    # page for 15 s per attempt: short waits while filling
    page.set_default_timeout(4000)
    try:
        fill(answers)
        for _ in range(3 if replan else 0):
            page.wait_for_timeout(400)
            extra, extra_sel = replan({a.name for a in answers})
            if not extra:
                break
            selectors.update(extra_sel)
            answers.extend(extra)
            fill(extra)
    finally:
        page.set_default_timeout(15000)
    return filled, unfilled


# State of one file field. Widgets that hide the real <input> (Ashby, Greenhouse, Lever)
# upload in the background and show the file name when done; only that counts as attached.
UPLOAD_STATE_JS = r"""
([sel, stem]) => {
  const el = document.querySelector(sel);
  if (!el) return 'missing';
  const shown = n => { const r = n.getBoundingClientRect(), s = getComputedStyle(n);
    return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0'; };
  const box = el.closest('.ashby-application-form-field-entry, [data-field-path], .application-question, .field, fieldset') || el.parentElement || document.body;
  const busy = Array.from(box.querySelectorAll('.loadingSvg, [class*="loading" i], [class*="spinner" i], [class*="uploading" i], [role="progressbar"], [aria-busy="true"], progress'));
  if (busy.some(shown)) return 'uploading';
  if ((box.innerText || '').includes(stem)) return 'attached';
  if (shown(el) && el.files && el.files.length) return 'attached';  // plain input: sent with the form
  return 'empty';
}
"""


def upload_state(page, selector: str, path: Path) -> str:
    try:
        return page.evaluate(UPLOAD_STATE_JS, [selector, path.stem])
    except Exception:  # noqa: BLE001
        return "missing"


UPLOAD_TIMEOUT_S = 45.0


def wait_for_uploads(page, answers: list[PlannedAnswer], files: dict[str, Path], selectors: dict[str, str],
                     timeout_s: float | None = None) -> list[str]:
    """Wait until every attached file has finished uploading. Re-attaches once if a
    file disappeared. Returns the labels of required files that are still not attached."""
    pending = []
    for a in answers:
        path = files.get(str(a.value)) if a.type == "file" else None
        sel = selectors.get(a.name) or (f"#{a.name}" if a.name and re.fullmatch(r"[A-Za-z_][\w-]*", a.name) else None)
        if path and sel:
            pending.append((a, sel, path))
    retried: set[str] = set()
    deadline = page.evaluate("Date.now()") + (timeout_s or UPLOAD_TIMEOUT_S) * 1000
    while pending:
        still = []
        for a, sel, path in pending:
            st = upload_state(page, sel, path)
            if st == "attached":
                continue
            if st == "empty" and a.name not in retried:
                retried.add(a.name)
                log.info("file for %s not attached; attaching again", a.label)
                try:
                    page.locator(sel).first.set_input_files(str(path))
                except Exception as e:  # noqa: BLE001
                    log.warning("re-attaching %s failed: %s", a.label, e)
            still.append((a, sel, path))
        pending = still
        if not pending or page.evaluate("Date.now()") > deadline:
            break
        page.wait_for_timeout(500)
    if not pending:
        page.wait_for_timeout(500)  # let the form record the uploaded file
    return [a.label for a, _, _ in pending if a.required]


def wait_for_form(page) -> None:
    page.wait_for_timeout(1200)
    try:
        page.wait_for_load_state("networkidle", timeout=8000)  # let the form finish rendering
    except Exception:  # noqa: BLE001
        pass


def run_form(page, url: str, answers: list[PlannedAnswer], files: dict[str, Path], submit: bool,
             selectors: dict[str, str] | None = None, navigate: bool = True, replan=None) -> SubmitResult:
    """Open the form, fill every planned answer, then (optionally) submit and wait
    for an observed confirmation. Returns without submitting on any blocker.
    navigate=False fills the page as already open, which is required when the
    selectors were read from it (Ashby field ids change on every page load)."""
    selectors = selectors or {}
    if navigate:
        page.goto(url, wait_until="domcontentloaded")
        wait_for_form(page)
    if requires_login(page):
        return SubmitResult("blocked", error="Application requires signing in to an account", final_url=page.url)
    cap = detect_captcha(page)
    if cap:
        return SubmitResult("blocked", error=f"CAPTCHA / bot check present before submission ({cap})", final_url=page.url,
                            screenshot=page.screenshot(full_page=True))
    filled, unfilled = fill_all(page, answers, files, selectors, replan)
    # (a question revealed while filling may need your answer: never submit without it)
    required_unfilled = [a.label for a in answers if a.required and (a.label in unfilled or a.kind == "human")]
    if required_unfilled:
        return SubmitResult("failed", error=f"Could not fill required fields: {required_unfilled}", final_url=page.url,
                            filled=filled, unfilled=unfilled, screenshot=page.screenshot(full_page=True))
    not_attached = wait_for_uploads(page, answers, files, selectors)
    if not_attached:
        return SubmitResult("failed", error=f"File did not finish uploading, so it was not submitted: {not_attached}",
                            final_url=page.url, filled=filled, unfilled=unfilled + not_attached,
                            screenshot=page.screenshot(full_page=True))
    if not submit:
        return SubmitResult("dry_run", final_url=page.url, filled=filled, unfilled=unfilled,
                            screenshot=page.screenshot(full_page=True))
    baseline = page_snapshot(page)
    if not click_submit(page):
        return SubmitResult("failed", error="Submit button not found", final_url=page.url, filled=filled, unfilled=unfilled)
    page.wait_for_timeout(1500)
    conf = wait_for_confirmation(page, baseline=baseline)
    shot = page.screenshot(full_page=True)
    if conf:
        return SubmitResult("submitted", confirmation_text=conf, final_url=page.url, screenshot=shot,
                            submit_clicked=True, filled=filled, unfilled=unfilled)
    if needs_email_verification(page):
        return SubmitResult("blocked", error="Employer requires an emailed verification code to confirm you're a human; "
                            "not submitted. Finish this one yourself.", final_url=page.url, screenshot=shot,
                            submit_clicked=True, filled=filled)
    cap = detect_captcha(page)
    if cap:
        return SubmitResult("blocked", error=f"CAPTCHA presented after clicking submit ({cap}); finish manually",
                            final_url=page.url, screenshot=shot, submit_clicked=True, filled=filled)
    return SubmitResult("unconfirmed", error="Submit clicked but no confirmation was observed", final_url=page.url,
                        screenshot=shot, submit_clicked=True, filled=filled, unfilled=unfilled)


def inspect_form(page, url: str) -> tuple[list[FormField], str | None]:
    """Read-only: list the form's fields without typing anything."""
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if requires_login(page):
        return [], "requires_login"
    return collect_fields(page), detect_captcha(page)
