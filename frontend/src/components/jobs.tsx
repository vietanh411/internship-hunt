import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Check, Download, ExternalLink as ExtIcon, MapPin, Send, ShieldCheck, ShieldX, X } from 'lucide-react'
import type { JobSummary, Question } from '../api/types'
import { useAnswerQuestion, useDismissQuestion, useJobAction } from '../api/hooks'
import { MANUAL_STATUSES, statusMeta } from '../lib/status'
import { DASH, fmtRelative, humanize } from '../lib/format'
import { Badge, Button, cx, Dialog, Field } from './ui'
import { useToast } from './ui/Toast'

export function LocationText({ job, className }: { job: Pick<JobSummary, 'location' | 'locations' | 'remote_type'>; className?: string }) {
  const locs = job.locations?.length ? job.locations : job.location ? [job.location] : []
  const first = locs[0] ?? job.location
  const remote = job.remote_type && job.remote_type !== 'unknown' && job.remote_type !== 'onsite' ? humanize(job.remote_type) : null
  if (!first && !remote) return <span className={cx('muted', className)}>{DASH}</span>
  return (
    <span className={cx('inline-flex min-w-0 items-center gap-1', className)} title={locs.join(' · ')}>
      <MapPin className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
      <span className="truncate">{first ?? remote}</span>
      {locs.length > 1 && <span className="shrink-0 text-xs text-slate-400">+{locs.length - 1}</span>}
      {remote && first && <Badge tone="teal" className="ml-1 shrink-0">{remote}</Badge>}
    </span>
  )
}

export function JobQuickLinks({ job, compact }: { job: JobSummary; compact?: boolean }) {
  return (
    <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
      {job.posting_url && (
        <a
          href={job.posting_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100 hover:text-indigo-600 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-indigo-300"
          title="Open the original posting"
          aria-label={`Open posting for ${job.title} at ${job.company} (new tab)`}
        >
          {compact ? null : 'Posting'}
          <ExtIcon className="h-3.5 w-3.5" aria-hidden />
        </a>
      )}
      {job.has_resume && (
        <a
          href={`/api/jobs/${job.id}/resume`}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100 hover:text-indigo-600 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-indigo-300"
          title="Download tailored resume"
          aria-label={`Download tailored resume for ${job.company}`}
        >
          {compact ? null : 'Resume'}
          <Download className="h-3.5 w-3.5" aria-hidden />
        </a>
      )}
    </div>
  )
}

export function JobTitleLink({ job }: { job: Pick<JobSummary, 'id' | 'title' | 'company' | 'lesser_known'> }) {
  return (
    <div className="min-w-0">
      <div className="flex min-w-0 items-center gap-1.5">
        <span className="truncate text-sm font-semibold text-slate-900 dark:text-white">{job.company}</span>
        {job.lesser_known && (
          <Badge tone="violet" className="shrink-0" title="Lesser-known employer (priority boost)">
            lesser-known
          </Badge>
        )}
      </div>
      <Link to={`/jobs/${job.id}`} className="line-clamp-2 text-sm text-slate-600 hover:text-indigo-600 hover:underline dark:text-slate-300 dark:hover:text-indigo-300">
        {job.title}
      </Link>
    </div>
  )
}

// ------------------------------------------------------------------ questions

export function QuestionForm({ q, showJob = true }: { q: Question; showJob?: boolean }) {
  const [answer, setAnswer] = useState(q.answer ?? '')
  const [reuse, setReuse] = useState(true)
  const save = useAnswerQuestion()
  const dismiss = useDismissQuestion()
  const push = useToast()
  const opts = (q.options ?? []).filter((o) => o !== null && o !== undefined && String(o).trim() !== '')
  const long = !opts.length && (q.field_type === 'textarea' || q.question.length > 90)
  const fid = `q-${q.id}`

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!answer.trim()) return
    save.mutate(
      { qid: q.id, jobId: q.job_id, answer: answer.trim(), save_to_library: reuse },
      { onSuccess: () => push('success', 'Answer saved', reuse ? 'Saved to your answer library for reuse.' : 'Saved for this application only.') },
    )
  }

  return (
    <form onSubmit={submit} className="rounded-lg border border-slate-200 p-3.5 dark:border-slate-700">
      {showJob && (q.company || q.title) && (
        <p className="mb-1 text-xs text-slate-500 dark:text-slate-400">
          <Link to={`/jobs/${q.job_id}`} className="link">
            {q.company}
            {q.title ? ` · ${q.title}` : ''}
          </Link>
          <span className="ml-2">{fmtRelative(q.created_at)}</span>
        </p>
      )}
      <label htmlFor={fid} className="block text-sm font-medium text-slate-900 dark:text-slate-100">
        {q.question}
        {q.required && <span className="ml-1 text-xs font-normal text-red-600 dark:text-red-400">required</span>}
      </label>
      {q.reason && (
        <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          Why it's asking: {q.reason}
          {/profile/i.test(q.reason) && (
            <>
              {' '}
              <Link to="/profile?tab=onboarding" className="link">
                Fix it once in Profile &amp; Onboarding
              </Link>{' '}
              to resolve it for every application.
            </>
          )}
        </p>
      )}
      <div className="mt-2">
        {opts.length ? (
          <select id={fid} className="input" value={answer} onChange={(e) => setAnswer(e.target.value)} required>
            <option value="">Choose an answer…</option>
            {opts.map((o) => (
              <option key={String(o)} value={String(o)}>
                {String(o)}
              </option>
            ))}
          </select>
        ) : long ? (
          <textarea id={fid} className="input min-h-[5rem]" value={answer} onChange={(e) => setAnswer(e.target.value)} required />
        ) : (
          <input id={fid} className="input" value={answer} onChange={(e) => setAnswer(e.target.value)} required />
        )}
      </div>
      <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2">
        <label className="inline-flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 dark:border-slate-600 dark:bg-slate-800"
            checked={reuse}
            onChange={(e) => setReuse(e.target.checked)}
          />
          Reuse for other applications
        </label>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="ghost"
            icon={<X className="h-3.5 w-3.5" />}
            loading={dismiss.isPending}
            onClick={() => dismiss.mutate({ qid: q.id, jobId: q.job_id }, { onSuccess: () => push('info', 'Question dismissed') })}
          >
            Dismiss
          </Button>
          <Button type="submit" size="sm" variant="primary" icon={<Check className="h-3.5 w-3.5" />} loading={save.isPending} disabled={!answer.trim()}>
            Save answer
          </Button>
        </div>
      </div>
    </form>
  )
}

// ------------------------------------------------------------------ eligibility

export function EligibilityDecision({ jobId, compact }: { jobId: number; compact?: boolean }) {
  const [note, setNote] = useState('')
  const act = useJobAction<{ verdict: string; note?: string }>('eligibility')
  const push = useToast()
  const decide = (verdict: 'eligible' | 'ineligible') =>
    act.mutate(
      { id: jobId, body: { verdict, note: note.trim() || undefined } },
      { onSuccess: () => push('success', verdict === 'eligible' ? 'Marked eligible' : 'Marked ineligible', verdict === 'eligible' ? 'Queued for resume tailoring.' : undefined) },
    )
  return (
    <div className={cx('space-y-2', compact ? '' : 'rounded-lg border border-amber-200 bg-amber-50/50 p-3 dark:border-amber-500/30 dark:bg-amber-500/5')}>
      <label htmlFor={`note-${jobId}`} className="sr-only">
        Optional note
      </label>
      <input
        id={`note-${jobId}`}
        className="input"
        placeholder="Optional note (e.g. confirmed CPT accepted with recruiter)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="success"
          icon={<ShieldCheck className="h-4 w-4" />}
          loading={act.isPending && act.variables?.body?.verdict === 'eligible'}
          disabled={act.isPending}
          onClick={() => decide('eligible')}
        >
          Mark eligible
        </Button>
        <Button
          size="sm"
          variant="secondary"
          icon={<ShieldX className="h-4 w-4" />}
          loading={act.isPending && act.variables?.body?.verdict === 'ineligible'}
          disabled={act.isPending}
          onClick={() => decide('ineligible')}
        >
          Mark ineligible
        </Button>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ status changes

export function StatusChangeDialog({
  open,
  onClose,
  jobId,
  current,
  initial,
}: {
  open: boolean
  onClose: () => void
  jobId: number
  current: string
  initial?: string
}) {
  const [status, setStatus] = useState(initial ?? (current === 'submitted' ? 'interview' : 'submitted'))
  const [note, setNote] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [nextAction, setNextAction] = useState('')
  const act = useJobAction<Record<string, string>>('status')
  const push = useToast()
  const needsConf = status === 'submitted'

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const body: Record<string, string> = { status }
    if (note.trim()) body.note = note.trim()
    if (needsConf) body.confirmation = confirmation.trim()
    if (nextAction.trim()) body.next_action = nextAction.trim()
    act.mutate(
      { id: jobId, body },
      {
        onSuccess: () => {
          push('success', `Status set to ${statusMeta(status).label}`)
          onClose()
          setNote('')
          setConfirmation('')
          setNextAction('')
        },
      },
    )
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Change status"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form={`status-form-${jobId}`} loading={act.isPending} disabled={needsConf && !confirmation.trim()}>
            Save status
          </Button>
        </>
      }
    >
      <form id={`status-form-${jobId}`} onSubmit={submit} className="space-y-4">
        <Field label="New status" htmlFor={`st-${jobId}`} hint={`Currently ${statusMeta(current).label}.`}>
          <select id={`st-${jobId}`} className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
            {MANUAL_STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusMeta(s).label}
              </option>
            ))}
          </select>
        </Field>
        {needsConf && (
          <Field
            label="Confirmation details"
            htmlFor={`conf-${jobId}`}
            required
            hint="Required: the confirmation email subject, confirmation number, or other proof that the application was actually submitted."
          >
            <input id={`conf-${jobId}`} className="input" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} required />
          </Field>
        )}
        <Field label="Note" htmlFor={`note-st-${jobId}`} hint="Optional; recorded in the activity timeline.">
          <input id={`note-st-${jobId}`} className="input" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <Field label="Next action" htmlFor={`na-${jobId}`} hint="Optional; e.g. 'Prepare for technical interview on Feb 3'.">
          <input id={`na-${jobId}`} className="input" value={nextAction} onChange={(e) => setNextAction(e.target.value)} />
        </Field>
      </form>
    </Dialog>
  )
}

export function MarkSubmittedButton({ jobId, size = 'sm' }: { jobId: number; size?: 'xs' | 'sm' }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button size={size} variant="secondary" icon={<Send className="h-3.5 w-3.5" />} onClick={() => setOpen(true)}>
        Mark submitted
      </Button>
      {open && <StatusChangeDialog open={open} onClose={() => setOpen(false)} jobId={jobId} current="ready_to_apply" initial="submitted" />}
    </>
  )
}
