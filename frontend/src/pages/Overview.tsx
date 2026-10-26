import { Link } from 'react-router-dom'
import {
  AlertOctagon,
  Award,
  Ban,
  CalendarCheck,
  CheckCircle2,
  FileText,
  FlaskConical,
  HelpCircle,
  Inbox,
  MessageSquareReply,
  Play,
  Search,
  Send,
  Sparkles,
  Star,
  TrendingUp,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { useOverview, useStartRun, useStatus } from '../api/hooks'
import type { JobSummary, OverviewResponse, RunSummary } from '../api/types'
import { ActivityChart } from '../components/charts/ActivityChart'
import { JobQuickLinks, LocationText } from '../components/jobs'
import { Badge, Button, Card, EligibilityBadge, EmptyState, ErrorState, PageHeader, ScoreBadge, Skeleton, StatusBadge, cx } from '../components/ui'
import { useToast } from '../components/ui/Toast'
import { DASH, fmtDuration, fmtNumber, fmtPercent, fmtRelative, fmtSalary, humanize } from '../lib/format'
import { RUN_STATUS_TONE } from '../lib/status'
import { stageHighlights, triggerLabel } from '../lib/runs'

interface Kpi {
  label: string
  value: string
  icon: ReactNode
  to?: string
  hint?: string
  accent?: string
}

function kpis(o: OverviewResponse): Kpi[] {
  return [
    { label: 'Total discovered', value: fmtNumber(o.total_discovered), icon: <Search className="h-4 w-4" />, to: '/jobs' },
    { label: 'Eligible', value: fmtNumber(o.eligible), icon: <CheckCircle2 className="h-4 w-4" />, to: '/jobs?eligibility=eligible', hint: `${fmtNumber(o.eligibility_review)} need review · ${fmtNumber(o.ineligible)} ineligible` },
    { label: 'High match', value: fmtNumber(o.high_match), icon: <Star className="h-4 w-4" />, to: '/jobs?eligibility=eligible&min_score=70&sort=score', hint: 'Eligible, score ≥ 70' },
    { label: 'Resumes generated', value: fmtNumber(o.resumes_generated), icon: <FileText className="h-4 w-4" />, to: '/jobs?has_resume=true' },
    { label: 'Applications submitted', value: fmtNumber(o.applications_submitted), icon: <Send className="h-4 w-4" />, to: '/pipeline' },
    { label: 'Awaiting review', value: fmtNumber(o.awaiting_review), icon: <Inbox className="h-4 w-4" />, to: '/review?tab=approval', accent: o.awaiting_review ? 'text-violet-600 dark:text-violet-400' : undefined },
    { label: 'Blocked', value: fmtNumber(o.blocked), icon: <Ban className="h-4 w-4" />, to: '/review?tab=blocked', accent: o.blocked ? 'text-orange-600 dark:text-orange-400' : undefined },
    { label: 'Failed', value: fmtNumber(o.failed), icon: <AlertOctagon className="h-4 w-4" />, to: '/review?tab=blocked', accent: o.failed ? 'text-red-600 dark:text-red-400' : undefined },
    { label: 'Interviews', value: fmtNumber(o.interviews), icon: <CalendarCheck className="h-4 w-4" />, to: '/jobs?status=interview' },
    { label: 'Offers', value: fmtNumber(o.offers), icon: <Award className="h-4 w-4" />, to: '/jobs?status=offer', accent: o.offers ? 'text-green-600 dark:text-green-400' : undefined },
    { label: 'Response rate', value: o.response_rate == null ? DASH : fmtPercent(o.response_rate, 1), icon: <MessageSquareReply className="h-4 w-4" />, hint: o.response_rate == null ? 'No submissions yet' : 'Assessment, interview, offer or rejection' },
    { label: 'Open questions', value: fmtNumber(o.open_questions), icon: <HelpCircle className="h-4 w-4" />, to: '/review?tab=questions', accent: o.open_questions ? 'text-rose-600 dark:text-rose-400' : undefined },
  ]
}

function KpiCard({ k }: { k: Kpi }) {
  const body = (
    <>
      <div className="flex items-center justify-between gap-2 text-slate-500 dark:text-slate-400">
        <span className="truncate text-xs font-medium">{k.label}</span>
        <span className="shrink-0 text-slate-400 dark:text-slate-500" aria-hidden>
          {k.icon}
        </span>
      </div>
      <p className={cx('mt-1.5 text-2xl font-semibold tracking-tight text-slate-900 dark:text-white', k.accent)}>{k.value}</p>
      {k.hint && <p className="mt-0.5 truncate text-[11px] text-slate-500 dark:text-slate-400" title={k.hint}>{k.hint}</p>}
    </>
  )
  const cls = 'card block p-3.5 sm:p-4'
  return k.to ? (
    <Link to={k.to} className={cx(cls, 'transition hover:border-indigo-300 hover:shadow-md dark:hover:border-indigo-500/50')}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  )
}

function TopOpportunities({ jobs }: { jobs: JobSummary[] }) {
  if (!jobs.length)
    return (
      <EmptyState
        compact
        icon={<Sparkles className="h-5 w-5" />}
        title="No eligible opportunities yet"
        description="Once discovery, eligibility screening and matching run, the highest-priority eligible postings show up here."
      />
    )
  return (
    <ul className="-my-2 divide-y divide-slate-100 dark:divide-slate-800">
      {jobs.map((j) => (
        <li key={j.id} className="flex items-start gap-3 py-3">
          <ScoreBadge score={j.match_score} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="text-sm font-semibold text-slate-900 dark:text-white">{j.company}</span>
              {j.lesser_known && <Badge tone="violet">lesser-known</Badge>}
              <EligibilityBadge eligibility={j.eligibility} />
              <StatusBadge status={j.status} />
            </div>
            <Link to={`/jobs/${j.id}`} className="mt-0.5 block truncate text-sm text-slate-700 hover:text-indigo-600 hover:underline dark:text-slate-300 dark:hover:text-indigo-300">
              {j.title.trim()}
            </Link>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
              <LocationText job={j} className="max-w-[16rem]" />
              <span>{fmtSalary(j)}</span>
              {j.date_posted && <span>Posted {fmtRelative(j.date_posted)}</span>}
            </div>
          </div>
          <JobQuickLinks job={j} compact />
        </li>
      ))}
    </ul>
  )
}

function RunStats({ run }: { run: RunSummary }) {
  const stages = Object.entries(run.stats ?? {}).filter(([k]) => !k.startsWith('_'))
  if (!stages.length) return <p className="text-xs text-slate-500 dark:text-slate-400">No stage results recorded.</p>
  return (
    <dl className="space-y-1.5 text-xs">
      {stages.map(([stage, res]) => (
        <div key={stage} className="flex min-w-0 gap-2">
          <dt className="w-28 shrink-0 font-medium text-slate-600 dark:text-slate-300">{humanize(stage)}</dt>
          <dd className="min-w-0 truncate text-slate-500 dark:text-slate-400" title={stageHighlights(stage, res, 8).join(' · ')}>
            {stageHighlights(stage, res).join(' · ') || 'no counts'}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function LastRun() {
  const { data: s } = useStatus()
  const start = useStartRun()
  const push = useToast()
  const active = s?.active_run
  const last = s?.last_run
  const go = (dry: boolean) =>
    start.mutate(
      { dry_run: dry },
      { onSuccess: () => push('success', dry ? 'Dry run started' : 'Run started', dry ? 'No employer will be contacted.' : 'Watch progress in the status bar.') },
    )
  return (
    <Card
      title="Pipeline run"
      icon={<TrendingUp className="h-4 w-4 text-slate-400" />}
      actions={
        <>
          <Button size="sm" icon={<FlaskConical className="h-4 w-4" />} onClick={() => go(true)} disabled={!!active} loading={start.isPending && start.variables?.dry_run === true}>
            Dry run
          </Button>
          <Button size="sm" variant="primary" icon={<Play className="h-4 w-4" />} onClick={() => go(false)} disabled={!!active} loading={start.isPending && start.variables?.dry_run === false}>
            Run now
          </Button>
        </>
      }
    >
      {!s ? (
        <Skeleton className="h-24 w-full" />
      ) : active ? (
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Run <Link to={`/runs/${active.id}`} className="link">#{active.id}</Link> is in progress ({active.current_stage ? humanize(active.current_stage) : 'starting'}).
        </p>
      ) : last ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Link to={`/runs/${last.id}`} className="font-semibold text-slate-900 hover:underline dark:text-white">
              Run #{last.id}
            </Link>
            <Badge tone={RUN_STATUS_TONE[last.status] ?? 'slate'} dot>
              {humanize(last.status)}
            </Badge>
            {last.dry_run && <Badge tone="sky">dry run</Badge>}
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {triggerLabel(last.trigger)} · {fmtRelative(last.finished_at ?? last.started_at)} · took {fmtDuration(last.started_at, last.finished_at)}
            </span>
          </div>
          {last.error && <p className="text-sm text-red-600 dark:text-red-400">{last.error}</p>}
          <RunStats run={last} />
          {last.report_url && (
            <a href={last.report_url} target="_blank" rel="noopener noreferrer" className="link text-sm">
              Open daily report ↗
            </a>
          )}
        </div>
      ) : (
        <EmptyState compact icon={<Play className="h-5 w-5" />} title="No runs yet — click Run now" description="Or start a dry run to see what the pipeline would do without contacting any employer." />
      )}
    </Card>
  )
}

function Totals({ o }: { o: OverviewResponse }) {
  const rows: [string, keyof OverviewResponse['today']][] = [
    ['Discovered', 'discovered'],
    ['Resumes', 'resumes'],
    ['Submitted', 'submitted'],
  ]
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-slate-500 dark:text-slate-400">
          <th className="pb-2 font-medium" />
          <th className="pb-2 text-right font-medium">Today</th>
          <th className="pb-2 text-right font-medium">Last 7 days</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
        {rows.map(([label, key], i) => (
          <tr key={key}>
            <td className="py-2 text-slate-600 dark:text-slate-300">
              <span className="mr-2 inline-block h-2.5 w-2.5 rounded-[3px] align-middle" style={{ background: `var(--series-${i + 1})` }} aria-hidden />
              {label}
            </td>
            <td className="py-2 text-right font-semibold tabular text-slate-900 dark:text-white">{fmtNumber(o.today[key])}</td>
            <td className="py-2 text-right font-semibold tabular text-slate-900 dark:text-white">{fmtNumber(o.week[key])}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function OverviewPage() {
  const { data: o, isLoading, error, refetch } = useOverview()

  return (
    <div>
      <PageHeader title="Overview" description="Where the Summer 2027 search stands right now." />
      {error && !o ? (
        <div className="card">
          <ErrorState error={error} onRetry={() => refetch()} />
        </div>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
            {isLoading || !o
              ? Array.from({ length: 12 }).map((_, i) => <Skeleton key={i} className="h-[92px] rounded-xl" />)
              : kpis(o).map((k) => <KpiCard key={k.label} k={k} />)}
          </div>

          <div className="grid gap-6 lg:grid-cols-3 [&>*]:min-w-0">
            <Card title="Activity, last 14 days" className="min-w-0 lg:col-span-2">
              {!o ? (
                <Skeleton className="h-64 w-full" />
              ) : (
                <ActivityChart
                  days={o.series.days}
                  series={[
                    { key: 'discovered', label: 'Discovered', color: 'var(--series-1)', values: o.series.discovered },
                    { key: 'resumes', label: 'Resumes generated', color: 'var(--series-2)', values: o.series.resumes },
                    { key: 'submitted', label: 'Submitted', color: 'var(--series-3)', values: o.series.submitted },
                  ]}
                />
              )}
            </Card>
            <div className="space-y-6">
              <Card title="Today and this week">{!o ? <Skeleton className="h-28 w-full" /> : <Totals o={o} />}</Card>
              <LastRun />
            </div>
          </div>

          <Card
            title="Top opportunities"
            subtitle="Eligible postings ranked by priority (match score, recency, lesser-known boost)."
            actions={
              <Link to="/jobs?eligibility=eligible" className="link text-sm">
                View all
              </Link>
            }
          >
            {!o ? <Skeleton className="h-64 w-full" /> : <TopOpportunities jobs={o.top_opportunities} />}
          </Card>
        </div>
      )}
    </div>
  )
}
