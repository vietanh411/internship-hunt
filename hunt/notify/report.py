"""Daily run report (markdown + HTML) and optional email delivery to the applicant."""
from __future__ import annotations

import html
import logging
import smtplib
from email.message import EmailMessage as Mail

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hunt.config import get_settings
from hunt.models import Application, Job, JobStatus, PendingQuestion, PipelineRun, ResumeVersion, StatusEvent

log = logging.getLogger(__name__)


def build_report(session: Session, run: PipelineRun) -> tuple[str, str, dict]:
    s = get_settings()
    base = f"http://{s.host}:{s.port}"
    stats = run.stats or {}
    started = run.started_at
    new_jobs = session.scalars(select(Job).where(Job.date_discovered >= started, Job.is_test.is_(False))).all()
    new_ids = {j.id for j in new_jobs}
    qualified = [j for j in new_jobs if j.eligibility == "eligible" and (j.match_score or 0) >= 55]
    inelig = [j for j in new_jobs if j.eligibility == "ineligible"]
    resumes = session.scalar(select(func.count(ResumeVersion.id)).where(ResumeVersion.created_at >= started)) or 0
    rows = session.execute(select(StatusEvent.to_status, Job.is_test).join(Job, Job.id == StatusEvent.job_id)
                           .where(StatusEvent.created_at >= started)).all()
    real_events = [st for st, test in rows if not test]
    test_events = [st for st, test in rows if test]
    attempted = real_events.count(JobStatus.APPLYING.value)
    submitted = real_events.count(JobStatus.SUBMITTED.value)
    blocked_or_failed = sum(1 for st in real_events if st in (JobStatus.BLOCKED.value, JobStatus.FAILED.value))
    mock = {"attempted": test_events.count(JobStatus.APPLYING.value), "submitted": test_events.count(JobStatus.SUBMITTED.value),
            "blocked": test_events.count(JobStatus.BLOCKED.value)}
    open_q = session.scalar(select(func.count(PendingQuestion.id)).where(PendingQuestion.status == "open")) or 0
    reviews = session.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.ELIGIBILITY_REVIEW.value)) or 0
    awaiting = session.scalars(select(Job).join(Application).where(Job.status == JobStatus.READY_TO_APPLY.value)).all()
    manual = [j for j in awaiting if j.application.apply_method == "manual"]
    approvals = [j for j in awaiting if j.application.apply_method == "browser" and not j.application.approved]
    top = sorted((j for j in new_jobs if j.eligibility != "ineligible" and j.match_score is not None),
                 key=lambda j: -(j.priority or 0))[:12]
    target = (stats.get("discovery") or {}).get("target", 30)
    headline = f"{len(qualified)} new qualified / {len(new_jobs)} discovered, {submitted} submitted"
    summary = {"headline": headline, "jobs_discovered": len(new_jobs), "qualified": len(qualified),
               "rejected_for_eligibility": len(inelig), "resumes_generated": resumes, "applications_attempted": attempted,
               "confirmed_submissions": submitted, "failed_or_blocked": blocked_or_failed, "open_questions": open_q,
               "eligibility_reviews": reviews, "manual_ready": len(manual), "awaiting_approval": len(approvals),
               "discovery_target": target, "target_met": len(qualified) >= target, "dry_run": run.dry_run,
               "mock_ats": mock}

    def row(j: Job) -> str:
        rv = j.resume_versions[-1] if j.resume_versions else None
        res = f" · [resume]({base}/api/jobs/{j.id}/resume)" if rv else ""
        return (f"- **{j.company}** — {j.title} ({j.location or 'n/a'}) · score {j.match_score:.0f} · {j.eligibility}"
                f" · [posting]({j.posting_url}){res} · [details]({base}/#/jobs/{j.id})")

    md = [f"# Summer 2027 Hunt — Run #{run.id} ({'DRY RUN' if run.dry_run else run.trigger})",
          f"Started {started:%Y-%m-%d %H:%M} UTC · status: {run.status}", "",
          f"- Jobs discovered: **{len(new_jobs)}** (target {target}; {'met' if summary['target_met'] else 'not met — fewer qualifying openings were available'})",
          f"- Qualified (eligible, score ≥ 55): **{len(qualified)}**",
          f"- Rejected for work-authorization: **{len(inelig)}**",
          f"- Resumes generated: **{resumes}**",
          f"- Applications attempted: **{attempted}** · confirmed submissions: **{submitted}** · failed/blocked: **{blocked_or_failed}**"]
    if any(mock.values()):
        md.append(f"- Local mock ATS (test only, not real employers): {mock['attempted']} attempted, "
                  f"{mock['submitted']} confirmed, {mock['blocked']} blocked")
    af = (stats.get("apply_first") or {})
    if af and "goal" in af:
        md.insert(3, f"- **Submitted today: {af.get('submitted_today', 0)} / {af.get('goal')}** "
                     f"({af.get('submitted_now', 0)} this run; stopped: {af.get('stop_reason')}). "
                     f"Waiting for you to Finish: {af.get('finish_queue', 0)}")
        summary.update(submitted_today=af.get("submitted_today", 0), submission_goal=af.get("goal"),
                       finish_queue=af.get("finish_queue", 0),
                       headline=f"{af.get('submitted_today', 0)}/{af.get('goal')} submitted today · {summary['headline']}")
    md += ["",
          "## Human actions required",
          f"- Questions to answer: {open_q}", f"- Eligibility reviews: {reviews}",
          f"- Applications awaiting approval: {len(approvals)}", f"- Ready for manual submission: {len(manual)}", "",
          "## Highest-ranking new opportunities"] + [row(j) for j in top]
    if (stats.get("application") or {}).get("not_submitted_reasons"):
        md += ["", "## Why some applications were not submitted"]
        md += [f"- {k}: {v}" for k, v in stats["application"]["not_submitted_reasons"].items()]
    skipped = (stats.get("discovery") or {}).get("skipped") or {}
    if skipped:
        md += ["", "## Skipped listings"] + [f"- {k}: {v}" for k, v in list(skipped.items())[:10]]
    md_text = "\n".join(md)
    html_doc = _to_html(md_text)
    return md_text, html_doc, summary


def _to_html(md: str) -> str:
    import re
    lines = []
    for line in md.splitlines():
        esc = html.escape(line)
        esc = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc)
        esc = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', esc)
        if line.startswith("# "):
            lines.append(f"<h1>{esc[2:]}</h1>")
        elif line.startswith("## "):
            lines.append(f"<h2>{esc[3:]}</h2>")
        elif line.startswith("- "):
            lines.append(f"<li>{esc[2:]}</li>")
        elif line:
            lines.append(f"<p>{esc}</p>")
    return ("<!doctype html><meta charset=utf-8><title>Summer 2027 Hunt report</title>"
            "<body style='font-family:system-ui,sans-serif;max-width:860px;margin:2rem auto;line-height:1.5'>"
            + "\n".join(lines) + "</body>")


def smtp_configured() -> bool:
    s = get_settings()
    return bool(s.smtp_user and s.smtp_password and s.notify_email)


def send_email(subject: str, text: str, html_body: str | None = None) -> bool:
    """Sends only to the applicant's own configured address (HUNT_NOTIFY_EMAIL)."""
    s = get_settings()
    if not smtp_configured():
        return False
    msg = Mail()
    msg["Subject"], msg["From"], msg["To"] = subject, s.smtp_user, s.notify_email
    msg.set_content(text)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("Report email failed: %s", e)
        return False


def deliver_report(md: str, html_doc: str, summary: dict) -> bool:
    return send_email(f"Summer 2027 Hunt: {summary['headline']}", md, html_doc)
