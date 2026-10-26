import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronsLeftRight, ChevronsRightLeft, KanbanSquare } from 'lucide-react'
import { usePipeline } from '../api/hooks'
import type { JobStatus, JobSummary } from '../api/types'
import { EmptyState, ErrorState, PageHeader, ScoreBadge, Skeleton, cx } from '../components/ui'
import { fmtNumber } from '../lib/format'
import { EXCEPTION_ORDER, STATUS_META, TONE_BORDER, TONE_DOT, WORKFLOW_ORDER } from '../lib/status'

function JobCard({ j }: { j: JobSummary }) {
  return (
    <li>
      <Link
        to={`/jobs/${j.id}`}
        className="block rounded-lg border border-slate-200 bg-white p-3 shadow-sm transition hover:border-indigo-300 hover:shadow-md dark:border-slate-700 dark:bg-slate-900 dark:hover:border-indigo-500/60"
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">{j.company}</p>
            <p className="line-clamp-2 text-xs text-slate-600 dark:text-slate-300">{j.title.trim()}</p>
          </div>
          <ScoreBadge score={j.match_score} size="sm" />
        </div>
        {j.next_action && <p className="mt-2 line-clamp-2 border-t border-slate-100 pt-2 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">{j.next_action}</p>}
      </Link>
    </li>
  )
}

function Column({ status, total, items, collapsed, onToggle }: { status: JobStatus; total: number; items: JobSummary[]; collapsed: boolean; onToggle: () => void }) {
  const m = STATUS_META[status]
  if (collapsed) {
    return (
      <button
        type="button"
        onClick={onToggle}
        className={cx(
          'flex w-12 shrink-0 snap-start flex-col items-center gap-3 rounded-xl border border-t-4 border-slate-200 bg-slate-100/70 py-3 text-slate-600 hover:bg-slate-100 dark:border-slate-800 dark:bg-slate-900/60 dark:text-slate-300 dark:hover:bg-slate-900',
          TONE_BORDER[m.tone],
        )}
        aria-label={`Expand ${m.label} column (${total})`}
        aria-expanded={false}
      >
        <ChevronsLeftRight className="h-4 w-4 shrink-0" aria-hidden />
        <span className="rounded-full bg-white px-1.5 text-xs font-semibold tabular shadow-sm dark:bg-slate-800">{fmtNumber(total)}</span>
        <span className="text-xs font-semibold [writing-mode:vertical-rl]">{m.label}</span>
      </button>
    )
  }
  return (
    <section
      aria-label={`${m.label}: ${total} jobs`}
      className={cx('flex max-h-[calc(100vh-15rem)] min-h-[12rem] w-[17rem] shrink-0 snap-start flex-col rounded-xl border border-t-4 border-slate-200 bg-slate-100/70 dark:border-slate-800 dark:bg-slate-900/60 sm:w-72', TONE_BORDER[m.tone])}
    >
      <header className="flex items-center justify-between gap-2 px-3 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className={cx('h-2 w-2 shrink-0 rounded-full', TONE_DOT[m.tone])} aria-hidden />
          <h2 className="truncate text-sm font-semibold text-slate-800 dark:text-slate-100" title={m.help}>
            {m.label}
          </h2>
          <span className="rounded-full bg-white px-1.5 text-xs font-semibold text-slate-600 tabular shadow-sm dark:bg-slate-800 dark:text-slate-300">{fmtNumber(total)}</span>
        </div>
        {EXCEPTION_ORDER.includes(status) && (
          <button type="button" onClick={onToggle} className="rounded p-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200" aria-label={`Collapse ${m.label}`} aria-expanded>
            <ChevronsRightLeft className="h-4 w-4" />
          </button>
        )}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 scrollbar-thin">
        {items.length ? (
          <ul className="space-y-2">
            {items.map((j) => (
              <JobCard key={j.id} j={j} />
            ))}
          </ul>
        ) : (
          <p className="px-2 py-6 text-center text-xs text-slate-400">Nothing here</p>
        )}
        {total > items.length && (
          <Link to={`/jobs?status=${status}`} className="mt-2 block rounded-lg px-2 py-2 text-center text-xs font-medium text-indigo-600 hover:bg-white dark:text-indigo-400 dark:hover:bg-slate-800">
            Showing top {items.length} of {fmtNumber(total)} — view all
          </Link>
        )}
      </div>
    </section>
  )
}

export default function PipelinePage() {
  const { data, isLoading, error, refetch } = usePipeline()
  const [expanded, setExpanded] = useState<Set<JobStatus>>(new Set())
  const toggle = (s: JobStatus) =>
    setExpanded((prev) => {
      const n = new Set(prev)
      if (n.has(s)) n.delete(s)
      else n.add(s)
      return n
    })
  const total = data ? Object.values(data).reduce((a, c) => a + (c?.total ?? 0), 0) : 0

  return (
    <div>
      <PageHeader
        title="Pipeline"
        description="Every job by workflow stage, highest priority first. Exception columns are collapsed; click to expand."
      />
      {error && !data ? (
        <div className="card">
          <ErrorState error={error} onRetry={() => refetch()} />
        </div>
      ) : isLoading || !data ? (
        <div className="flex gap-3 overflow-hidden">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-96 w-72 shrink-0 rounded-xl" />
          ))}
        </div>
      ) : total === 0 ? (
        <div className="card">
          <EmptyState icon={<KanbanSquare className="h-5 w-5" />} title="The pipeline is empty" description="Run discovery from the Overview or Automation page; new postings land in Discovered." />
        </div>
      ) : (
        <div className="relative -mx-4 overflow-x-auto px-4 pb-4 scrollbar-thin sm:-mx-6 sm:px-6">
          <div className="flex snap-x snap-mandatory gap-3 sm:snap-none">
            {WORKFLOW_ORDER.map((s) => (
              <Column key={s} status={s} total={data[s]?.total ?? 0} items={data[s]?.items ?? []} collapsed={false} onToggle={() => {}} />
            ))}
            <div className="w-px shrink-0 bg-slate-200 dark:bg-slate-800" aria-hidden />
            {EXCEPTION_ORDER.map((s) => (
              <Column key={s} status={s} total={data[s]?.total ?? 0} items={data[s]?.items ?? []} collapsed={!expanded.has(s)} onToggle={() => toggle(s)} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
