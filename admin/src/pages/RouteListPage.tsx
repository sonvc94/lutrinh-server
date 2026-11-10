import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { api, unwrap } from '../api/client'
import { errorText } from '../api/errors'
import { sumStats, useCreateRoute, useRoutes, useStats } from '../api/hooks'
import type { RouteOut } from '../api/types'
import { Contours } from '../ui/Contours'
import { Icon } from '../ui/Icon'
import { Badge, Button, ui } from '../ui/ui'
import { count, lastEdited } from '../util/format'
import css from './RouteListPage.module.css'
import { STATUS } from './routeStatus'
import { useQueryClient } from '@tanstack/react-query'

const FILTERS: { key: string; label: string }[] = [
  { key: '', label: 'Tất cả' },
  { key: 'draft', label: 'Nháp' },
  { key: 'shared', label: 'Đang chia sẻ' },
  { key: 'unpublished', label: 'Đã gỡ' },
]

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

/** Page 04 A: every route with status, version, code, 30-day downloads and last edit. */
export function RouteListPage() {
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const q = useDebounced(search.trim(), 250)
  const routes = useRoutes(status || undefined, q || undefined)
  const all = useRoutes()
  const stats = useStats()
  const create = useCreateRoute()
  const navigate = useNavigate()

  const total = all.data?.length ?? 0
  const shared = all.data?.filter((r) => r.status === 'shared').length ?? 0

  const newRoute = async () => {
    const r = await create.mutateAsync(undefined)
    navigate(`/lo-trinh/${r.id}/diem-dung?them=1`)
  }

  return (
    <section className={css.page}>
      <header className={css.head}>
        <div>
          <div className="eyebrow">
            {total} lộ trình · {shared} đang chia sẻ
          </div>
          <h1 className={css.title}>Lộ trình</h1>
        </div>
        <label className={css.search}>
          <Icon name="search" />
          <span className="sr-only">Tìm</span>
          <input
            type="search"
            placeholder="Tìm theo tên, mã"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <Link to="/nhap" className={ui.button}>
          <Icon name="file" /> Nhập…
        </Link>
        <Button variant="primary" onClick={() => void newRoute()} disabled={create.isPending}>
          <Icon name="plus" /> Lộ trình mới
        </Button>
      </header>
      {create.error && <div className={ui.notice}>{errorText(create.error)}</div>}

      <div className={css.filters} role="group" aria-label="Lọc theo trạng thái">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            className={status === f.key ? `${css.filter} ${css.filterOn}` : css.filter}
            aria-pressed={status === f.key}
            onClick={() => setStatus(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className={css.tableCard}>
        <table className={css.table}>
          <thead>
            <tr>
              <th aria-label="Ảnh bìa" />
              <th>Tên</th>
              <th>Trạng thái</th>
              <th>Phiên bản</th>
              <th>Mã</th>
              <th>Lượt tải 30 ngày</th>
              <th>Sửa lần cuối</th>
              <th aria-label="Thao tác" />
            </tr>
          </thead>
          <tbody>
            {routes.data?.map((r) => (
              <RouteRow key={r.id} r={r} downloads={sumStats(stats.data, 'download', r.id)} />
            ))}
          </tbody>
        </table>
        {routes.isPending && <p className={css.empty}>Đang tải…</p>}
        {routes.error && <p className={css.empty}>{errorText(routes.error)}</p>}
        {routes.data?.length === 0 && (
          <div className={css.empty}>
            <Contours width={160} height={96} />
            <p>
              {q || status
                ? 'Không có lộ trình khớp.'
                : 'Chưa có lộ trình. Bấm “Lộ trình mới” hoặc “Nhập…”.'}
            </p>
          </div>
        )}
      </div>
      <p className={css.note}>
        Trạng thái chỉ có ba: <b>Nháp</b> (chưa từng xuất bản), <b>Đang chia sẻ</b>, <b>Đã gỡ</b>;
        “nháp có thay đổi” = bản nháp khác phiên bản đang phát. Xóa = vào Thùng rác.
      </p>
    </section>
  )
}

function RouteRow({ r, downloads }: { r: RouteOut; downloads: number }) {
  const [menu, setMenu] = useState(false)
  const qc = useQueryClient()
  const navigate = useNavigate()
  const open = () => navigate(`/lo-trinh/${r.id}`)
  const st = STATUS[r.status]

  const trash = async () => {
    setMenu(false)
    await unwrap(
      api.DELETE('/admin/api/v1/routes/{route_id}', { params: { path: { route_id: r.id } } }),
    )
    await qc.invalidateQueries({ queryKey: ['routes'] })
  }

  return (
    <tr className={css.row} data-testid="route-row">
      <td className={css.thumbCell} onClick={open}>
        {/* Covers need an admin media endpoint (follow-up); the contour mark stands in. */}
        <div className={css.thumb}>
          <Contours rings={4} />
        </div>
      </td>
      <td onClick={open}>
        <Link to={`/lo-trinh/${r.id}`} className={css.name}>
          {r.title}
        </Link>
        <div className="muted">{r.stops} điểm</div>
      </td>
      <td>
        <Badge tone={st.tone}>{st.label}</Badge>
      </td>
      <td>
        {r.latestVersion ? (
          <>
            <span className="num">v{r.latestVersion}</span>
            {r.draftChanged && <span className="muted"> · nháp có thay đổi</span>}
          </>
        ) : (
          <span className="muted">chưa xuất bản</span>
        )}
      </td>
      <td>
        {r.code ? (
          <span className={`num ${css.code} ${r.status === 'unpublished' ? css.struck : ''}`}>
            {r.code}
          </span>
        ) : (
          <span className="muted">chưa có</span>
        )}
      </td>
      <td className="num">{r.latestVersion ? count(downloads) : '–'}</td>
      <td>{lastEdited(r.updatedAt)}</td>
      <td className={css.menuCell}>
        <Button
          variant="quiet"
          small
          aria-label={`Thao tác ${r.title}`}
          onClick={() => setMenu((m) => !m)}
        >
          <Icon name="more" />
        </Button>
        {menu && (
          <div className={css.menu} role="menu">
            <button role="menuitem" type="button" onClick={open}>
              Mở
            </button>
            {r.code && (
              <button
                role="menuitem"
                type="button"
                onClick={() => {
                  void navigator.clipboard?.writeText(r.code ?? '')
                  setMenu(false)
                }}
              >
                Sao chép mã
              </button>
            )}
            <button
              role="menuitem"
              type="button"
              className={css.menuDanger}
              onClick={() => void trash()}
            >
              Xóa (vào Thùng rác)
            </button>
          </div>
        )}
      </td>
    </tr>
  )
}
