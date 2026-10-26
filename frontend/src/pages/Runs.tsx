import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, ChevronDown, FileText, FlaskConical, History, ListChecks, Play, ScrollText } from 'lucide-react'
import { useRun, useRunLogs, useRuns, useStartRun, useStatus, useTasks } from '../api/hooks'
import type { RunDetail, RunLogRow, StageRow } from '../api/types'
import { Badge, Button, Card, EmptyState, ErrorState, KeyValue, PageHeader, Skeleton, SkeletonRows, cx } from '../components/ui'
import { useToast } from '../components/ui/Toast'
import { fmtDateTime, fmtDuration, fmtRelative, humanize } from '../lib/format'
import { LOG_LEVEL_TONE, RUN_STATUS_TONE } from '../lib/status'
import { stageHighlights, triggerLabel } from '../lib/runs'

function RunList({ selected }: { selected: number | null }) {
  const { data, isLoading, error, refetch } = useRuns()
  const start = useStartRun()
  const { data: status } = useStatus()
  const push = useToast()
  if (error && !data) return <ErrorState error={error} onRetry={() => refetch()} compact />
  if (isLoading || !data) return <SkeletonRows rows={6} />
  if (!data.length)
    return (
      <EmptyState
        icon={<History className="h-5 w-5" />}
        title="No runs yet — click Run now"
        action={
          <Button
            variant="primary"
            icon={<Play className="h-4 w-4" />}
            disabled={!!status?.active_run}
            loading={start.isPending}
            onClick={() => start.mutate({ dry_run: false }, { onSuccess: () => push('success', 'Run started') })}
          >
            Run now
          </Button>
        }
      />
    )
  return (
    <ul className="space-y-2">
      {data.map((r) => {
        const stages = Object.entries(r.stats ?? {}).filter(([k]) => !k.startsWith('_'))
        return (
          <li key={r.id}>
            <Link
              to={`/runs/${r.id}`}
              aria-current={selected === r.id ? 'page' : undefined}
              className={cx(
                'block rounded-lg border p-3 transition',
                selected === r.id
                  ? 'border-indigo-400 bg-indigo-50/60 dark:border-indigo-500/60 dark:bg-indigo-500/10'
                  : 'border-slate-200 bg-white hover:border-slate-300 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-700',
              )}
            >
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-sm font-semibold text-slate-900 dark:text-white">#{r.id}</span>
                <Badge tone={RUN_STATUS_TONE[r.status] ?? 'slate'} dot>
                  {humanize(r.status)}
                </Badge>
                {r.dry_run && <Badge tone="sky">dry run</Badge>}
                <span className="text-xs text-slate-500 dark:text-slate-400">{triggerLabel(r.trigger)}</span>
              </div>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {fmtDateTime(r.started_at)} · {r.status === 'running' ? `running ${fmtDuration(r.started_at, null)}` : fmtDuration(r.started_at, r.finished_at)}
                {r.status === 'running' && r.current_stage && ` · ${humanize(r.current_stage)}`}
              </p>
              {stages.length > 0 && (
                <ul className="mt-1.5 space-y-0.5">
                  {stages.slice(0, 4).map(([s, res]) => (
                    <li key={s} className="truncate text-[11px] text-slate-500 dark:text-slate-400">
                      <span className="font-medium text-slate-600 dark:text-slate-300">{humanize(s)}:</span> {stageHighlights(s, res, 2).join(' · ') || '—'}
                    </li>
                  ))}
                  {stages.length > 4 && <li className="text-[11px] text-slate-400">+{stages.length - 4} more stages</li>}
                </ul>
              )}
              {r.error && <p className="mt-1 line-clamp-2 text-xs text-red-600 dark:text-red-400">{r.error}</p>}
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

function StageItem({ s }: { s: StageRow }) {
  const [open, setOpen] = useState(false)
  const hasResult = s.result && Object.keys(s.result).length > 0
  return (
    <li className="rounded-lg border border-slate-200 dark:border-slate-800">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full flex-wrap items-center gap-2 p-3 text-left">
        <ChevronDown className={cx('h-4 w-4 shrink-0 text-slate-400 transition-transform', open && 'rotate-180')} aria-hidden />
        <span className="text-sm font-semibold text-slate-900 dark:text-white">{humanize(s.stage)}</span>
        <Badge tone={RUN_STATUS_TONE[s.status] ?? 'slate'} dot>
          {humanize(s.status)}
        </Badge>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {fmtDuration(s.started_at, s.finished_at)} · {s.processed.toLocaleString()} processed
        </span>
        <span className="ml-auto hidden truncate text-xs text-slate-500 dark:text-slate-400 sm:inline">{stageHighlights(s.stage, s.result, 3).join(' · ')}</span>
      </button>
      {s.error && <p className="mx-3 mb-3 whitespace-pre-wrap rounded bg-red-50 p-2 text-xs text-red-800 dark:bg-red-500/10 dark:text-red-200">{s.error}</p>}
      {open && (
        <div className="border-t border-slate-100 p-3 dark:border-slate-800">{hasResult ? <KeyValue data={s.result} /> : <p className="text-sm text-slate-500">No result recorded.</p>}</div>
      )}
    </li>
  )
}

function LogLine({ l }: { l: RunLogRow }) {
  const [open, setOpen] = useState(false)
  const long = l.message.length > 220 || l.message.includes('\n')
  return (
    <li className="flex gap-2 px-3 py-2 text-xs">
      <span className="w-[4.5rem] shrink-0 tabular text-slate-400" title={fmtDateTime(l.at)}>
        {l.at ? new Date(l.at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'}
      </span>
      <span className="w-12 shrink-0">
        <Badge tone={LOG_LEVEL_TONE[l.level] ?? 'slate'}>{l.level}</Badge>
      </span>
      <div className="min-w-0 flex-1">
        <span className="mr-2 text-slate-400">{l.stage ? humanize(l.stage) : ''}</span>
        {l.job_id && (
          <Link to={`/jobs/${l.job_id}`} className="link mr-2">
            job #{l.job_id}
          </Link>
        )}
        <span className={cx('whitespace-pre-wrap break-words font-mono text-slate-700 dark:text-slate-300', !open && long && 'line-clamp-2')}>{l.message}</span>
        {long && (
          <button type="button" className="link ml-1 text-xs" onClick={() => setOpen((o) => !o)}>
            {open ? 'less' : 'more'}
          </button>
        )}
      </div>
    </li>
  )
}

function Logs({ run }: { run: RunDetail }) {
  const [level, setLevel] = useState('')
  const [stage, setStage] = useState('')
  const { data, isLoading, isFetching, error, refetch } = useRunLogs(run.id, level, stage, run.status === 'running')
  return (
    <Card
      title="Logs"
      icon={<ScrollText className="h-4 w-4 text-slate-400" />}
      actions={
        <div className="flex flex-wrap gap-2">
          <label htmlFor="log-level" className="sr-only">
            Level
          </label>
          <select id="log-level" className="input w-auto py-1.5" value={level} onChange={(e) => setLevel(e.target.value)}>
            <option value="">All levels</option>
            <option value="info">Info</option>
            <option value="warn">Warnings</option>
            <option value="error">Errors</option>
            <option value="warn,error">Warnings + errors</option>
          </select>
          <label htmlFor="log-stage" className="sr-only">
            Stage
          </label>
          <select id="log-stage" className="input w-auto py-1.5" value={stage} onChange={(e) => setStage(e.target.value)}>
            <option value="">All stages</option>
            {run.stages.map((s) => (
              <option key={s.stage} value={s.stage}>
                {humanize(s.stage)}
              </option>
            ))}
          </select>
        </div>
      }
      bodyClassName="p-0 sm:p-0"
    >
      {error && !data ? (
        <ErrorState error={error} onRetry={() => refetch()} compact />
      ) : isLoading || !data ? (
        <div className="p-4">
          <SkeletonRows rows={4} />
        </div>
      ) : !data.length ? (
        <EmptyState compact title="No log entries" description={level || stage ? 'Nothing matches these filters.' : 'This run did not record any log messages.'} />
      ) : (
        <ul className={cx('max-h-[32rem] divide-y divide-slate-100 overflow-y-auto dark:divide-slate-800', isFetching && 'opacity-80')}>
          {data.map((l) => (
            <LogLine key={l.id} l={l} />
          ))}
        </ul>
      )}
    </Card>
  )
}

function RunDetailView({ id }: { id: number }) {
  const { data: run, isLoading, error, refetch } = useRun(id)
  if (error && !run)
    return (
      <div className="card">
        <ErrorState error={error} onRetry={() => refetch()} />
      </div>
    )
  if (isLoading || !run) return <Skeleton className="h-96 w-full rounded-xl" />
  const meta = run.stats?._meta as Record<string, unknown> | undefined
  return (
    <div className="space-y-6">
      <Card
        title={
          <span className="flex flex-wrap items-center gap-2">
            Run #{run.id}
            <Badge tone={RUN_STATUS_TONE[run.status] ?? 'slate'} dot>
              {humanize(run.status)}
            </Badge>
            {run.dry_run && <Badge tone="sky">dry run</Badge>}
          </span>
        }
        actions={
          run.report_url ? (
            <a href={run.report_url} target="_blank" rel="noopener noreferrer" className="link inline-flex items-center gap-1 text-sm">
              <FileText className="h-4 w-4" /> Report ↗
            </a>
          ) : undefined
        }
      >
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-xs text-slate-500 dark:text-slate-400">Trigger</dt>
            <dd className="font-medium">{triggerLabel(run.trigger)}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 dark:text-slate-400">Started</dt>
            <dd className="font-medium">{fmtDateTime(run.started_at)}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 dark:text-slate-400">Finished</dt>
            <dd className="font-medium">{run.finished_at ? fmtDateTime(run.finished_at) : run.status === 'running' ? `running · ${humanize(run.current_stage ?? 'starting')}` : '—'}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500 dark:text-slate-400">Duration</dt>
            <dd className="font-medium">{fmtDuration(run.started_at, run.finished_at)}</dd>
          </div>
          {meta && (
            <div className="col-span-2 sm:col-span-4">
              <dt className="text-xs text-slate-500 dark:text-slate-400">Resources</dt>
              <dd className="text-slate-700 dark:text-slate-300">
                {String(meta.http_requests ?? '—')} HTTP requests · {String(meta.llm_calls ?? '—')} LLM calls
                {meta.llm_failures ? ` (${String(meta.llm_failures)} failed)` : ''} · LLM {meta.llm_available ? 'available' : 'not configured'}
              </dd>
            </div>
          )}
        </dl>
        {run.cancel_requested && run.status === 'running' && <p className="mt-3 text-sm text-amber-700 dark:text-amber-300">Stop requested — the run will halt after the current item.</p>}
        {run.error && <p className="mt-3 whitespace-pre-wrap rounded bg-red-50 p-2 text-sm text-red-800 dark:bg-red-500/10 dark:text-red-200">{run.error}</p>}
      </Card>

      <Card title="Stages" icon={<ListChecks className="h-4 w-4 text-slate-400" />}>
        {run.stages.length ? (
          <ol className="space-y-2">
            {run.stages.map((s) => (
              <StageItem key={`${s.stage}-${s.started_at}`} s={s} />
            ))}
          </ol>
        ) : (
          <p className="text-sm text-slate-500 dark:text-slate-400">No stages recorded{run.status === 'running' ? ' yet' : ''}.</p>
        )}
      </Card>

      <Logs run={run} />
    </div>
  )
}

function Tasks() {
  const { data, isLoading, error, refetch } = useTasks()
  return (
    <Card title="Work queue" subtitle="Queued and dead (exhausted) tasks. Queued tasks resume on the next run with exponential backoff.">
      {error && !data ? (
        <ErrorState error={error} onRetry={() => refetch()} compact />
      ) : isLoading || !data ? (
        <SkeletonRows rows={3} />
      ) : !data.length ? (
        <EmptyState compact title="Queue is empty" description="No tasks are waiting or dead." />
      ) : (
        <div className="relative -mx-4 overflow-x-auto sm:mx-0">
          <table className="w-full min-w-[40rem] text-sm">
            <thead>
              <tr className="table-head">
                <th className="px-3 py-2">Task</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Attempts</th>
                <th className="px-3 py-2">Next attempt</th>
                <th className="px-3 py-2">Last error / payload</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {data.slice(0, 200).map((t) => (
                <tr key={t.id} className="align-top">
                  <td className="whitespace-nowrap px-3 py-2">
                    <span className="font-medium">{humanize(t.kind)}</span> <span className="text-xs text-slate-400">#{t.id}</span>
                  </td>
                  <td className="px-3 py-2">
                    <Badge tone={RUN_STATUS_TONE[t.status] ?? 'slate'}>{t.status}</Badge>
                  </td>
                  <td className="px-3 py-2 tabular">
                    {t.attempts}/{t.max_attempts}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-500 dark:text-slate-400">{t.status === 'queued' ? fmtRelative(t.next_attempt_at) : '—'}</td>
                  <td className="max-w-md px-3 py-2">
                    {t.last_error && <p className="line-clamp-2 break-words text-xs text-red-700 dark:text-red-300" title={t.last_error}>{t.last_error}</p>}
                    <p className="truncate font-mono text-[11px] text-slate-500" title={JSON.stringify(t.payload)}>
                      {t.payload && 'job_id' in t.payload ? (
                        <Link to={`/jobs/${String(t.payload.job_id)}`} className="link">
                          job #{String(t.payload.job_id)}
                        </Link>
                      ) : (
                        JSON.stringify(t.payload)
                      )}
                    </p>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.length > 200 && <p className="mt-2 text-xs text-slate-500">Showing 200 of {data.length}.</p>}
        </div>
      )}
    </Card>
  )
}

export default function RunsPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const selected = id ? Number(id) : null
  const start = useStartRun()
  const { data: status } = useStatus()
  const push = useToast()

  return (
    <div>
      <PageHeader
        title="Runs"
        description="Pipeline history, per-stage results and logs."
        actions={
          <>
            <Button icon={<FlaskConical className="h-4 w-4" />} disabled={!!status?.active_run} loading={start.isPending && start.variables?.dry_run === true} onClick={() => start.mutate({ dry_run: true }, { onSuccess: () => push('success', 'Dry run started') })}>
              Dry run
            </Button>
            <Button variant="primary" icon={<Play className="h-4 w-4" />} disabled={!!status?.active_run} loading={start.isPending && start.variables?.dry_run === false} onClick={() => start.mutate({ dry_run: false }, { onSuccess: () => push('success', 'Run started') })}>
              Run now
            </Button>
          </>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <div className={cx(selected != null && 'hidden lg:block')}>
          <div className="lg:sticky lg:top-32 lg:max-h-[calc(100vh-9rem)] lg:overflow-y-auto lg:pr-1">
            <RunList selected={selected} />
          </div>
        </div>
        <div className={cx('min-w-0', selected == null && 'hidden lg:block')}>
          {selected != null ? (
            <>
              <button type="button" onClick={() => navigate('/runs')} className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white lg:hidden">
                <ArrowLeft className="h-4 w-4" /> All runs
              </button>
              <RunDetailView id={selected} />
            </>
          ) : (
            <div className="card">
              <EmptyState icon={<History className="h-5 w-5" />} title="Select a run" description="Choose a run on the left to see its stages, results and logs." />
            </div>
          )}
        </div>
      </div>
      <div className="mt-6">
        <Tasks />
      </div>
    </div>
  )
}
