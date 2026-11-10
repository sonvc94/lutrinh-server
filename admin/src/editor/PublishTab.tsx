/** Page 04 D "Xuất bản & mã": preflight → publish; the share code (copy, expiry, revoke + reissue). */
import { useState } from 'react'
import { api, unwrap } from '../api/client'
import { errorText } from '../api/errors'
import { sumStats, useInvalidateRoute, useStats } from '../api/hooks'
import type { CodeOut, PublishOut } from '../api/types'
import { localProblems } from '../draft/model'
import { Icon } from '../ui/Icon'
import { Button, Field, ui } from '../ui/ui'
import { count, dayMonth, dateTime, megabytes } from '../util/format'
import { useEditor } from './context'
import css from './PublishTab.module.css'
import { PROBLEM_TEXT, useCodes, usePreflight } from './publishing'
import { VersionList } from './VersionsTab'

export function PublishTab() {
  return (
    <div className={css.layout}>
      <div className={css.col}>
        <PreflightCard />
        <VersionList />
      </div>
      <div className={css.col}>
        <CodeCard />
        <StatsCard />
        <OldCodes />
      </div>
    </div>
  )
}

function PreflightCard() {
  const { routeId, route, saver, state } = useEditor()
  const pre = usePreflight(routeId)
  const invalidate = useInvalidateRoute()
  const [note, setNote] = useState('')
  const [prefix, setPrefix] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<PublishOut | null>(null)
  const [confirmUnpublish, setConfirmUnpublish] = useState(false)
  const p = pre.data
  const local = localProblems(state.body)
  const unsaved = state.status !== 'saved'
  const hasCode = Boolean(route?.code)

  const publish = async () => {
    setBusy(true)
    setError(null)
    setDone(null)
    try {
      await saver.flush()
      const res = await unwrap(
        api.POST('/admin/api/v1/routes/{route_id}/publish', {
          params: { path: { route_id: routeId } },
          body: {
            note: note.trim() || null,
            codePrefix: !hasCode && prefix.trim() ? prefix.trim().toUpperCase() : null,
          },
        }),
      )
      setDone(res)
      setNote('')
      await invalidate(routeId)
    } catch (e) {
      setError(errorText(e))
      void pre.refetch()
    } finally {
      setBusy(false)
    }
  }

  const unpublish = async () => {
    setBusy(true)
    setError(null)
    try {
      await unwrap(
        api.POST('/admin/api/v1/routes/{route_id}/unpublish', {
          params: { path: { route_id: routeId } },
        }),
      )
      setConfirmUnpublish(false)
      await invalidate(routeId)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className={ui.card} aria-label="Kiểm tra trước khi xuất bản">
      <div className="eyebrow">Kiểm tra trước khi xuất bản {p ? `v${p.nextVersion}` : ''}</div>
      {pre.isLoading && <p className="muted">Đang kiểm tra…</p>}
      {pre.error && (
        <div className={ui.notice} role="alert">
          {errorText(pre.error)}
        </div>
      )}
      {p && (
        <ul className={css.checks}>
          {local.map((t) => (
            <Check key={t} kind="bad" text={t} />
          ))}
          {p.blockers.map((b, i) => (
            <Check
              key={`b${i}`}
              kind="bad"
              text={PROBLEM_TEXT[b.code] ?? b.message}
              detail={b.path}
            />
          ))}
          {p.warnings.map((w, i) => (
            <Check
              key={`w${i}`}
              kind="warn"
              text={PROBLEM_TEXT[w.code] ?? w.message}
              detail={w.path}
            />
          ))}
          {p.blockers.length === 0 && local.length === 0 && (
            <Check kind="ok" text="Không có lỗi chặn xuất bản." />
          )}
          <Check
            kind="ok"
            text={`Gói tải về: ${p.mediaFiles ?? 0} tệp ảnh/video · ${megabytes(p.mediaBytes ?? 0)}`}
          />
        </ul>
      )}
      {route?.latestVersion ? (
        <p className={css.diff}>
          {route.draftChanged
            ? `Nháp đã thay đổi so với v${route.latestVersion}.`
            : `Nháp giống v${route.latestVersion}; xuất bản lại sẽ tạo bản giống hệt.`}
        </p>
      ) : null}
      <div className={css.publishForm}>
        <Field label="Ghi chú phiên bản (người dùng thấy khi có bản mới)" htmlFor="pub-note">
          <input
            id="pub-note"
            className={ui.input}
            maxLength={1000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Ví dụ: thêm điểm ngắm hoàng hôn ngày 2"
          />
        </Field>
        {!hasCode && (
          <Field label="Hai ký tự đầu của mã (tuỳ chọn)" htmlFor="pub-prefix">
            <input
              id="pub-prefix"
              className={ui.input}
              maxLength={2}
              value={prefix}
              onChange={(e) => setPrefix(e.target.value)}
            />
          </Field>
        )}
      </div>
      {error && (
        <div className={ui.notice} role="alert">
          {error}
        </div>
      )}
      {done && (
        <div className={`${ui.notice} ${ui.noticeInfo}`} role="status">
          Đã xuất bản v{done.version.version}
          {done.codeIssued ? ` · mã mới ${done.code.code}` : ` · mã ${done.code.code} trỏ bản mới`}.
        </div>
      )}
      <div className={css.actions}>
        <Button
          variant="primary"
          disabled={busy || !p?.canPublish || local.length > 0 || unsaved}
          onClick={() => void publish()}
        >
          Xuất bản {p ? `v${p.nextVersion}` : ''}
        </Button>
        {unsaved && <span className="muted">Đang lưu nháp…</span>}
        {route?.status === 'shared' &&
          (confirmUnpublish ? (
            <span className={css.confirm}>
              Người dùng sẽ không tải được nữa (máy đã tải vẫn giữ).
              <Button small variant="danger" disabled={busy} onClick={() => void unpublish()}>
                Gỡ xuất bản
              </Button>
              <Button small variant="quiet" onClick={() => setConfirmUnpublish(false)}>
                Không
              </Button>
            </span>
          ) : (
            <Button variant="danger" onClick={() => setConfirmUnpublish(true)}>
              Gỡ xuất bản
            </Button>
          ))}
      </div>
    </section>
  )
}

function Check({
  kind,
  text,
  detail,
}: {
  kind: 'ok' | 'bad' | 'warn'
  text: string
  detail?: string
}) {
  const icon = kind === 'ok' ? 'check' : kind === 'bad' ? 'cross' : 'clock'
  return (
    <li className={`${css.check} ${css[kind]}`}>
      <Icon name={icon} size={18} />
      <span>
        {text}
        {detail ? <span className="muted"> · {detail}</span> : null}
      </span>
    </li>
  )
}

function CodeCard() {
  const { routeId, route } = useEditor()
  const codes = useCodes(routeId)
  const invalidate = useInvalidateRoute()
  const live = codes.data?.find((c) => c.live)
  const [mode, setMode] = useState<'none' | 'expiry' | 'revoke'>('none')
  const [expiry, setExpiry] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const run = async (fn: () => Promise<unknown>, after?: string) => {
    setBusy(true)
    setMsg(null)
    try {
      await fn()
      setMode('none')
      if (after) setMsg(after)
      await invalidate(routeId)
    } catch (e) {
      setMsg(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  const copy = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code)
      setMsg('Đã sao chép mã.')
    } catch {
      setMsg('Không sao chép được; hãy chọn mã và sao chép tay.')
    }
  }

  if (!live) {
    return (
      <section className={css.codeCard} aria-label="Mã chia sẻ">
        <div className={css.codeEyebrow}>Mã chia sẻ</div>
        <p>
          {route?.latestVersion
            ? 'Lộ trình chưa có mã đang chạy.'
            : 'Mã được tạo khi xuất bản lần đầu.'}
        </p>
        {route?.latestVersion ? (
          <Button
            variant="primary"
            disabled={busy}
            onClick={() =>
              void run(() =>
                unwrap(
                  api.POST('/admin/api/v1/routes/{route_id}/codes', {
                    params: { path: { route_id: routeId } },
                    body: {},
                  }),
                ),
              )
            }
          >
            Tạo mã
          </Button>
        ) : null}
        {msg && <p className={css.codeMsg}>{msg}</p>}
      </section>
    )
  }

  return (
    <section className={css.codeCard} aria-label="Mã chia sẻ">
      <div className={css.codeEyebrow}>
        Mã chia sẻ · {route?.status === 'shared' ? 'đang chạy' : 'đã gỡ xuất bản'}
      </div>
      <div className={css.code} data-testid="share-code">
        {live.code}
      </div>
      <div className={css.codeMeta}>
        Trỏ phiên bản mới nhất{route?.latestVersion ? ` (v${route.latestVersion})` : ''} · tạo{' '}
        {dayMonth(live.createdAt)} ·{' '}
        {live.expiresAt ? `hết hạn ${dateTime(live.expiresAt)}` : 'không hết hạn'}
      </div>
      <div className={css.codeActions}>
        <Button small onClick={() => void copy(live.code)}>
          Sao chép mã
        </Button>
        <Button small onClick={() => setMode(mode === 'expiry' ? 'none' : 'expiry')}>
          Đặt hạn…
        </Button>
        <Button small onClick={() => setMode(mode === 'revoke' ? 'none' : 'revoke')}>
          Thu hồi và tạo mã mới
        </Button>
      </div>
      {mode === 'expiry' && (
        <div className={css.codeForm}>
          <label>
            Hết hạn ngày{' '}
            <input
              type="date"
              className={ui.input}
              value={expiry}
              onChange={(e) => setExpiry(e.target.value)}
            />
          </label>
          <Button
            small
            disabled={busy || !expiry}
            onClick={() => void run(() => patchExpiry(live, endOfDay(expiry)), 'Đã đặt hạn.')}
          >
            Lưu hạn
          </Button>
          {live.expiresAt && (
            <Button
              small
              variant="quiet"
              disabled={busy}
              onClick={() => void run(() => patchExpiry(live, null), 'Đã bỏ hạn.')}
            >
              Bỏ hạn
            </Button>
          )}
        </div>
      )}
      {mode === 'revoke' && (
        <div className={css.codeForm}>
          <span>
            Mã {live.code} ngừng dùng ngay và không bao giờ cấp lại. Máy đã tải vẫn giữ lộ trình
            nhưng không nhận bản mới qua mã cũ.
          </span>
          <input
            className={ui.input}
            placeholder="Lý do (tuỳ chọn)"
            maxLength={500}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <Button
            small
            variant="primary"
            disabled={busy}
            onClick={() =>
              void run(
                () =>
                  unwrap(
                    api.POST('/admin/api/v1/codes/{code}/revoke', {
                      params: { path: { code: live.code } },
                      body: { reason: reason.trim() || null, reissue: true },
                    }),
                  ),
                'Đã thu hồi mã cũ và tạo mã mới.',
              )
            }
          >
            Thu hồi và tạo mã mới
          </Button>
        </div>
      )}
      {msg && (
        <p className={css.codeMsg} role="status">
          {msg}
        </p>
      )}
    </section>
  )
}

function endOfDay(date: string): string {
  return new Date(`${date}T23:59:59`).toISOString()
}

function patchExpiry(code: CodeOut, expiresAt: string | null) {
  return unwrap(
    api.PATCH('/admin/api/v1/codes/{code}', {
      params: { path: { code: code.code } },
      body: { expiresAt },
    }),
  )
}

function StatsCard() {
  const { routeId } = useEditor()
  const stats = useStats(routeId)
  const rows = stats.data
  const items = [
    ['Lượt tra mã', sumStats(rows, 'lookup', routeId)],
    ['Lượt tải', sumStats(rows, 'download', routeId)],
    ['Mã sai', sumStats(rows, 'bad_lookup', routeId)],
  ] as const
  return (
    <section className={ui.card} aria-label="30 ngày qua">
      <div className="eyebrow">30 ngày qua</div>
      <div className={css.stats}>
        {items.map(([label, n]) => (
          <div key={label}>
            <div className={`num ${css.statNum}`}>{count(n)}</div>
            <div className="muted">{label}</div>
          </div>
        ))}
      </div>
    </section>
  )
}

function OldCodes() {
  const { routeId } = useEditor()
  const codes = useCodes(routeId)
  const old = (codes.data ?? []).filter((c) => !c.live)
  if (!old.length) return null
  return (
    <section className={ui.card} aria-label="Mã cũ">
      <div className="eyebrow">Mã cũ</div>
      <ul className={css.oldCodes}>
        {old.map((c) => (
          <li key={c.code}>
            <span className={`num ${css.oldCode}`}>{c.code}</span>
            <span className="muted">
              thu hồi {c.revokedAt ? dateTime(c.revokedAt) : ''}
              {c.revokeReason ? ` · ${c.revokeReason}` : ''}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
