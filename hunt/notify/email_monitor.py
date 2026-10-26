"""Optional Gmail monitoring over IMAP (read-only; uses BODY.PEEK so messages stay
unread). Classifies employer emails and matches them to applications. Never sends
replies. Configure HUNT_IMAP_USER and HUNT_IMAP_PASSWORD (a Gmail app password)."""
from __future__ import annotations

import email
import imaplib
import logging
import re
from datetime import timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt.config import get_settings
from hunt.db import utcnow
from hunt.models import Application, EmailMessage, Job, JobStatus
from hunt.settings_store import get_value, set_value
from hunt.workflow import notify, set_status

log = logging.getLogger(__name__)

CATEGORIES = [
    ("offer", re.compile(r"\boffer (letter|of employment)|pleased to (extend|offer)|we(?:'d| would) like to offer you|internship offer", re.I)),
    ("rejection", re.compile(r"unfortunately|regret to inform|not (?:be )?moving forward|decided to (?:pursue|move forward with) other|"
                             r"position has been filled|will not be proceeding|not been selected|no longer under consideration", re.I)),
    ("interview", re.compile(r"(?:schedule|invite you to|invitation to|like to set up) (?:an? |a time for )?(?:interview|phone screen|call|conversation)|"
                             r"interview (?:invitation|request)|availability for (?:an? )?(?:interview|call)|calendly", re.I)),
    ("assessment", re.compile(r"online assessment|coding (?:challenge|assessment|test)|hackerrank|codesignal|codility|hirevue|"
                              r"take-home|assessment invitation|complete (?:the|an|your) assessment|pymetrics", re.I)),
    ("info_request", re.compile(r"additional information|please (?:provide|send|complete)|action required|missing (?:information|documents)", re.I)),
    ("confirmation", re.compile(r"thank you for (?:applying|your application|your interest)|application (?:received|submitted|confirmation)|"
                                r"we(?:'ve| have) received your application|thanks for applying", re.I)),
]
RECRUITING_SENDERS = re.compile(r"greenhouse|lever\.co|ashbyhq|myworkday|icims|smartrecruiters|taleo|successfactors|"
                                r"recruit|talent|careers|jobs|hiring|no-?reply", re.I)
STATUS_FOR = {"rejection": JobStatus.REJECTED, "interview": JobStatus.INTERVIEW, "assessment": JobStatus.ASSESSMENT,
              "offer": JobStatus.OFFER}


def imap_configured() -> bool:
    s = get_settings()
    return bool(s.imap_user and s.imap_password)


def classify_email(subject: str, body: str, sender: str) -> str:
    text = f"{subject}\n{body[:5000]}"
    for cat, rx in CATEGORIES:
        if rx.search(text):
            return cat
    return "recruiter" if RECRUITING_SENDERS.search(sender) else "other"


def _decode(h: str | None) -> str:
    if not h:
        return ""
    try:
        return str(make_header(decode_header(h)))
    except Exception:  # noqa: BLE001
        return h


def _body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                except Exception:  # noqa: BLE001
                    continue
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                from hunt.discovery.normalize import html_to_text
                return html_to_text(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace"))
        return ""
    payload = msg.get_payload(decode=True) or b""
    return payload.decode(msg.get_content_charset() or "utf-8", "replace")


# words that say nothing about which role an email is about
_GENERIC = {"intern", "internship", "internships", "summer", "2027", "the", "and", "of", "for", "a", "an", "to", "in",
            "co", "op", "program", "student", "position", "role", "team", "opportunity", "early", "career"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9+#]+", text.lower()) if t not in _GENERIC and len(t) > 1}


def role_overlap(title: str, text: str) -> float:
    """Share of the job title's meaningful words that appear in the email."""
    want = _tokens(re.sub(r"\(.*?\)", " ", title)) or _tokens(title)
    return len(want & _tokens(text)) / len(want) if want else 0.0


def _company_hit(job: Job, text: str, sender_domain: str) -> bool:
    """Whole-word company name in the email, or the sender's own domain is the company's.
    ('KLA' must not match 'Klaviyo'; 'Sage' must not match 'message'.)"""
    for name in {job.company.lower().strip(), (job.company_norm or "").lower().strip()}:
        if len(name) >= 3 and re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", text):
            return True
    compact = re.sub(r"[^a-z0-9]", "", (job.company_norm or job.company).lower())
    labels = sender_domain.split(".")
    return bool(compact) and len(labels) >= 2 and labels[-2] == compact


def match_job(session: Session, sender: str, subject: str, body: str, category: str | None = None) -> Job | None:
    """The application this email is about, or None when unsure. Requires the company
    and, unless you have exactly one application there that is already past submission,
    the role; a confirmation always needs the role (it marks an application submitted)."""
    text = f"{sender} {subject} {body[:6000]}".lower()
    domain = parseaddr(sender)[1].split("@")[-1].lower()
    # every application, whatever its status, so an email about a closed one is not
    # attached to a different open role at the same company
    cands = session.scalars(select(Job).join(Application)).all()
    hits = [j for j in cands if _company_hit(j, text, domain)]
    if not hits:
        return None
    for j in hits:  # the posting's own id in the email settles it
        if j.ats_job_id and len(j.ats_job_id) > 4 and j.ats_job_id.lower() in text:
            return j
    role_text = f"{subject} {body[:1500]}"  # the role is named up front; footers add noise
    scored = sorted(((role_overlap(j.title, role_text), j) for j in hits), key=lambda x: -x[0])
    best_score, best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= 0.6 and best_score - second >= 0.2:
        return best
    applied = (JobStatus.SUBMITTED.value, JobStatus.ASSESSMENT.value, JobStatus.INTERVIEW.value)
    if len(hits) == 1 and category != "confirmation" and best.status in applied and best_score == 0.0 \
            and not re.search(r"\b(intern(ship)?|position|role)\b", subject.lower()):
        return best  # no role named at all and it is your only application there
    return None


def apply_email(session: Session, job: Job | None, category: str, subject: str, run_id: int | None,
                received=None) -> str | None:
    if job is None:
        return None
    app = job.application
    if category == "confirmation":
        if job.status in (JobStatus.READY_TO_APPLY.value, JobStatus.APPLYING.value, JobStatus.BLOCKED.value, JobStatus.FAILED.value,
                          JobStatus.SKIPPED.value):  # skipped here but applied in your own browser
            if app and app.date_applied is None:
                app.date_applied = received or utcnow()  # when you applied, not when the email was read
            if app:
                app.confirmation_text = f"Email: {subject}"
                app.confirmation_source = "email"
            set_status(session, job, JobStatus.SUBMITTED, "Confirmation email received", run_id=run_id,
                       next_action="Wait for response; follow up in ~2 weeks")
            return JobStatus.SUBMITTED.value
        return None
    if category in STATUS_FOR:
        new = STATUS_FOR[category]
        set_status(session, job, new, f"Email: {subject[:200]}", run_id=run_id,
                   next_action={"interview": "Reply to schedule the interview (not automated)",
                                "assessment": "Complete the assessment",
                                "offer": "Review the offer", "rejection": ""}.get(category))
        notify(session, category, f"{category.title()}: {job.company} – {job.title}", subject, job.id)
        return new.value
    if category == "info_request":
        job.next_action = f"Employer requested information: {subject[:200]}"
        notify(session, "info_request", f"Info requested: {job.company}", subject, job.id)
    return None


# ------------------------------------------------------------ verification codes
# Shown to you while you finish an application yourself; never typed in by the system.
_CODE_HINT = re.compile(r"(security|verification|one[- ]time|login|sign[- ]in)\s+(code|password)|passcode|\botp\b", re.I)
_LABEL = r"(?:code|passcode|one[- ]time password|otp)"
_CODE_AFTER = [
    # "...security code field on your application: NojgLEvI" / "one-time password: 123456"
    re.compile(rf"\b{_LABEL}\b[^:\n]{{0,80}}:\s*([A-Za-z0-9]{{4,12}})(?![A-Za-z0-9])", re.I),
    # "Your verification code is 816339"
    re.compile(rf"\b{_LABEL}\s+is\s*:?\s*([A-Za-z0-9]{{4,12}})(?![A-Za-z0-9])", re.I),
]
_CODE_STOPWORDS = {"IMPORTANT", "SECURITY", "VERIFY", "CONFIRM", "APPLICATION"}


def _looks_like_code(tok: str, labelled: bool = False) -> bool:
    """labelled: the token directly follows 'code:' / 'code is', so a mixed-case
    letter code such as Greenhouse's 'NojgLEvI' is accepted (but not 'iPhone' elsewhere)."""
    if tok.isdigit():
        return 4 <= len(tok) <= 8 and not re.fullmatch(r"(19|20)\d\d", tok)  # not a year
    if re.search(r"\d", tok):
        return len(tok) >= 5
    if labelled and len(tok) >= 6 and any(c.isupper() for c in tok[1:]) and any(c.islower() for c in tok):
        return True
    return tok.isupper() and len(tok) >= 6 and tok not in _CODE_STOPWORDS


def extract_code(subject: str, body: str) -> str | None:
    """The one-time code in a verification email, or None. Order/transfer
    'confirmation codes' are not verification codes and are ignored."""
    text = re.sub(r"https?://\S+|data:\S+|<[^>]+>", " ", f"{subject}\n{body[:4000]}")
    if not _CODE_HINT.search(text):
        return None
    for rx in _CODE_AFTER:
        for m in rx.finditer(text):
            if _looks_like_code(m.group(1), labelled=True):
                return m.group(1)
    for m in re.finditer(rf"\b{_LABEL}\b", text, re.I):
        for tok in re.findall(r"(?<![A-Za-z0-9])([A-Za-z0-9]{4,10})(?![A-Za-z0-9])", text[m.end():m.end() + 160]):
            if _looks_like_code(tok):
                return tok
    return None


def find_verification_code(since, company: str | None = None, max_messages: int = 25) -> tuple[str, str, object] | None:
    """The newest emailed verification code that arrived after `since` (naive UTC), as
    (code, subject, received_at). Emails naming `company` win over others. Read-only:
    messages stay unread."""
    if not imap_configured():
        return None
    s = get_settings()
    M = imaplib.IMAP4_SSL(s.imap_host)
    found = []
    try:
        M.login(s.imap_user, s.imap_password)
        M.select("INBOX", readonly=True)
        # IMAP SINCE is a calendar date in the mail server's own time zone: in a US evening the
        # UTC date is already tomorrow and would skip the code that just arrived, so search from
        # a day earlier and keep only mail received after `since` (below)
        typ, data = M.search(None, f'(SINCE "{since - timedelta(days=1):%d-%b-%Y}")')
        for num in (data[0].split() if data and data[0] else [])[-max_messages:]:
            typ, msg_data = M.fetch(num, "(BODY.PEEK[])")
            if not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            try:
                received = parsedate_to_datetime(msg.get("Date")).astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:  # noqa: BLE001
                continue
            if received < since:
                continue  # an older code (an earlier attempt) is no longer valid
            subject, sender = _decode(msg.get("Subject")), _decode(msg.get("From"))
            body = _body(msg)
            code = extract_code(subject, body)
            if not code:
                continue
            named = bool(company) and bool(re.search(rf"(?<![a-z0-9]){re.escape(company.lower())}(?![a-z0-9])",
                                                     f"{subject} {sender} {body[:3000]}".lower()))
            found.append((named, received, code, subject))
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass
    if not found:
        return None
    named, received, code, subject = max(found, key=lambda x: (x[0], x[1]))  # this employer first, then newest
    return code, subject, received


def check_inbox(session: Session, run_id: int | None = None, max_messages: int = 400) -> dict:
    s = get_settings()
    last = get_value(session, "email_last_check")
    since = utcnow() - timedelta(days=30) if not last else utcnow() - timedelta(days=2)
    stats = {"scanned": 0, "relevant": 0, "matched": 0, "status_updates": 0}
    M = imaplib.IMAP4_SSL(s.imap_host)
    try:
        M.login(s.imap_user, s.imap_password)
        M.select("INBOX", readonly=True)
        typ, data = M.search(None, f'(SINCE "{since:%d-%b-%Y}")')
        ids = data[0].split()[-max_messages:] if data and data[0] else []
        for num in ids:
            typ, msg_data = M.fetch(num, "(BODY.PEEK[])")
            if not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            stats["scanned"] += 1
            mid = msg.get("Message-ID") or f"{msg.get('Date')}|{msg.get('From')}|{msg.get('Subject')}"
            if session.scalar(select(EmailMessage).where(EmailMessage.message_id == mid)):
                continue
            sender, subject = _decode(msg.get("From")), _decode(msg.get("Subject"))
            body = _body(msg)
            cat = classify_email(subject, body, sender)
            if cat == "other":
                continue
            stats["relevant"] += 1
            job = match_job(session, sender, subject, body, cat)
            stats["matched"] += int(job is not None)
            try:
                received = parsedate_to_datetime(msg.get("Date")).astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:  # noqa: BLE001
                received = None
            new_status = apply_email(session, job, cat, subject, run_id, received)
            stats["status_updates"] += int(new_status is not None)
            session.add(EmailMessage(message_id=mid[:500], sender=sender[:500], subject=subject[:1000], received_at=received,
                                     category=cat, job_id=job.id if job else None, snippet=body[:600], applied_status=new_status))
            session.commit()
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass
    set_value(session, "email_last_check", utcnow().isoformat())
    session.commit()
    return stats
