import { useCallback, useEffect, useState } from 'react'

export class ApiError extends Error {
  status: number
  body: unknown

  constructor(status: number, body: unknown) {
    super(messageFrom(body) ?? `Request failed (${status})`)
    this.status = status
    this.body = body
  }
}

function messageFrom(body: unknown): string | undefined {
  if (!body || typeof body !== 'object') return undefined
  const b = body as Record<string, unknown>
  if (typeof b.detail === 'string') return b.detail
  // DRF field errors: { note: ["..."] }
  const first = Object.entries(b)[0]
  if (first) {
    const [field, msg] = first
    return `${field}: ${Array.isArray(msg) ? msg.join(' ') : String(msg)}`
  }
  return undefined
}

function csrfToken(): string {
  const m = document.cookie.match(/(?:^|;\s*)pawguard-csrftoken=([^;]+)/)
  return m ? decodeURIComponent(m[1]) : ''
}

export async function api<T>(
  path: string,
  options: { method?: 'GET' | 'POST'; body?: unknown } = {},
  retriedCsrf = false,
): Promise<T> {
  const method = options.method ?? 'GET'
  // Paths starting with /api/ are absolute (used by the end-user app); others are console-relative.
  const url = path.startsWith('/api/') ? path : `/api/console${path}`
  const res = await fetch(url, {
    method,
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(method === 'POST'
        ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() }
        : {}),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  if (res.status === 204) return undefined as T
  const body: unknown = await res.json().catch(() => null)
  if (!res.ok) {
    const err = new ApiError(res.status, body)
    // A stale or missing csrftoken cookie (cookies are shared across localhost ports) is
    // fixed by fetching a fresh one; retry the request once.
    if (res.status === 403 && method === 'POST' && !retriedCsrf && err.message.startsWith('CSRF')) {
      await api('/auth/csrf/')
      return api<T>(path, options, true)
    }
    throw err
  }
  return body as T
}

/** Ensures the pawguard-csrftoken cookie exists before any POST. */
export function primeCsrf(path = '/auth/csrf/'): Promise<unknown> {
  return api(path)
}

/** Fetch on mount and whenever `path` changes; `reload` refetches. */
export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (path === null) return
    let cancelled = false
    api<T>(path)
      .then((d) => {
        if (!cancelled) {
          setData(d)
          setError(null)
        }
      })
      .catch((e: ApiError) => !cancelled && setError(e))
    return () => {
      cancelled = true
    }
  }, [path, tick])

  const loading = path !== null && data === null && error === null
  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, error, loading, reload }
}
