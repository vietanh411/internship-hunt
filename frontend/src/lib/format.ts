// Formatting helpers. Missing data always renders as an em dash, never a made-up value.

export const DASH = '—'

/** Parse an API timestamp. Naive ISO strings (no zone) are UTC in this backend. */
export function parseDate(s: string | null | undefined): Date | null {
  if (!s) return null
  let str = s
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(str) && !/(Z|[+-]\d{2}:?\d{2})$/.test(str)) str += 'Z'
  const d = new Date(str)
  return Number.isNaN(d.getTime()) ? null : d
}

export function fmtDate(s: string | null | undefined, opts?: { year?: boolean }): string {
  const d = parseDate(s)
  if (!d) return DASH
  const sameYear = d.getFullYear() === new Date().getFullYear()
  return d.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: opts?.year || !sameYear ? 'numeric' : undefined,
  })
}

export function fmtDateTime(s: string | null | undefined): string {
  const d = parseDate(s)
  if (!d) return DASH
  const sameYear = d.getFullYear() === new Date().getFullYear()
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: sameYear ? undefined : 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function fmtRelative(s: string | null | undefined): string {
  const d = parseDate(s)
  if (!d) return DASH
  const diff = d.getTime() - Date.now()
  const abs = Math.abs(diff)
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  const min = 60_000
  const hr = 60 * min
  const day = 24 * hr
  if (abs < min) return diff < 0 ? 'just now' : 'in under a minute'
  if (abs < hr) return rtf.format(Math.round(diff / min), 'minute')
  if (abs < day) return rtf.format(Math.round(diff / hr), 'hour')
  if (abs < 30 * day) return rtf.format(Math.round(diff / day), 'day')
  return fmtDate(s)
}

export function fmtDuration(start: string | null | undefined, end: string | null | undefined): string {
  const a = parseDate(start)
  if (!a) return DASH
  const b = parseDate(end) ?? new Date()
  let secs = Math.max(0, Math.round((b.getTime() - a.getTime()) / 1000))
  if (secs < 60) return `${secs}s`
  const h = Math.floor(secs / 3600)
  secs -= h * 3600
  const m = Math.floor(secs / 60)
  const s = secs - m * 60
  if (h) return `${h}h ${m}m`
  return s ? `${m}m ${s}s` : `${m}m`
}

export function fmtNumber(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return DASH
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 })
}

export function fmtPercent(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return DASH
  return `${(n * 100).toFixed(digits)}%`
}

function money(n: number, period: string | null | undefined): string {
  if (period === 'hour') return `$${n % 1 === 0 ? n.toFixed(0) : n.toFixed(2)}`
  if (n >= 1000) return `$${Math.round(n / 1000)}k`
  return `$${Math.round(n)}`
}

const PERIOD_SUFFIX: Record<string, string> = { hour: '/hr', year: '/yr', month: '/mo', week: '/wk' }

export function fmtSalary(j: { salary_text?: string | null; salary_min?: number | null; salary_max?: number | null; salary_period?: string | null }): string {
  const { salary_min: lo, salary_max: hi, salary_period: p } = j
  const suffix = p ? PERIOD_SUFFIX[p] ?? `/${p}` : ''
  if (lo != null && hi != null && lo !== hi) return `${money(lo, p)}–${money(hi, p)}${suffix}`
  if (lo != null || hi != null) return `${money((lo ?? hi) as number, p)}${suffix}`
  if (j.salary_text) return j.salary_text
  return DASH
}

export function humanize(s: string | null | undefined): string {
  if (!s) return DASH
  const t = s.replace(/[_-]+/g, ' ').trim()
  return t.charAt(0).toUpperCase() + t.slice(1)
}

export function plural(n: number, word: string, pluralWord?: string): string {
  return `${n.toLocaleString()} ${n === 1 ? word : pluralWord ?? word + 's'}`
}

/** Convert a dot path and value into a nested object: ("contact.city", "X") -> {contact: {city: "X"}} */
export function pathToObject(path: string, value: unknown): Record<string, unknown> {
  const parts = path.split('.')
  const root: Record<string, unknown> = {}
  let cur = root
  parts.forEach((p, i) => {
    if (i === parts.length - 1) cur[p] = value
    else {
      const next: Record<string, unknown> = {}
      cur[p] = next
      cur = next
    }
  })
  return root
}

export function getPath(obj: unknown, path: string): unknown {
  let cur: unknown = obj
  for (const part of path.split('.')) {
    if (!cur || typeof cur !== 'object' || !(part in (cur as Record<string, unknown>))) return undefined
    cur = (cur as Record<string, unknown>)[part]
  }
  return cur
}

export function hostOf(url: string | null | undefined): string {
  if (!url) return ''
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

/** Local datetime-local value -> ISO string with the browser's UTC offset. */
export function localInputToIsoWithOffset(v: string): string {
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return v
  const off = -d.getTimezoneOffset()
  const sign = off >= 0 ? '+' : '-'
  const pad = (n: number) => String(Math.floor(Math.abs(n))).padStart(2, '0')
  return `${v.length === 16 ? v + ':00' : v}${sign}${pad(off / 60)}:${pad(off % 60)}`
}
