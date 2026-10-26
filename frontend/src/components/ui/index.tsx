import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  useState,
  type AnchorHTMLAttributes,
  type ButtonHTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
} from 'react'
import { AlertTriangle, Loader2, RefreshCw, X } from 'lucide-react'
import { TONE_BADGE, TONE_DOT, eligibilityMeta, statusMeta, tierOf, TIER_META, type Tone } from '../../lib/status'
import { DASH, humanize } from '../../lib/format'
import { errorMessage } from '../../api/client'

export function cx(...xs: (string | false | null | undefined)[]): string {
  return xs.filter(Boolean).join(' ')
}

// ------------------------------------------------------------------ buttons

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success'
type Size = 'xs' | 'sm' | 'md'

const VARIANT: Record<Variant, string> = {
  primary:
    'bg-indigo-600 text-white shadow-sm hover:bg-indigo-500 disabled:hover:bg-indigo-600 dark:bg-indigo-500 dark:hover:bg-indigo-400',
  secondary:
    'border border-slate-300 bg-white text-slate-700 shadow-sm hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700',
  ghost: 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white',
  danger: 'bg-red-600 text-white shadow-sm hover:bg-red-500 dark:bg-red-600 dark:hover:bg-red-500',
  success: 'bg-emerald-600 text-white shadow-sm hover:bg-emerald-500 dark:bg-emerald-600 dark:hover:bg-emerald-500',
}
const SIZE: Record<Size, string> = {
  xs: 'h-7 gap-1 px-2 text-xs',
  sm: 'h-8 gap-1.5 px-3 text-sm',
  md: 'h-10 gap-2 px-4 text-sm',
}

const baseBtn =
  'inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: ReactNode
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'sm', loading, icon, className, children, disabled, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cx(baseBtn, VARIANT[variant], SIZE[size], className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  )
})

export function ButtonLink({
  variant = 'secondary',
  size = 'sm',
  icon,
  className,
  children,
  ...rest
}: AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: Variant; size?: Size; icon?: ReactNode }) {
  return (
    <a className={cx(baseBtn, VARIANT[variant], SIZE[size], className)} {...rest}>
      {icon}
      {children}
    </a>
  )
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx('h-4 w-4 animate-spin text-slate-400', className)} aria-label="Loading" />
}

// ------------------------------------------------------------------ badges

export function Badge({
  tone = 'slate',
  children,
  dot,
  className,
  title,
}: {
  tone?: Tone
  children: ReactNode
  dot?: boolean
  className?: string
  title?: string
}) {
  return (
    <span
      title={title}
      className={cx(
        'inline-flex max-w-full items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
        TONE_BADGE[tone],
        className,
      )}
    >
      {dot && <span className={cx('h-1.5 w-1.5 shrink-0 rounded-full', TONE_DOT[tone])} aria-hidden />}
      <span className="truncate">{children}</span>
    </span>
  )
}

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const m = statusMeta(status)
  return (
    <Badge tone={m.tone} dot className={className} title={m.help}>
      {m.label}
    </Badge>
  )
}

export function EligibilityBadge({ eligibility, className }: { eligibility: string | null | undefined; className?: string }) {
  const m = eligibilityMeta(eligibility)
  return (
    <Badge tone={m.tone} className={className}>
      {m.label}
    </Badge>
  )
}

export function ScoreBadge({ score, size = 'md' }: { score: number | null | undefined; size?: 'sm' | 'md' | 'lg' }) {
  const tier = tierOf(score)
  const dims = size === 'lg' ? 'h-14 w-14 text-xl' : size === 'sm' ? 'h-7 min-w-[2.25rem] text-xs' : 'h-8 min-w-[2.75rem] text-sm'
  if (!tier) {
    return (
      <span
        className={cx('inline-flex items-center justify-center rounded-lg bg-slate-100 px-1.5 font-semibold text-slate-400 dark:bg-slate-800', dims)}
        title="Not scored yet"
      >
        {DASH}
      </span>
    )
  }
  const m = TIER_META[tier]
  return (
    <span
      className={cx('inline-flex items-center justify-center rounded-lg px-1.5 font-bold tabular', m.solid, dims)}
      title={`${m.label} match (${score?.toFixed(1)})`}
      aria-label={`Match score ${Math.round(score ?? 0)}, ${m.label}`}
    >
      {Math.round(score ?? 0)}
    </span>
  )
}

export function Chip({ children, tone, title }: { children: ReactNode; tone?: 'good' | 'bad' | 'warn' | 'neutral'; title?: string }) {
  const cls =
    tone === 'good'
      ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-400/10 dark:text-emerald-300'
      : tone === 'bad'
        ? 'bg-red-50 text-red-700 dark:bg-red-400/10 dark:text-red-300'
        : tone === 'warn'
          ? 'bg-amber-50 text-amber-800 dark:bg-amber-400/10 dark:text-amber-300'
          : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'
  return (
    <span title={title} className={cx('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium', cls)}>
      {children}
    </span>
  )
}

// ------------------------------------------------------------------ cards

export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClassName,
  id,
  icon,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children?: ReactNode
  className?: string
  bodyClassName?: string
  id?: string
  icon?: ReactNode
}) {
  return (
    <section id={id} className={cx('card', className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-4 py-3 dark:border-slate-800 sm:px-5">
          <div className="min-w-0">
            {title && (
              <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
                {icon}
                {title}
              </h2>
            )}
            {subtitle && <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx('px-4 py-4 sm:px-5', bodyClassName)}>{children}</div>
    </section>
  )
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-white sm:text-2xl">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

// ------------------------------------------------------------------ states

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx('animate-pulse rounded-md bg-slate-200/80 dark:bg-slate-800', className)} aria-hidden />
}

export function SkeletonRows({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cx('space-y-3', className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  compact,
}: {
  icon?: ReactNode
  title: string
  description?: ReactNode
  action?: ReactNode
  compact?: boolean
}) {
  return (
    <div className={cx('flex flex-col items-center justify-center text-center', compact ? 'py-6' : 'py-12')}>
      {icon && (
        <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500">
          {icon}
        </div>
      )}
      <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">{title}</p>
      {description && <p className="mt-1 max-w-md text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ErrorState({ error, onRetry, compact }: { error: unknown; onRetry?: () => void; compact?: boolean }) {
  return (
    <div
      role="alert"
      className={cx(
        'flex flex-col items-center justify-center rounded-lg text-center',
        compact ? 'py-4' : 'py-10',
      )}
    >
      <AlertTriangle className="mb-2 h-6 w-6 text-red-500" aria-hidden />
      <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">Couldn't load this</p>
      <p className="mt-1 max-w-md break-words text-sm text-slate-500 dark:text-slate-400">{errorMessage(error)}</p>
      {onRetry && (
        <Button size="sm" className="mt-3" onClick={onRetry} icon={<RefreshCw className="h-3.5 w-3.5" />}>
          Try again
        </Button>
      )}
    </div>
  )
}

export function Callout({
  tone = 'amber',
  title,
  children,
  icon,
  className,
}: {
  tone?: 'amber' | 'red' | 'sky' | 'emerald' | 'slate' | 'violet'
  title?: ReactNode
  children?: ReactNode
  icon?: ReactNode
  className?: string
}) {
  const cls = {
    amber: 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100',
    red: 'border-red-200 bg-red-50 text-red-900 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-100',
    sky: 'border-sky-200 bg-sky-50 text-sky-900 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-100',
    emerald: 'border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-100',
    slate: 'border-slate-200 bg-slate-50 text-slate-800 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-200',
    violet: 'border-violet-200 bg-violet-50 text-violet-900 dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-violet-100',
  }[tone]
  return (
    <div className={cx('flex gap-3 rounded-lg border px-3.5 py-3 text-sm', cls, className)}>
      {icon && <div className="mt-0.5 shrink-0">{icon}</div>}
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={cx(title ? 'mt-0.5' : '', 'break-words opacity-90')}>{children}</div>}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ form controls

export function Field({
  label,
  hint,
  children,
  htmlFor,
  className,
  required,
}: {
  label: ReactNode
  hint?: ReactNode
  children: ReactNode
  htmlFor?: string
  className?: string
  required?: boolean
}) {
  return (
    <div className={className}>
      <label htmlFor={htmlFor} className="label">
        {label}
        {required && <span className="ml-0.5 text-red-500" aria-hidden>*</span>}
      </label>
      <div className="mt-1.5">{children}</div>
      {hint && <p className="hint">{hint}</p>}
    </div>
  )
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
  disabled,
  id,
  size = 'md',
  ariaLabel,
}: {
  ariaLabel?: string
  checked: boolean
  onChange: (v: boolean) => void
  label?: ReactNode
  description?: ReactNode
  disabled?: boolean
  id?: string
  size?: 'sm' | 'md'
}) {
  const auto = useId()
  const tid = id ?? auto
  const sw = (
    <button
      id={tid}
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        'relative inline-flex shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'h-5 w-9' : 'h-6 w-11',
        checked ? 'bg-indigo-600 dark:bg-indigo-500' : 'bg-slate-300 dark:bg-slate-600',
      )}
    >
      <span className="sr-only">{ariaLabel ?? (typeof label === 'string' ? label : 'Toggle')}</span>
      <span
        aria-hidden
        className={cx(
          'pointer-events-none inline-block transform rounded-full bg-white shadow ring-0 transition',
          size === 'sm' ? 'h-4 w-4' : 'h-5 w-5',
          checked ? (size === 'sm' ? 'translate-x-4' : 'translate-x-5') : 'translate-x-0',
        )}
      />
    </button>
  )
  if (!label) return sw
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <label htmlFor={tid} className="text-sm font-medium text-slate-800 dark:text-slate-200">
          {label}
        </label>
        {description && <p className="text-xs text-slate-500 dark:text-slate-400">{description}</p>}
      </div>
      {sw}
    </div>
  )
}

export function TagInput({
  value,
  onChange,
  placeholder,
  id,
  ariaLabel,
}: {
  value: string[]
  onChange: (v: string[]) => void
  placeholder?: string
  id?: string
  ariaLabel?: string
}) {
  const [draft, setDraft] = useState('')
  const add = (raw: string) => {
    const parts = raw
      .split(/[;\n]/)
      .map((s) => s.trim())
      .filter(Boolean)
    if (!parts.length) return
    const next = [...value]
    for (const p of parts) if (!next.some((x) => x.toLowerCase() === p.toLowerCase())) next.push(p)
    onChange(next)
    setDraft('')
  }
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      add(draft)
    } else if (e.key === 'Backspace' && !draft && value.length) {
      onChange(value.slice(0, -1))
    }
  }
  return (
    <div className="flex min-h-[2.5rem] flex-wrap items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-2 py-1.5 shadow-sm focus-within:border-indigo-500 focus-within:ring-2 focus-within:ring-indigo-500/30 dark:border-slate-700 dark:bg-slate-900">
      {value.map((t) => (
        <span
          key={t}
          className="inline-flex items-center gap-1 rounded-md bg-indigo-50 py-0.5 pl-2 pr-1 text-xs font-medium text-indigo-800 dark:bg-indigo-400/15 dark:text-indigo-200"
        >
          {t}
          <button
            type="button"
            onClick={() => onChange(value.filter((x) => x !== t))}
            className="rounded p-0.5 hover:bg-indigo-100 dark:hover:bg-indigo-400/20"
            aria-label={`Remove ${t}`}
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <input
        id={id}
        aria-label={ariaLabel}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKey}
        onBlur={() => draft && add(draft)}
        placeholder={value.length ? 'Add…' : placeholder ?? 'Type and press Enter'}
        className="min-w-[8rem] flex-1 border-0 bg-transparent px-1 py-0.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-0 dark:text-slate-100"
      />
    </div>
  )
}

// ------------------------------------------------------------------ dialog

export function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
  size = 'md',
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  children: ReactNode
  footer?: ReactNode
  size?: 'sm' | 'md' | 'lg'
}) {
  const panel = useRef<HTMLDivElement>(null)
  const titleId = useId()
  useEffect(() => {
    if (!open) return
    const prev = document.activeElement as HTMLElement | null
    const t = window.setTimeout(() => {
      const el = panel.current?.querySelector<HTMLElement>('input, textarea, select, button[data-autofocus]')
      ;(el ?? panel.current)?.focus()
    }, 10)
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      window.clearTimeout(t)
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
      prev?.focus?.()
    }
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4">
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-[1px]" onClick={onClose} aria-hidden />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cx(
          'relative max-h-[92vh] w-full animate-slide-in overflow-y-auto rounded-t-2xl bg-white shadow-xl focus:outline-none dark:bg-slate-900 sm:rounded-2xl',
          size === 'sm' ? 'sm:max-w-sm' : size === 'lg' ? 'sm:max-w-2xl' : 'sm:max-w-lg',
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4 dark:border-slate-800">
          <h2 id={titleId} className="text-base font-semibold text-slate-900 dark:text-white">
            {title}
          </h2>
          <button onClick={onClose} className="rounded-md p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200" aria-label="Close dialog">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && (
          <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 bg-slate-50/60 px-5 py-3 dark:border-slate-800 dark:bg-slate-900">
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ tabs

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  ariaLabel,
}: {
  tabs: { id: T; label: ReactNode; count?: number | null }[]
  value: T
  onChange: (v: T) => void
  ariaLabel: string
}) {
  return (
    <div className="relative -mx-4 overflow-x-auto px-4 scrollbar-thin sm:mx-0 sm:px-0">
      <div role="tablist" aria-label={ariaLabel} className="inline-flex min-w-full gap-1 border-b border-slate-200 dark:border-slate-800 sm:min-w-0">
        {tabs.map((t) => {
          const active = t.id === value
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={active}
              onClick={() => onChange(t.id)}
              className={cx(
                '-mb-px inline-flex items-center gap-2 whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium transition-colors',
                active
                  ? 'border-indigo-600 text-indigo-700 dark:border-indigo-400 dark:text-indigo-300'
                  : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200',
              )}
            >
              {t.label}
              {t.count != null && (
                <span
                  className={cx(
                    'rounded-full px-1.5 py-0.5 text-[11px] font-semibold tabular',
                    active ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-400/20 dark:text-indigo-200' : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
                  )}
                >
                  {t.count}
                </span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ data display

/** Render **bold** spans used in the master resume. */
export function RichText({ text }: { text: string | null | undefined }) {
  if (!text) return <>{DASH}</>
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith('**') && p.endsWith('**') ? (
          <strong key={i} className="font-semibold text-slate-900 dark:text-white">
            {p.slice(2, -2)}
          </strong>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  )
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v)
}

/** Pretty key-value rendering of arbitrary JSON (stage results, payloads). */
export function KeyValue({ data, depth = 0 }: { data: unknown; depth?: number }) {
  if (data === null || data === undefined || data === '') return <span className="muted">{DASH}</span>
  if (typeof data === 'boolean') return <span>{data ? 'Yes' : 'No'}</span>
  if (typeof data === 'number') return <span className="tabular">{data.toLocaleString()}</span>
  if (typeof data === 'string') return <span className="break-words">{data}</span>
  if (Array.isArray(data)) {
    if (!data.length) return <span className="muted">none</span>
    if (data.every((x) => typeof x !== 'object' || x === null))
      return <span className="break-words">{data.map((x) => String(x)).join(', ')}</span>
    return (
      <ul className="space-y-1">
        {data.map((x, i) => (
          <li key={i} className="rounded border border-slate-100 p-2 dark:border-slate-800">
            <KeyValue data={x} depth={depth + 1} />
          </li>
        ))}
      </ul>
    )
  }
  if (isPlainObject(data)) {
    const entries = Object.entries(data)
    if (!entries.length) return <span className="muted">none</span>
    // Counters (e.g. skipped reasons) read best sorted by count.
    const allNums = entries.every(([, v]) => typeof v === 'number')
    const sorted = allNums ? [...entries].sort((a, b) => (b[1] as number) - (a[1] as number)) : entries
    return (
      <dl className={cx('grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm', depth > 0 && 'border-l-2 border-slate-100 pl-3 dark:border-slate-800')}>
        {sorted.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="max-w-[16rem] truncate text-slate-500 dark:text-slate-400" title={k}>
              {humanize(k)}
            </dt>
            <dd className="min-w-0 text-slate-800 dark:text-slate-200">
              <KeyValue data={v} depth={depth + 1} />
            </dd>
          </div>
        ))}
      </dl>
    )
  }
  return <span>{String(data)}</span>
}

export function ExternalLink({ href, children, className }: { href: string | null | undefined; children: ReactNode; className?: string }) {
  if (!href) return null
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={cx('link', className)}>
      {children}
    </a>
  )
}
