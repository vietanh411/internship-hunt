import { useMemo, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Ban, ChevronLeft, ChevronRight, Download, ExternalLink as ExtIcon, HelpCircle, Inbox, RotateCcw, ShieldQuestion, ThumbsUp, Hand } from 'lucide-react'
import { useJob, useJobAction, useJobs, useQuestions } from '../api/hooks'
import type { JobSummary, Question } from '../api/types'
import { canFinish, FinishAllButton, FinishButton } from '../components/assist'
import { EligibilityDecision, LocationText, MarkSubmittedButton, QuestionForm } from '../components/jobs'
import { Badge, Button, ButtonLink, Card, EligibilityBadge, EmptyState, ErrorState, PageHeader, ScoreBadge, Skeleton, SkeletonRows, StatusBadge, Tabs } from '../components/ui'
import { useToast } from '../components/ui/Toast'
import { fmtNumber, fmtRelative, humanize } from '../lib/format'
import { eligibilityMeta } from '../lib/status'

type Tab = 'finish' | 'questions' | 'approval' | 'eligibility' | 'blocked' | 'manual'

function JobLine({ j, children }: { j: JobSummary; children?: ReactNode }) {
  return (
    <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start">
      <div className="flex min-w-0 flex-1 gap-3">
        <ScoreBadge score={j.match_score} />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-semibold text-slate-900 dark:text-white">{j.company}</span>
            {j.lesser_known && <Badge tone="violet">lesser-known</Badge>}
            <StatusBadge status={j.status} />
          </div>
          <Link to={`/jobs/${j.id}`} className="block text-sm text-slate-700 hover:text-indigo-600 hover:underline dark:text-slate-300 dark:hover:text-indigo-300">
            {j.title.trim()}
          </Link>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
            <LocationText job={j} className="max-w-[16rem]" />
            {j.status_updated_at && <span>updated {fmtRelative(j.status_updated_at)}</span>}
          </div>
          {j.next_action && <p className="mt-1.5 text-sm text-slate-600 dark:text-slate-300">{j.next_action}</p>}
        </div>
      </div>
      {children && <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">{children}</div>}
    </div>
  )
}

// ------------------------------------------------------------------ questions

function QuestionsTab({ questions }: { questions: Question[] }) {
  const [grouped, setGrouped] = useState(true)
  const groups = useMemo(() => {
    const m = new Map<string, Question[]>()
    for (const q of questions) {
      const k = q.question.trim().toLowerCase()
      m.set(k, [...(m.get(k) ?? []), q])
    }
    return [...m.values()].sort((a, b) => b.length - a.length)
  }, [questions])

  if (!questions.length)
    return <EmptyState icon={<HelpCircle className="h-5 w-5" />} title="No open questions" description="When an application form asks something your profile and answer library can't answer truthfully, it appears here." />

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-500 dark:text-slate-400">
        <p>
          {fmtNumber(questions.length)} open question{questions.length === 1 ? '' : 's'} · {fmtNumber(groups.length)} unique
        </p>
        <label className="inline-flex items-center gap-2">
          <input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-indigo-600 dark:border-slate-600 dark:bg-slate-800" checked={grouped} onChange={(e) => setGrouped(e.target.checked)} />
          Group identical questions
        </label>
      </div>
      {grouped
        ? groups.map((g) => (
            <div key={g[0].id} className="card p-1">
              {g.length > 1 && (
                <div className="px-3 pb-1 pt-2 text-xs text-slate-500 dark:text-slate-400">
                  Asked by {g.length} applications:{' '}
                  {g.slice(0, 6).map((q, i) => (
                    <span key={q.id}>
                      {i > 0 && ', '}
                      <Link to={`/jobs/${q.job_id}`} className="link">
                        {q.company}
                      </Link>
                    </span>
                  ))}
                  {g.length > 6 && ` and ${g.length - 6} more`}. Saving with “reuse” answers all of them.
                </div>
              )}
              <QuestionForm q={g[0]} showJob={g.length === 1} />
            </div>
          ))
        : questions.map((q) => (
            <div key={q.id} className="card p-1">
              <QuestionForm q={q} />
            </div>
          ))}
    </div>
  )
}

// ------------------------------------------------------------------ eligibility

function EligibilityCard({ j }: { j: JobSummary }) {
  const { data: d, isLoading } = useJob(j.id)
  const reasons = d?.eligibility_reasons ?? []
  return (
    <li className="p-4">
      <div className="flex gap-3">
        <ScoreBadge score={j.match_score} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-semibold text-slate-900 dark:text-white">{j.company}</span>
            <EligibilityBadge eligibility={j.eligibility} />
            {j.eligibility_category && <Badge tone="slate">{humanize(j.eligibility_category)}</Badge>}
          </div>
          <Link to={`/jobs/${j.id}`} className="block text-sm text-slate-700 hover:underline dark:text-slate-300">
            {j.title.trim()}
          </Link>
          <div className="mt-2 space-y-1.5">
            {isLoading ? (
              <Skeleton className="h-10 w-full" />
            ) : reasons.length ? (
              reasons.map((r, i) => (
                <div key={i} className="text-sm">
                  <span className="mr-1.5 inline-block">
                    <Badge tone={eligibilityMeta(r.verdict).tone}>{eligibilityMeta(r.verdict).label}</Badge>
                  </span>
                  <span className="font-medium text-slate-700 dark:text-slate-200">{r.rule}</span>
                  {r.quote && <blockquote className="mt-1 border-l-2 border-slate-300 pl-3 italic text-slate-600 dark:border-slate-600 dark:text-slate-300">“{r.quote}”</blockquote>}
                </div>
              ))
            ) : (
              <p className="text-sm text-slate-500">No quoted statements.</p>
            )}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {j.posting_url && (
              <ButtonLink href={j.posting_url} target="_blank" rel="noopener noreferrer" size="xs" icon={<ExtIcon className="h-3.5 w-3.5" />}>
                Read posting
              </ButtonLink>
            )}
          </div>
          <div className="mt-3">
            <EligibilityDecision jobId={j.id} compact />
          </div>
        </div>
      </div>
    </li>
  )
}

function EligibilityTab() {
  const [page, setPage] = useState(1)
  const pageSize = 10
  const { data, isLoading, isFetching, error, refetch } = useJobs({ status: 'eligibility_review', sort: 'score', order: 'desc', page: String(page), page_size: String(pageSize) })
  if (error && !data) return <ErrorState error={error} onRetry={() => refetch()} />
  if (isLoading || !data) return <SkeletonRows rows={4} />
  if (!data.total)
    return <EmptyState icon={<ShieldQuestion className="h-5 w-5" />} title="No eligibility reviews" description="Postings with ambiguous work-authorization language wait here for your decision." />
  const pages = Math.ceil(data.total / pageSize)
  return (
    <div className={isFetching ? 'opacity-70' : ''}>
      <p className="mb-3 text-sm text-slate-500 dark:text-slate-400">
        {fmtNumber(data.total)} postings need a decision, highest match score first. Approving queues the job for resume tailoring.
      </p>
      <ul className="card divide-y divide-slate-100 dark:divide-slate-800">
        {data.items.map((j) => (
          <EligibilityCard key={j.id} j={j} />
        ))}
      </ul>
      <div className="mt-3 flex items-center justify-end gap-2 text-sm">
        <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} icon={<ChevronLeft className="h-4 w-4" />} aria-label="Previous page" />
        <span className="tabular text-slate-500">
          {page} / {pages}
        </span>
        <Button size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)} icon={<ChevronRight className="h-4 w-4" />} aria-label="Next page" />
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ page

export default function ReviewPage() {
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab) || 'finish'
  const setTab = (t: Tab) => setParams({ tab: t }, { replace: true })
  const push = useToast()

  const questions = useQuestions('open')
  const ready = useJobs({ status: 'ready_to_apply', sort: 'priority', page_size: '500' })
  const blocked = useJobs({ status: 'blocked,failed', sort: 'priority', page_size: '500' })
  const eligCount = useJobs({ status: 'eligibility_review', page_size: '1' })
  const approve = useJobAction('approve')
  const retry = useJobAction('retry')

  const needsFinish = (j: JobSummary) => /Finish application|confirm you.?re human|verification code/i.test(j.next_action ?? '')
  const toFinish = [...(ready.data?.items ?? []), ...(blocked.data?.items ?? [])].filter((j) => canFinish(j) && needsFinish(j))
  const awaiting = (ready.data?.items ?? []).filter((j) => j.apply_method === 'browser' && !j.approved && !needsFinish(j))
  const manual = (ready.data?.items ?? []).filter((j) => j.apply_method === 'manual' && !canFinish(j))

  const tabs: { id: Tab; label: string; count: number | null }[] = [
    { id: 'finish', label: 'To finish', count: ready.data && blocked.data ? toFinish.length : null },
    { id: 'questions', label: 'Open questions', count: questions.data?.length ?? null },
    { id: 'approval', label: 'Awaiting approval', count: ready.data ? awaiting.length : null },
    { id: 'eligibility', label: 'Eligibility reviews', count: eligCount.data?.total ?? null },
    { id: 'blocked', label: 'Blocked & failed', count: blocked.data?.total ?? null },
    { id: 'manual', label: 'Manual apply', count: ready.data ? manual.length : null },
  ]

  return (
    <div>
      <PageHeader title="Review queue" description="Everything that needs a decision or an answer from you." />
      <div className="mb-5">
        <Tabs tabs={tabs} value={tab} onChange={setTab} ariaLabel="Review sections" />
      </div>

      {tab === 'finish' && (
        <Card
          title="Applications to finish"
          subtitle="Fully prepared. These sites ask you to confirm you're human (an emailed code, a picture check or a sign-in). Finish all opens them one after another in a single browser window: check each, click Submit (or Skip), and the next opens by itself. Confirmations are recorded and count toward today's target."
          actions={toFinish.length ? <FinishAllButton count={toFinish.length} /> : undefined}
        >
          {!ready.data || !blocked.data ? (
            <SkeletonRows rows={3} />
          ) : !toFinish.length ? (
            <EmptyState compact icon={<Inbox className="h-5 w-5" />} title="Nothing to finish" description="Applications that need your one-click finish appear here." />
          ) : (
            <ul className="-mx-4 -my-4 divide-y divide-slate-100 dark:divide-slate-800 sm:-mx-5">
              {toFinish.map((j) => (
                <li key={j.id}>
                  <JobLine j={j}>
                    <Link to={`/jobs/${j.id}`} className="link text-sm">
                      Review answers
                    </Link>
                    <FinishButton job={j} />
                  </JobLine>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {tab === 'questions' &&
        (questions.error && !questions.data ? (
          <ErrorState error={questions.error} onRetry={() => questions.refetch()} />
        ) : !questions.data ? (
          <SkeletonRows rows={4} />
        ) : (
          <QuestionsTab questions={questions.data} />
        ))}

      {tab === 'approval' && (
        <Card title="Applications awaiting approval" subtitle="Prepared browser submissions in review mode (Mode B). Approving lets the next run, or Submit now, send them.">
          {ready.error && !ready.data ? (
            <ErrorState error={ready.error} onRetry={() => ready.refetch()} compact />
          ) : !ready.data ? (
            <SkeletonRows rows={3} />
          ) : !awaiting.length ? (
            <EmptyState compact icon={<Inbox className="h-5 w-5" />} title="Nothing awaiting approval" description="Prepared applications that need your sign-off appear here." />
          ) : (
            <ul className="-mx-4 -my-4 divide-y divide-slate-100 dark:divide-slate-800 sm:-mx-5">
              {awaiting.map((j) => (
                <li key={j.id}>
                  <JobLine j={j}>
                    <Link to={`/jobs/${j.id}`} className="link text-sm">
                      Review answers
                    </Link>
                    <FinishButton job={j} />
                    <Button
                      size="sm"
                      variant="success"
                      icon={<ThumbsUp className="h-4 w-4" />}
                      loading={approve.isPending && approve.variables?.id === j.id}
                      onClick={() => approve.mutate({ id: j.id }, { onSuccess: () => push('success', `Approved ${j.company}`) })}
                    >
                      Approve
                    </Button>
                  </JobLine>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {tab === 'eligibility' && <EligibilityTab />}

      {tab === 'blocked' && (
        <Card title="Blocked and failed" subtitle="Answer the open questions (or fix the cause shown), then Retry so the next run re-prepares the application.">
          {blocked.error && !blocked.data ? (
            <ErrorState error={blocked.error} onRetry={() => blocked.refetch()} compact />
          ) : !blocked.data ? (
            <SkeletonRows rows={3} />
          ) : !blocked.data.items.length ? (
            <EmptyState compact icon={<Ban className="h-5 w-5" />} title="Nothing is blocked" description="Jobs that need input or hit an error show up here." />
          ) : (
            <ul className="-mx-4 -my-4 divide-y divide-slate-100 dark:divide-slate-800 sm:-mx-5">
              {blocked.data.items.map((j) => (
                <li key={j.id}>
                  <JobLine j={j}>
                    {j.open_questions > 0 && <Badge tone="rose">{j.open_questions} question{j.open_questions > 1 ? 's' : ''} in plan</Badge>}
                    <Link to={`/jobs/${j.id}`} className="link text-sm">
                      Details
                    </Link>
                    {j.apply_method === 'browser' && j.open_questions === 0 && <FinishButton job={j} />}
                    <Button
                      size="sm"
                      icon={<RotateCcw className="h-4 w-4" />}
                      loading={retry.isPending && retry.variables?.id === j.id}
                      onClick={() => retry.mutate({ id: j.id }, { onSuccess: () => push('success', `Retry scheduled for ${j.company}`) })}
                    >
                      Retry
                    </Button>
                  </JobLine>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {tab === 'manual' && (
        <Card title="Manual applications" subtitle="Apply in your own browser: Apply opens the employer's form, Resume downloads the tailored PDF, and Answers lists every answer with Copy buttons. Then mark the job submitted. (Sites like iCIMS and SmartRecruiters, and Lever, whose bot check rejects the automated window, land here.)">
          {ready.error && !ready.data ? (
            <ErrorState error={ready.error} onRetry={() => ready.refetch()} compact />
          ) : !ready.data ? (
            <SkeletonRows rows={3} />
          ) : !manual.length ? (
            <EmptyState compact icon={<Hand className="h-5 w-5" />} title="No manual applications waiting" description="Prepared applications on platforms like Workday or iCIMS appear here with a ready packet." />
          ) : (
            <ul className="-mx-4 -my-4 divide-y divide-slate-100 dark:divide-slate-800 sm:-mx-5">
              {manual.map((j) => (
                <li key={j.id}>
                  <JobLine j={j}>
                    {(j.apply_url || j.posting_url) && (
                      <ButtonLink href={(j.apply_url || j.posting_url)!} target="_blank" rel="noopener noreferrer" size="sm" variant="primary" icon={<ExtIcon className="h-4 w-4" />}>
                        Apply
                      </ButtonLink>
                    )}
                    {j.has_resume && (
                      <ButtonLink href={`/api/jobs/${j.id}/resume`} size="sm" icon={<Download className="h-4 w-4" />}>
                        Resume
                      </ButtonLink>
                    )}
                    <Link to={`/jobs/${j.id}`} className="link text-sm" title="Every answer for this form, with Copy buttons">
                      Answers
                    </Link>
                    <MarkSubmittedButton jobId={j.id} />
                  </JobLine>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  )
}
