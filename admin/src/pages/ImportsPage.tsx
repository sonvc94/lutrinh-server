import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { api, unwrap } from '../api/client'
import { errorText } from '../api/errors'
import { useCreateRoute } from '../api/hooks'
import type { ImportOut } from '../api/types'
import { sendChunks } from '../api/upload'
import { Badge, Button, ui } from '../ui/ui'
import css from './ImportsPage.module.css'

type Kind = 'gpx' | 'backup'

interface Trip {
  id: string
  title: string
  startDate?: string | null
  endDate?: string | null
  stops: number
  draftsSkipped?: number
  photos?: number
  videos?: number
  legsOk?: number
  legsTotal?: number
}

/** Upload a file as an import (chunks) and read it: the server answers with a preview. */
export async function uploadImport(
  kind: Kind,
  file: File,
  onProgress: (f: number) => void,
): Promise<ImportOut> {
  const created = await unwrap(
    api.POST('/admin/api/v1/imports', { body: { kind, filename: file.name, bytes: file.size } }),
  )
  if (!created.upload) throw new Error('server sent no upload plan')
  await sendChunks({ kind: 'imports', id: created.id, file, state: created.upload, onProgress })
  return unwrap(
    api.POST('/admin/api/v1/imports/{import_id}/complete', {
      params: { path: { import_id: created.id } },
    }),
  )
}

/** Page 04 E: from GPX, from an app backup, or drawn on the map; always through a preview. */
export function ImportsPage() {
  const [current, setCurrent] = useState<ImportOut | null>(null)
  const [progress, setProgress] = useState<{ kind: Kind; name: string; f: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [trip, setTrip] = useState<string | null>(null)
  const [applying, setApplying] = useState(false)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const create = useCreateRoute()

  const start = async (kind: Kind, file: File) => {
    setError(null)
    setCurrent(null)
    setTrip(null)
    setProgress({ kind, name: file.name, f: 0 })
    try {
      const row = await uploadImport(kind, file, (f) => setProgress({ kind, name: file.name, f }))
      setCurrent(row)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setProgress(null)
    }
  }

  const apply = async () => {
    if (!current) return
    setApplying(true)
    setError(null)
    try {
      const ref = await unwrap(
        api.POST('/admin/api/v1/imports/{import_id}/apply', {
          params: { path: { import_id: current.id } },
          body: current.kind === 'backup' ? { tripId: trip } : {},
        }),
      )
      await qc.invalidateQueries({ queryKey: ['routes'] })
      navigate(`/lo-trinh/${ref.routeId}/diem-dung`)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setApplying(false)
    }
  }

  return (
    <section className={css.page}>
      <header>
        <div className="eyebrow">Nhập lộ trình</div>
        <h1 className={css.title}>Từ GPX, từ bản sao lưu của app, hoặc vẽ trên bản đồ</h1>
      </header>
      <div className={css.cards}>
        <SourceCard
          tag="GPX"
          title="Tệp GPX 1.0/1.1"
          accept=".gpx,application/gpx+xml"
          inputLabel="Chọn tệp GPX"
          busy={progress?.kind === 'gpx'}
          onFile={(f) => void start('gpx', f)}
        >
          Cùng bộ đọc như app (không tải DTD/entity ngoài). <code>wpt</code> → điểm dừng theo thứ tự
          tệp, <code>name</code>/<code>desc</code> → tên/ghi chú, thời gian → ngày thứ mấy + giờ.{' '}
          <code>trk</code>/<code>rte</code> → cắt thành đường của từng chặng; không có{' '}
          <code>trk</code> thì máy chủ tính đường bộ. Không có <code>wpt</code>: đề xuất điểm ở đầu,
          cuối và các chỗ dừng lâu trên track.
        </SourceCard>
        <SourceCard
          tag="Sao lưu app"
          title="LuTrinh-saoluu-….zip"
          accept=".zip,application/zip"
          inputLabel="Chọn bản sao lưu"
          busy={progress?.kind === 'backup'}
          onFile={(f) => void start('backup', f)}
        >
          Đọc <code>manifest.json</code> + <code>lutrinh.db</code> (schema 7–10; cũ hơn thì từ
          chối), liệt kê các chuyến đi, anh/chị chọn <b>một</b>. Lấy điểm đã đăng (bỏ nháp),
          ảnh/video theo thứ tự, chặng có đường; ngày thật → “ngày thứ mấy”. Ảnh vẫn được thu nhỏ và
          xóa EXIF lại.
        </SourceCard>
        <div className={css.card}>
          <Badge tone="dark">Trên bản đồ</Badge>
          <h2 className={css.cardTitle}>Vẽ từ đầu</h2>
          <p className={css.text}>
            “Lộ trình mới” → đặt điểm bằng công cụ “Thêm điểm”; chặng tự tính. Gói lộ trình
            (.lutrinh-route.zip) chưa nhập được ở bản này.
          </p>
          <Button
            variant="primary"
            disabled={create.isPending}
            onClick={() =>
              void create
                .mutateAsync(undefined)
                .then((r) => navigate(`/lo-trinh/${r.id}/diem-dung?them=1`))
            }
          >
            Lộ trình mới
          </Button>
        </div>
      </div>

      {progress && (
        <div className={css.progress} role="status">
          Đang tải lên {progress.name} ·{' '}
          <span className="num">{Math.round(progress.f * 100)} %</span>
          <div className={css.bar}>
            <div style={{ width: `${progress.f * 100}%` }} />
          </div>
        </div>
      )}
      {error && (
        <div className={ui.notice} role="alert">
          {error}
        </div>
      )}
      {current && (
        <Preview
          row={current}
          trip={trip}
          onTrip={setTrip}
          applying={applying}
          onCancel={() => setCurrent(null)}
          onApply={() => void apply()}
        />
      )}
    </section>
  )
}

function SourceCard(props: {
  tag: string
  title: string
  accept: string
  inputLabel: string
  busy: boolean
  onFile: (f: File) => void
  children: React.ReactNode
}) {
  const input = useRef<HTMLInputElement>(null)
  return (
    <div className={css.card}>
      <Badge tone="dark">{props.tag}</Badge>
      <h2 className={css.cardTitle}>{props.title}</h2>
      <p className={css.text}>{props.children}</p>
      <input
        ref={input}
        type="file"
        accept={props.accept}
        aria-label={props.inputLabel}
        className="sr-only"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) props.onFile(f)
          e.target.value = ''
        }}
      />
      <Button disabled={props.busy} onClick={() => input.current?.click()}>
        {props.inputLabel}
      </Button>
    </div>
  )
}

function Preview(props: {
  row: ImportOut
  trip: string | null
  onTrip: (id: string) => void
  applying: boolean
  onCancel: () => void
  onApply: () => void
}) {
  const { row } = props
  const p = (row.preview ?? {}) as Record<string, unknown>
  const failed = row.status === 'failed'
  const trips = (Array.isArray(p.trips) ? p.trips : []) as Trip[]
  const ready = row.status === 'ready' && (row.kind === 'gpx' || props.trip !== null)
  return (
    <div className={css.preview} data-testid="import-preview">
      <div className={css.previewHead}>
        {row.kind === 'gpx' ? 'Nhập từ GPX' : 'Nhập từ bản sao lưu'} · {row.filename}
      </div>
      <div className={css.previewBody}>
        {failed ? (
          <div className={ui.notice} role="alert">
            Không đọc được tệp: {String(row.error?.code ?? '')} {String(row.error?.detail ?? '')}
          </div>
        ) : row.kind === 'gpx' ? (
          <dl className={css.facts}>
            <div>
              <dt>Tên</dt>
              <dd>{String(p.title ?? '')}</dd>
            </div>
            <div>
              <dt>Điểm dừng</dt>
              <dd className="num" data-testid="preview-stops">
                {String(p.stops ?? 0)}
              </dd>
            </div>
            <div>
              <dt>Số ngày</dt>
              <dd className="num">{String(p.days ?? 1)}</dd>
            </div>
            <div>
              <dt>Lấy điểm từ</dt>
              <dd>{p.stopsFrom === 'track' ? 'chỗ dừng trên track' : 'waypoint (wpt)'}</dd>
            </div>
            <div>
              <dt>Chặng</dt>
              <dd>
                {String(p.legsFromTrack ?? 0)} từ track · {String(p.legsToCompute ?? 0)} máy chủ sẽ
                tính
              </dd>
            </div>
          </dl>
        ) : (
          <>
            <p>
              Bản sao lưu schema {String(p.schemaVersion ?? '?')}: <b>{trips.length} chuyến đi</b>.
              Chọn chuyến đi để tạo lộ trình nháp:
            </p>
            <div className={css.trips} role="radiogroup" aria-label="Chuyến đi">
              {trips.map((t) => (
                <label
                  key={t.id}
                  className={props.trip === t.id ? `${css.trip} ${css.tripOn}` : css.trip}
                >
                  <input
                    type="radio"
                    name="trip"
                    checked={props.trip === t.id}
                    onChange={() => props.onTrip(t.id)}
                  />
                  <b>{t.title}</b>
                  <span className="muted">
                    {[t.startDate, t.endDate].filter(Boolean).join('–')} · {t.stops} điểm
                    {t.draftsSkipped ? ` (${t.draftsSkipped} nháp, bỏ qua)` : ''} · {t.photos ?? 0}{' '}
                    ảnh
                    {t.videos ? ` · ${t.videos} video` : ''}
                    {t.legsTotal ? ` · ${t.legsOk ?? 0}/${t.legsTotal} chặng có đường bộ` : ''}
                  </span>
                </label>
              ))}
            </div>
          </>
        )}
        <div className={css.actions}>
          <Button variant="quiet" onClick={props.onCancel}>
            Hủy
          </Button>
          <Button variant="primary" disabled={!ready || props.applying} onClick={props.onApply}>
            Tạo lộ trình nháp
          </Button>
        </div>
      </div>
    </div>
  )
}
