# Internship Hunt

A personal pipeline that finds internship postings the day they go up, checks whether you're eligible, writes a tailored resume for each one, and fills the application in for you. You review every page and click submit yourself.

**Discover → Verify → Deduplicate → Eligibility → Match → Tailor resume → Fill application → Confirm → Report**

It runs every morning and comes with a local dashboard, the **Internship Command Center**.

> I built this with [Claude Code](https://claude.com/claude-code) for my own Summer 2027 internship search, and used it every day of that search. On its busiest day it helped me submit 44 applications.
> — Viet Anh Nguyen ([@vietanh411](https://github.com/vietanh411))

---

## Highlights

- **Finds jobs at the source.** Polls company job boards directly through the public APIs of Greenhouse, Lever, Ashby, SmartRecruiters and Workday, plus the community Summer 2027 internship lists. Fresh postings (today/yesterday) on quick-to-finish platforms go to the top of the queue.
- **Eligibility from the actual posting text.** Sentence-level rules for work authorization (citizenship, clearance, sponsorship, CPT/OPT), degree level and graduation window. Every verdict stores the sentence it was based on.
- **Tailored resumes that stay true.** Each resume is reordered and reworded toward the posting, then passed through a *fact guard* that rejects any number, tool or claim not already in your master resume. Rendered to a one-page, ATS-checked PDF.
- **Assisted "Finish all".** Opens each application in a real browser window and fills it from your profile and a library of answers you've written once: contact details, education and experience entries, dropdowns, dates, EEO policy, uploads. It handles Workday's multi-step flow, too. Anything it can't answer becomes a question for you, and your answer is saved for next time.
- **Inbox monitoring.** Optional read-only IMAP: marks applications submitted when the confirmation email arrives and shows emailed verification codes in the dashboard.
- **Safe by default.** Never fabricates, never solves CAPTCHAs or bot checks, never stores passwords, never scrapes LinkedIn/Indeed/Glassdoor/Handshake. Real submissions are off until you switch them on.

## Use it yourself

Requirements: Python 3.12+, Node 18+ (only to build the dashboard), Git.

```bash
git clone https://github.com/vietanh411/internship-hunt.git
cd internship-hunt
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cd frontend && npm install && npm run build && cd ..
cp .env.example .env
```

Then make it yours:

1. **Profile**: copy `config/profile.yaml` to `config/profile.local.yaml` and fill in your details (name, school, degree, graduation date, work authorization).
2. **Master resume**: copy `config/master_resume.yaml` to `config/master_resume.local.yaml` and put *everything true* about you in it. Tailoring can only use what's here.
3. **Cities**: copy `config/metros.example.yaml` to `config/metros.yaml` and list the metros you want to work in.
4. **Companies (optional)**: add employer job boards to `seeds/companies.yaml`. The included list is my own, which leans toward the Midwest and Texas.

The `*.local.yaml` files and `config/metros.yaml` are git-ignored, so your details never end up in a commit. Then:

```bash
python -m hunt init      # create the database, import your profile, resume and job boards
python -m hunt serve     # dashboard at http://127.0.0.1:8000 (+ the daily scheduler)
```

Open the dashboard → **Profile & Onboarding** and finish the checklist: confirm your work-authorization answers, the 18+ attestation and your EEO policy. Target roles, cities, score thresholds and daily caps are under **Automation**.

| Command | What it does |
|---|---|
| `python -m hunt run` | Run the whole pipeline once. |
| `python -m hunt run --dry-run` | Run it without contacting any real employer. |
| `python -m hunt dry-run` | Demo: real discovery and resumes, browser submissions to the **local mock ATS only**. |
| `python -m hunt keygen` | Generate a key for `HUNT_SECRET_KEY` (encrypts phone, address, visa status and EEO answers). |
| `python -m pytest tests` | Unit, integration and Playwright end-to-end tests against the mock ATS. |

Optional settings in `.env`: `ANTHROPIC_API_KEY` (Claude rewording, cover letters, open-ended answers; templates are used without it), `HUNT_IMAP_USER`/`HUNT_IMAP_PASSWORD` (Gmail app password for inbox monitoring), `HUNT_SMTP_*` (emailed daily report). The search targets **Summer 2027** internships; the term lives in `hunt/discovery/` and `hunt/matching.py`.

---

## How it works

1. **Discovery** (`hunt/discovery/`): community `listings.json` feeds plus direct polling of employer boards. Boards are seeded from `seeds/companies.yaml` and learned automatically from feed links. Filters: internship title, target roles, US location, term, posting age.
2. **Verification**: every posting is re-checked on the employer's site; closed or removed ones become **Expired**.
3. **Deduplication**: the same requisition across sites becomes one job (ATS id, then company + title + location).
4. **Eligibility** (`hunt/eligibility.py`): checks your profile against the posting's own words.

   | Posting says | Default verdict |
   |---|---|
   | CPT/OPT accepted, or generic "authorized to work" | Eligible |
   | "Without sponsorship" with no mention of the future | Review (configurable) |
   | Employer won't sponsor H-1B | Review (configurable) |
   | Future sponsorship excluded, citizenship / clearance / ITAR required | **Ineligible** for applicants it applies to |
   | Undergraduate-only (for graduate applicants) or PhD-only | **Ineligible** |
   | Nothing stated | Eligible (configurable) |

5. **Matching** (`hunt/matching.py`): a 0–100 score from editable weights (skills, experience, education, location, eligibility and timing, pay), with strengths, gaps and the resume bullets that back it up.
6. **Resume tailoring** (`hunt/resume/`): reorder → reword (fact-guarded) → render a one-page PDF → extract the text back out to verify it. Cover letters when required.
7. **Applications** (`hunt/apply/`): every form field gets an answer plan: **fixed** (profile facts), **saved** (your answer library), **contextual** (generated and fact-guarded), **sensitive** (EEO policy) or **ask me**. Then Playwright fills the form. Greenhouse, Lever and Ashby are single-page; Workday is driven step by step (sign-in pauses for you, the autofill step, entry syncing, date widgets, error checks).
8. **Confirmation & reporting**: **Submitted** is recorded only when a confirmation page or email is seen. A daily report goes to the dashboard and, optionally, your inbox.

Orchestration (`hunt/pipeline/`): a durable task queue with backoff, per-host rate limits, a run lock, per-item checkpoints, time budgets and recovery of interrupted work.

### Platforms

| Platform | Discovery | Applications |
|---|---|---|
| Greenhouse (incl. company-site embeds) | API | Assisted (emailed security codes shown in the dashboard) |
| Lever | API | Assisted |
| Ashby | API | Assisted or automatic |
| Workday | CXS API | Assisted, multi-step (you sign in; the rest is filled) |
| SmartRecruiters, iCIMS, others | API / feeds | Tailored resume + answer sheet for you to submit |

---

## What I learned building it

- **The real world is the hard part, not the model.** Workday's custom dropdowns and date pickers broke the filler over and over; one page "twitched" for two minutes because every field waited out a 15-second timeout. What fixed it was evidence: recording real sessions (screenshots, video, Playwright traces), dumping each step's layout, and building a mock Workday to test against.
- **Don't trust automation's output, including other people's.** Workday's own "autofill from resume" put the wrong text in names and job descriptions, so the filler now compares every prefilled value with the profile and fixes only what contradicts it.
- **Draw the lines on purpose.** The tool never invents an answer, never touches a CAPTCHA and never handles passwords. Instead, unknown questions come back to me once and are remembered, so the tool got more automatic over time without ever making things up.
- **Ranking matters as much as finding.** Applying early matters, so the queue puts postings from today and yesterday on quick-to-finish platforms first, not just the highest match scores.

---

## Running daily without your computer

- **GitHub Actions + free Postgres**: `.github/workflows/daily-hunt.yml` runs the pipeline at 9:00 America/Chicago. Add the `DATABASE_URL` and `HUNT_SECRET_KEY` secrets (plus the optional ones listed in the file) and set the repo variable `HUNT_ENABLE_SCHEDULE=true`. Use a **private** fork if you commit your real profile.
- **Always-on host**: `docker compose up -d`, or deploy the `Dockerfile` with `DATABASE_URL` set. Set `HUNT_DASHBOARD_PASSWORD` if the dashboard is reachable from the internet.
- **Windows Task Scheduler**: `scripts/register-windows-task.ps1` (daily run) and `scripts/register-dashboard-task.ps1` (dashboard at sign-in).

## Data & security

- Secrets live only in `.env` / CI secrets; your data lives in `data/` (git-ignored).
- Phone, address, visa status and EEO answers are encrypted at rest when `HUNT_SECRET_KEY` is set.
- The dashboard binds to localhost by default; password login is available.
- Every action and status change is written to an audit log. **Profile → Export** downloads everything; **Delete** wipes it.
- Real submissions require `HUNT_ALLOW_REAL_SUBMISSIONS=true` *and* your approval in the dashboard.

## Disclaimer

Use it responsibly: follow each site's terms, answer every question truthfully, and review every application before it's sent. You are responsible for what you submit.
