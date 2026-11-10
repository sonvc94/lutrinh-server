import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, unwrap } from '../api/client'
import { errorText } from '../api/errors'
import { useRoutes } from '../api/hooks'
import type { RouteOut } from '../api/types'
import { Contours } from '../ui/Contours'
import { Button, ui } from '../ui/ui'
import { dateTime } from '../util/format'
import css from './RouteListPage.module.css'

const KEEP_DAYS = 30

export function daysLeft(deletedAt: string, now: Date = new Date()): number {
  const end = new Date(deletedAt).getTime() + KEEP_DAYS * 86_400_000
  return Math.max(0, Math.ceil((end - now.getTime()) / 86_400_000))
}

/** Page 04 "Thùng rác": routes deleted in the last 30 days; restore or delete for good. */
export function TrashPage() {
  const routes = useRoutes('trash')
  return (
    <section className={css.page}>
      <header className={css.head}>
        <div>
          <div className="eyebrow">{routes.data?.length ?? 0} lộ trình đã xóa</div>
          <h1 className={css.title}>Thùng rác</h1>
        </div>
      </header>
      <p className={css.note}>
        Lộ trình ở đây không tra được mã. Sau {KEEP_DAYS} ngày máy chủ xóa hẳn; “Xóa hẳn” làm ngay
        (mã cũ không bao giờ được cấp lại).
      </p>
      <div className={css.tableCard}>
        <table className={css.table}>
          <thead>
            <tr>
              <th aria-label="Ảnh bìa" />
              <th>Tên</th>
              <th>Đã xóa lúc</th>
              <th>Còn lại</th>
              <th aria-label="Thao tác" />
            </tr>
          </thead>
          <tbody>
            {routes.data?.map((r) => (
              <TrashRow key={r.id} r={r} />
            ))}
          </tbody>
        </table>
        {routes.data?.length === 0 && (
          <div className={css.empty}>
            <Contours width={160} height={96} />
            <p>Thùng rác trống.</p>
          </div>
        )}
        {routes.error && <p className={css.empty}>{errorText(routes.error)}</p>}
      </div>
    </section>
  )
}

function TrashRow({ r }: { r: RouteOut }) {
  const qc = useQueryClient()
  const [confirm, setConfirm] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const path = { params: { path: { route_id: r.id } } }

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      await qc.invalidateQueries({ queryKey: ['routes'] })
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <tr className={css.row} data-testid="trash-row">
      <td className={css.thumbCell}>
        <div className={css.thumb}>
          <Contours rings={4} />
        </div>
      </td>
      <td>
        <span className={css.name}>{r.title}</span>
        <div className="muted">
          {r.stops} điểm{r.code ? ` · mã ${r.code}` : ''}
        </div>
        {error && <div className={ui.error}>{error}</div>}
      </td>
      <td>{r.deletedAt ? dateTime(r.deletedAt) : '–'}</td>
      <td>{r.deletedAt ? `${daysLeft(r.deletedAt)} ngày` : '–'}</td>
      <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
        {confirm ? (
          <>
            <span className={ui.error}>Xóa hẳn cả ảnh/video và mọi phiên bản? </span>
            <Button small variant="quiet" onClick={() => setConfirm(false)}>
              Hủy
            </Button>
            <Button
              small
              variant="danger"
              disabled={busy}
              onClick={() =>
                void run(() =>
                  unwrap(
                    api.DELETE('/admin/api/v1/routes/{route_id}', {
                      params: { path: { route_id: r.id }, query: { purge: true } },
                    }),
                  ),
                )
              }
            >
              Xóa hẳn
            </Button>
          </>
        ) : (
          <>
            <Button
              small
              disabled={busy}
              onClick={() =>
                void run(() => unwrap(api.POST('/admin/api/v1/routes/{route_id}/restore', path)))
              }
            >
              Khôi phục
            </Button>{' '}
            <Button small variant="danger" onClick={() => setConfirm(true)}>
              Xóa hẳn…
            </Button>
          </>
        )}
      </td>
    </tr>
  )
}
