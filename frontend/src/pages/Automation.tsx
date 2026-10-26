import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  Building2,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleSlash,
  FlaskConical,
  Play,
  Plus,
  Power,
  Save,
  Server,
  ShieldCheck,
  Square,
  Undo2,
  XCircle,
} from 'lucide-react'
import { useAddBoard, useAutomationAction, useBoards, usePatchBoard, usePatchSettings, useSettings, useStartRun, useStatus } from '../api/hooks'
import type { AutomationSettings, StatusResponse } from '../api/types'
import { Badge, Button, Callout, Card, Dialog, EmptyState, ErrorState, Field, PageHeader, Skeleton, SkeletonRows, TagInput, Toggle, cx } from '../components/ui'
import { useToast } from '../components/ui/Toast'
import { fmtDateTime, fmtNumber, fmtRelative, humanize } from '../lib/format'

const IMMEDIATE_KEYS = ['automation_enabled', 'paused', 'apply_mode']

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T
}

function diff(base: AutomationSettings, draft: AutomationSettings): Partial<AutomationSettings> {
  const out: Record<string, unknown> = {}
  for (const k of Object.keys(draft)) {
    if (IMMEDIATE_KEYS.includes(k)) continue
    if (JSON.stringify(draft[k]) !== JSON.stringify(base[k])) out[k] = draft[k]
  }
  return out as Partial<AutomationSettings>
}

// ------------------------------------------------------------------ controls

function Controls({ status }: { status: StatusResponse | undefined }) {
  const act = useAutomationAction()
  const start = useStartRun()
  const push = useToast()
  const active = status?.active_run
  const busy = (a: string) => act.isPending && act.variables === a
  return (
    <Card title="Controls" icon={<Power className="h-4 w-4 text-slate-400" />}>
      {!status ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <div className="space-y-4">
          <Toggle
            label="Automation enabled"
            description="When off, scheduled runs are skipped entirely. Manual runs still work."
            checked={status.automation_enabled}
            disabled={act.isPending}
            onChange={(v) => act.mutate(v ? 'enable' : 'disable', { onSuccess: () => push('success', v ? 'Automation enabled' : 'Automation disabled') })}
          />
          <Toggle
            label="Paused"
            description="Temporarily skip scheduled runs and block automatic submissions without changing other settings."
            checked={status.paused}
            disabled={act.isPending}
            onChange={(v) => act.mutate(v ? 'pause' : 'resume', { onSuccess: () => push('success', v ? 'Automation paused' : 'Automation resumed') })}
          />
          <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
            <Button
              variant="primary"
              icon={<Play className="h-4 w-4" />}
              disabled={!!active}
              loading={busy('start')}
              onClick={() => act.mutate('start', { onSuccess: () => push('success', 'Run started') })}
            >
              Run now
            </Button>
            <Button
              icon={<FlaskConical className="h-4 w-4" />}
              disabled={!!active}
              loading={start.isPending}
              onClick={() => start.mutate({ dry_run: true }, { onSuccess: () => push('success', 'Dry run started', 'No employer will be contacted.') })}
            >
              Dry run
            </Button>
            <Button
              variant="danger"
              icon={<Square className="h-4 w-4" />}
              disabled={!active || active.cancel_requested}
              loading={busy('stop')}
              onClick={() =>
                act.mutate('stop', {
                  onSuccess: (r) => push(r.cancel_requested ? 'success' : 'info', r.cancel_requested ? 'Stop requested' : 'No active run to stop'),
                })
              }
            >
              {active?.cancel_requested ? 'Stopping…' : 'Stop'}
            </Button>
          </div>
          <dl className="grid grid-cols-1 gap-3 border-t border-slate-100 pt-4 text-sm dark:border-slate-800 sm:grid-cols-2">
            <div>
              <dt className="text-xs text-slate-500 dark:text-slate-400">Active run</dt>
              <dd className="mt-0.5 font-medium">
                {active ? (
                  <Link to={`/runs/${active.id}`} className="link">
                    #{active.id} · {active.current_stage ? humanize(active.current_stage) : 'starting'}
                  </Link>
                ) : (
                  'None'
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500 dark:text-slate-400">Last run</dt>
              <dd className="mt-0.5 font-medium">
                {status.last_run ? (
                  <Link to={`/runs/${status.last_run.id}`} className="link">
                    #{status.last_run.id} {status.last_run.status} · {fmtRelative(status.last_run.finished_at ?? status.last_run.started_at)}
                  </Link>
                ) : (
                  'No runs yet'
                )}
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-xs text-slate-500 dark:text-slate-400">Next scheduled run</dt>
              <dd className="mt-0.5 font-medium">
                {status.next_run ? `${fmtDateTime(status.next_run)} (${fmtRelative(status.next_run)})` : '—'}
                <span className="ml-1 font-normal text-slate-500 dark:text-slate-400">· {status.schedule}</span>
              </dd>
              {!status.scheduler_running && (
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  The in-process scheduler isn't running on this server, so the next run relies on an external trigger (cron or GitHub Actions).
                </p>
              )}
            </div>
          </dl>
        </div>
      )}
    </Card>
  )
}

function ApplyMode({ status, settings }: { status: StatusResponse | undefined; settings: AutomationSettings }) {
  const patch = usePatchSettings()
  const push = useToast()
  const [confirmAuto, setConfirmAuto] = useState(false)
  const set = (mode: 'auto' | 'review') =>
    patch.mutate({ apply_mode: mode }, { onSuccess: () => push('success', mode === 'auto' ? 'Mode A: automatic submission' : 'Mode B: review before submitting') })
  const modes = [
    {
      id: 'auto' as const,
      title: 'Mode A — Automatic',
      body: 'Qualifying applications are submitted automatically, but only when every answer on the form is verified (no unanswered questions, no contradictions), the posting is eligible, the score is at least the auto-apply minimum, the resume passed ATS and fact checks, and onboarding is complete.',
    },
    {
      id: 'review' as const,
      title: 'Mode B — Review first',
      body: 'Applications are fully prepared, then wait in the Review queue. Nothing is submitted until you approve it (or press Submit now on the job).',
    },
  ]
  return (
    <Card title="Apply mode" icon={<ShieldCheck className="h-4 w-4 text-slate-400" />}>
      <div role="radiogroup" aria-label="Apply mode" className="grid gap-3 sm:grid-cols-2">
        {modes.map((m) => {
          const selected = settings.apply_mode === m.id
          return (
            <button
              key={m.id}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={patch.isPending}
              onClick={() => (selected ? undefined : m.id === 'auto' ? setConfirmAuto(true) : set('review'))}
              className={cx(
                'rounded-xl border-2 p-4 text-left transition',
                selected
                  ? 'border-indigo-600 bg-indigo-50/60 dark:border-indigo-400 dark:bg-indigo-500/10'
                  : 'border-slate-200 hover:border-slate-300 dark:border-slate-700 dark:hover:border-slate-600',
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-slate-900 dark:text-white">{m.title}</span>
                <span
                  className={cx('flex h-4 w-4 items-center justify-center rounded-full border-2', selected ? 'border-indigo-600 dark:border-indigo-400' : 'border-slate-300 dark:border-slate-600')}
                  aria-hidden
                >
                  {selected && <span className="h-2 w-2 rounded-full bg-indigo-600 dark:bg-indigo-400" />}
                </span>
              </div>
              <p className="mt-1.5 text-sm text-slate-600 dark:text-slate-300">{m.body}</p>
            </button>
          )
        })}
      </div>
      {status && (
        <Callout tone={status.allow_real_submissions ? 'emerald' : 'amber'} className="mt-4" icon={status.allow_real_submissions ? <CheckCircle2 className="h-4 w-4" /> : <CircleSlash className="h-4 w-4" />}>
          Real submissions to employers additionally require <code className="rounded bg-black/5 px-1 font-mono text-xs dark:bg-white/10">HUNT_ALLOW_REAL_SUBMISSIONS=true</code> on the server. Currently:{' '}
          <strong>{status.allow_real_submissions ? 'enabled — approved or qualifying applications will really be sent.' : 'disabled — applications are prepared but never sent, in either mode.'}</strong>
        </Callout>
      )}
      <Dialog
        open={confirmAuto}
        onClose={() => setConfirmAuto(false)}
        title="Switch to Mode A (automatic)?"
        size="sm"
        footer={
          <>
            <Button onClick={() => setConfirmAuto(false)}>Cancel</Button>
            <Button
              variant="primary"
              loading={patch.isPending}
              onClick={() => {
                set('auto')
                setConfirmAuto(false)
              }}
            >
              Switch to automatic
            </Button>
          </>
        }
      >
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Qualifying applications will be submitted without asking you first, up to the daily application cap. Every answer must still be verified before anything is sent.
        </p>
      </Dialog>
    </Card>
  )
}

// ------------------------------------------------------------------ settings form helpers

function NumberField({
  label,
  value,
  onChange,
  min = 0,
  max = 1000,
  step = 1,
  hint,
  id,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  min?: number
  max?: number
  step?: number
  hint?: ReactNode
  id: string
}) {
  const [text, setText] = useState(String(value ?? ''))
  useEffect(() => setText(String(value ?? '')), [value])
  const n = Number(text)
  const invalid = text.trim() === '' || Number.isNaN(n) || n < min || n > max
  return (
    <Field label={label} htmlFor={id} hint={invalid ? <span className="text-red-600 dark:text-red-400">Enter a number from {min} to {max}.</span> : hint}>
      <input
        id={id}
        type="number"
        inputMode="decimal"
        min={min}
        max={max}
        step={step}
        className={cx('input', invalid && 'border-red-400 focus:border-red-500 focus:ring-red-500/30')}
        value={text}
        aria-invalid={invalid}
        onChange={(e) => {
          setText(e.target.value)
          const v = Number(e.target.value)
          if (e.target.value.trim() !== '' && !Number.isNaN(v) && v >= min && v <= max) onChange(v)
        }}
      />
    </Field>
  )
}

const WEIGHT_LABELS: Record<string, string> = {
  skills: 'Skills',
  experience: 'Experience',
  education: 'Education',
  location: 'Location',
  eligibility_timing: 'Eligibility & timing',
  compensation: 'Compensation',
}

const ELIG_POLICY: Record<string, { label: string; help: string }> = {
  no_sponsorship_current_only: {
    label: '“Must be authorized to work without sponsorship” (future sponsorship not mentioned)',
    help: 'CPT/OPT is not employer sponsorship, but many employers who write this exclude F-1 students.',
  },
  no_visa_sponsorship_statement: {
    label: '“We do not sponsor H-1B / visas” with no explicit CPT/OPT exclusion',
    help: 'Usually about future H-1B sponsorship rather than internship work authorization.',
  },
  unstated: {
    label: 'Posting says nothing about work authorization',
    help: 'The most common case for internships.',
  },
}

const SOURCE_LABELS: Record<string, string> = {
  simplify: 'SimplifyJobs Summer 2027 feed',
  vanshb03: 'vanshb03 Summer 2027 feed',
  greenhouse: 'Greenhouse boards',
  lever: 'Lever boards',
  ashby: 'Ashby boards',
  smartrecruiters: 'SmartRecruiters boards',
  workday: 'Workday sites',
}

function SettingsForm({ settings }: { settings: AutomationSettings }) {
  const [draft, setDraft] = useState<AutomationSettings>(() => clone(settings))
  const patch = usePatchSettings()
  const push = useToast()
  const changes = useMemo(() => diff(settings, draft), [settings, draft])
  const dirty = Object.keys(changes).length > 0

  // Keep immediate keys (mode, enabled, paused) and untouched sections in sync with the server.
  useEffect(() => {
    setDraft((d) => {
      const pending = diff(settings, d)
      return { ...clone(settings), ...clone(pending) }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings])

  const up = <K extends keyof AutomationSettings>(k: K, v: AutomationSettings[K]) => setDraft((d) => ({ ...d, [k]: v }))
  const weights = draft.scoring_weights ?? {}
  const wsum = Object.values(weights).reduce((a, b) => a + (Number(b) || 0), 0)

  const save = () =>
    patch.mutate(changes, {
      onSuccess: (data) => {
        setDraft(clone(data))
        push('success', 'Settings saved', `${Object.keys(changes).length} setting group(s) updated.`)
      },
    })

  return (
    <div className="space-y-6">
      <Card title="Targets" subtitle="Where and what to look for.">
        <div className="grid gap-5 lg:grid-cols-2">
          <Field label="Preferred cities" htmlFor="cities" hint="Postings in these metros get the full location score.">
            <TagInput id="cities" value={draft.preferred_cities ?? []} onChange={(v) => up('preferred_cities', v)} placeholder="e.g. Madison, WI" />
          </Field>
          <Field label="Target roles" htmlFor="roles" hint="Role families used to judge relevance.">
            <TagInput id="roles" value={draft.target_roles ?? []} onChange={(v) => up('target_roles', v)} placeholder="e.g. Data Science Intern" />
          </Field>
        </div>
        <div className="mt-5 grid gap-4 sm:grid-cols-3">
          <Toggle label="Nearby metros" description="Score metros near preferred cities." checked={!!draft.include_nearby_metros} onChange={(v) => up('include_nearby_metros', v)} />
          <Toggle label="Remote (US)" description="Include remote US roles." checked={!!draft.include_remote_us} onChange={(v) => up('include_remote_us', v)} />
          <Toggle label="Other US locations" description="Include the rest of the US." checked={!!draft.include_other_us} onChange={(v) => up('include_other_us', v)} />
        </div>
      </Card>

      <Card
        title="Apply first"
        subtitle="Each run submits applications before looking for new jobs: it keeps tailoring and submitting the best matches until today's target is confirmed, candidates run out, or the time limit is hit."
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <NumberField
            id="dst"
            label="Daily submission target"
            value={draft.daily_submission_target}
            onChange={(v) => up('daily_submission_target', v)}
            hint="Confirmed submissions per day (automatic + ones you finish). 0 turns apply-first off."
          />
          <NumberField
            id="alm"
            label="Apply-first time limit (minutes)"
            value={draft.apply_loop_max_minutes}
            onChange={(v) => up('apply_loop_max_minutes', v)}
            max={240}
            hint="Then discovery runs."
          />
        </div>
        {(draft.daily_submission_target ?? 0) > (draft.daily_application_cap ?? 0) && (
          <Callout tone="amber" className="mt-4" title="The daily application cap is lower than the target">
            Runs stop at the cap ({draft.daily_application_cap}). Raise the cap below to reach {draft.daily_submission_target}.
          </Callout>
        )}
        <p className="mt-5 text-sm font-medium text-slate-700 dark:text-slate-200">Sites you finish yourself</p>
        <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          These sites make applicants confirm they're human (an emailed code or a CAPTCHA). Applications for them are prepared and wait for your Finish application click instead of being attempted automatically.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          {(['greenhouse', 'lever', 'ashby'] as const).map((p) => {
            const list = draft.assisted_only_platforms ?? []
            const on = list.includes(p)
            return (
              <Toggle
                key={p}
                size="sm"
                label={humanize(p)}
                description={on ? 'You finish (Finish application)' : 'Submitted automatically'}
                checked={on}
                onChange={(v) => up('assisted_only_platforms', v ? [...list.filter((x) => x !== p), p] : list.filter((x) => x !== p))}
              />
            )
          })}
        </div>
      </Card>

      <Card title="Limits & thresholds">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <NumberField id="ddt" label="Daily discovery target" value={draft.daily_discovery_target} onChange={(v) => up('daily_discovery_target', v)} hint="New qualifying postings per day." />
          <NumberField id="dac" label="Daily application cap" value={draft.daily_application_cap} onChange={(v) => up('daily_application_cap', v)} hint="Max submissions per day." />
          <NumberField id="drc" label="Daily resume cap" value={draft.daily_resume_cap} onChange={(v) => up('daily_resume_cap', v)} hint="Max tailored resumes per day." />
          <NumberField id="mpa" label="Max posting age (days)" value={draft.max_posting_age_days} onChange={(v) => up('max_posting_age_days', v)} max={365} />
          <NumberField id="mms" label="Minimum match score" value={draft.min_match_score} onChange={(v) => up('min_match_score', v)} max={100} hint="Below this, no resume is tailored." />
          <NumberField id="maas" label="Minimum auto-apply score" value={draft.min_auto_apply_score} onChange={(v) => up('min_auto_apply_score', v)} max={100} hint="Mode A only." />
          <NumberField id="lkb" label="Lesser-known boost" value={draft.lesser_known_boost} onChange={(v) => up('lesser_known_boost', v)} max={50} hint="Priority points for smaller employers." />
        </div>
      </Card>

      <Card title="Scoring weights" subtitle="Relative importance of each component in the 0–100 match score. Shares update live.">
        <ul className="grid gap-x-8 gap-y-4 md:grid-cols-2">
          {Object.entries(weights).map(([k, v]) => {
            const share = wsum > 0 ? (Number(v) / wsum) * 100 : 0
            return (
              <li key={k}>
                <div className="flex items-baseline justify-between gap-2">
                  <label htmlFor={`w-${k}`} className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {WEIGHT_LABELS[k] ?? humanize(k)}
                  </label>
                  <span className="text-xs text-slate-500 tabular dark:text-slate-400">
                    weight <span className="font-semibold text-slate-800 dark:text-slate-100">{v}</span> · <span className="font-semibold text-slate-800 dark:text-slate-100">{share.toFixed(1)}%</span> of score
                  </span>
                </div>
                <input
                  id={`w-${k}`}
                  type="range"
                  min={0}
                  max={60}
                  step={1}
                  value={Number(v)}
                  onChange={(e) => up('scoring_weights', { ...weights, [k]: Number(e.target.value) })}
                  className="mt-2 w-full accent-indigo-600"
                  aria-valuetext={`${v} (${share.toFixed(0)} percent)`}
                />
              </li>
            )
          })}
        </ul>
        {wsum === 0 && <p className="mt-3 text-sm text-red-600 dark:text-red-400">At least one weight must be above zero.</p>}
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Resume tailoring">
          <div className="space-y-4">
            <Toggle label="Use Claude for rewording" description="Requires the API key on the server; every rewrite is fact-checked." checked={!!draft.resume?.use_llm} onChange={(v) => up('resume', { ...draft.resume, use_llm: v })} />
            <Toggle label="Keep to one page" checked={!!draft.resume?.one_page} onChange={(v) => up('resume', { ...draft.resume, one_page: v })} />
            <Toggle label="Reword bullets" description="Align terminology with the posting without changing facts." checked={!!draft.resume?.reword_bullets} onChange={(v) => up('resume', { ...draft.resume, reword_bullets: v })} />
            <div className="grid gap-4 sm:grid-cols-2">
              <NumberField id="mp" label="Max projects" value={draft.resume?.max_projects ?? 3} onChange={(v) => up('resume', { ...draft.resume, max_projects: v })} min={0} max={10} />
              <Field label="Cover letters" htmlFor="cl">
                <select id="cl" className="input" value={draft.resume?.cover_letters ?? 'when_required'} onChange={(e) => up('resume', { ...draft.resume, cover_letters: e.target.value })}>
                  <option value="when_required">When required</option>
                  <option value="always">Always</option>
                  <option value="never">Never</option>
                </select>
              </Field>
            </div>
          </div>
        </Card>

        <Card title="Eligibility policy" subtitle="How ambiguous work-authorization language is treated.">
          <div className="space-y-4">
            {Object.entries(draft.eligibility ?? {}).map(([k, v]) => (
              <Field key={k} label={ELIG_POLICY[k]?.label ?? humanize(k)} htmlFor={`ep-${k}`} hint={ELIG_POLICY[k]?.help}>
                <select id={`ep-${k}`} className="input" value={v} onChange={(e) => up('eligibility', { ...draft.eligibility, [k]: e.target.value })}>
                  <option value="eligible">Treat as eligible</option>
                  <option value="review">Send to review</option>
                </select>
              </Field>
            ))}
            <Toggle
              label="Auto-answer contextual questions"
              description="Write short answers (e.g. “Why this company?”) from your verified background. Off sends them to the review queue."
              checked={!!draft.auto_contextual_answers}
              onChange={(v) => up('auto_contextual_answers', v)}
            />
          </div>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Company lists">
          <div className="space-y-4">
            <Field label="Blacklist" htmlFor="bl" hint="Never apply to these companies (matched case-insensitively).">
              <TagInput id="bl" value={draft.blacklist ?? []} onChange={(v) => up('blacklist', v)} placeholder="Company name" />
            </Field>
            <Field label="Whitelist" htmlFor="wl" hint="+10 priority for these companies.">
              <TagInput id="wl" value={draft.whitelist ?? []} onChange={(v) => up('whitelist', v)} placeholder="Company name" />
            </Field>
          </div>
        </Card>
        <Card title="Discovery sources">
          <div className="space-y-3">
            {Object.entries(draft.sources ?? {}).map(([k, v]) => (
              <Toggle key={k} size="sm" label={SOURCE_LABELS[k] ?? humanize(k)} checked={!!v} onChange={(nv) => up('sources', { ...draft.sources, [k]: nv })} />
            ))}
            <div className="border-t border-slate-100 pt-3 dark:border-slate-800">
              <Toggle size="sm" label="Learn new boards from feeds" description="Add company ATS boards seen in feeds to direct polling." checked={!!draft.learn_boards_from_feeds} onChange={(v) => up('learn_boards_from_feeds', v)} />
            </div>
            <NumberField id="mlb" label="Max learned boards polled per run" value={draft.max_learned_boards_per_run} onChange={(v) => up('max_learned_boards_per_run', v)} max={5000} />
          </div>
        </Card>
      </div>

      {dirty && (
        <div className="sticky bottom-4 z-30">
          <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-3 rounded-xl border border-indigo-200 bg-white/95 px-4 py-3 shadow-lg backdrop-blur dark:border-indigo-500/40 dark:bg-slate-900/95">
            <p className="text-sm text-slate-700 dark:text-slate-200">
              Unsaved changes: <span className="font-medium">{Object.keys(changes).map(humanize).join(', ')}</span>
            </p>
            <div className="flex gap-2">
              <Button icon={<Undo2 className="h-4 w-4" />} onClick={() => setDraft(clone(settings))}>
                Discard
              </Button>
              <Button variant="primary" icon={<Save className="h-4 w-4" />} loading={patch.isPending} disabled={wsum === 0} onClick={save}>
                Save changes
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ system status

function SystemStatus({ status }: { status: StatusResponse | undefined }) {
  if (!status) return <Card title="System status"><Skeleton className="h-48 w-full" /></Card>
  const rows: [string, boolean, string][] = [
    ['Claude API (LLM)', status.llm_available, status.llm_available ? status.llm_model : 'Not configured — deterministic templates are used'],
    ['Inbox monitoring (IMAP)', status.imap_configured, status.imap_configured ? 'Configured' : 'Set HUNT_IMAP_USER / HUNT_IMAP_PASSWORD'],
    ['Report email (SMTP)', status.smtp_configured, status.smtp_configured ? 'Configured' : 'Daily report is not emailed'],
    ['Encryption at rest', status.encryption_enabled, status.encryption_enabled ? 'Sensitive fields encrypted' : 'Set HUNT_SECRET_KEY'],
    ['Browser automation (Playwright)', status.playwright_available, status.playwright_available ? 'Available' : 'Not installed — browser submissions unavailable'],
    ['Real submissions', status.allow_real_submissions, status.allow_real_submissions ? 'Enabled' : 'Disabled (HUNT_ALLOW_REAL_SUBMISSIONS=false)'],
    ['Scheduler', status.scheduler_running, status.scheduler_running ? status.schedule : 'Not running in this process'],
  ]
  return (
    <Card title="System status" icon={<Server className="h-4 w-4 text-slate-400" />}>
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
        {rows.map(([label, ok, detail]) => (
          <li key={label} className="flex items-start gap-3 py-2.5 first:pt-0 last:pb-0">
            {ok ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" aria-label="OK" />
            ) : (
              <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-label="Off" />
            )}
            <div className="min-w-0">
              <p className="text-sm font-medium text-slate-800 dark:text-slate-200">{label}</p>
              <p className="break-words text-xs text-slate-500 dark:text-slate-400">{detail}</p>
            </div>
          </li>
        ))}
        <li className="flex items-start gap-3 py-2.5 last:pb-0">
          <Server className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden />
          <div>
            <p className="text-sm font-medium text-slate-800 dark:text-slate-200">Database</p>
            <p className="text-xs text-slate-500 dark:text-slate-400">{({ sqlite: 'SQLite', postgresql: 'PostgreSQL' } as Record<string, string>)[status.database] ?? humanize(status.database)}</p>
          </div>
        </li>
      </ul>
    </Card>
  )
}

// ------------------------------------------------------------------ boards

const PLATFORMS = ['greenhouse', 'lever', 'ashby', 'smartrecruiters', 'workday']

function AddBoard({ onDone }: { onDone: () => void }) {
  const [platform, setPlatform] = useState('greenhouse')
  const [token, setToken] = useState('')
  const [company, setCompany] = useState('')
  const [metro, setMetro] = useState('')
  const add = useAddBoard()
  const push = useToast()
  const submit = (e: FormEvent) => {
    e.preventDefault()
    add.mutate(
      { platform, token: token.trim(), company: company.trim() || undefined, metro: metro.trim() || undefined },
      {
        onSuccess: () => {
          push('success', 'Board added', 'It will be polled on the next discovery run.')
          setToken('')
          setCompany('')
          setMetro('')
          onDone()
        },
      },
    )
  }
  return (
    <form onSubmit={submit} className="grid gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700 sm:grid-cols-2 lg:grid-cols-5">
      <Field label="Platform" htmlFor="b-plat">
        <select id="b-plat" className="input" value={platform} onChange={(e) => setPlatform(e.target.value)}>
          {PLATFORMS.map((p) => (
            <option key={p} value={p}>
              {humanize(p)}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Board token" htmlFor="b-token" required hint={platform === 'workday' ? 'host|tenant|site' : 'e.g. the slug in boards.greenhouse.io/<token>'}>
        <input id="b-token" className="input" value={token} onChange={(e) => setToken(e.target.value)} required />
      </Field>
      <Field label="Company" htmlFor="b-company">
        <input id="b-company" className="input" value={company} onChange={(e) => setCompany(e.target.value)} />
      </Field>
      <Field label="Metro" htmlFor="b-metro">
        <input id="b-metro" className="input" value={metro} onChange={(e) => setMetro(e.target.value)} placeholder="e.g. Chicago, IL" />
      </Field>
      <div className="flex items-end">
        <Button type="submit" variant="primary" size="md" className="w-full" icon={<Plus className="h-4 w-4" />} loading={add.isPending} disabled={!token.trim()}>
          Add board
        </Button>
      </div>
    </form>
  )
}

function Boards() {
  const { data, isLoading, error, refetch } = useBoards()
  const toggle = usePatchBoard()
  const [origin, setOrigin] = useState('')
  const [active, setActive] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [adding, setAdding] = useState(false)
  const pageSize = 25

  const rows = useMemo(() => {
    const ql = q.trim().toLowerCase()
    return (data ?? []).filter(
      (b) =>
        (!origin || b.origin === origin) &&
        (!active || String(b.active) === active) &&
        (!ql || `${b.company ?? ''} ${b.token} ${b.platform} ${b.metro ?? ''}`.toLowerCase().includes(ql)),
    )
  }, [data, origin, active, q])
  useEffect(() => setPage(1), [origin, active, q])
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const b of data ?? []) c[b.origin] = (c[b.origin] ?? 0) + 1
    return c
  }, [data])
  const pages = Math.max(1, Math.ceil(rows.length / pageSize))
  const slice = rows.slice((page - 1) * pageSize, page * pageSize)

  return (
    <Card
      title="Company boards"
      icon={<Building2 className="h-4 w-4 text-slate-400" />}
      subtitle={data ? `${fmtNumber(data.length)} boards · ${fmtNumber(data.filter((b) => b.active).length)} active` : undefined}
      actions={
        <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => setAdding((a) => !a)} aria-expanded={adding}>
          Add board
        </Button>
      }
    >
      {adding && (
        <div className="mb-4">
          <AddBoard onDone={() => setAdding(false)} />
        </div>
      )}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label htmlFor="b-q" className="sr-only">
          Search boards
        </label>
        <input id="b-q" type="search" className="input max-w-xs" placeholder="Search company, token, metro…" value={q} onChange={(e) => setQ(e.target.value)} />
        <label htmlFor="b-origin" className="sr-only">
          Origin
        </label>
        <select id="b-origin" className="input w-auto" value={origin} onChange={(e) => setOrigin(e.target.value)}>
          <option value="">All origins</option>
          {['seed', 'learned', 'user'].map((o) => (
            <option key={o} value={o}>
              {humanize(o)} ({fmtNumber(counts[o] ?? 0)})
            </option>
          ))}
        </select>
        <label htmlFor="b-active" className="sr-only">
          Active
        </label>
        <select id="b-active" className="input w-auto" value={active} onChange={(e) => setActive(e.target.value)}>
          <option value="">Active and inactive</option>
          <option value="true">Active only</option>
          <option value="false">Inactive only</option>
        </select>
      </div>
      {error && !data ? (
        <ErrorState error={error} onRetry={() => refetch()} compact />
      ) : isLoading || !data ? (
        <SkeletonRows rows={5} />
      ) : !rows.length ? (
        <EmptyState compact icon={<Building2 className="h-5 w-5" />} title={data.length ? 'No boards match' : 'No boards yet'} description={data.length ? 'Adjust the filters.' : 'Seed boards load on init; learned boards are added from feeds during discovery.'} />
      ) : (
        <>
          <div className="relative -mx-4 overflow-x-auto sm:mx-0">
            <table className="w-full min-w-[46rem] text-sm">
              <thead>
                <tr className="table-head">
                  <th className="px-3 py-2">Active</th>
                  <th className="px-3 py-2">Company</th>
                  <th className="px-3 py-2">Platform / token</th>
                  <th className="px-3 py-2">Origin</th>
                  <th className="px-3 py-2">Metro</th>
                  <th className="px-3 py-2 text-right">Jobs</th>
                  <th className="px-3 py-2">Last polled</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {slice.map((b) => (
                  <tr key={b.id} className="align-top">
                    <td className="px-3 py-2">
                      <Toggle size="sm" checked={b.active} onChange={(v) => toggle.mutate({ id: b.id, active: v })} ariaLabel={`Poll ${b.company ?? b.token} (${b.platform})`} />
                    </td>
                    <td className="px-3 py-2 font-medium text-slate-800 dark:text-slate-200">{b.company ?? <span className="text-slate-400">—</span>}</td>
                    <td className="max-w-[16rem] px-3 py-2">
                      <span className="text-slate-600 dark:text-slate-300">{humanize(b.platform)}</span>
                      <span className="block truncate font-mono text-xs text-slate-500" title={b.token}>
                        {b.token}
                      </span>
                      {b.last_error && (
                        <span className="block truncate text-xs text-red-600 dark:text-red-400" title={b.last_error}>
                          {b.last_error}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <Badge tone={b.origin === 'user' ? 'indigo' : b.origin === 'learned' ? 'teal' : 'slate'}>{b.origin}</Badge>
                    </td>
                    <td className="px-3 py-2 text-slate-600 dark:text-slate-300">{b.metro ?? '—'}</td>
                    <td className="px-3 py-2 text-right tabular">{fmtNumber(b.jobs_found)}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-500 dark:text-slate-400">{b.last_polled_at ? fmtRelative(b.last_polled_at) : 'never'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex items-center justify-between gap-2 text-sm text-slate-500 dark:text-slate-400">
            <span>
              {fmtNumber(rows.length)} board{rows.length === 1 ? '' : 's'}
            </span>
            <div className="flex items-center gap-2">
              <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} icon={<ChevronLeft className="h-4 w-4" />} aria-label="Previous page" />
              <span className="tabular">
                {page} / {pages}
              </span>
              <Button size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)} icon={<ChevronRight className="h-4 w-4" />} aria-label="Next page" />
            </div>
          </div>
        </>
      )}
    </Card>
  )
}

// ------------------------------------------------------------------ page

export default function AutomationPage() {
  const { data: status } = useStatus()
  const { data: settings, isLoading, error, refetch } = useSettings()
  return (
    <div>
      <PageHeader title="Automation" description="Control when the pipeline runs, how it decides, and what it is allowed to do." />
      <div className="space-y-6">
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <Controls status={status} />
          </div>
          <SystemStatus status={status} />
        </div>
        {error && !settings ? (
          <div className="card">
            <ErrorState error={error} onRetry={() => refetch()} />
          </div>
        ) : isLoading || !settings ? (
          <Skeleton className="h-96 w-full rounded-xl" />
        ) : (
          <>
            <ApplyMode status={status} settings={settings} />
            <SettingsForm settings={settings} />
          </>
        )}
        <Boards />
      </div>
    </div>
  )
}
