"""Parsing helpers shared by discovery sources: ATS URL parsing, company and title
normalisation, location / remote / term / salary extraction."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

# ------------------------------------------------------------------ text

def html_to_text(raw: str | None) -> str:
    if not raw:
        return ""
    s = raw
    if "&lt;" in s and "<" not in s[:200]:
        s = html.unescape(s)
    soup = BeautifulSoup(s, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("\n- ")
    for tag in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "ul", "ol", "tr"]):
        tag.insert_after("\n")
    text = soup.get_text()
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


# ------------------------------------------------------------------ ATS urls

@dataclass
class AtsRef:
    platform: str | None
    board: str | None = None
    job_id: str | None = None


_WD = re.compile(r"^(?P<tenant>[\w-]+)\.(?P<wd>wd\d+)\.myworkdayjobs\.com$", re.I)


def parse_ats_url(url: str | None) -> AtsRef:
    if not url:
        return AtsRef(None)
    try:
        parts = urlsplit(url)
    except ValueError:
        return AtsRef(None)
    host = parts.netloc.lower()
    segs = [s for s in parts.path.split("/") if s]
    qs = parse_qs(parts.query)

    if host.endswith("greenhouse.io"):
        if "embed" in segs and "for" in qs:
            return AtsRef("greenhouse", qs["for"][0].lower(), (qs.get("token") or [None])[0])
        if len(segs) >= 3 and segs[1] == "jobs":
            return AtsRef("greenhouse", segs[0].lower(), segs[2])
        if segs:
            return AtsRef("greenhouse", segs[0].lower(), (qs.get("gh_jid") or [None])[0])
    if "gh_jid" in qs:
        return AtsRef("greenhouse", None, qs["gh_jid"][0])
    if host == "jobs.lever.co" and len(segs) >= 2:
        return AtsRef("lever", segs[0].lower(), segs[1])
    if host == "jobs.ashbyhq.com" and len(segs) >= 2:
        return AtsRef("ashby", segs[0], segs[1])
    if host in ("jobs.smartrecruiters.com", "careers.smartrecruiters.com") and len(segs) >= 2:
        m = re.match(r"(\d{6,})", segs[1])
        return AtsRef("smartrecruiters", segs[0], m.group(1) if m else segs[1])
    m = _WD.match(host)
    if m:
        # /{locale}/{site}/job/... or /{site}/job/...
        if "job" in segs:
            i = segs.index("job")
            site_segs = segs[:i]
            if site_segs and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", site_segs[0]):
                site_segs = site_segs[1:]
            site = site_segs[-1] if site_segs else None
            if site:
                board = f"{host}|{m.group('tenant')}|{site}"
                return AtsRef("workday", board, "/" + "/".join(segs[i:]))
        return AtsRef("workday", None, None)
    if "icims.com" in host:
        m2 = re.search(r"/jobs/(\d+)", parts.path)
        return AtsRef("icims", host, m2.group(1) if m2 else None)
    if "oraclecloud.com" in host:
        m2 = re.search(r"/job/(\d+)", parts.path)
        return AtsRef("oracle", host, m2.group(1) if m2 else None)
    for key, name in (("successfactors", "successfactors"), ("taleo.net", "taleo"), ("jobvite.com", "jobvite"),
                      ("workable.com", "workable"), ("bamboohr.com", "bamboohr"), ("rippling.com", "rippling"),
                      ("paylocity.com", "paylocity"), ("ultipro.com", "ukg"), ("adp.com", "adp"),
                      ("eightfold.ai", "eightfold"), ("phenompeople", "phenom")):
        if key in host:
            return AtsRef(name, host, None)
    return AtsRef(None)


# ------------------------------------------------------------------ names

_SUFFIX = re.compile(
    r"\b(incorporated|inc|llc|l\.l\.c|corp|corporation|co|company|ltd|limited|plc|lp|llp|group|holdings|"
    r"the|usa|us|na|n\.a)\b\.?", re.I)


def normalize_company(name: str) -> str:
    s = name.lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = _SUFFIX.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_TITLE_NOISE = re.compile(
    r"\b(summer|fall|spring|winter|20\d\d|internship|intern|co-?op|program|-|–|—|\(|\)|,|:|/)\b", re.I)


def normalize_title(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[\(\)\[\],:/|–—-]+", " ", s)
    s = re.sub(r"\b(summer|fall|spring|winter|20\d\d|internship|interns?|co ?op|program)\b", " ", s)
    s = re.sub(r"\b(r|req|jr)[-_ ]?\d{4,}\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_REQ = re.compile(r"\b((?:R|REQ|JR|JOB|REQ-)[-_ ]?\d{4,}(?:-\d+)?)\b", re.I)


def extract_req_id(*texts: str | None) -> str | None:
    for t in texts:
        if t:
            m = _REQ.search(t)
            if m:
                return re.sub(r"[-_ ]", "", m.group(1)).upper()
    return None


# ------------------------------------------------------------------ title filters

INTERN_RE = re.compile(
    r"\b(interns?|internships?|co-?op|summer (?:analyst|associate|scholar|student|technology analyst)|"
    r"student (?:researcher|analyst|developer|engineer|programmer|assistant)|apprentice(?:ship)?)\b", re.I)

CATEGORY_RULES: list[tuple[str, re.Pattern]] = [
    ("quant", re.compile(r"\b(quant|quantitative|trading|trader|algorithmic)\b", re.I)),
    ("ml_ai", re.compile(r"\b(machine learning|ml|ai|artificial intelligence|deep learning|nlp|computer vision|llm|generative|genai)\b", re.I)),
    ("data_science", re.compile(r"\b(data scien\w*|statistic\w*|biostatistic\w*|decision scien\w*|applied scien\w*)\b", re.I)),
    ("data_engineering", re.compile(r"\b(data engineer\w*|analytics engineer\w*|data platform|etl|big data)\b", re.I)),
    ("operations_research", re.compile(r"\b(operations research|optimization|supply chain analyt\w*)\b", re.I)),
    ("data_analytics", re.compile(r"\b(data analy\w*|analytics|business intelligence|bi analyst|reporting analyst|insights?|data)\b", re.I)),
    ("business_analytics", re.compile(r"\b(business analy\w*|product analy\w*|strategy analy\w*|technology analyst|it analyst|systems analyst|financial analy\w*|risk analy\w*|actuar\w*)\b", re.I)),
    ("research", re.compile(r"\b(research)\b", re.I)),
    ("software", re.compile(r"\b(software|developer|swe|full[- ]?stack|back[- ]?end|front[- ]?end|web|mobile|devops|cloud|platform|sre|site reliability|programmer|engineering intern|application)\b", re.I)),
]

EXCLUDE_TITLE_RE = re.compile(
    r"\b(mechanical|electrical|civil|chemical|structural|manufacturing engineer|process engineer|hardware|"
    r"firmware|asic|fpga|rf |analog|pcb|nurs\w*|pharmac\w*|clinical|legal|attorney|paralegal|"
    r"recruit\w*|human resources|hr |payroll|marketing(?! analy)|sales(?! analy)|social media|graphic|"
    r"designer|ux|ui/ux|accounting|audit(?!.*data)|tax |construction|warehouse|driver|technician|"
    r"facilities|culinary|hospitality|retail|teacher|teaching|tutor|phd|ph\.d|doctoral|postdoc|mba)\b", re.I)


def classify_category(title: str, simplify_category: str | None = None) -> str | None:
    if EXCLUDE_TITLE_RE.search(title) and not re.search(r"\b(data|software|machine learning|analytics)\b", title, re.I):
        return None
    for name, rx in CATEGORY_RULES:
        if rx.search(title):
            return name
    sc = (simplify_category or "").lower()
    if "data" in sc or "ai" in sc or "ml" in sc:
        return "data_science"
    if "software" in sc:
        return "software"
    if "quant" in sc:
        return "quant"
    return None


# ------------------------------------------------------------------ locations

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
}
_STATE_NAMES = {v.lower(): k for k, v in STATES.items()}
NON_US = re.compile(
    r"\b(canada|ontario|toronto|vancouver|montreal|quebec|british columbia|alberta|uk|united kingdom|england|"
    r"london|ireland|dublin|india|bangalore|bengaluru|hyderabad|pune|germany|berlin|munich|france|paris|"
    r"netherlands|amsterdam|singapore|china|shanghai|beijing|hong kong|japan|tokyo|korea|seoul|taiwan|"
    r"australia|sydney|mexico|brazil|poland|spain|italy|switzerland|zurich|israel|tel aviv|sweden|"
    r"philippines|vietnam|romania|czech|portugal|argentina|colombia|costa rica|emea|apac|latam)\b", re.I)

METROS: dict[str, list[str]] = {
    "Madison, WI": ["madison", "middleton", "verona", "fitchburg", "sun prairie", "monona", "waunakee", "deforest"],
    "Chicago, IL": ["chicago", "evanston", "naperville", "schaumburg", "oak brook", "oakbrook", "deerfield",
                    "northbrook", "downers grove", "lombard", "itasca", "rosemont", "hoffman estates",
                    "lake forest", "lincolnshire", "skokie", "aurora", "elgin", "joliet", "bolingbrook", "lisle",
                    "glenview", "arlington heights", "riverwoods", "mettawa", "north chicago", "abbott park",
                    "waukegan", "vernon hills", "rolling meadows", "elk grove village", "des plaines",
                    "park ridge", "oak park", "warrenville", "westchester", "lake zurich", "libertyville",
                    "northfield", "bannockburn", "buffalo grove", "wheeling", "hammond", "west chicago"],
    "Oklahoma City, OK": ["oklahoma city", "norman", "edmond", "moore", "midwest city", "yukon", "mustang",
                          "tinker", "del city", "okc"],
    "Dallas, TX": ["dallas", "plano", "irving", "richardson", "frisco", "addison", "fort worth", "arlington, tx",
                   "carrollton", "lewisville", "allen", "mckinney", "garland", "grapevine", "coppell",
                   "southlake", "westlake", "las colinas", "farmers branch", "denton", "grand prairie",
                   "mansfield", "flower mound", "roanoke", "the colony", "dfw", "euless", "bedford"],
}
NEARBY_METROS: dict[str, list[str]] = {
    "Milwaukee, WI": ["milwaukee", "waukesha", "brookfield", "menomonee falls", "wauwatosa", "glendale, wi",
                      "pewaukee", "oak creek", "west allis", "mequon", "racine", "kenosha"],
    "Tulsa, OK": ["tulsa", "broken arrow", "owasso", "bartlesville"],
    "Rockford, IL": ["rockford", "janesville", "beloit"],
}


def is_remote(loc: str) -> bool:
    return bool(re.search(r"\b(remote|virtual|work from home|anywhere)\b", loc, re.I))


def is_us_location(loc: str) -> bool:
    l = loc.strip()
    if not l:
        return False
    if NON_US.search(l):
        return bool(re.search(r"\b(us|usa|united states)\b", l, re.I)) and not re.search(r"\bcanada\b", l, re.I)
    if re.search(r"\b(usa|u\.s\.a?|united states|us)\b", l, re.I):
        return True
    if is_remote(l):
        return True  # bare "Remote" is treated as US for US-sourced feeds; refined later by JD text
    if re.search(r",\s*([A-Z]{2})\b", l) and re.search(r",\s*([A-Z]{2})\b", l).group(1) in STATES:
        return True
    low = l.lower()
    if any(name in low for name in _STATE_NAMES):
        return True
    return any(c in low for cities in list(METROS.values()) + list(NEARBY_METROS.values()) for c in cities)


def metro_of(loc: str) -> tuple[str | None, str]:
    """Return (metro_name, tier) where tier is preferred / nearby / remote / other / non_us."""
    low = loc.lower()
    for metro, cities in METROS.items():
        if any(re.search(rf"\b{re.escape(c)}\b", low) for c in cities):
            if "arlington" in low and "tx" not in low and "texas" not in low and metro == "Dallas, TX":
                continue
            return metro, "preferred"
    for metro, cities in NEARBY_METROS.items():
        if any(re.search(rf"\b{re.escape(c)}\b", low) for c in cities):
            return metro, "nearby"
    if is_remote(loc):
        return None, "remote"
    if is_us_location(loc):
        return None, "other"
    return None, "non_us"


def remote_type(locations: list[str], text: str = "", hint: str | None = None) -> str:
    if hint:
        h = hint.lower()
        if "remote" in h:
            return "remote"
        if "hybrid" in h:
            return "hybrid"
        if "on" in h and "site" in h or h == "onsite":
            return "onsite"
    joined = " ".join(locations)
    if all(is_remote(l) for l in locations) and locations:
        return "remote"
    if re.search(r"\bhybrid\b", joined + " " + text[:3000], re.I):
        return "hybrid"
    if any(is_remote(l) for l in locations):
        return "remote"
    if re.search(r"\b(on-?site|in[- ]office|in[- ]person)\b", text[:5000], re.I):
        return "onsite"
    return "onsite" if locations else "unknown"


# ------------------------------------------------------------------ terms

TERM_RE = re.compile(r"\b(summer|fall|autumn|spring|winter)\s*(?:of\s*)?(20\d\d)\b|\b(20\d\d)\s*(summer|fall|spring|winter)\b", re.I)


def detect_terms(*texts: str | None) -> list[str]:
    found: list[str] = []
    for t in texts:
        if not t:
            continue
        for m in TERM_RE.finditer(t):
            season = (m.group(1) or m.group(4)).capitalize()
            year = m.group(2) or m.group(3)
            if season == "Autumn":
                season = "Fall"
            term = f"{season} {year}"
            if term not in found:
                found.append(term)
    return found


def summer_2027_status(title: str, text: str, feed_terms: list[str] | None = None) -> str:
    """confirmed / likely / unconfirmed / other_term"""
    if feed_terms:
        if "Summer 2027" in feed_terms:
            return "confirmed"
        if any(t != "N/A" for t in feed_terms):
            return "other_term"
    title_terms = detect_terms(title)
    if title_terms:
        return "confirmed" if "Summer 2027" in title_terms else "other_term"
    body_terms = detect_terms(text[:6000])
    if "Summer 2027" in body_terms:
        return "confirmed"
    if re.search(r"\b2027\b", title + " " + text[:4000]) and re.search(r"\bsummer\b", title + " " + text[:4000], re.I):
        return "confirmed"
    if body_terms and not any(t.endswith("2027") for t in body_terms):
        return "other_term"
    if re.search(r"\bsummer\b", title, re.I):
        return "likely"
    return "unconfirmed"


# ------------------------------------------------------------------ salary

_MONEY = r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s?(k|K)?"
SALARY_RE = re.compile(
    _MONEY + r"(?:\s*(?:-|–|—|to)\s*" + _MONEY + r")?\s*(?:/|per|an|a)?\s*(hour|hr|hourly|year|yr|annually|annual|month|mo|week|wk)?",
    re.I)


def parse_salary(text: str | None) -> tuple[float | None, float | None, str | None, str | None]:
    if not text:
        return None, None, None, None
    best = None
    for m in SALARY_RE.finditer(text):
        lo = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
        hi = float(m.group(3).replace(",", "")) * (1000 if m.group(4) else 1) if m.group(3) else lo
        unit = (m.group(5) or "").lower()
        if unit in ("hour", "hr", "hourly"):
            period = "hour"
        elif unit in ("month", "mo"):
            period = "month"
        elif unit in ("week", "wk"):
            period = "week"
        elif unit in ("year", "yr", "annually", "annual"):
            period = "year"
        else:
            period = "hour" if hi < 300 else ("year" if hi > 20000 else None)
        if period is None or lo < 7:
            continue
        if period == "hour" and hi > 400:
            continue
        cand = (lo, hi, period, m.group(0).strip())
        if best is None or (period == "hour" and best[2] != "hour"):
            best = cand
        if best[2] == "hour":
            break
    return best if best else (None, None, None, None)


def hourly_equivalent(lo: float | None, hi: float | None, period: str | None) -> float | None:
    if lo is None or period is None:
        return None
    mid = (lo + (hi or lo)) / 2
    return {"hour": mid, "week": mid / 40, "month": mid / 173, "year": mid / 2080}.get(period)
