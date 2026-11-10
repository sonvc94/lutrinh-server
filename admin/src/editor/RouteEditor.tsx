/** Page 04 B: the editor of one route (its own bar, tabs, autosave of the draft). */
import { useQueries, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useParams } from 'react-router'
import { api, unwrap } from '../api/client'
import { errorText } from '../api/errors'
import { isJobDone, keys, useDraftQuery, useRoute } from '../api/hooks'
import { DraftSaver } from '../draft/saver'
import { STATUS } from '../pages/routeStatus'
import { Icon } from '../ui/Icon'
import { Badge, Button, ui } from '../ui/ui'
import { EditorCtx, useEditor } from './context'
import css from './RouteEditor.module.css'
import { draftGetter, draftPutter } from './putDraft'

const TABS = [
  ['thong-tin', 'Thông tin'],
  ['diem-dung', 'Điểm dừng'],
  ['anh-video', 'Ảnh/video'],
  ['xuat-ban', 'Xuất bản & mã'],
  ['phien-ban', 'Phiên bản'],
] as const

export function RouteEditor() {
  const { routeId = '' } = useParams()
  const draft = useDraftQuery(routeId)
  const route = useRoute(routeId)
  const data = draft.data
  // One saver per route, made when its draft first arrives; later reads reach it via adopt/reset.
  const [made, setMade] = useState<{ id: string; saver: DraftSaver } | null>(null)
  if (data && made?.id !== routeId) {
    setMade({
      id: routeId,
      saver: new DraftSaver(data, draftPutter(routeId), draftGetter(routeId)),
    })
  }
  const saver = made?.id === routeId ? made.saver : null
  useEffect(() => {
    return () => {
      void saver?.flush().finally(() => saver.dispose())
    }
  }, [saver])

  if (draft.error) {
    return (
      <div className={css.loading}>
        <div className={ui.notice} role="alert">
          {errorText(draft.error)} <Link to="/lo-trinh">Về danh sách</Link>
        </div>
      </div>
    )
  }
  if (!saver) return <div className={css.loading}>Đang mở lộ trình…</div>
  return (
    <EditorCtx.Provider value={{ routeId, route: route.data, saver }}>
      <EditorFrame />
    </EditorCtx.Provider>
  )
}

const SAVE_TEXT = {
  saved: 'Đã lưu',
  pending: 'Chưa lưu…',
  saving: 'Đang lưu…',
  error: 'Lưu lỗi',
  conflict: 'Không lưu',
} as const

function EditorFrame() {
  const { routeId, route, saver, state } = useEditor()
  const qc = useQueryClient()
  const status = route ? STATUS[route.status as keyof typeof STATUS] : undefined

  const reload = async () => {
    const fresh = await draftGetter(routeId)()
    saver.reset(fresh)
    qc.setQueryData(keys.draft(routeId), fresh)
  }

  // Saved: the list, the badge ("Nháp có thay đổi") and the preflight are stale.
  const savedRevision = state.status === 'saved' ? state.revision : null
  useEffect(() => {
    if (savedRevision === null) return
    void qc.invalidateQueries({ queryKey: keys.route(routeId) })
    void qc.invalidateQueries({ queryKey: keys.preflight(routeId) })
  }, [qc, routeId, savedRevision])

  return (
    <div className={css.shell}>
      <header className={css.bar}>
        <Link to="/lo-trinh" className={css.back} aria-label="Về danh sách">
          <Icon name="back" />
        </Link>
        <div className={css.titleBlock}>
          <div className={css.title} data-testid="editor-title">
            {state.body.title || 'Lộ trình chưa có tên'}
          </div>
          <div className={css.badges}>
            {status && (
              <Badge tone={status.tone}>
                {status.label}
                {route?.latestVersion ? ` v${route.latestVersion}` : ''}
              </Badge>
            )}
            {route?.latestVersion && route.draftChanged ? (
              <Badge tone="moderate">Nháp có thay đổi</Badge>
            ) : null}
          </div>
        </div>
        <nav className={css.tabs} aria-label="Phần của lộ trình">
          {TABS.map(([path, label]) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) => (isActive ? `${css.tab} ${css.tabOn}` : css.tab)}
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <div className={css.save}>
          <span className={css.saveText} data-testid="save-status" data-status={state.status}>
            {SAVE_TEXT[state.status]}
          </span>
          <Button small variant="quiet" disabled={!state.canUndo} onClick={() => saver.undoLast()}>
            <Icon name="undo" size={16} /> Hoàn tác
          </Button>
        </div>
      </header>
      {state.status === 'conflict' && (
        <div className={css.banner} role="alert">
          Bản nháp vừa đổi ở nơi khác (tab khác hoặc máy khác). Thay đổi chưa lưu ở đây sẽ bỏ.{' '}
          <Button small onClick={() => void reload()}>
            Tải lại
          </Button>
        </div>
      )}
      {state.status === 'error' && (
        <div className={css.banner} role="alert">
          Chưa lưu được: {state.error}{' '}
          <Button small onClick={() => saver.retry()}>
            Thử lại
          </Button>
        </div>
      )}
      <JobWatcher />
      <main className={css.main}>
        <Outlet />
      </main>
    </div>
  )
}

/** Leg jobs queued by a draft write: when they finish, the new lines are read back (adopt). */
function JobWatcher() {
  const { routeId, saver, state } = useEditor()
  const qc = useQueryClient()
  const results = useQueries({
    queries: state.queuedJobs.map((id) => ({
      queryKey: keys.job(id),
      queryFn: () =>
        unwrap(api.GET('/admin/api/v1/jobs/{job_id}', { params: { path: { job_id: id } } })),
      refetchInterval: (q: { state: { data?: { status: string } } }) =>
        isJobDone(q.state.data?.status) ? false : 3000,
    })),
  })
  const finished = results.filter((r) => isJobDone(r.data?.status)).length
  const all = state.queuedJobs.length
  useEffect(() => {
    if (!all || finished < all) return
    let live = true
    void draftGetter(routeId)().then((fresh) => {
      if (!live) return
      if (saver.adopt({ ...fresh, queuedJobs: [] })) qc.setQueryData(keys.draft(routeId), fresh)
    })
    return () => {
      live = false
    }
  }, [all, finished, qc, routeId, saver])
  if (!all || finished >= all) return null
  return (
    <div className={css.jobs} role="status">
      Đang tính {all - finished} chặng đường bộ…
    </div>
  )
}
