import { Link } from 'react-router-dom'
import { CheckCircle2, ListChecks, MonitorUp, SkipForward, X } from 'lucide-react'
import { ApiError } from '../api/client'
import { useAssistCancel, useAssistQueueStart, useAssistSkip, useAssistStart, useAssistStatus } from '../api/hooks'
import type { AssistStatus, JobSummary } from '../api/types'
import { POST_SUBMISSION } from '../lib/status'
import { Button, Callout, Spinner } from './ui'
import { useToast } from './ui/Toast'

const ACTIVE = ['starting', 'filling', 'waiting']

export function isActive(s: AssistStatus | undefined): boolean {
  return !!s && ACTIVE.includes(s.state)
}

/** Why "Finish application" is unavailable for this job (null = available). */
export function canFinish(job: Pick<JobSummary, 'apply_method' | 'ats_platform'>): boolean {
  return job.apply_method === 'browser' || job.ats_platform === 'workday'
}

export function finishUnavailable(job: Pick<JobSummary, 'status' | 'eligibility' | 'apply_method' | 'has_resume' | 'ats_platform'>): string | null {
  if (POST_SUBMISSION.includes(job.status)) return 'Already submitted'
  if (job.eligibility === 'ineligible') return 'Ineligible work-authorization requirements'
  if (!canFinish(job)) return 'This platform needs an account; use the Apply link'
  if (!job.has_resume) return 'No tailored resume yet'
  return null
}

export function FinishButton({ job, size = 'sm', full }: { job: JobSummary; size?: 'xs' | 'sm' | 'md'; full?: boolean }) {
  const push = useToast()
  const start = useAssistStart()
  const { data: st } = useAssistStatus()
  const why = finishUnavailable(job)
  const busyElsewhere = isActive(st) && st?.job_id !== job.id
  const mine = isActive(st) && st?.job_id === job.id
  return (
    <Button
      size={size}
      variant="primary"
      className={full ? 'w-full' : undefined}
      icon={<MonitorUp className="h-4 w-4" />}
      disabled={!!why || busyElsewhere || mine}
      title={why ?? (busyElsewhere ? `A window is already open for ${st?.company}` : job.ats_platform === 'workday'
        ? 'Opens the Workday posting in a browser window on this PC. Sign in; every step is filled in for you; you click Submit.'
        : 'Opens a browser window on this PC with the form filled in. You click Submit.')}
      loading={start.isPending}
      onClick={() =>
        start.mutate(job.id, {
          onSuccess: () => push('success', 'Opening the application', 'A browser window is opening with the form filled in. Review it and click Submit there.'),
          onError: (e) => push('error', "Couldn't start", e instanceof ApiError ? e.message : String(e)),
        })
      }
    >
      {mine ? 'Window open…' : 'Finish application'}
    </Button>
  )
}

/** Finish all: one window opens each waiting application in turn; you submit or skip each. */
export function FinishAllButton({ count }: { count: number }) {
  const push = useToast()
  const start = useAssistQueueStart()
  const { data: st } = useAssistStatus()
  const busy = isActive(st)
  return (
    <Button
      size="sm"
      variant="primary"
      icon={<ListChecks className="h-4 w-4" />}
      disabled={busy || count === 0}
      title={busy ? `A window is already open for ${st?.company}` : 'Opens one browser window on this PC and goes through every application below (quick single-page forms first, then Workday; newest first within each). Each one is filled in; you check it and click Submit (or Skip if you do not want to apply; skipped jobs are not offered again), and the next one opens by itself.'}
      loading={start.isPending}
      onClick={() =>
        start.mutate(undefined, {
          onSuccess: (s) => push('success', 'Finish all started', `Opening ${s.company}. Submit or skip each one in the browser window; the next opens by itself.`),
          onError: (e) => push('error', "Couldn't start", e instanceof ApiError ? e.message : String(e)),
        })
      }
    >
      {busy && st?.queue ? `Finishing ${st.queue.position} of ${st.queue.total}…` : `Finish all (${count})`}
    </Button>
  )
}

/** Live status of the current / most recent assisted session. */
export function AssistStatusPanel({ jobId, compact }: { jobId?: number; compact?: boolean }) {
  const { data: st } = useAssistStatus()
  const cancel = useAssistCancel()
  const skip = useAssistSkip()
  if (!st || st.state === 'idle') return null
  if (jobId != null && st.job_id !== jobId) return null
  const active = isActive(st)
  const recent = st.finished_at && Date.now() - new Date(st.finished_at).getTime() < 10 * 60 * 1000
  if (!active && !recent) return null
  const q = st.queue
  const tone = st.state === 'confirmed' || (q && st.state === 'done') ? 'emerald' : active ? 'violet' : st.state === 'error' ? 'red' : 'amber'
  const title = q
    ? active
      ? `Finish all: ${st.company} (${q.position} of ${q.total}) · ${q.submitted} submitted`
      : `Finish all ended · ${q.submitted} submitted`
    : st.state === 'confirmed'
      ? `Submitted: ${st.company}`
      : active
        ? `Finishing ${st.company}${compact ? '' : ` – ${st.title ?? ''}`}`
        : `Finish application ended: ${st.company}`
  return (
    <Callout
      tone={tone}
      icon={st.state === 'confirmed' ? <CheckCircle2 className="h-4 w-4" /> : active ? <Spinner /> : <MonitorUp className="h-4 w-4" />}
      title={title}
      className={compact ? 'rounded-none border-x-0' : 'mt-3'}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {active && st.code && (
          <span className="inline-flex items-center gap-2">
            Your code:
            <code className="select-all rounded-md bg-white px-2 py-0.5 font-mono text-base font-semibold tracking-wider text-slate-900 ring-1 ring-slate-300 dark:bg-slate-900 dark:text-slate-100 dark:ring-slate-600">
              {st.code}
            </code>
          </span>
        )}
        <span>{st.message}</span>
        {active && st.left_for_you.length > 0 && (
          <span className="text-xs">Fill in the browser: {st.left_for_you.slice(0, 4).join('; ')}{st.left_for_you.length > 4 ? '…' : ''}</span>
        )}
        {jobId == null && st.job_id != null && (
          <Link to={`/jobs/${st.job_id}`} className="link text-xs">
            Open job
          </Link>
        )}
        {active && q && (
          <Button size="xs" variant="ghost" icon={<SkipForward className="h-3 w-3" />} loading={skip.isPending} onClick={() => skip.mutate()}>
            Skip (don't apply)
          </Button>
        )}
        {active && (
          <Button size="xs" variant="ghost" icon={<X className="h-3 w-3" />} loading={cancel.isPending} onClick={() => cancel.mutate()}>
            {q ? 'Stop' : 'Close window'}
          </Button>
        )}
      </div>
    </Callout>
  )
}
