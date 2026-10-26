"""Applicant profile and master resume persistence.

Sensitive fields are split out of the profile JSON and stored Fernet-encrypted in
ProfileRow.secret_blob. Callers always see a merged plain dict."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hunt.config import get_settings
from hunt.models import MasterResume, ProfileRow
from hunt.security import decrypt_json, encrypt_json

SENSITIVE_PATHS = [
    "contact.phone",
    "contact.address_line1",
    "contact.postal_code",
    "work_authorization.visa_status",
    "eeo.gender",
    "eeo.race_ethnicity",
    "eeo.hispanic_latino",
    "eeo.veteran_status",
    "eeo.disability_status",
]

# Onboarding checklist: (path, label, required_for_auto_apply, help)
ONBOARDING_FIELDS: list[tuple[str, str, bool, str]] = [
    ("work_authorization.confirmed", "Confirm work authorization answers", True,
     "F-1; authorized to work via CPT/OPT; will require sponsorship now or in the future; not a US citizen or permanent resident."),
    ("attestations.is_over_18", "Are you at least 18 years old?", True, "Asked on most applications."),
    ("contact.city", "Current city", True, "Many forms ask for your current location."),
    ("contact.state", "Current state", True, ""),
    ("eeo.policy", "How to handle voluntary EEO self-identification", True,
     "'ask' stops for you on required EEO questions; 'decline' answers 'I don't wish to answer'."),
    ("contact.postal_code", "ZIP code", False, "Some Workday/iCIMS forms require it."),
    ("contact.address_line1", "Street address", False, "Only used when a form requires it. Stored encrypted."),
    ("contact.github_url", "GitHub URL", False, ""),
    ("contact.portfolio_url", "Portfolio / website URL", False, ""),
    ("education.current_gpa", "UW–Madison GPA (if you want it shared)", False, ""),
    ("education.current_start_date", "MS program start date (YYYY-MM)", False,
     "Greenhouse education sections often require the start month/year of your current degree, e.g. 2026-09."),
    ("availability.latest_end_date", "Latest internship end date", False, "Fall semester start, e.g. 2027-08-27."),
    ("attestations.has_relatives_at_employer", "Default answer: relatives employed at the company?", False, "Usually 'No'."),
    ("attestations.subject_to_noncompete", "Are you subject to a non-compete agreement?", False, ""),
    ("preferences.min_hourly_rate", "Minimum acceptable hourly pay", False, "Used for scoring only."),
]


def _get_path(d: dict, path: str) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _set_path(d: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = d
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def _pop_path(d: dict, path: str) -> Any:
    parts = path.split(".")
    cur = d
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            return None
        cur = cur[part]
    return cur.pop(parts[-1], None)


get_path = _get_path


def _deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _split(profile: dict) -> tuple[dict, dict]:
    plain = copy.deepcopy(profile)
    secret: dict = {}
    for p in SENSITIVE_PATHS:
        v = _pop_path(plain, p)
        if v is not None:
            secret[p] = v
    return plain, secret


def get_profile(session: Session) -> dict:
    row = session.get(ProfileRow, 1)
    if row is None:
        return {}
    data = copy.deepcopy(row.data or {})
    for p, v in decrypt_json(row.secret_blob).items():
        _set_path(data, p, v)
    return data


def save_profile(session: Session, profile: dict) -> dict:
    plain, secret = _split(_jsonable(profile))
    row = session.get(ProfileRow, 1)
    if row is None:
        row = ProfileRow(id=1)
        session.add(row)
    row.data = plain
    row.secret_blob = encrypt_json(secret)
    session.flush()
    return get_profile(session)


def update_profile(session: Session, patch: dict) -> dict:
    return save_profile(session, _deep_merge(get_profile(session), patch))


def onboarding_status(profile: dict) -> list[dict]:
    out = []
    for path, label, required, help_text in ONBOARDING_FIELDS:
        value = _get_path(profile, path)
        if path == "work_authorization.confirmed":
            done = value is True
        else:
            done = value not in (None, "")
        out.append({"path": path, "label": label, "required": required, "help": help_text,
                    "value": value, "complete": done})
    return out


def auto_apply_blockers(profile: dict) -> list[str]:
    return [f["label"] for f in onboarding_status(profile) if f["required"] and not f["complete"]]


# ---------------------------------------------------------------- master resume

def _jsonable(obj: Any) -> Any:
    """YAML parses 2027-05-30 as a date; store everything JSON-safe."""
    import datetime as _dt
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (_dt.date, _dt.datetime)):
        return obj.isoformat()
    return obj


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return _jsonable(yaml.safe_load(f))


def get_master_resume(session: Session) -> tuple[int, dict]:
    row = session.scalars(
        select(MasterResume).where(MasterResume.active.is_(True)).order_by(MasterResume.version.desc())
    ).first()
    if row is None:
        raise RuntimeError("No master resume imported. Run `hunt init`.")
    return row.version, row.data


def import_master_resume(session: Session, data: dict, source: str) -> int:
    validate_master_resume(data)
    current = session.scalars(select(MasterResume).where(MasterResume.active.is_(True))).all()
    for r in current:
        if r.data == data:
            return r.version
        r.active = False
    version = (session.scalar(select(func.max(MasterResume.version))) or 0) + 1
    session.add(MasterResume(version=version, data=data, source=source, active=True))
    session.flush()
    return version


def validate_master_resume(data: dict) -> None:
    for key in ("basics", "education", "experience", "projects", "skills"):
        if key not in data:
            raise ValueError(f"master resume missing section: {key}")
    seen = set()
    for section in ("experience", "projects"):
        for entry in data[section]:
            for b in entry.get("bullets", []):
                if b["id"] in seen:
                    raise ValueError(f"duplicate bullet id {b['id']}")
                seen.add(b["id"])


def config_file(name: str) -> Path:
    """config/<name>.local.yaml (private, git-ignored) when present, else the committed sample."""
    s = get_settings()
    local = s.config_dir / f"{name}.local.yaml"
    return local if local.exists() else s.config_dir / f"{name}.yaml"


def bootstrap_profile(session: Session) -> None:
    """Import profile.yaml and master_resume.yaml on first run."""
    if session.get(ProfileRow, 1) is None:
        save_profile(session, load_yaml(config_file("profile")))
    if session.scalar(select(func.count(MasterResume.id))) == 0:
        path = config_file("master_resume")
        import_master_resume(session, load_yaml(path), source=f"config/{path.name}")
