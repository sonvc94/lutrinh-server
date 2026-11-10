/**
 * The admin API client: openapi-fetch typed from src/api/schema.d.ts (generated from the
 * server's /openapi.json). Auth (page 04 §G): the session is an HttpOnly cookie the page never
 * sees; the CSRF token lives only in memory here and goes in `X-CSRF-Token` on every write. A 401
 * anywhere sends the admin to the login screen; a 403 `csrf_failed` re-reads /session once and
 * retries.
 */
import createClient from 'openapi-fetch'
import { ApiError } from './errors'
import type { paths } from './schema'

export const API = '/admin/api/v1'
const SAFE = new Set(['GET', 'HEAD', 'OPTIONS'])

let csrfToken: string | null = null
let onUnauthenticated: () => void = () => {}

export function setCsrfToken(token: string | null): void {
  csrfToken = token
}

export function getCsrfToken(): string | null {
  return csrfToken
}

/** Called on any 401 outside `POST /session` (the session provider shows the login screen). */
export function setUnauthenticatedHandler(fn: () => void): void {
  onUnauthenticated = fn
}

async function refreshCsrf(): Promise<boolean> {
  const res = await fetch(`${API}/session`, { credentials: 'same-origin' })
  if (!res.ok) return false
  const body = (await res.json()) as { csrfToken?: string }
  csrfToken = body.csrfToken ?? null
  return csrfToken !== null
}

function isLogin(req: Request): boolean {
  return req.method === 'POST' && new URL(req.url).pathname === `${API}/session`
}

/** fetch with the CSRF header, the 403 retry and the 401 hook; used by every API call. */
export async function adminFetch(input: Request): Promise<Response> {
  const write = !SAFE.has(input.method)
  const retry = write ? input.clone() : null
  if (write && csrfToken) input.headers.set('X-CSRF-Token', csrfToken)
  let res = await fetch(input)
  if (res.status === 403 && retry) {
    const body = (await res
      .clone()
      .json()
      .catch(() => null)) as { error?: { code?: string } } | null
    if (body?.error?.code === 'csrf_failed' && (await refreshCsrf())) {
      retry.headers.set('X-CSRF-Token', csrfToken ?? '')
      res = await fetch(retry)
    }
  }
  if (res.status === 401 && !isLogin(input)) onUnauthenticated()
  return res
}

export const api = createClient<paths>({
  baseUrl: '',
  fetch: adminFetch,
  credentials: 'same-origin',
})

/** The data of an openapi-fetch result, or an ApiError with the server's envelope. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw new ApiError(response.status, error)
  return data as T
}
