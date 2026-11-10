/**
 * The admin session (page 04 §G). The cookie is HttpOnly; what the page holds is the state and
 * the CSRF token (in memory only, never localStorage). Any 401 → logged out → login screen.
 */
import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, setCsrfToken, setUnauthenticatedHandler, unwrap } from '../api/client'
import { ApiError } from '../api/errors'

export type SessionState = 'loading' | 'in' | 'out'

interface SessionValue {
  state: SessionState
  login(password: string, code: string): Promise<void>
  logout(): Promise<void>
}

const Ctx = createContext<SessionValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>('loading')
  const qc = useQueryClient()

  useEffect(() => {
    setUnauthenticatedHandler(() => {
      setCsrfToken(null)
      setState('out')
    })
    let live = true
    unwrap(api.GET('/admin/api/v1/session'))
      .then((s) => {
        setCsrfToken(s.csrfToken)
        if (live) setState('in')
      })
      .catch((e: unknown) => {
        if (!live) return
        if (!(e instanceof ApiError) || e.status !== 401) console.error(e)
        setState('out')
      })
    return () => {
      live = false
    }
  }, [])

  const login = useCallback(async (password: string, code: string) => {
    const s = await unwrap(api.POST('/admin/api/v1/session', { body: { password, code } }))
    setCsrfToken(s.csrfToken)
    setState('in')
  }, [])

  const logout = useCallback(async () => {
    try {
      await unwrap(api.DELETE('/admin/api/v1/session'))
    } finally {
      setCsrfToken(null)
      qc.clear()
      setState('out')
    }
  }, [qc])

  const value = useMemo(() => ({ state, login, logout }), [state, login, logout])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSession(): SessionValue {
  const v = useContext(Ctx)
  if (!v) throw new Error('useSession outside SessionProvider')
  return v
}
