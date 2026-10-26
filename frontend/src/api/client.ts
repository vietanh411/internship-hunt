// Thin fetch wrapper. Every error carries the API's `detail` message so it can be
// shown verbatim in toasts; 401 responses broadcast an event that swaps the app
// to the login screen.

export const AUTH_EVENT = 'icc:auth-required'

export class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, message: string, body: unknown) {
    super(message)
    this.status = status
    this.body = body
  }
}

type Query = Record<string, string | number | boolean | null | undefined>

export function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams()
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === '') continue
      params.set(k, String(v))
    }
  }
  const qs = params.toString()
  return qs ? `${path}?${qs}` : path
}

function messageFrom(status: number, body: unknown, fallback: string): string {
  if (body && typeof body === 'object') {
    const b = body as Record<string, unknown>
    const d = b.detail
    if (typeof d === 'string') return d
    if (Array.isArray(d)) {
      // FastAPI validation errors: [{loc, msg, type}]
      return d
        .map((e) => {
          if (e && typeof e === 'object') {
            const r = e as Record<string, unknown>
            const loc = Array.isArray(r.loc) ? r.loc.filter((x) => x !== 'body' && x !== 'query').join('.') : ''
            return loc ? `${loc}: ${String(r.msg ?? '')}` : String(r.msg ?? '')
          }
          return String(e)
        })
        .join('; ')
    }
    if (Array.isArray(b.reasons)) return (b.reasons as unknown[]).map(String).join('; ')
  }
  if (typeof body === 'string' && body.trim()) return body.trim().slice(0, 300)
  return `${fallback} (HTTP ${status})`
}

export async function api<T = unknown>(
  path: string,
  opts: { method?: string; body?: unknown; query?: Query; signal?: AbortSignal } = {},
): Promise<T> {
  const { method = 'GET', body, query, signal } = opts
  let res: Response
  try {
    res = await fetch(buildUrl(path, query), {
      method,
      credentials: 'same-origin',
      headers: body !== undefined ? { 'Content-Type': 'application/json', Accept: 'application/json' } : { Accept: 'application/json' },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    })
  } catch (e) {
    if ((e as Error)?.name === 'AbortError') throw e
    throw new ApiError(0, 'Cannot reach the server. Is `python -m hunt serve` running?', null)
  }
  const text = await res.text()
  let parsed: unknown = null
  if (text) {
    try {
      parsed = JSON.parse(text)
    } catch {
      parsed = text
    }
  }
  if (!res.ok) {
    if (res.status === 401 && path !== '/api/login') {
      window.dispatchEvent(new CustomEvent(AUTH_EVENT))
    }
    throw new ApiError(res.status, messageFrom(res.status, parsed, res.statusText || 'Request failed'), parsed)
  }
  return parsed as T
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return String(e)
}
