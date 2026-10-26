import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import {
  AlertTriangle,
  Bell,
  BellOff,
  Bot,
  CalendarClock,
  CheckCheck,
  ClipboardList,
  Gauge,
  History,
  KanbanSquare,
  Laptop,
  Moon,
  PauseCircle,
  Search,
  Square,
  Sun,
  UserRound,
  Zap,
} from 'lucide-react'
import { useAutomationAction, useNotifications, useOverview, useReadAllNotifications, useStatus } from '../api/hooks'
import { useTheme } from '../lib/theme'
import { fmtDateTime, fmtRelative, humanize } from '../lib/format'
import { Badge, Button, cx, Spinner } from './ui'
import { AssistStatusPanel } from './assist'

const NAV = [
  { to: '/', label: 'Overview', icon: Gauge, end: true },
  { to: '/jobs', label: 'Opportunities', icon: Search },
  { to: '/pipeline', label: 'Pipeline', icon: KanbanSquare },
  { to: '/review', label: 'Review', icon: ClipboardList, badge: true },
  { to: '/automation', label: 'Automation', icon: Bot },
  { to: '/runs', label: 'Runs', icon: History },
  { to: '/profile', label: 'Profile', icon: UserRound },
]

function ThemeButton() {
  const { pref, dark, setPref } = useTheme()
  const next = pref === 'system' ? (dark ? 'light' : 'dark') : pref === 'dark' ? 'light' : 'system'
  const Icon = pref === 'system' ? Laptop : pref === 'dark' ? Moon : Sun
  return (
    <button
      type="button"
      onClick={() => setPref(next)}
      className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
      title={`Theme: ${pref} (click for ${next})`}
      aria-label={`Theme: ${pref}. Switch to ${next}`}
    >
      <Icon className="h-5 w-5" />
    </button>
  )
}

function NotificationsBell() {
  const { data, isLoading } = useNotifications()
  const readAll = useReadAllNotifications()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const loc = useLocation()
  useEffect(() => setOpen(false), [loc.pathname])
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])
  const count = data?.length ?? 0
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="relative rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
        aria-label={`Notifications: ${count} unread`}
        aria-expanded={open}
        aria-haspopup="dialog"
      >
        <Bell className="h-5 w-5" />
        {count > 0 && (
          <span className="absolute right-1 top-1 flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Unread notifications"
          className="fixed inset-x-2 top-16 z-50 max-h-[70vh] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-900 sm:absolute sm:inset-x-auto sm:right-0 sm:top-12 sm:w-96"
        >
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3 dark:border-slate-800">
            <p className="text-sm font-semibold">Notifications</p>
            <Button
              size="xs"
              variant="ghost"
              icon={<CheckCheck className="h-3.5 w-3.5" />}
              disabled={!count}
              loading={readAll.isPending}
              onClick={() => readAll.mutate()}
            >
              Mark all read
            </Button>
          </div>
          <div className="max-h-[calc(70vh-3.5rem)] overflow-y-auto">
            {isLoading ? (
              <div className="flex justify-center p-6">
                <Spinner />
              </div>
            ) : !count ? (
              <div className="flex flex-col items-center gap-2 px-4 py-10 text-center text-sm text-slate-500 dark:text-slate-400">
                <BellOff className="h-6 w-6" />
                You're all caught up.
              </div>
            ) : (
              <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                {data!.map((n) => (
                  <li key={n.id} className="px-4 py-3">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm font-medium text-slate-900 dark:text-slate-100">{n.title}</p>
                      <Badge tone={n.kind === 'error' ? 'red' : n.kind === 'blocked' ? 'orange' : n.kind === 'offer' ? 'green' : 'slate'}>
                        {humanize(n.kind)}
                      </Badge>
                    </div>
                    {n.body && <p className="mt-1 line-clamp-3 whitespace-pre-line text-xs text-slate-500 dark:text-slate-400">{n.body}</p>}
                    <div className="mt-1.5 flex items-center gap-3 text-xs text-slate-400">
                      <span>{fmtRelative(n.created_at)}</span>
                      {n.job_id && (
                        <Link to={`/jobs/${n.job_id}`} className="link">
                          Open job
                        </Link>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function StatusStrip() {
  const { data: s, isLoading } = useStatus()
  const act = useAutomationAction()
  if (isLoading || !s) {
    return <div className="h-10 border-b border-slate-200 bg-white/70 dark:border-slate-800 dark:bg-slate-900/70" aria-hidden />
  }
  const run = s.active_run
  return (
    <div className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2 text-xs sm:px-6">
        {run ? (
          <div className="flex items-center gap-2" role="status">
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-blue-500" />
            </span>
            <Link to={`/runs/${run.id}`} className="font-medium text-slate-800 hover:underline dark:text-slate-100">
              Run #{run.id}
              {run.dry_run ? ' (dry run)' : ''}: {run.current_stage ? humanize(run.current_stage) : 'starting'}
            </Link>
            <span className="text-slate-400">started {fmtRelative(run.started_at)}</span>
            {run.cancel_requested ? (
              <Badge tone="zinc">Stopping…</Badge>
            ) : (
              <Button size="xs" variant="danger" icon={<Square className="h-3 w-3" />} loading={act.isPending && act.variables === 'stop'} onClick={() => act.mutate('stop')}>
                Stop
              </Button>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-1.5 text-slate-600 dark:text-slate-300">
            <CalendarClock className="h-3.5 w-3.5 text-slate-400" aria-hidden />
            <span>
              Next run{' '}
              <span className="font-medium text-slate-800 dark:text-slate-100" title={s.schedule}>
                {s.next_run ? `${fmtDateTime(s.next_run)} (${fmtRelative(s.next_run)})` : '—'}
              </span>
              {!s.scheduler_running && <span className="text-slate-400"> · scheduler not running in this process</span>}
            </span>
          </div>
        )}
        <div className="flex items-center gap-2">
          {!s.automation_enabled ? (
            <Badge tone="red" dot>
              Automation disabled
            </Badge>
          ) : s.paused ? (
            <Badge tone="amber" dot>
              <PauseCircle className="-ml-0.5 inline h-3 w-3" /> Paused
            </Badge>
          ) : (
            <Badge tone="emerald" dot>
              Automation on
            </Badge>
          )}
          {s.daily_submission_target ? (
            <Link to="/review?tab=finish" title="Confirmed submissions today (automatic + finished by you) and applications waiting for your Finish click">
              <Badge tone={(s.submitted_today ?? 0) >= s.daily_submission_target ? 'emerald' : 'sky'}>
                Today {s.submitted_today ?? 0}/{s.daily_submission_target} submitted
                {s.finish_queue ? ` · ${s.finish_queue} to finish` : ''}
              </Badge>
            </Link>
          ) : null}
          <Badge tone={s.apply_mode === 'auto' ? 'violet' : 'sky'} title={s.apply_mode === 'auto' ? 'Mode A: automatic submission' : 'Mode B: waits for your approval'}>
            <Zap className="-ml-0.5 inline h-3 w-3" /> {s.apply_mode === 'auto' ? 'Mode A · auto' : 'Mode B · review'}
          </Badge>
          {s.last_run && (
            <Link to={`/runs/${s.last_run.id}`} className="hidden text-slate-500 hover:underline dark:text-slate-400 md:inline">
              Last run #{s.last_run.id} {s.last_run.status} {fmtRelative(s.last_run.finished_at ?? s.last_run.started_at)}
            </Link>
          )}
        </div>
      </div>
      <AssistStatusPanel compact />
      {s.warnings.length > 0 && (
        <div className="border-t border-amber-200 bg-amber-50 dark:border-amber-500/20 dark:bg-amber-500/10">
          <ul className="mx-auto max-w-7xl space-y-1 px-4 py-2 sm:px-6" aria-label="System warnings">
            {s.warnings.map((w) => (
              <li key={w} className="flex items-start gap-2 text-xs font-medium text-amber-900 dark:text-amber-100 sm:text-sm">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />
                <span className="min-w-0 break-words">{w}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export function Layout({ children }: { children: ReactNode }) {
  const { data: ov } = useOverview()
  // Immediate decisions only; eligibility reviews can number in the thousands and are counted on the Review page.
  const reviewCount = ov ? ov.open_questions + ov.awaiting_review : null
  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6">
          <Link to="/" className="flex min-w-0 items-center gap-2.5">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-600 text-white shadow-sm">
              <svg viewBox="0 0 32 32" className="h-5 w-5" aria-hidden>
                <path d="M7 21l6-6 4 4 8-9" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <span className="min-w-0 truncate text-sm font-semibold tracking-tight text-slate-900 dark:text-white sm:text-base">
              <span className="hidden sm:inline">Summer 2027 Internship Command Center</span>
              <span className="sm:hidden">Summer 2027 Command Center</span>
            </span>
          </Link>
          <div className="flex items-center gap-1">
            <NotificationsBell />
            <ThemeButton />
          </div>
        </div>
        <nav aria-label="Main" className="relative mx-auto max-w-7xl overflow-x-auto px-2 scrollbar-thin sm:px-4">
          <ul className="flex min-w-max gap-1">
            {NAV.map((n) => (
              <li key={n.to}>
                <NavLink
                  to={n.to}
                  end={n.end}
                  className={({ isActive }) =>
                    cx(
                      'group -mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors',
                      isActive
                        ? 'border-indigo-600 text-indigo-700 dark:border-indigo-400 dark:text-indigo-300'
                        : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white',
                    )
                  }
                >
                  <n.icon className="h-4 w-4" aria-hidden />
                  {n.label}
                  {n.badge && reviewCount ? (
                    <span className="rounded-full bg-orange-100 px-1.5 py-0.5 text-[11px] font-semibold text-orange-800 tabular dark:bg-orange-400/20 dark:text-orange-200">
                      {reviewCount > 999 ? '999+' : reviewCount}
                    </span>
                  ) : null}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <StatusStrip />
      <main id="main" className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {children}
      </main>
    </div>
  )
}
