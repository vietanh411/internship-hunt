import { useEffect, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  CalendarPlus,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  ClipboardCheck,
  Copy,
  Download,
  ExternalLink as ExtIcon,
  Eye,
  FileText,
  Mail,
  RefreshCcw,
  RotateCcw,
  Send,
  ShieldAlert,
  Sparkles,
  StickyNote,
  ThumbsUp,
  XCircle,
} from 'lucide-react'
import { ApiError } from '../api/client'
import { useJob, useJobAction, useRegenerateResume, useSaveNotes, useSubmitNow } from '../api/hooks'
import type { Application, JobDetail, PlannedAnswer, ResumeVersion } from '../api/types'
import { AssistStatusPanel, canFinish, FinishButton } from '../components/assist'
import { EligibilityDecision, QuestionForm, StatusChangeDialog } from '../components/jobs'
import {
  Badge,
  Button,
  ButtonLink,
  Callout,
  Card,
  Chip,
  Dialog,
  EligibilityBadge,
  EmptyState,
  ErrorState,
  Field,
  RichText,
  ScoreBadge,
  Skeleton,
  StatusBadge,
  cx,
} from '../components/ui'
import { useToast } from '../components/ui/Toast'
import { DASH, fmtDate, fmtDateTime, fmtRelative, fmtSalary, hostOf, humanize, localInputToIsoWithOffset } from '../lib/format'
import { kindMeta, POST_SUBMISSION, statusMeta, tierOf, TIER_META, TONE_DOT, eligibilityMeta } from '../lib/status'

// ------------------------------------------------------------------ header

function Header({ job }: { job: JobDetail }) {
  const tier = tierOf(job.match_score)
  const locs = job.locations?.length ? job.locations : job.location ? [job.location] : []
  return (
    <div className="card p-4 sm:p-5">
      <div className="flex items-start gap-4">
        <ScoreBadge score={job.match_score} size="lg" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-slate-600 dark:text-slate-300">{job.company}</p>
            {job.lesser_known && <Badge tone="violet">lesser-known</Badge>}
            {job.is_test && <Badge tone="amber">test job</Badge>}
          </div>
          <h1 className="mt-0.5 text-lg font-semibold leading-snug tracking-tight text-slate-900 dark:text-white sm:text-xl">{job.title.trim()}</h1>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <StatusBadge status={job.status} />
            <EligibilityBadge eligibility={job.eligibility} />
            {tier && <Badge tone={TIER_META[tier].tone}>{TIER_META[tier].label} match</Badge>}
            {job.category && <Badge tone="slate">{humanize(job.category)}</Badge>}
            {job.remote_type && job.remote_type !== 'unknown' && <Badge tone="teal">{humanize(job.remote_type)}</Badge>}
            {job.verified_active === true && <Badge tone="emerald">Verified active</Badge>}
          </div>
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-slate-100 pt-4 text-sm dark:border-slate-800 sm:grid-cols-3 lg:grid-cols-6">
        <Meta label="Location" className="col-span-2 sm:col-span-1 lg:col-span-2">
          {locs.length ? locs.join(' · ') : DASH}
        </Meta>
        <Meta label="Salary">{fmtSalary(job)}</Meta>
        <Meta label="Posted">{fmtDate(job.date_posted)}</Meta>
        <Meta label="Discovered">{fmtDate(job.date_discovered)}</Meta>
        <Meta label="Deadline">{fmtDate(job.deadline)}</Meta>
        <Meta label="Sources" className="col-span-2 sm:col-span-1 lg:col-span-2">
          {job.sources?.length ? job.sources.map(humanize).join(', ') : humanize(job.source)}
          {job.ats_platform && <span className="text-slate-400"> · ATS {humanize(job.ats_platform)}</span>}
        </Meta>
        <Meta label="Term">{job.terms?.length ? job.terms.join(', ') : job.term_status ? humanize(job.term_status) : DASH}</Meta>
        {job.internship_dates && <Meta label="Dates">{job.internship_dates}</Meta>}
        {job.date_applied && <Meta label="Applied">{fmtDate(job.date_applied)}</Meta>}
      </dl>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {job.posting_url && (
          <ButtonLink href={job.posting_url} target="_blank" rel="noopener noreferrer" icon={<ExtIcon className="h-4 w-4" />}>
            Posting
          </ButtonLink>
        )}
        {job.apply_url && (
          <ButtonLink href={job.apply_url} target="_blank" rel="noopener noreferrer" variant="primary" icon={<ExtIcon className="h-4 w-4" />}>
            Apply{hostOf(job.apply_url) ? ` on ${hostOf(job.apply_url)}` : ''}
          </ButtonLink>
        )}
      </div>

      {job.next_action && (
        <Callout tone="violet" className="mt-4" icon={<Sparkles className="h-4 w-4" />} title="Next action">
          {job.next_action}
        </Callout>
      )}
      {job.last_error && (
        <Callout tone="red" className="mt-3" icon={<CircleAlert className="h-4 w-4" />} title="Last error">
          <span className="whitespace-pre-wrap">{job.last_error}</span>
        </Callout>
      )}
    </div>
  )
}

function Meta({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cx('min-w-0', className)}>
      <dt className="text-xs text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="mt-0.5 break-words font-medium text-slate-800 dark:text-slate-200">{children}</dd>
    </div>
  )
}

// ------------------------------------------------------------------ actions

function Actions({ job }: { job: JobDetail }) {
  const push = useToast()
  const approve = useJobAction('approve')
  const retry = useJobAction('retry')
  const submit = useSubmitNow()
  const regen = useRegenerateResume()
  const [gates, setGates] = useState<string[] | null>(null)
  const [statusOpen, setStatusOpen] = useState(false)
  const [icsOpen, setIcsOpen] = useState(false)
  const posted = POST_SUBMISSION.includes(job.status)
  const canRetry = job.status === 'blocked' || job.status === 'failed'

  const doSubmit = () =>
    submit.mutate(job.id, {
      onSuccess: () => {
        setGates(null)
        push('success', 'Submission queued', 'A background run will submit this application now.')
      },
      onError: (e) => {
        if (e instanceof ApiError && e.status === 409 && e.body && typeof e.body === 'object' && Array.isArray((e.body as { reasons?: unknown }).reasons)) {
          setGates((e.body as { reasons: string[] }).reasons)
        } else push('error', 'Submit failed', e instanceof Error ? e.message : String(e))
      },
    })

  return (
    <Card title="Actions" icon={<ClipboardCheck className="h-4 w-4 text-slate-400" />}>
      {!posted && job.application && canFinish(job) && (
        <div className="mb-3">
          <FinishButton job={job} size="md" full />
          <p className="mt-1.5 text-xs text-slate-500 dark:text-slate-400">
            {job.ats_platform === 'workday'
              ? 'Opens the Workday posting in a browser window on this PC. You sign in (or create the account); the system uploads your resume and fills each step; you review and click Submit. The confirmation is recorded automatically.'
              : 'Opens a browser window on this PC with every field filled in. You review it, click Submit, and enter any emailed code; the confirmation is recorded automatically.'}
          </p>
          <AssistStatusPanel jobId={job.id} />
        </div>
      )}
      <div className="grid grid-cols-2 gap-2 [&>button]:h-auto [&>button]:min-h-[2.25rem] [&>button]:whitespace-normal [&>button]:py-1.5 [&>button]:leading-tight">
        <Button
          variant="success"
          icon={<ThumbsUp className="h-4 w-4" />}
          disabled={!job.application || job.application.approved || posted}
          title={!job.application ? 'Application not prepared yet' : job.application.approved ? 'Already approved' : undefined}
          loading={approve.isPending}
          onClick={() => approve.mutate({ id: job.id }, { onSuccess: () => push('success', 'Approved', 'It will be submitted on the next run, or use Submit now.') })}
        >
          {job.application?.approved ? 'Approved' : 'Approve'}
        </Button>
        <Button variant="primary" icon={<Send className="h-4 w-4" />} loading={submit.isPending} disabled={posted} onClick={doSubmit}>
          Submit now
        </Button>
        <Button
          icon={<RotateCcw className="h-4 w-4" />}
          disabled={!canRetry}
          title={canRetry ? 'Re-prepare on the next run' : 'Only blocked or failed jobs can be retried'}
          loading={retry.isPending}
          onClick={() => retry.mutate({ id: job.id }, { onSuccess: () => push('success', 'Retry scheduled', 'It will be re-prepared on the next run.') })}
        >
          Retry
        </Button>
        <Button
          icon={<RefreshCcw className="h-4 w-4" />}
          disabled={posted}
          title={posted ? 'Already submitted; the submitted resume is preserved' : undefined}
          loading={regen.isPending}
          onClick={() => regen.mutate(job.id, { onSuccess: (rv) => push('success', 'Resume regenerated', rv.version_id) })}
        >
          Regenerate resume
        </Button>
        <Button icon={<Check className="h-4 w-4" />} onClick={() => setStatusOpen(true)}>
          Change status
        </Button>
        <Button icon={<CalendarPlus className="h-4 w-4" />} onClick={() => setIcsOpen(true)}>
          Add interview
        </Button>
      </div>
      {gates && (
        <Callout tone="amber" className="mt-3" icon={<ShieldAlert className="h-4 w-4" />} title="Not submitted — these gates are still closed:">
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {gates.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        </Callout>
      )}
      {statusOpen && <StatusChangeDialog open={statusOpen} onClose={() => setStatusOpen(false)} jobId={job.id} current={job.status} />}
      <InterviewDialog open={icsOpen} onClose={() => setIcsOpen(false)} job={job} />
    </Card>
  )
}

function InterviewDialog({ open, onClose, job }: { open: boolean; onClose: () => void; job: JobDetail }) {
  const [start, setStart] = useState('')
  const [minutes, setMinutes] = useState(45)
  const [location, setLocation] = useState('')
  const url = start
    ? `/api/jobs/${job.id}/interview.ics?start=${encodeURIComponent(localInputToIsoWithOffset(start))}&minutes=${minutes}${location ? `&location=${encodeURIComponent(location)}` : ''}`
    : undefined
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add interview to calendar"
      footer={
        <>
          <Button onClick={onClose}>Close</Button>
          <ButtonLink
            href={url}
            download
            variant="primary"
            aria-disabled={!url}
            className={!url ? 'pointer-events-none opacity-50' : ''}
            icon={<Download className="h-4 w-4" />}
            onClick={() => url && window.setTimeout(onClose, 300)}
          >
            Download .ics
          </ButtonLink>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-slate-600 dark:text-slate-300">
          {job.company} · {job.title.trim()}
        </p>
        <Field label="Start" htmlFor="ics-start" hint={`In your local time zone (${tz}).`} required>
          <input id="ics-start" type="datetime-local" className="input" value={start} onChange={(e) => setStart(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Duration (minutes)" htmlFor="ics-min">
            <input id="ics-min" type="number" min={5} max={480} step={5} className="input" value={minutes} onChange={(e) => setMinutes(Number(e.target.value) || 45)} />
          </Field>
          <Field label="Location / link" htmlFor="ics-loc">
            <input id="ics-loc" className="input" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Zoom link or address" />
          </Field>
        </div>
      </div>
    </Dialog>
  )
}

function Notes({ job }: { job: JobDetail }) {
  const [text, setText] = useState(job.notes ?? '')
  const save = useSaveNotes()
  const push = useToast()
  useEffect(() => setText(job.notes ?? ''), [job.notes])
  const dirty = text !== (job.notes ?? '')
  return (
    <Card title="Notes" icon={<StickyNote className="h-4 w-4 text-slate-400" />}>
      <label htmlFor="job-notes" className="sr-only">
        Notes
      </label>
      <textarea
        id="job-notes"
        className="input min-h-[7rem]"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Recruiter contacts, referral, interview prep…"
      />
      <div className="mt-2 flex justify-end">
        <Button size="sm" variant="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate({ id: job.id, notes: text }, { onSuccess: () => push('success', 'Notes saved') })}>
          Save notes
        </Button>
      </div>
    </Card>
  )
}

// ------------------------------------------------------------------ match

const COMPONENT_LABELS: Record<string, string> = {
  skills: 'Skills',
  experience: 'Experience',
  education: 'Education',
  location: 'Location',
  eligibility_timing: 'Eligibility & timing',
  compensation: 'Compensation',
}

function MatchPanel({ job }: { job: JobDetail }) {
  const ex = job.score_explanation ?? {}
  const breakdown = Object.entries(job.score_breakdown ?? {})
  if (job.match_score == null && !breakdown.length) {
    return (
      <Card title="Match">
        <EmptyState compact title="Not scored yet" description="Matching runs after eligibility screening. Ineligible postings are not scored." />
      </Card>
    )
  }
  return (
    <Card title="Match" subtitle={ex.summary ?? undefined}>
      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Score breakdown</h3>
          <ul className="space-y-3">
            {breakdown.map(([k, v]) => (
              <li key={k}>
                <div className="flex items-baseline justify-between gap-2 text-sm">
                  <span className="font-medium text-slate-700 dark:text-slate-200">{COMPONENT_LABELS[k] ?? humanize(k)}</span>
                  <span className="text-xs text-slate-500 tabular dark:text-slate-400">
                    <span className="font-semibold text-slate-800 dark:text-slate-100">{v.points.toFixed(1)}</span> pts · {Math.round(v.score)}/100 · weight {v.weight}
                  </span>
                </div>
                <div
                  className="mt-1 h-2 overflow-hidden rounded-full"
                  style={{ background: 'var(--meter-track)' }}
                  role="meter"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(v.score)}
                  aria-label={`${COMPONENT_LABELS[k] ?? k} score`}
                >
                  <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, v.score))}%`, background: 'var(--meter-fill)' }} />
                </div>
              </li>
            ))}
          </ul>
          {(ex.missing_required?.length || ex.missing_preferred?.length || ex.matched_skills?.length) ? (
            <div className="mt-5 space-y-3">
              {!!ex.matched_skills?.length && (
                <SkillRow label="Matched skills" items={ex.matched_skills} tone="good" />
              )}
              {!!ex.missing_required?.length && <SkillRow label="Missing required" items={ex.missing_required} tone="bad" />}
              {!!ex.missing_preferred?.length && <SkillRow label="Missing preferred" items={ex.missing_preferred} tone="warn" />}
            </div>
          ) : null}
        </div>
        <div className="space-y-5">
          {!!ex.strengths?.length && (
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Strengths</h3>
              <ul className="space-y-1.5">
                {ex.strengths.map((s) => (
                  <li key={s} className="flex gap-2 text-sm text-slate-700 dark:text-slate-300">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />
                    <span>{s}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {!!ex.gaps?.length && (
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Gaps</h3>
              <ul className="space-y-1.5">
                {ex.gaps.map((s) => (
                  <li key={s} className="flex gap-2 text-sm text-slate-700 dark:text-slate-300">
                    <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />
                    <span>{s}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
      {!!ex.evidence?.length && (
        <div className="mt-6">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Evidence from your resume</h3>
          <ul className="space-y-2">
            {ex.evidence.map((e) => (
              <li key={e.bullet_id} className="rounded-lg border border-slate-100 bg-slate-50/60 p-3 dark:border-slate-800 dark:bg-slate-800/40">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs font-semibold text-slate-600 dark:text-slate-300">{e.entry}</p>
                  <span className="text-xs text-slate-400 tabular">relevance {(e.relevance * 100).toFixed(0)}%</span>
                </div>
                <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
                  <RichText text={e.text} />
                </p>
                {!!e.skills?.length && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {e.skills.map((s) => (
                      <Chip key={s}>{s}</Chip>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  )
}

function SkillRow({ label, items, tone }: { label: string; items: string[]; tone: 'good' | 'bad' | 'warn' }) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-slate-500 dark:text-slate-400">{label}</p>
      <div className="flex flex-wrap gap-1">
        {items.map((s) => (
          <Chip key={s} tone={tone}>
            {s}
          </Chip>
        ))}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ eligibility

function EligibilityPanel({ job }: { job: JobDetail }) {
  const m = eligibilityMeta(job.eligibility)
  const reasons = job.eligibility_reasons ?? []
  const snippets = (job.work_auth_text ?? []).filter((s) => !reasons.some((r) => r.quote === s))
  const needsReview = job.status === 'eligibility_review' || job.eligibility === 'review'
  return (
    <Card title="Eligibility" subtitle="Work-authorization screening for an F-1 student using CPT/OPT.">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={m.tone} dot>
          {m.label}
        </Badge>
        {job.eligibility_category && <span className="text-sm text-slate-600 dark:text-slate-300">{humanize(job.eligibility_category)}</span>}
      </div>
      {reasons.length ? (
        <ul className="mt-3 space-y-2.5">
          {reasons.map((r, i) => (
            <li key={i} className="rounded-lg border border-slate-100 p-3 dark:border-slate-800">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={eligibilityMeta(r.verdict).tone}>{eligibilityMeta(r.verdict).label}</Badge>
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">{r.rule}</span>
              </div>
              {r.quote ? (
                <blockquote className="mt-2 border-l-2 border-slate-300 pl-3 text-sm italic text-slate-600 dark:border-slate-600 dark:text-slate-300">“{r.quote}”</blockquote>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-slate-500 dark:text-slate-400">No work-authorization statements were found in the posting.</p>
      )}
      {snippets.length > 0 && (
        <div className="mt-3">
          <p className="mb-1 text-xs font-medium text-slate-500 dark:text-slate-400">Other work-authorization text</p>
          {snippets.map((s) => (
            <blockquote key={s} className="mt-1 border-l-2 border-slate-300 pl-3 text-sm italic text-slate-600 dark:border-slate-600 dark:text-slate-300">
              “{s}”
            </blockquote>
          ))}
        </div>
      )}
      {needsReview && (
        <div className="mt-4">
          <p className="mb-2 text-sm font-medium text-slate-800 dark:text-slate-100">Your decision</p>
          <EligibilityDecision jobId={job.id} />
        </div>
      )}
    </Card>
  )
}

// ------------------------------------------------------------------ description

function Description({ job }: { job: JobDetail }) {
  const [open, setOpen] = useState(false)
  const text = job.description_text?.trim()
  return (
    <Card
      title="Full description"
      actions={
        text ? (
          <Button size="xs" variant="ghost" onClick={() => setOpen((o) => !o)} aria-expanded={open} icon={<ChevronDown className={cx('h-4 w-4 transition-transform', open && 'rotate-180')} />}>
            {open ? 'Collapse' : 'Expand'}
          </Button>
        ) : undefined
      }
    >
      {!text ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">The full posting text could not be retrieved. Open the posting to read it.</p>
      ) : (
        <div className="relative">
          <div className={cx('whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-700 dark:text-slate-300', !open && 'max-h-48 overflow-hidden')}>{text}</div>
          {!open && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-white dark:from-slate-900" />}
        </div>
      )}
      {(!!job.required_quals?.length || !!job.preferred_quals?.length) && (
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {!!job.required_quals?.length && (
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Required</h3>
              <ul className="list-disc space-y-1 pl-4 text-sm text-slate-700 dark:text-slate-300">
                {job.required_quals.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </div>
          )}
          {!!job.preferred_quals?.length && (
            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Preferred</h3>
              <ul className="list-disc space-y-1 pl-4 text-sm text-slate-700 dark:text-slate-300">
                {job.preferred_quals.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

// ------------------------------------------------------------------ resumes

function ResumeVersionCard({ rv, latest }: { rv: ResumeVersion; latest: boolean }) {
  const [open, setOpen] = useState(latest)
  const fc = rv.factcheck ?? {}
  const ats = rv.ats_check ?? {}
  const matched = new Set(rv.matched_keywords ?? [])
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700">
      <div className="flex flex-wrap items-center justify-between gap-2 p-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs font-semibold text-slate-800 dark:text-slate-200">{rv.version_id}</span>
            {latest && <Badge tone="indigo">latest</Badge>}
            <Badge tone={ats.passed ? 'emerald' : 'red'}>{ats.passed ? 'ATS passed' : 'ATS issues'}</Badge>
            <Badge tone={fc.passed === false ? 'red' : 'emerald'}>{fc.passed === false ? 'Fact check reverted edits' : 'Fact check passed'}</Badge>
            <Badge tone={rv.llm_used ? 'violet' : 'slate'}>{rv.llm_used ? 'LLM reworded' : 'Deterministic'}</Badge>
          </div>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {fmtDateTime(rv.created_at)} · master v{rv.master_version} · score at generation {rv.match_score != null ? Math.round(rv.match_score) : DASH}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ButtonLink href={`${rv.download_url}?inline=true`} target="_blank" rel="noopener noreferrer" size="xs" icon={<Eye className="h-3.5 w-3.5" />}>
            Open
          </ButtonLink>
          <ButtonLink href={rv.download_url} size="xs" icon={<Download className="h-3.5 w-3.5" />}>
            Download
          </ButtonLink>
          <Button size="xs" variant="ghost" onClick={() => setOpen((o) => !o)} aria-expanded={open} icon={<ChevronDown className={cx('h-3.5 w-3.5 transition-transform', open && 'rotate-180')} />}>
            Details
          </Button>
        </div>
      </div>
      {open && (
        <div className="space-y-5 border-t border-slate-100 p-3 dark:border-slate-800">
          <div>
            <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">Posting keywords</h4>
            <div className="flex flex-wrap gap-1">
              {(rv.keywords ?? []).map((k) => (
                <Chip key={k} tone={matched.has(k) ? 'good' : 'neutral'} title={matched.has(k) ? 'On your tailored resume' : 'Not on your resume'}>
                  {matched.has(k) ? '✓ ' : ''}
                  {k}
                </Chip>
              ))}
              {!rv.keywords?.length && <span className="text-sm text-slate-500">{DASH}</span>}
            </div>
            {ats.keyword_coverage && (
              <p className="mt-1.5 text-xs text-slate-500 dark:text-slate-400">
                Keyword coverage in the PDF text: {(ats.keyword_coverage.ratio * 100).toFixed(0)}% ({ats.keyword_coverage.present.length}/
                {ats.keyword_coverage.present.length + ats.keyword_coverage.absent.length})
              </p>
            )}
          </div>

          <div>
            <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">Change log</h4>
            {rv.changes?.length ? (
              <ul className="space-y-2">
                {rv.changes.map((c, i) => (
                  <li key={i} className="text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone="slate">{humanize(c.type)}</Badge>
                      {(c.entry || c.bullet) && <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{c.entry ?? c.bullet}</span>}
                    </div>
                    {c.detail && <p className="mt-0.5 text-slate-600 dark:text-slate-300">{c.detail}</p>}
                    {(c.before || c.after) && (
                      <div className="mt-1 grid gap-1 sm:grid-cols-2">
                        <div className="rounded border border-red-100 bg-red-50/60 p-2 text-xs text-slate-700 dark:border-red-500/20 dark:bg-red-500/5 dark:text-slate-300">
                          <span className="mb-0.5 block font-semibold text-red-700 dark:text-red-300">Before</span>
                          {c.before}
                        </div>
                        <div className="rounded border border-emerald-100 bg-emerald-50/60 p-2 text-xs text-slate-700 dark:border-emerald-500/20 dark:bg-emerald-500/5 dark:text-slate-300">
                          <span className="mb-0.5 block font-semibold text-emerald-700 dark:text-emerald-300">After</span>
                          {c.after}
                        </div>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-500 dark:text-slate-400">No changes from the master resume.</p>
            )}
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <div>
              <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">Fact check</h4>
              {!!fc.violations_reverted?.length && (
                <div className="mb-2">
                  <p className="text-xs font-medium text-red-700 dark:text-red-300">Reverted to master wording:</p>
                  <ul className="list-disc pl-4 text-xs text-slate-600 dark:text-slate-300">
                    {fc.violations_reverted.map((v) => (
                      <li key={v}>{v}</li>
                    ))}
                  </ul>
                </div>
              )}
              {fc.rejected_rewrites?.length ? (
                <div className="mb-2 space-y-1.5">
                  <p className="text-xs font-medium text-amber-700 dark:text-amber-300">Rejected rewrites ({fc.rejected_rewrites.length})</p>
                  {fc.rejected_rewrites.map((r, i) => (
                    <div key={i} className="rounded border border-amber-200 bg-amber-50/60 p-2 text-xs dark:border-amber-500/20 dark:bg-amber-500/5">
                      <p className="font-mono text-[11px] text-slate-500">{r.bullet}</p>
                      <p className="mt-0.5 text-slate-700 line-through decoration-amber-500/60 dark:text-slate-300">{r.proposed}</p>
                      <p className="mt-0.5 text-amber-800 dark:text-amber-200">{Array.isArray(r.issues) ? r.issues.join('; ') : String(r.issues)}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mb-2 text-xs text-slate-500 dark:text-slate-400">No rejected rewrites.</p>
              )}
              {!!fc.rules?.length && (
                <ul className="space-y-0.5 text-xs text-slate-500 dark:text-slate-400">
                  {fc.rules.map((r) => (
                    <li key={r} className="flex gap-1.5">
                      <Check className="mt-0.5 h-3 w-3 shrink-0 text-emerald-600" aria-hidden />
                      {r}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">ATS checks</h4>
              <ul className="space-y-1">
                {(ats.checks ?? []).map((c) => (
                  <li key={c.name} className="flex items-start gap-2 text-xs">
                    {c.passed ? (
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" aria-label="passed" />
                    ) : (
                      <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-600 dark:text-red-400" aria-label="failed" />
                    )}
                    <span className="min-w-0">
                      <span className="font-medium text-slate-700 dark:text-slate-200">{humanize(c.name)}</span>
                      {c.detail && <span className="break-words text-slate-500 dark:text-slate-400"> — {c.detail}</span>}
                    </span>
                  </li>
                ))}
                {!ats.checks?.length && <li className="text-xs text-slate-500">{DASH}</li>}
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Resumes({ job }: { job: JobDetail }) {
  const versions = [...(job.resume_versions ?? [])].reverse()
  const cover = job.application?.cover_letter_url ?? (job.has_cover_letter ? `/api/jobs/${job.id}/cover-letter` : null)
  return (
    <Card
      title="Tailored resumes"
      icon={<FileText className="h-4 w-4 text-slate-400" />}
      subtitle={versions.length ? `${versions.length} version${versions.length > 1 ? 's' : ''}` : undefined}
      actions={
        cover ? (
          <div className="flex gap-2">
            <ButtonLink href={`/api/jobs/${job.id}/cover-letter?inline=true`} target="_blank" rel="noopener noreferrer" size="xs" icon={<Eye className="h-3.5 w-3.5" />}>
              Cover letter
            </ButtonLink>
            <ButtonLink href={`/api/jobs/${job.id}/cover-letter`} size="xs" icon={<Download className="h-3.5 w-3.5" />} aria-label="Download cover letter" />
          </div>
        ) : undefined
      }
    >
      {versions.length ? (
        <div className="space-y-3">
          {versions.map((rv, i) => (
            <ResumeVersionCard key={rv.id} rv={rv} latest={i === 0} />
          ))}
        </div>
      ) : (
        <EmptyState
          compact
          icon={<FileText className="h-5 w-5" />}
          title="No tailored resume yet"
          description="Resumes are generated for eligible postings above the minimum match score. You can also use Regenerate resume."
        />
      )}
    </Card>
  )
}

// ------------------------------------------------------------------ application

/** Copies a planned answer, for pasting into the employer's form in your own browser. */
function CopyValue({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      className="ml-2 inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 align-middle text-xs text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:hover:bg-slate-800 dark:hover:text-slate-200"
      title="Copy this answer"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => {
          setCopied(true)
          window.setTimeout(() => setCopied(false), 1500)
        })
      }}
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

function AnswerValue({ a }: { a: PlannedAnswer }) {
  if (a.value === null || a.value === undefined || a.value === '') return <span className="text-slate-400">{DASH}</span>
  if (a.kind === 'sensitive') return <span className="text-slate-500">•••• (sensitive)</span>
  if (a.kind === 'file') return <span className="text-slate-500">Tailored resume (use the Resume download)</span>
  const text = Array.isArray(a.value) ? a.value.join(', ') : String(a.value)
  return (
    <span className="whitespace-pre-wrap break-words">
      {text}
      <CopyValue text={text} />
    </span>
  )
}

function ApplicationPanel({ job }: { job: JobDetail }) {
  const app: Application | null = job.application
  const openQs = (job.questions ?? []).filter((q) => q.status === 'open')
  const answeredQs = (job.questions ?? []).filter((q) => q.status !== 'open')
  if (!app) {
    return (
      <Card title="Application">
        <EmptyState compact icon={<Send className="h-5 w-5" />} title="Application not prepared yet" description="The application stage prepares the form answers after a tailored resume exists." />
      </Card>
    )
  }
  const plan = app.plan ?? {}
  const answers = plan.live_answers?.length ? plan.live_answers : plan.answers ?? []
  return (
    <Card
      title="Application"
      icon={<Send className="h-4 w-4 text-slate-400" />}
      subtitle={plan.prepared_at ? `Prepared ${fmtRelative(plan.prepared_at)}` : undefined}
      actions={app.evidence_url ? <ButtonLink href={app.evidence_url} target="_blank" rel="noopener noreferrer" size="xs" icon={<Eye className="h-3.5 w-3.5" />}>Evidence screenshot</ButtonLink> : undefined}
    >
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-4">
        <Meta label="Method">{humanize(app.apply_method)}</Meta>
        <Meta label="Platform">{humanize(app.platform ?? plan.platform)}</Meta>
        <Meta label="Approved">{app.approved ? `Yes · ${fmtDate(app.approved_at)}` : 'No'}</Meta>
        <Meta label="Attempts">
          {app.attempts}
          {app.last_attempt_at ? <span className="text-slate-400"> · {fmtRelative(app.last_attempt_at)}</span> : null}
        </Meta>
        {plan.form_url && (
          <Meta label="Form" className="col-span-2">
            <a href={plan.form_url} target="_blank" rel="noopener noreferrer" className="link break-all">
              {hostOf(plan.form_url) || plan.form_url} ↗
            </a>
            {plan.form_source && <span className="text-slate-400"> · {humanize(plan.form_source)}</span>}
          </Meta>
        )}
        {app.date_applied && <Meta label="Applied">{fmtDateTime(app.date_applied)}</Meta>}
      </dl>

      <div className="mt-4 space-y-3">
        {plan.manual_reason && (
          <Callout tone="sky" title="Manual application">
            {plan.manual_reason}
          </Callout>
        )}
        {!!app.contradictions?.length && (
          <Callout tone="red" icon={<ShieldAlert className="h-4 w-4" />} title="Contradictory answers">
            <ul className="list-disc space-y-0.5 pl-4">
              {app.contradictions.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </Callout>
        )}
        {app.confirmation_text && (
          <Callout tone="emerald" icon={<CheckCircle2 className="h-4 w-4" />} title={`Confirmation${app.confirmation_source ? ` (${app.confirmation_source})` : ''}`}>
            <span className="whitespace-pre-wrap">{app.confirmation_text}</span>
          </Callout>
        )}
        {app.last_error && (
          <Callout tone="red" icon={<CircleAlert className="h-4 w-4" />} title="Last submission error">
            <span className="whitespace-pre-wrap">{app.last_error}</span>
          </Callout>
        )}
        {!!plan.notes?.length && (
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-slate-500 dark:text-slate-400">
            {plan.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </div>

      {openQs.length > 0 && (
        <div className="mt-5">
          <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
            Unresolved questions <Badge tone="rose">{openQs.length}</Badge>
          </h3>
          <div className="space-y-3">
            {openQs.map((q) => (
              <QuestionForm key={q.id} q={q} showJob={false} />
            ))}
          </div>
        </div>
      )}
      {openQs.length === 0 && !!app.unresolved?.length && (
        <Callout tone="amber" className="mt-4" title="Answers saved — re-prepare needed">
          All questions for this job have been answered or dismissed, but the prepared plan still lists {app.unresolved.length} unresolved item(s). Use Retry so the next run re-prepares it.
        </Callout>
      )}

      <div className="mt-5">
        <h3 className="mb-2 text-sm font-semibold text-slate-900 dark:text-white">Planned answers</h3>
        {answers.length ? (
          <div className="relative -mx-4 overflow-x-auto sm:mx-0">
            <table className="w-full min-w-[34rem] text-sm">
              <thead>
                <tr className="table-head">
                  <th className="px-3 py-2">Field</th>
                  <th className="px-3 py-2">Source</th>
                  <th className="px-3 py-2">Value</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {answers.map((a, i) => {
                  const km = kindMeta(a.kind)
                  return (
                    <tr key={`${a.name}-${i}`} className="align-top">
                      <td className="max-w-[16rem] px-3 py-2">
                        <span className="font-medium text-slate-800 dark:text-slate-200">{a.label}</span>
                        {a.required && <span className="ml-1 text-xs text-red-600 dark:text-red-400">*</span>}
                        {a.reason && <p className="text-xs text-slate-500 dark:text-slate-400">{a.reason}</p>}
                      </td>
                      <td className="px-3 py-2">
                        <Badge tone={km.tone} title={km.help}>
                          {km.label}
                        </Badge>
                      </td>
                      <td className="max-w-[22rem] px-3 py-2 text-slate-700 dark:text-slate-300">
                        <AnswerValue a={a} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-slate-500 dark:text-slate-400">No form fields were planned.</p>
        )}
      </div>

      {answeredQs.length > 0 && (
        <div className="mt-5">
          <h3 className="mb-2 text-sm font-semibold text-slate-900 dark:text-white">Answered questions</h3>
          <ul className="space-y-1.5 text-sm">
            {answeredQs.map((q) => (
              <li key={q.id} className="flex flex-wrap gap-x-2">
                <span className="text-slate-600 dark:text-slate-300">{q.question}</span>
                <span className="font-medium text-slate-900 dark:text-white">{q.status === 'dismissed' ? <Badge tone="gray">dismissed</Badge> : q.answer}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  )
}

// ------------------------------------------------------------------ timeline

function Timeline({ job }: { job: JobDetail }) {
  const events = [...(job.events ?? [])].reverse()
  return (
    <Card title="Activity">
      {events.length ? (
        <ol className="relative space-y-4 border-l border-slate-200 pl-4 dark:border-slate-700">
          {events.map((e, i) => (
            <li key={i} className="relative">
              <span className={cx('absolute -left-[1.33rem] top-1.5 h-2.5 w-2.5 rounded-full ring-4 ring-white dark:ring-slate-900', TONE_DOT[statusMeta(e.to).tone])} aria-hidden />
              <div className="flex flex-wrap items-center gap-1.5">
                {e.from && (
                  <>
                    <StatusBadge status={e.from} />
                    <span className="text-xs text-slate-400" aria-label="to">
                      →
                    </span>
                  </>
                )}
                <StatusBadge status={e.to} />
              </div>
              {e.reason && <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">{e.reason}</p>}
              <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                {fmtDateTime(e.at)} · {e.actor}
                {e.run_id != null && (
                  <>
                    {' · '}
                    <Link to={`/runs/${e.run_id}`} className="link">
                      run #{e.run_id}
                    </Link>
                  </>
                )}
              </p>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-sm text-slate-500 dark:text-slate-400">No status changes recorded yet.</p>
      )}
    </Card>
  )
}

function Emails({ job }: { job: JobDetail }) {
  if (!job.emails?.length) return null
  return (
    <Card title="Related emails" icon={<Mail className="h-4 w-4 text-slate-400" />}>
      <ul className="space-y-2 text-sm">
        {job.emails.map((m, i) => (
          <li key={i}>
            <p className="font-medium text-slate-800 dark:text-slate-200">{m.subject}</p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {m.sender} · {humanize(m.category)} · {fmtDateTime(m.received_at)}
            </p>
          </li>
        ))}
      </ul>
    </Card>
  )
}

// ------------------------------------------------------------------ page

export default function JobDetailPage() {
  const { id } = useParams()
  const jobId = Number(id)
  const { data: job, isLoading, error, refetch } = useJob(jobId)

  return (
    <div>
      <Link to="/jobs" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white">
        <ArrowLeft className="h-4 w-4" /> Opportunities
      </Link>
      {error && !job ? (
        <div className="card">
          <ErrorState error={error} onRetry={() => refetch()} />
        </div>
      ) : isLoading || !job ? (
        <div className="space-y-4">
          <Skeleton className="h-56 w-full rounded-xl" />
          <div className="grid gap-4 lg:grid-cols-3">
            <Skeleton className="h-96 rounded-xl lg:col-span-2" />
            <Skeleton className="h-96 rounded-xl" />
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          <Header job={job} />
          <div className="grid items-start gap-6 lg:grid-cols-3">
            {/* Actions come first on small screens, top of the sidebar on desktop */}
            <div className="min-w-0 lg:col-start-3 lg:row-start-1">
              <Actions job={job} />
            </div>
            <div className="min-w-0 space-y-6 lg:col-span-2 lg:col-start-1 lg:row-span-2 lg:row-start-1">
              <MatchPanel job={job} />
              <EligibilityPanel job={job} />
              <ApplicationPanel job={job} />
              <Resumes job={job} />
              <Description job={job} />
            </div>
            <div className="min-w-0 space-y-6 lg:col-start-3 lg:row-start-2">
              <Notes job={job} />
              <Timeline job={job} />
              <Emails job={job} />
              <p className="px-1 text-xs text-slate-400">
                {statusMeta(job.status).help} Job #{job.id} · {job.uid}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
