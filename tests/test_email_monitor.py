"""Matching employer emails to applications (cases from real inbox mistakes)."""
import hashlib

from hunt.models import Application, Job, JobStatus
from hunt.notify.email_monitor import classify_email, match_job


def _job(s, company, title, status=JobStatus.READY_TO_APPLY):
    key = f"t:{company}:{title}"
    j = Job(uid=hashlib.sha1(key.encode()).hexdigest()[:16], canonical_key=key, company=company,
            company_norm=company.lower(), title=title, status=status.value, source="test", sources=["test"])
    s.add(j)
    s.flush()
    s.add(Application(job_id=j.id, idempotency_key=f"app:{key}"))
    s.flush()
    return j


def _match(s, sender, subject, body):
    return match_job(s, sender, subject, body, classify_email(subject, body, sender))


def test_partial_company_names_do_not_match(session):
    _job(session, "KLA", "PLM BI & Analytics Intern")
    _job(session, "Sage", "Software Engineering Intern (Full Stack)", JobStatus.BLOCKED)
    assert _match(session, "Klaviyo <no-reply@klaviyo.com>", "Thank you for applying to Klaviyo",
                  "Thank you for applying to the Machine Learning Engineer Internship-Summer 2027 role with Klaviyo") is None
    assert _match(session, "Live Oak Bank <talent@liveoak.bank>", "Application Received: Thank you",
                  "Thank you for applying to the Summer 2027 Intern: Software Engineering position at Live Oak Bank. "
                  "This message was sent automatically.") is None


def test_role_must_match_when_the_company_has_several_applications(session):
    analytics = _job(session, "Perpay", "Analytics Intern")
    _job(session, "Perpay", "Super Day - Data Science Internship", JobStatus.BLOCKED)
    sender = "Perpay <no-reply@ashbyhq.com>"
    assert _match(session, sender, "Perpay | Thank you for applying, Viet Anh!",
                  "Thank you for your interest in Analytics Internship, Summer 2027 at Perpay!") == analytics
    assert _match(session, sender, "Perpay | Thank you for applying, Viet Anh!",
                  "Thank you for your interest in Software Engineering Internship, Summer 2027 at Perpay!") is None


def test_confirmation_for_a_different_role_does_not_mark_submitted(session):
    _job(session, "Intel", "Software Research Engineering - (PhD Intern)")
    assert _match(session, "Intel <intel@myworkday.com>", "Thank You for Your Application!",
                  "Thank you for your interest in the Graduate Intern, Artificial Intelligence & Data Science - "
                  "Summer 2027 position at Intel.") is None


def test_rejection_without_a_role_matches_your_only_submitted_application(session):
    glean = _job(session, "Glean", "Software Engineer Intern", JobStatus.SUBMITTED)
    assert _match(session, "Glean Recruiting <no-reply@glean.com>", "Update from Glean",
                  "Unfortunately, we have decided to move forward with other candidates.") == glean


def test_email_about_a_closed_application_is_not_moved_to_another_role(session):
    analytics = _job(session, "Perpay", "Analytics Intern", JobStatus.REJECTED)
    _job(session, "Perpay", "Super Day - Data Science Internship", JobStatus.BLOCKED)
    body = ("Thank you for taking the time to apply to our Analytics Internship, Summer 2027 position! "
            "Unfortunately we decided to move forward with other candidates." + " " * 2000 +
            "Perpay builds data science products. Have a great day.")
    assert _match(session, "Perpay <no-reply@ashbyhq.com>", "Perpay | Thanks for your interest", body) == analytics


def test_verification_codes_are_read_from_real_email_formats():
    from hunt.notify.email_monitor import extract_code
    gh = ("Hi Viet Anh, Copy and paste this code into the security code field on your application: NojgLEvQ "
          "After you enter the code, resubmit your application.")
    assert extract_code("Security code for your application to Coinbase", gh) == "NojgLEvQ"
    assert extract_code("ByteDance verification code: 816339", "Your verification code is 816339. Valid for 30 minutes.") == "816339"
    assert extract_code("Verification code for ParkMobile.io", "ParkMobile A Smarter Way to Park. Please enter this "
                        "one-time password: 431907 Your code will expire in 10 minutes.") == "431907"
    assert extract_code("Transferology: Your Verification Code", "<p>Your verification code for Transferology is:</p> <p>328814</p>") == "328814"
    # not verification codes
    assert extract_code("You sent $70.00", "Bank Code vietnam_tech Confirmation Code BAN-261234-JL99") is None
    assert extract_code("Check out with just your iPhone", "you may need to enter your card's security code during set-up on iPhone") is None
    assert extract_code("Summer 2027 internships", "Use code SUMMER at checkout") is None


def test_newest_code_after_the_form_opened_is_chosen(monkeypatch):
    """Old codes (an earlier automatic attempt) are skipped; this employer's newest wins."""
    from datetime import datetime, timedelta, timezone
    from email.message import EmailMessage
    from email.utils import format_datetime
    from hunt.notify import email_monitor

    now = datetime(2026, 10, 18, 23, 30, tzinfo=timezone.utc)

    def msg(minutes_ago, company, code):
        m = EmailMessage()
        m["From"], m["Subject"] = "Greenhouse <no-reply@us.greenhouse-mail.io>", f"Security code for your application to {company}"
        m["Date"] = format_datetime(now - timedelta(minutes=minutes_ago))
        m.set_content(f"Copy and paste this code into the security code field on your application: {code} After you enter it, resubmit.")
        return m.as_bytes()

    inbox = [msg(25, "Point72", "OldCodeQx"), msg(1, "Arc", "ArcCodeZz"), msg(0.5, "Point72", "NewCodeRy")]

    class FakeIMAP:
        def __init__(self, host): pass
        def login(self, user, password): pass
        def select(self, box, readonly=True): return "OK", [str(len(inbox)).encode()]
        def search(self, charset, criteria): return "OK", [b" ".join(str(i + 1).encode() for i in range(len(inbox)))]
        def fetch(self, num, parts): return "OK", [(num, inbox[int(num) - 1])]
        def logout(self): pass

    monkeypatch.setattr(email_monitor.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(email_monitor, "imap_configured", lambda: True)
    opened = (now - timedelta(minutes=3)).replace(tzinfo=None)
    code, subject, received = email_monitor.find_verification_code(opened, "Point72")
    assert code == "NewCodeRy" and "Point72" in subject
    assert email_monitor.find_verification_code(opened, "Arc")[0] == "ArcCodeZz"
    assert email_monitor.find_verification_code((now + timedelta(minutes=1)).replace(tzinfo=None), "Point72") is None


def test_code_found_in_the_evening_when_utc_is_already_tomorrow(monkeypatch):
    """IMAP SINCE uses the mail server's own calendar date. At 10 pm in Chicago it is already
    tomorrow in UTC, so searching by the UTC date missed the code that had just arrived."""
    import re
    from datetime import datetime, timedelta, timezone
    from email.message import EmailMessage
    from email.utils import format_datetime
    from zoneinfo import ZoneInfo
    from hunt.notify import email_monitor

    sent = datetime(2026, 10, 21, 3, 5, tzinfo=timezone.utc)  # Oct 20, 10:05 pm in Chicago
    m = EmailMessage()
    m["From"], m["Subject"] = "Greenhouse <no-reply@us.greenhouse-mail.io>", "Security code for your application to Ai2"
    m["Date"] = format_datetime(sent)
    m.set_content("Copy and paste this code into the security code field on your application: Ai2CodeQx After you enter it, resubmit.")
    inbox = [(sent, m.as_bytes())]

    class GmailLikeIMAP:  # SINCE compares the date in the server's (Pacific) time zone
        def __init__(self, host): pass
        def login(self, user, password): pass
        def select(self, box, readonly=True): return "OK", [b"1"]
        def search(self, charset, criteria):
            day = datetime.strptime(re.search(r'SINCE "([^"]+)"', criteria).group(1), "%d-%b-%Y").date()
            hits = [str(i + 1).encode() for i, (when, _) in enumerate(inbox)
                    if when.astimezone(ZoneInfo("America/Los_Angeles")).date() >= day]
            return "OK", [b" ".join(hits)]
        def fetch(self, num, parts): return "OK", [(num, inbox[int(num) - 1][1])]
        def logout(self): pass

    monkeypatch.setattr(email_monitor.imaplib, "IMAP4_SSL", GmailLikeIMAP)
    monkeypatch.setattr(email_monitor, "imap_configured", lambda: True)
    opened = datetime(2026, 10, 21, 3, 4)  # form opened 10:04 pm Chicago (naive UTC)
    code, subject, _ = email_monitor.find_verification_code(opened, "Ai2")
    assert code == "Ai2CodeQx" and "Ai2" in subject
