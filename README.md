# Viet Anh's Summer 2027 Hunt

An internship pipeline that runs every day at **9:00 AM America/Chicago**:

**Discover → Verify → Deduplicate → Eligibility (CPT/OPT) → Match → Tailor resume → Prepare/submit application → Confirm → Report**

with a dashboard, the **Summer 2027 Internship Command Center**.

---

## Quick start (this PC)

```powershell
cd D:\claude\internship-hunt
.\.venv\Scripts\python.exe -m hunt init          # migrate DB, load profile + master resume + seed boards
.\.venv\Scripts\python.exe -m hunt serve         # dashboard at http://127.0.0.1:8000 (+ daily 9:00 scheduler)
```

`config/profile.yaml` and `config/master_resume.yaml` are sample files with placeholder contact details. Put your real ones in `config/profile.local.yaml` and `config/master_resume.local.yaml` (git-ignored); they take precedence when present.

Other commands:

| Command | What it does |
|---|---|
| `python -m hunt run` | Run the whole pipeline once (respects the dashboard settings). |
| `python -m hunt run --dry-run` | Run it with no contact to any real employer. |
| `python -m hunt run --stages discovery,verification` | Run only some stages. Every stage can be restarted safely. |
| `python -m hunt dry-run` | Full demo: real discovery, scoring and resumes, plus real browser submissions to the **local mock ATS only**. |
| `python -m hunt keygen` | Generate the key for `HUNT_SECRET_KEY`. |
| `python -m pytest tests` | Run the test suite (unit, integration, Playwright end-to-end against the mock ATS). |

The dashboard is in `frontend/` (React + TypeScript + Tailwind). Rebuild it with `npm install && npm run build`; the server serves `frontend/dist`.

---

## What's grounded in what

| Your request | How it's handled |
|---|---|
| Fabricate qualifications, numbers, projects, employers, or work authorization | **Not implemented, by design.** Lying on an application can get an offer rescinded, and misstating immigration status can put F-1 status at risk. The tailoring engine only reorders and rewords facts in `config/master_resume.yaml`. Every reworded bullet goes through a fact guard (`hunt/resume/factguard.py`) that rejects new numbers, tools, leadership claims, or names, and keeps the original text instead. To use a skill that isn't on the resume, add it to **Profile → confirmed extra skills**. |
| Circumvent CAPTCHAs / security controls | **Not implemented.** When the system detects a CAPTCHA, a bot check, a login wall, or MFA, it marks the application **Blocked** and alerts you to finish it yourself. |
| Scrape LinkedIn, Indeed, Glassdoor, Handshake, ZipRecruiter | **Not implemented.** Their terms prohibit automated scraping and they block it, which could get your accounts banned. Discovery uses public ATS job-board APIs (the same JSON employers' own career pages load) and the community-maintained Summer 2027 lists, which already aggregate those sites' postings and link to employer pages. |

---

## Pipeline

1. **Discovery** (`hunt/discovery/`)
   - Community feeds: SimplifyJobs and vanshb03 Summer 2027 `listings.json` (public GitHub data).
   - Direct employer boards, polled via public APIs: **Greenhouse, Lever, Ashby, SmartRecruiters, Workday**.
   - Boards come from `seeds/companies.yaml` (curated regional, lesser-known employers in Madison, Chicago, OKC and DFW) and are also learned automatically from feed URLs.
   - Direct polling finds postings before they appear on the lists. Lesser-known companies get a ranking boost.
   - Filters: internship title, target role categories, US location, Summer 2027 term, posting age, PhD-only.
2. **Verification**: each posting is re-checked on the employer's ATS (API, or the page itself with robots.txt honored). Closed or missing postings become **Expired**. Jobs are re-verified every 3 days.
3. **Deduplication**: the same requisition on several sites becomes one job. Matching uses the ATS id, then company + title + location / requisition id.
4. **Eligibility** (`hunt/eligibility.py`): sentence-level rules on the exact posting language, keeping these categories distinct:

   | Category | Default verdict |
   |---|---|
   | CPT/OPT accepted | Eligible |
   | Generic "authorized to work" | Eligible (CPT/OPT satisfies it) |
   | "Without sponsorship" with no mention of future | Review (configurable) |
   | Employer won't sponsor H-1B | Review (configurable) |
   | Applicants needing future sponsorship are excluded | **Ineligible** |
   | Citizenship / permanent residency / security clearance / ITAR US-person required, or F-1 explicitly excluded | **Ineligible** |
   | Nothing stated | Eligible (configurable) |

   Every verdict stores the quoted sentence. Ineligible jobs are never applied to.
5. **Matching** (`hunt/matching.py`): 0–100 score using your weights (skills 30 / experience 25 / education 15 / location 10 / eligibility+timing 15 / compensation 5, editable). Eligibility is a hard gate. Each score comes with strengths, gaps, missing required/preferred skills, and the resume bullets that support it. Tiers: Excellent ≥85, Strong ≥70, Moderate ≥55, Low.
6. **Resume tailoring** (`hunt/resume/`):
   - Reorders bullets, projects and skills toward the posting and aligns terminology.
   - Rewords bullets with Claude when `ANTHROPIC_API_KEY` is set, with every change fact-guarded.
   - Renders a one-page ATS-safe PDF matching your LaTeX template, then validates it by extracting the text back out.
   - Saves to `data/applications/2027/<company>/<job_id>/<version>/Resume_VietAnhNguyen.pdf`, and stores it in the database with its keywords, change log, fact-check, ATS check, version id and score.
   - Generates a cover letter when the form or posting requires one (or per your setting).
7. **Applications** (`hunt/apply/`):
   - Builds an answer plan for every form field: **fixed** (verified profile facts), **contextual** (generated and fact-guarded), **sensitive** (EEO, per your policy), or **human-required** (legal, ambiguous or unverifiable).
   - Checks for contradictions, then submits with Playwright.
   - Details in [How submission works](#how-submission-works).
8. **Confirmation**: optional Gmail monitoring over read-only IMAP. Classifies confirmations, interviews, assessments, rejections, offers and info requests, and updates the matching application. It never replies to anyone.
9. **Reporting**: daily report (dashboard, plus email to you if SMTP is set).

Orchestration (`hunt/pipeline/`):
- Durable DB task queue with exponential backoff.
- Per-host rate limits and Retry-After handling.
- A run lock (no duplicate runs), per-item commits (checkpointing), and stage failure isolation.
- Cancellation, time budgets, and recovery of interrupted work.

## How submission works

Applications are sent automatically only when **all** of these hold. Otherwise they wait in the dashboard with the reason.

- `HUNT_ALLOW_REAL_SUBMISSIONS=true` is set on the server (hard kill switch; default **false**).
- Mode A (auto) is selected and the score ≥ the auto-apply minimum, **or** you approved the application (Mode B, the default).
- Eligibility is **Eligible** (Review jobs need your approval).
- Onboarding is complete, including confirming the work-authorization answers.
- Every required question has a verified answer and there are no contradictions.
- The resume passed the fact check and the ATS check.
- The daily cap isn't reached and there's no prior submission to the same requisition.

**Submitted** is recorded only when a confirmation page or confirmation email is observed. If the submit button was clicked but no confirmation appeared, the application goes to **Blocked** for you to verify. It is never resubmitted automatically.

### Supported application platforms

| Platform | Discovery | Verification | Automatic submission |
|---|---|---|---|
| Greenhouse | ✅ API | ✅ API | ✅ Browser (questions read from the API in advance) |
| Lever | ✅ API | ✅ API | ✅ Browser (questions read from the live form) |
| Ashby | ✅ API | ✅ API | ✅ Browser (questions read from the live form) |
| SmartRecruiters | ✅ API | ✅ API | ➖ Manual packet |
| Workday | ✅ CXS API | ✅ | ➖ Manual: needs an applicant account per employer |
| iCIMS, Oracle, SuccessFactors, Taleo, others | via feeds | page check | ➖ Manual: needs an account |

For "Manual" jobs the system still tailors the resume and prepares an answer sheet. You submit through the link, then click **Mark submitted** (it asks for confirmation details).

The browser automation has been verified end to end against the local mock ATS. Per your instructions, no test applications were sent to real employers, so a live Greenhouse, Lever or Ashby submission hasn't been exercised yet. Selectors can drift when an ATS changes its markup. Failures then show up as **Failed**/**Blocked** with a screenshot, never as a false "Submitted".

---

## Running daily without your PC

`python -m hunt serve` runs the 9:00 scheduler only while the process is up. For PC-off operation, pick one:

**A. GitHub Actions + free Postgres (no server to manage)**
1. Push this folder to a GitHub repo (use a **private** one if you commit your real profile). `.env`, `data/` and `config/*.local.yaml` are git-ignored.
   The scheduled run is off until you set the repo variable `HUNT_ENABLE_SCHEDULE=true`.
2. Create a free Postgres database (e.g. Neon or Supabase) and copy its connection string as `postgresql+psycopg://…`.
3. Add repository secrets:
   - Required: `DATABASE_URL`, `HUNT_SECRET_KEY`
   - Optional: `ANTHROPIC_API_KEY`, `HUNT_IMAP_*`, `HUNT_SMTP_*`, `HUNT_NOTIFY_EMAIL`
4. Optional: set the repo variable `HUNT_ALLOW_REAL_SUBMISSIONS=true` once you've reviewed a few runs.
5. `.github/workflows/daily-hunt.yml` runs at 09:00 Chicago time year-round (it fires at both UTC offsets and exits outside the 9 o'clock hour).
6. Point the dashboard at the same `DATABASE_URL` (locally, or with option B) to watch it.

**B. Always-on host** (VPS / Render / Railway / Fly.io): `docker compose up -d`, or deploy the `Dockerfile` with `DATABASE_URL` set. Set `HUNT_DASHBOARD_PASSWORD` whenever the dashboard is reachable from the internet.

**C. This PC only**: `scripts\register-windows-task.ps1` registers a daily 9:00 Task Scheduler job. It runs only when the PC is on.

---

## Setup checklist

1. Open the dashboard → **Profile & Onboarding**:
   - Confirm the work-authorization statements.
   - Fill in city/state, the 18+ attestation, and the EEO policy.
   - Optionally add GitHub, portfolio, ZIP, latest end date and minimum pay.
2. **Answer library**: approve the standard "certify information is accurate" and privacy-consent acknowledgements if you want them reused.
3. Optional integrations (in `.env`):
   - `HUNT_SECRET_KEY`: encryption at rest. Set it **before** entering your address.
   - `ANTHROPIC_API_KEY`: Claude rewording, cover letters, open-ended answers. Without it, deterministic templates are used.
   - `HUNT_IMAP_USER` / `HUNT_IMAP_PASSWORD`: Gmail app password for inbox monitoring.
   - `HUNT_SMTP_*` + `HUNT_NOTIFY_EMAIL`: emailed daily report and alerts.
4. Review a few prepared applications in **Review** mode. Then, if you want, set `HUNT_ALLOW_REAL_SUBMISSIONS=true` and switch to Mode A.

## Data & security

- Secrets live only in `.env` / CI secrets.
- Phone, address, visa status and EEO answers are Fernet-encrypted when `HUNT_SECRET_KEY` is set.
- The dashboard binds to localhost unless configured otherwise; password login is available.
- Every user action and status transition is written to an audit log.
- Dashboard → Profile → **Export** downloads a zip of all data, including every resume version. **Delete** wipes job data, or everything.
