import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { useSession } from './session'

export const LOGIN_PATH = '/dang-nhap'

export function RequireSession({ children }: { children: ReactNode }) {
  const { state } = useSession()
  const loc = useLocation()
  if (state === 'loading')
    return (
      <div className="muted" style={{ padding: 32 }}>
        Đang tải…
      </div>
    )
  if (state === 'out') {
    const next = loc.pathname + loc.search
    return <Navigate to={`${LOGIN_PATH}?next=${encodeURIComponent(next)}`} replace />
  }
  return <>{children}</>
}
