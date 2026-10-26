import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowDownWideNarrow, ArrowUpNarrowWide, ChevronLeft, ChevronRight, FilterX, SearchX, SlidersHorizontal } from 'lucide-react'
import { useJobs } from '../api/hooks'
import type { JobSummary } from '../api/types'
import { JobQuickLinks, LocationText } from '../components/jobs'
import { Badge, Button, EligibilityBadge, EmptyState, ErrorState, PageHeader, ScoreBadge, SkeletonRows, StatusBadge, cx } from '../components/ui'
import { fmtDate, fmtNumber, fmtSalary, humanize } from '../lib/format'
import { ALL_STATUSES, eligibilityMeta, statusMeta } from '../lib/status'

const FILTER_KEYS = ['q', 'company', 'location', 'category', 'min_score', 'eligibility', 'status', 'salary_min', 'posted_after', 'lesser_known', 'has_resume'] as const
const SORTS = [
  ['priority', 'Priority'],
  ['score', 'Match score'],
  ['posted', 'Date posted'],
  ['discovered', 'Date discovered'],
  ['company', 'Company'],
  ['salary', 'Salary'],
] as const

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(t)
  }, [value, ms])
  return v
}

function FacetSelect({
  id,
  label,
  value,
  onChange,
  facets,
  labelFor,
  order,
}: {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  facets: Record<string, number> | undefined
  labelFor?: (k: string) => string
  order?: string[]
}) {
  const keys = useMemo(() => {
    const ks = Object.keys(facets ?? {}).filter((k) => k !== 'null' && k !== '')
    if (order) return [...order.filter((k) => ks.includes(k)), ...ks.filter((k) => !order.includes(k))]
    return ks.sort((a, b) => (facets![b] ?? 0) - (facets![a] ?? 0))
  }, [facets, order])
  return (
    <div>
      <label htmlFor={id} className="label text-xs">
        {label}
      </label>
      <select id={id} className="input mt-1" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Any</option>
        {value && !keys.includes(value) && <option value={value}>{value.split(',').map((v) => (labelFor ? labelFor(v) : humanize(v))).join(', ')}</option>}
        {keys.map((k) => (
          <option key={k} value={k}>
            {labelFor ? labelFor(k) : humanize(k)} ({fmtNumber(facets?.[k])})
          </option>
        ))}
      </select>
    </div>
  )
}

function ScoreSlider({ value, onCommit }: { value: string; onCommit: (v: string) => void }) {
  const [v, setV] = useState(value || '0')
  useEffect(() => setV(value || '0'), [value])
  const commit = () => onCommit(v === '0' ? '' : v)
  return (
    <div>
      <label htmlFor="f-score" className="label text-xs">
        Minimum score <span className="font-normal text-slate-500 dark:text-slate-400">{v === '0' ? 'any' : `≥ ${v}`}</span>
      </label>
      <input
        id="f-score"
        type="range"
        min={0}
        max={95}
        step={5}
        className="mt-3 w-full accent-indigo-600"
        value={v}
        onChange={(e) => setV(e.target.value)}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
        aria-valuetext={v === '0' ? 'any score' : `at least ${v}`}
      />
    </div>
  )
}

export default function JobsPage() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const [showFilters, setShowFilters] = useState(() => FILTER_KEYS.some((k) => k !== 'q' && params.get(k)))
  const [q, setQ] = useState(params.get('q') ?? '')
  const dq = useDebounced(q)

  const get = (k: string) => params.get(k) ?? ''
  const set = (patch: Record<string, string>, resetPage = true) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    if (resetPage) next.delete('page')
    setParams(next, { replace: true })
  }

  useEffect(() => {
    if ((params.get('q') ?? '') !== dq) set({ q: dq })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dq])

  const page = Math.max(1, Number(get('page')) || 1)
  const pageSize = Number(get('page_size')) || 50
  const sort = get('sort') || 'priority'
  const order = get('order') || (sort === 'company' ? 'asc' : 'desc')

  const query = useMemo(() => {
    const out: Record<string, string> = { sort, order, page: String(page), page_size: String(pageSize) }
    for (const k of FILTER_KEYS) {
      const v = params.get(k)
      if (v) out[k] = v
    }
    return out
  }, [params, sort, order, page, pageSize])

  const { data, isLoading, isFetching, error, refetch } = useJobs(query)
  const activeFilters = FILTER_KEYS.filter((k) => params.get(k)).length
  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1
  const open = (j: JobSummary) => navigate(`/jobs/${j.id}`)

  return (
    <div>
      <PageHeader
        title="Opportunities"
        description={data ? `${fmtNumber(data.total)} postings match the current filters.` : 'Every discovered posting, searchable and filterable.'}
      />

      <div className="card mb-4 p-3 sm:p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative min-w-0 flex-1">
            <label htmlFor="job-search" className="sr-only">
              Search title, company or description
            </label>
            <input
              id="job-search"
              type="search"
              className="input pl-9"
              placeholder="Search title, company or description…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <svg className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
              <path fillRule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.45 4.39l3.08 3.08a.75.75 0 11-1.06 1.06l-3.08-3.08A7 7 0 012 9z" clipRule="evenodd" />
            </svg>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="sort" className="sr-only">
              Sort by
            </label>
            <select id="sort" className="input w-auto" value={sort} onChange={(e) => set({ sort: e.target.value, order: '' })}>
              {SORTS.map(([v, l]) => (
                <option key={v} value={v}>
                  Sort: {l}
                </option>
              ))}
            </select>
            <Button
              size="md"
              className="px-3"
              onClick={() => set({ order: order === 'desc' ? 'asc' : 'desc' })}
              aria-label={order === 'desc' ? 'Sorted descending; switch to ascending' : 'Sorted ascending; switch to descending'}
              title={order === 'desc' ? 'Descending' : 'Ascending'}
              icon={order === 'desc' ? <ArrowDownWideNarrow className="h-4 w-4" /> : <ArrowUpNarrowWide className="h-4 w-4" />}
            />
            <Button size="md" onClick={() => setShowFilters((s) => !s)} aria-expanded={showFilters} icon={<SlidersHorizontal className="h-4 w-4" />}>
              Filters
              {activeFilters - (params.get('q') ? 1 : 0) > 0 && (
                <span className="rounded-full bg-indigo-100 px-1.5 text-xs font-semibold text-indigo-700 dark:bg-indigo-400/20 dark:text-indigo-200">
                  {activeFilters - (params.get('q') ? 1 : 0)}
                </span>
              )}
            </Button>
            {activeFilters > 0 && (
              <Button
                size="md"
                variant="ghost"
                icon={<FilterX className="h-4 w-4" />}
                onClick={() => {
                  setQ('')
                  setParams(new URLSearchParams(), { replace: true })
                }}
              >
                Clear
              </Button>
            )}
          </div>
        </div>

        {showFilters && (
          <div className="mt-4 grid grid-cols-1 gap-3 border-t border-slate-100 pt-4 dark:border-slate-800 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label htmlFor="f-company" className="label text-xs">
                Company
              </label>
              <input id="f-company" className="input mt-1" defaultValue={get('company')} onBlur={(e) => set({ company: e.target.value.trim() })} onKeyDown={(e) => e.key === 'Enter' && set({ company: (e.target as HTMLInputElement).value.trim() })} placeholder="e.g. Stripe" />
            </div>
            <div>
              <label htmlFor="f-location" className="label text-xs">
                Location
              </label>
              <input id="f-location" className="input mt-1" defaultValue={get('location')} onBlur={(e) => set({ location: e.target.value.trim() })} onKeyDown={(e) => e.key === 'Enter' && set({ location: (e.target as HTMLInputElement).value.trim() })} placeholder="e.g. Chicago" />
            </div>
            <FacetSelect id="f-category" label="Category" value={get('category')} onChange={(v) => set({ category: v })} facets={data?.facets.categories} />
            <ScoreSlider value={get('min_score')} onCommit={(v) => v !== get('min_score') && set({ min_score: v })} />
            <FacetSelect id="f-elig" label="Eligibility" value={get('eligibility')} onChange={(v) => set({ eligibility: v })} facets={data?.facets.eligibility} labelFor={(k) => eligibilityMeta(k).label} order={['eligible', 'review', 'ineligible', 'unknown']} />
            <FacetSelect id="f-status" label="Status" value={get('status')} onChange={(v) => set({ status: v })} facets={data?.facets.statuses} labelFor={(k) => statusMeta(k).label} order={ALL_STATUSES} />
            <div>
              <label htmlFor="f-salary" className="label text-xs">
                Minimum salary
              </label>
              <input
                id="f-salary"
                type="number"
                min={0}
                inputMode="numeric"
                className="input mt-1"
                defaultValue={get('salary_min')}
                placeholder="e.g. 30 (hourly) or 60000"
                onBlur={(e) => set({ salary_min: e.target.value })}
                onKeyDown={(e) => e.key === 'Enter' && set({ salary_min: (e.target as HTMLInputElement).value })}
              />
              <p className="hint">Compared against the posting's own pay period.</p>
            </div>
            <div>
              <label htmlFor="f-posted" className="label text-xs">
                Posted on or after
              </label>
              <input id="f-posted" type="date" className="input mt-1" value={get('posted_after')} onChange={(e) => set({ posted_after: e.target.value })} />
            </div>
            <div>
              <label htmlFor="f-lk" className="label text-xs">
                Lesser-known employers
              </label>
              <select id="f-lk" className="input mt-1" value={get('lesser_known')} onChange={(e) => set({ lesser_known: e.target.value })}>
                <option value="">Any</option>
                <option value="true">Only lesser-known</option>
                <option value="false">Exclude lesser-known</option>
              </select>
            </div>
            <div>
              <label htmlFor="f-res" className="label text-xs">
                Tailored resume
              </label>
              <select id="f-res" className="input mt-1" value={get('has_resume')} onChange={(e) => set({ has_resume: e.target.value })}>
                <option value="">Any</option>
                <option value="true">Has resume</option>
                <option value="false">No resume yet</option>
              </select>
            </div>
          </div>
        )}
      </div>

      <div className={cx('card relative overflow-hidden transition-opacity', isFetching && data ? 'opacity-70' : '')}>
        {error && !data ? (
          <ErrorState error={error} onRetry={() => refetch()} />
        ) : isLoading || !data ? (
          <div className="p-4">
            <SkeletonRows rows={8} />
          </div>
        ) : !data.items.length ? (
          <EmptyState
            icon={<SearchX className="h-5 w-5" />}
            title={activeFilters ? 'No postings match these filters' : 'No postings discovered yet'}
            description={activeFilters ? 'Try loosening a filter or clearing the search.' : 'Start a run from the Overview or Automation page to discover Summer 2027 internships.'}
          />
        ) : (
          <>
            {/* desktop table */}
            <div className="relative hidden overflow-x-auto lg:block">
              <table className="w-full text-sm">
                <thead>
                  <tr className="table-head">
                    <th className="px-4 py-2.5">Score</th>
                    <th className="px-3 py-2.5">Company / title</th>
                    <th className="px-3 py-2.5">Location</th>
                    <th className="px-3 py-2.5">Salary</th>
                    <th className="px-3 py-2.5">Eligibility</th>
                    <th className="px-3 py-2.5">Status</th>
                    <th className="hidden px-3 py-2.5 xl:table-cell">Posted</th>
                    <th className="px-3 py-2.5">
                      <span className="sr-only">Links</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {data.items.map((j) => (
                    <tr
                      key={j.id}
                      className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50"
                      onClick={(e) => {
                        if ((e.target as HTMLElement).closest('a,button')) return
                        open(j)
                      }}
                    >
                      <td className="px-4 py-3 align-top">
                        <ScoreBadge score={j.match_score} />
                      </td>
                      <td className="max-w-[20rem] px-3 py-3 align-top">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate font-semibold text-slate-900 dark:text-white">{j.company}</span>
                          {j.lesser_known && <Badge tone="violet">lesser-known</Badge>}
                        </div>
                        <a
                          href={`#/jobs/${j.id}`}
                          className="line-clamp-2 text-slate-600 hover:text-indigo-600 hover:underline dark:text-slate-300 dark:hover:text-indigo-300"
                        >
                          {j.title.trim()}
                        </a>
                        {j.next_action && <p className="mt-0.5 line-clamp-1 text-xs text-slate-400" title={j.next_action}>{j.next_action}</p>}
                      </td>
                      <td className="max-w-[12rem] px-3 py-3 align-top text-slate-600 dark:text-slate-300">
                        <LocationText job={j} />
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 align-top tabular text-slate-600 dark:text-slate-300">
                        {fmtSalary(j)}
                        <span className="block text-xs text-slate-400 xl:hidden">posted {fmtDate(j.date_posted)}</span>
                      </td>
                      <td className="px-3 py-3 align-top">
                        <EligibilityBadge eligibility={j.eligibility} />
                      </td>
                      <td className="px-3 py-3 align-top">
                        <StatusBadge status={j.status} />
                      </td>
                      <td className="hidden whitespace-nowrap px-3 py-3 align-top text-slate-500 dark:text-slate-400 xl:table-cell">{fmtDate(j.date_posted)}</td>
                      <td className="px-3 py-3 align-top">
                        <JobQuickLinks job={j} compact />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* mobile cards */}
            <ul className="divide-y divide-slate-100 dark:divide-slate-800 lg:hidden">
              {data.items.map((j) => (
                <li key={j.id} className="flex gap-3 p-4">
                  <ScoreBadge score={j.match_score} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-semibold text-slate-900 dark:text-white">{j.company}</span>
                      {j.lesser_known && <Badge tone="violet">lesser-known</Badge>}
                    </div>
                    <a href={`#/jobs/${j.id}`} className="mt-0.5 block text-sm text-slate-700 hover:underline dark:text-slate-300">
                      {j.title.trim()}
                    </a>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      <EligibilityBadge eligibility={j.eligibility} />
                      <StatusBadge status={j.status} />
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
                      <LocationText job={j} className="max-w-full" />
                      <span>{fmtSalary(j)}</span>
                      <span>Posted {fmtDate(j.date_posted)}</span>
                    </div>
                    <div className="-ml-1.5 mt-1">
                      <JobQuickLinks job={j} />
                    </div>
                  </div>
                </li>
              ))}
            </ul>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-4 py-3 text-sm dark:border-slate-800">
              <p className="text-slate-500 dark:text-slate-400">
                Showing <span className="font-medium text-slate-800 dark:text-slate-200">{fmtNumber((page - 1) * pageSize + 1)}</span>–
                <span className="font-medium text-slate-800 dark:text-slate-200">{fmtNumber(Math.min(page * pageSize, data.total))}</span> of{' '}
                <span className="font-medium text-slate-800 dark:text-slate-200">{fmtNumber(data.total)}</span>
              </p>
              <div className="flex items-center gap-2">
                <label htmlFor="psize" className="sr-only">
                  Rows per page
                </label>
                <select id="psize" className="input w-auto py-1.5" value={pageSize} onChange={(e) => set({ page_size: e.target.value })}>
                  {[25, 50, 100, 200].map((n) => (
                    <option key={n} value={n}>
                      {n} / page
                    </option>
                  ))}
                </select>
                <Button size="sm" disabled={page <= 1} onClick={() => set({ page: String(page - 1) }, false)} icon={<ChevronLeft className="h-4 w-4" />} aria-label="Previous page" />
                <span className="text-slate-500 tabular dark:text-slate-400">
                  {page} / {totalPages}
                </span>
                <Button size="sm" disabled={page >= totalPages} onClick={() => set({ page: String(page + 1) }, false)} icon={<ChevronRight className="h-4 w-4" />} aria-label="Next page" />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
