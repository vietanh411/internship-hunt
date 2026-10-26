"""Public job-board APIs of applicant-tracking systems. Each function lists a
company's postings (filtered to internships) and/or fetches one posting's detail.
These endpoints are the same public JSON the employers' own career pages use."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Callable

from hunt.db import utcnow
from hunt.discovery.base import RawPosting
from hunt.discovery.normalize import INTERN_RE, html_to_text, parse_salary
from hunt.http import PermanentHTTPError, PoliteClient


def _iso(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d
    except ValueError:
        return None


def _ms(v) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None


def is_intern_title(title: str) -> bool:
    return bool(INTERN_RE.search(title or ""))


class PostingGone(Exception):
    """The ATS reports the posting no longer exists (expired / filled)."""


# ------------------------------------------------------------------ Greenhouse

GH_API = "https://boards-api.greenhouse.io/v1/boards"


def greenhouse_company(client: PoliteClient, token: str) -> str | None:
    try:
        return client.get_json(f"{GH_API}/{token}").get("name")
    except PermanentHTTPError:
        return None


def _gh_posting(token: str, company: str, j: dict) -> RawPosting:
    text = html_to_text(j.get("content"))
    lo, hi, period, stxt = parse_salary(text)
    locs = [j.get("location", {}).get("name") or ""]
    for o in j.get("offices") or []:
        if o.get("location") and o["location"] not in locs:
            locs.append(o["location"])
    return RawPosting(
        source="greenhouse", company=company, title=j.get("title", ""),
        url=j.get("absolute_url") or f"https://job-boards.greenhouse.io/{token}/jobs/{j['id']}",
        apply_url=f"https://job-boards.greenhouse.io/{token}/jobs/{j['id']}",
        ats_platform="greenhouse", ats_board=token, ats_job_id=str(j["id"]),
        locations=[l for l in locs if l],
        date_posted=_iso(j.get("first_published") or j.get("updated_at")),
        description_text=text, salary_min=lo, salary_max=hi, salary_period=period, salary_text=stxt,
    )


def greenhouse_list(client: PoliteClient, token: str, company: str, interns_only: bool = True, **_) -> list[RawPosting]:
    data = client.get_json(f"{GH_API}/{token}/jobs", params={"content": "true"})
    return [_gh_posting(token, company, j) for j in data.get("jobs", [])
            if not interns_only or is_intern_title(j.get("title", ""))]


def greenhouse_job(client: PoliteClient, token: str, job_id: str, company: str = "") -> tuple[RawPosting, dict]:
    """Returns the posting plus its application questions."""
    try:
        j = client.get_json(f"{GH_API}/{token}/jobs/{job_id}", params={"questions": "true"})
    except PermanentHTTPError as e:
        if e.status == 404:
            raise PostingGone(f"greenhouse {token}/{job_id}") from e
        raise
    form = {
        "questions": j.get("questions") or [],
        "location_questions": j.get("location_questions") or [],
        "compliance": j.get("compliance") or [],
        "demographic_questions": j.get("demographic_questions") or {},
    }
    return _gh_posting(token, company or token, j), form


# ------------------------------------------------------------------ Lever

LEVER_API = "https://api.lever.co/v0/postings"


def _lever_posting(company_token: str, company: str, p: dict) -> RawPosting:
    parts = [p.get("descriptionPlain") or html_to_text(p.get("description"))]
    for lst in p.get("lists") or []:
        parts.append(lst.get("text", ""))
        parts.append(html_to_text(lst.get("content")))
    parts.append(p.get("additionalPlain") or html_to_text(p.get("additional")))
    text = "\n".join(x for x in parts if x)
    cats = p.get("categories") or {}
    locs = cats.get("allLocations") or ([cats["location"]] if cats.get("location") else [])
    sr = p.get("salaryRange") or {}
    lo, hi, period, stxt = (None, None, None, None)
    if sr.get("min"):
        interval = (sr.get("interval") or "").lower()
        period = "hour" if "hour" in interval else "year" if "year" in interval else "month" if "month" in interval else None
        lo, hi, stxt = float(sr["min"]), float(sr.get("max") or sr["min"]), f"{sr.get('currency', '')} {sr['min']}-{sr.get('max')} {interval}"
    else:
        lo, hi, period, stxt = parse_salary(text)
    return RawPosting(
        source="lever", company=company, title=p.get("text", ""),
        url=p.get("hostedUrl") or f"https://jobs.lever.co/{company_token}/{p['id']}",
        apply_url=p.get("applyUrl") or f"https://jobs.lever.co/{company_token}/{p['id']}/apply",
        ats_platform="lever", ats_board=company_token, ats_job_id=p["id"],
        locations=locs, date_posted=_ms(p.get("createdAt")), description_text=text,
        salary_min=lo, salary_max=hi, salary_period=period, salary_text=stxt,
        remote_hint=p.get("workplaceType"),
    )


def lever_list(client: PoliteClient, token: str, company: str, interns_only: bool = True, **_) -> list[RawPosting]:
    data = client.get_json(f"{LEVER_API}/{token}", params={"mode": "json"})
    return [_lever_posting(token, company, p) for p in data
            if not interns_only or is_intern_title(p.get("text", ""))]


def lever_job(client: PoliteClient, token: str, job_id: str, company: str = "") -> RawPosting:
    try:
        p = client.get_json(f"{LEVER_API}/{token}/{job_id}")
    except PermanentHTTPError as e:
        if e.status == 404:
            raise PostingGone(f"lever {token}/{job_id}") from e
        raise
    return _lever_posting(token, company or token, p)


# ------------------------------------------------------------------ Ashby

ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board"


def _ashby_posting(org: str, company: str, j: dict) -> RawPosting:
    text = j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml"))
    locs = [j.get("location")] if j.get("location") else []
    for s in j.get("secondaryLocations") or []:
        if s.get("location"):
            locs.append(s["location"])
    comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
    lo, hi, period, stxt = parse_salary(comp or text)
    return RawPosting(
        source="ashby", company=company, title=j.get("title", ""),
        url=j.get("jobUrl") or f"https://jobs.ashbyhq.com/{org}/{j['id']}",
        apply_url=j.get("applyUrl") or f"https://jobs.ashbyhq.com/{org}/{j['id']}/application",
        ats_platform="ashby", ats_board=org, ats_job_id=j["id"], locations=locs,
        date_posted=_iso(j.get("publishedAt")), description_text=text,
        salary_min=lo, salary_max=hi, salary_period=period, salary_text=stxt or comp or None,
        remote_hint="remote" if j.get("isRemote") else j.get("workplaceType"),
    )


def ashby_list(client: PoliteClient, org: str, company: str, interns_only: bool = True, **_) -> list[RawPosting]:
    data = client.get_json(f"{ASHBY_API}/{org}", params={"includeCompensation": "true"})
    return [_ashby_posting(org, company, j) for j in data.get("jobs", [])
            if j.get("isListed", True) and (not interns_only or is_intern_title(j.get("title", "")))]


# ------------------------------------------------------------------ SmartRecruiters

SR_API = "https://api.smartrecruiters.com/v1/companies"


def smartrecruiters_list(client: PoliteClient, company_id: str, company: str, max_details: int = 40,
                         prefilter: Callable[[str], bool] | None = None, known: set[str] | None = None, **_) -> list[RawPosting]:
    out = []
    data = client.get_json(f"{SR_API}/{company_id}/postings", params={"q": "intern", "limit": 100})
    for p in data.get("content", []):
        if not is_intern_title(p.get("name", "")):
            continue
        if prefilter and not prefilter(p.get("name", "")):
            continue
        if known and str(p["id"]) in known:
            continue
        if len(out) >= max_details:
            break
        out.append(smartrecruiters_job(client, company_id, p["id"], company))
    return out


def smartrecruiters_job(client: PoliteClient, company_id: str, job_id: str, company: str = "") -> RawPosting:
    try:
        p = client.get_json(f"{SR_API}/{company_id}/postings/{job_id}")
    except PermanentHTTPError as e:
        if e.status == 404:
            raise PostingGone(f"smartrecruiters {company_id}/{job_id}") from e
        raise
    sections = (p.get("jobAd") or {}).get("sections") or {}
    text = "\n\n".join(html_to_text(s.get("text")) for s in sections.values() if isinstance(s, dict))
    loc = p.get("location") or {}
    loc_s = ", ".join(x for x in [loc.get("city"), loc.get("region"), loc.get("country", "").upper()] if x)
    if loc.get("remote"):
        loc_s = (loc_s + " (Remote)").strip()
    lo, hi, period, stxt = parse_salary(text)
    return RawPosting(
        source="smartrecruiters", company=(p.get("company") or {}).get("name") or company, title=p.get("name", ""),
        url=p.get("postingUrl") or f"https://jobs.smartrecruiters.com/{company_id}/{job_id}",
        apply_url=p.get("applyUrl") or p.get("postingUrl"),
        ats_platform="smartrecruiters", ats_board=company_id, ats_job_id=str(job_id),
        locations=[loc_s] if loc_s else [], date_posted=_iso(p.get("releasedDate")), description_text=text,
        salary_min=lo, salary_max=hi, salary_period=period, salary_text=stxt,
    )


# ------------------------------------------------------------------ Workday

def _wd_parts(board: str) -> tuple[str, str, str]:
    host, tenant, site = board.split("|")
    return host, tenant, site


def _wd_posted(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.lower()
    now = utcnow()
    if "today" in s:
        return now
    if "yesterday" in s:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*days?", s)
    if m:
        return now - timedelta(days=int(m.group(1)))
    return None


def workday_list(client: PoliteClient, board: str, company: str, max_pages: int = 5,
                 searches: tuple[str, ...] = ("intern",), prefilter: Callable[[str], bool] | None = None,
                 known: set[str] | None = None, max_details: int = 30, max_seconds: float = 90, **_) -> list[RawPosting]:
    """Detail requests are the expensive part (one per posting at ~1 req/s), so
    postings are pre-filtered by title and skipped when already known."""
    host, tenant, site = _wd_parts(board)
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    seen: dict[str, dict] = {}
    for search in searches:
        for page in range(max_pages):
            data = client.post_json(url, {"appliedFacets": {}, "limit": 20, "offset": page * 20, "searchText": search})
            posts = data.get("jobPostings") or []
            for p in posts:
                t = p.get("title", "")
                if not (is_intern_title(t) and p.get("externalPath")):
                    continue
                if prefilter and not prefilter(t):
                    continue
                if known and p["externalPath"] in known:
                    continue
                seen.setdefault(p["externalPath"], p)
            if len(posts) < 20:
                break
    out = []
    import time as _time
    started, failures = _time.monotonic(), 0
    for path in list(seen)[:max_details]:
        if _time.monotonic() - started > max_seconds or failures >= 3:
            break  # remaining postings are picked up on later runs
        try:
            out.append(workday_job(client, board, path, company))
            failures = 0
        except PostingGone:
            continue
        except Exception:  # noqa: BLE001  (slow / erroring tenant)
            failures += 1
    return out


def workday_job(client: PoliteClient, board: str, external_path: str, company: str = "") -> RawPosting:
    host, tenant, site = _wd_parts(board)
    try:
        d = client.get_json(f"https://{host}/wday/cxs/{tenant}/{site}{external_path}")
    except PermanentHTTPError as e:
        if e.status in (404, 410):
            raise PostingGone(f"workday {board}{external_path}") from e
        if e.status == 403:
            # Workday answers a removed posting with 403 "permission denied"; if the same
            # site still lists jobs, the block is about this posting, not about us
            try:
                client.post_json(f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                                 {"limit": 1, "offset": 0, "searchText": "", "appliedFacets": {}})
            except Exception:  # noqa: BLE001
                raise e from None
            raise PostingGone(f"workday {board}{external_path} (403: posting removed)") from e
        raise
    info = d.get("jobPostingInfo") or {}
    if info.get("canApply") is False:
        raise PostingGone(f"workday {board}{external_path} (closed)")
    text = html_to_text(info.get("jobDescription"))
    locs = [info.get("location")] + list(info.get("additionalLocations") or [])
    lo, hi, period, stxt = parse_salary(text)
    org = (d.get("hiringOrganization") or {}).get("name")
    return RawPosting(
        source="workday", company=company or org or tenant, title=info.get("title", ""),
        url=info.get("externalUrl") or f"https://{host}/{site}{external_path}",
        apply_url=(info.get("externalUrl") or f"https://{host}/{site}{external_path}"),
        ats_platform="workday", ats_board=board, ats_job_id=external_path,
        locations=[l for l in locs if l], date_posted=_wd_posted(info.get("postedOn")),
        description_text=text, salary_min=lo, salary_max=hi, salary_period=period, salary_text=stxt,
        feed_flags={"req_id": info.get("jobReqId")},
    )


LISTERS: dict[str, Callable[..., list[RawPosting]]] = {
    "greenhouse": greenhouse_list,
    "lever": lever_list,
    "ashby": ashby_list,
    "smartrecruiters": smartrecruiters_list,
    "workday": workday_list,
}
