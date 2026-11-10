/** Page 04 D "Phiên bản": every published version; republishing an old one makes a new version. */
import { useState } from 'react'
import { api, unwrap } from '../api/client'
import { errorText } from '../api/errors'
import { useInvalidateRoute } from '../api/hooks'
import { Button, ui } from '../ui/ui'
import { dateTime, megabytes } from '../util/format'
import { useEditor } from './context'
import css from './PublishTab.module.css'
import { useVersions } from './publishing'

export function VersionsTab() {
  return (
    <div className={css.single}>
      <VersionList />
    </div>
  )
}

export function VersionList() {
  const { routeId, route } = useEditor()
  const versions = useVersions(routeId)
  const invalidate = useInvalidateRoute()
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const latest = route?.latestVersion ?? null

  const republish = async (v: number) => {
    setBusy(v)
    setError(null)
    try {
      await unwrap(
        api.POST('/admin/api/v1/routes/{route_id}/versions/{version}/republish', {
          params: { path: { route_id: routeId, version: v } },
          body: { note: `Xuất bản lại v${v}` },
        }),
      )
      await invalidate(routeId)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(null)
    }
  }

  const rows = [...(versions.data ?? [])].sort((a, b) => b.version - a.version)
  return (
    <section className={ui.card} aria-label="Phiên bản">
      <div className="eyebrow">Phiên bản</div>
      {error && (
        <div className={ui.notice} role="alert">
          {error}
        </div>
      )}
      {rows.length === 0 ? (
        <p className="muted">Chưa xuất bản phiên bản nào.</p>
      ) : (
        <ol className={css.versions}>
          {rows.map((v) => (
            <li key={v.version} className={css.version} data-testid="version-row">
              <b className={`num ${css.vno}`}>v{v.version}</b>
              <div className={css.vtext}>
                <div>
                  {dateTime(v.publishedAt)}
                  {v.sourceVersion ? (
                    <span className="muted"> · lại từ v{v.sourceVersion}</span>
                  ) : null}
                  {v.version === latest ? <span className="muted"> · đang chia sẻ</span> : null}
                </div>
                {v.note && <div className={css.vnote}>{v.note}</div>}
                <div className="muted num">
                  {megabytes(v.bytes + v.mediaBytes)} · {v.mediaFiles} tệp · sha256{' '}
                  {v.sha256.slice(0, 8)}
                </div>
              </div>
              {v.version !== latest && (
                <Button small disabled={busy !== null} onClick={() => void republish(v.version)}>
                  xuất bản lại
                </Button>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
