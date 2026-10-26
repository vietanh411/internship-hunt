from __future__ import annotations

from datetime import datetime

from hunt.models import Application, Job, PendingQuestion, PipelineRun, ResumeVersion


def iso(d: datetime | None) -> str | None:
    return d.isoformat() + "Z" if d else None


def job_summary(j: Job) -> dict:
    app: Application | None = j.application
    rv = j.resume_versions[-1] if j.resume_versions else None
    return {
        "id": j.id, "uid": j.uid, "company": j.company, "title": j.title, "location": j.location,
        "locations": j.locations or [], "remote_type": j.remote_type, "category": j.category or (j.feed_flags or {}).get("category"),
        "match_score": j.match_score, "match_tier": j.match_tier, "priority": j.priority,
        "eligibility": j.eligibility, "eligibility_category": j.eligibility_category,
        "status": j.status, "next_action": j.next_action, "date_posted": iso(j.date_posted),
        "date_discovered": iso(j.date_discovered), "status_updated_at": iso(j.status_updated_at),
        "salary_text": j.salary_text, "salary_min": j.salary_min, "salary_max": j.salary_max, "salary_period": j.salary_period,
        "source": j.source, "sources": j.sources or [], "ats_platform": j.ats_platform,
        "apply_url": j.apply_url, "posting_url": j.posting_url, "has_resume": rv is not None,
        "resume_version": rv.version_id if rv else None, "has_cover_letter": bool(app and app.cover_letter_artifact_id),
        "lesser_known": j.lesser_known, "verified_active": j.verified_active, "terms": j.terms or [],
        "term_status": (j.feed_flags or {}).get("term_status"),
        "apply_method": app.apply_method if app else None, "approved": bool(app and app.approved),
        "date_applied": iso(app.date_applied) if app else None, "is_test": j.is_test,
        "open_questions": len(app.unresolved or []) if app else 0,
    }


def resume_version(rv: ResumeVersion) -> dict:
    return {"id": rv.id, "version_id": rv.version_id, "created_at": iso(rv.created_at), "master_version": rv.master_version,
            "keywords": rv.keywords, "matched_keywords": rv.matched_keywords, "changes": rv.changes,
            "factcheck": rv.factcheck, "ats_check": {k: v for k, v in (rv.ats_check or {}).items() if k != "text_preview"},
            "match_score": rv.match_score, "llm_used": rv.llm_used,
            "download_url": f"/api/resumes/{rv.version_id}/pdf"}


def application(app: Application | None) -> dict | None:
    if app is None:
        return None
    return {"id": app.id, "apply_method": app.apply_method, "platform": app.platform, "approved": app.approved,
            "approved_at": iso(app.approved_at), "attempts": app.attempts, "last_attempt_at": iso(app.last_attempt_at),
            "date_applied": iso(app.date_applied), "confirmation_text": app.confirmation_text,
            "confirmation_source": app.confirmation_source, "last_error": app.last_error, "plan": app.plan,
            "unresolved": app.unresolved, "contradictions": app.contradictions,
            "evidence_url": f"/api/artifacts/{app.evidence_artifact_id}" if app.evidence_artifact_id else None,
            "cover_letter_url": f"/api/artifacts/{app.cover_letter_artifact_id}" if app.cover_letter_artifact_id else None}


def job_detail(j: Job) -> dict:
    d = job_summary(j)
    d.update({
        "description_text": j.description_text, "required_quals": j.required_quals, "preferred_quals": j.preferred_quals,
        "deadline": iso(j.deadline), "internship_dates": j.internship_dates, "degrees": j.degrees,
        "ats_board": j.ats_board, "ats_job_id": j.ats_job_id, "canonical_key": j.canonical_key,
        "verified_at": iso(j.verified_at), "verification_note": j.verification_note, "feed_flags": j.feed_flags,
        "eligibility_reasons": j.eligibility_reasons, "work_auth_text": j.work_auth_text,
        "score_breakdown": {k: v for k, v in (j.score_breakdown or {}).items() if not k.startswith("_")},
        "score_explanation": j.score_explanation, "notes": j.notes, "last_error": j.last_error,
        "resume_versions": [resume_version(rv) for rv in j.resume_versions],
        "application": application(j.application),
        "events": [{"from": e.from_status, "to": e.to_status, "reason": e.reason, "actor": e.actor,
                    "at": iso(e.created_at), "run_id": e.run_id} for e in j.events],
    })
    return d


def question(q: PendingQuestion, j: Job | None = None) -> dict:
    return {"id": q.id, "job_id": q.job_id, "question": q.question, "field_name": q.field_name, "field_type": q.field_type,
            "options": q.options, "required": q.required, "reason": q.reason, "answer": q.answer, "status": q.status,
            "created_at": iso(q.created_at), "company": j.company if j else None, "title": j.title if j else None}


def run(r: PipelineRun, with_stages: bool = False) -> dict:
    d = {"id": r.id, "trigger": r.trigger, "status": r.status, "dry_run": r.dry_run, "current_stage": r.current_stage,
         "started_at": iso(r.started_at), "finished_at": iso(r.finished_at), "stats": r.stats, "error": r.error,
         "cancel_requested": r.cancel_requested,
         "report_url": f"/api/artifacts/{r.report_artifact_id}" if r.report_artifact_id else None}
    if with_stages:
        d["stages"] = [{"stage": s.stage, "status": s.status, "started_at": iso(s.started_at), "finished_at": iso(s.finished_at),
                        "processed": s.processed, "error": s.error, "result": s.checkpoint} for s in r.stages]
    return d
