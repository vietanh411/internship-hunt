"""Runtime automation settings, editable from the dashboard and persisted in the DB."""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from hunt.models import SettingRow

AUTOMATION_KEY = "automation"

DEFAULT_WEIGHTS = {
    "skills": 30,
    "experience": 25,
    "education": 15,
    "location": 10,
    "eligibility_timing": 15,
    "compensation": 5,
}

DEFAULT_AUTOMATION: dict[str, Any] = {
    "automation_enabled": True,
    "paused": False,
    "apply_mode": "review",  # "auto" (Mode A) or "review" (Mode B)
    "preferred_cities": ["Madison, WI", "Chicago, IL", "Oklahoma City, OK", "Dallas, TX"],
    "include_nearby_metros": True,
    "include_remote_us": True,
    "include_other_us": True,
    "target_roles": [
        "Data Analyst Intern", "Data Science Intern", "Business Analyst Intern",
        "Software Engineering Intern", "Machine Learning Intern", "AI Intern",
        "Quantitative Analyst Intern", "Research Intern", "Statistics Intern",
        "Operations Research Intern", "Data Engineering Intern", "Analytics Intern",
    ],
    "daily_discovery_target": 30,
    "daily_resume_cap": 40,
    "daily_application_cap": 40,
    # Apply-first: each run submits until this many applications are confirmed today
    # (automatic + ones you finish), before looking for new jobs.
    "daily_submission_target": 30,
    "apply_loop_max_minutes": 120,
    # Sites that make you confirm you're human (Greenhouse emailed code, Lever CAPTCHA):
    # prepared for "Finish application" instead of being attempted automatically.
    "assisted_only_platforms": ["greenhouse", "lever"],
    "min_match_score": 55,
    "min_auto_apply_score": 70,
    "max_posting_age_days": 30,
    "scoring_weights": DEFAULT_WEIGHTS,
    "lesser_known_boost": 6,
    "resume": {
        "use_llm": True,
        "one_page": True,
        "max_projects": 3,
        "reword_bullets": True,
        "cover_letters": "when_required",  # when_required / always / never
    },
    "eligibility": {
        # How to treat "must be authorized to work without sponsorship" when the
        # posting does not mention future sponsorship. CPT/OPT is not employer
        # sponsorship, but many employers who write this exclude F-1 students.
        "no_sponsorship_current_only": "review",
        # "We do not sponsor H-1B / visas" with no explicit CPT/OPT exclusion.
        "no_visa_sponsorship_statement": "review",
        # Posting says nothing about work authorization.
        "unstated": "eligible",
    },
    "auto_contextual_answers": True,
    "blacklist": [],
    "whitelist": [],
    "sources": {
        "simplify": True,
        "vanshb03": True,
        "greenhouse": True,
        "lever": True,
        "ashby": True,
        "smartrecruiters": True,
        "workday": True,
    },
    "learn_boards_from_feeds": True,
    "max_learned_boards_per_run": 400,
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def get_automation(session: Session) -> dict:
    row = session.get(SettingRow, AUTOMATION_KEY)
    return _deep_merge(DEFAULT_AUTOMATION, row.value if row else {})


def update_automation(session: Session, patch: dict) -> dict:
    row = session.get(SettingRow, AUTOMATION_KEY)
    current = row.value if row else {}
    merged = _deep_merge(current, patch)
    if row is None:
        session.add(SettingRow(key=AUTOMATION_KEY, value=merged))
    else:
        row.value = merged
    session.flush()
    return get_automation(session)


def get_value(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(SettingRow, key)
    return row.value if row else default


def set_value(session: Session, key: str, value: Any) -> None:
    row = session.get(SettingRow, key)
    if row is None:
        session.add(SettingRow(key=key, value=value))
    else:
        row.value = value
    session.flush()
