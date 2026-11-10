/** Page 04 C "Ảnh/video": the media of one stop, in order; chunked upload that resumes. */
import {
  closestCenter,
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { arrayMove, rectSortingStrategy, SortableContext, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, unwrap } from '../api/client'
import { errorText } from '../api/errors'
import { keys, useMedia } from '../api/hooks'
import type { MediaOut } from '../api/types'
import { LIMITS } from '../draft/limits'
import { updateStop } from '../draft/model'
import { previewUrl } from '../media/mediaUrl'
import { ACCEPT, uploadMedia } from '../media/uploadMedia'
import { Icon } from '../ui/Icon'
import { Badge, ui } from '../ui/ui'
import { megabytes } from '../util/format'
import { useEditor } from './context'
import css from './MediaTab.module.css'

interface Pending {
  key: string
  name: string
  f: number
  error: string | null
}

export function MediaTab() {
  const { routeId, saver, state } = useEditor()
  const body = state.body
  const [stopId, setStopId] = useState<string | null>(body.stops[0]?.id ?? null)
  const stop = body.stops.find((s) => s.id === stopId)
  const media = useMedia(routeId)
  const byId = new Map((media.data ?? []).map((m) => [m.id, m]))
  const [pending, setPending] = useState<Pending[]>([])
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const seq = useRef(0)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))

  if (!stop) {
    return <div className={css.empty}>Thêm điểm dừng trước, rồi gắn ảnh/video cho từng điểm.</div>
  }
  const items = stop.media
  const photos = items.filter((id) => byId.get(id)?.type !== 'video').length
  const room = LIMITS.stopMedia - items.length - pending.filter((p) => !p.error).length

  const upload = async (files: File[]) => {
    const target = stop.id
    for (const file of files.slice(0, Math.max(0, room))) {
      const key = `${file.name}:${++seq.current}`
      const patch = (p: Partial<Pending>) =>
        setPending((all) => all.map((x) => (x.key === key ? { ...x, ...p } : x)))
      setPending((all) => [...all, { key, name: file.name, f: 0, error: null }])
      try {
        const row = await uploadMedia(routeId, file, (f) => patch({ f }))
        saver.edit((b) => {
          const s = b.stops.find((x) => x.id === target)
          return s ? updateStop(b, target, { media: [...s.media, row.id] }) : b
        })
        setPending((all) => all.filter((x) => x.key !== key))
        void qc.invalidateQueries({ queryKey: keys.media(routeId) })
      } catch (e) {
        patch({ error: errorText(e) })
      }
    }
  }

  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return
    const from = items.indexOf(String(e.active.id))
    const to = items.indexOf(String(e.over.id))
    if (from < 0 || to < 0) return
    saver.edit((b) => updateStop(b, stop.id, { media: arrayMove(items, from, to) }))
  }

  const remove = async (id: string) => {
    saver.edit((b) => {
      const s = b.stops.find((x) => x.id === stop.id)
      const next = s ? updateStop(b, stop.id, { media: s.media.filter((m) => m !== id) }) : b
      return next.cover === id ? { ...next, cover: null } : next
    })
    await saver.flush()
    const usedElsewhere = saver.snapshot.body.stops.some((s) => s.media.includes(id))
    if (!usedElsewhere) {
      // still used by a published version → the server keeps it; nothing to tell the admin
      await api.DELETE('/admin/api/v1/media/{media_id}', { params: { path: { media_id: id } } })
      void qc.invalidateQueries({ queryKey: keys.media(routeId) })
    }
  }

  return (
    <div className={css.layout}>
      <nav className={css.stops} aria-label="Điểm dừng">
        {body.stops.map((s, i) => (
          <button
            key={s.id}
            type="button"
            className={s.id === stop.id ? `${css.stopBtn} ${css.stopOn}` : css.stopBtn}
            onClick={() => setStopId(s.id)}
          >
            <span className={`num ${css.stopNo}`}>{i + 1}</span>
            <span className={css.stopName}>{s.title || 'Chưa có tên'}</span>
            <span className="muted num">{s.media.length}</span>
          </button>
        ))}
      </nav>
      <section className={css.main}>
        <header className={css.head}>
          <b>{stop.title} · Ảnh/video</b>
          <span className="num">
            {photos} ảnh · {items.length - photos} video · {items.length}/{LIMITS.stopMedia}
          </span>
        </header>
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext items={items} strategy={rectSortingStrategy}>
            <div className={css.grid}>
              {items.map((id, i) => (
                <Tile
                  key={id}
                  id={id}
                  row={byId.get(id)}
                  first={i === 0}
                  cover={body.cover === id}
                  onCover={() => saver.edit((b) => ({ ...b, cover: b.cover === id ? null : id }))}
                  onRemove={() => void remove(id)}
                />
              ))}
              {pending.map((p) => (
                <div key={p.key} className={css.tile}>
                  <div className={css.thumb}>
                    <Icon name="upload" size={28} />
                    <span className={css.badgeTop}>
                      <Badge tone={p.error ? 'hard' : 'moderate'}>
                        {p.error ? 'Lỗi tải lên' : `Đang tải ${Math.round(p.f * 100)} %`}
                      </Badge>
                    </span>
                  </div>
                  <div className={css.tileName}>{p.name}</div>
                  {p.error && (
                    <div className={css.tileErr}>
                      {p.error}{' '}
                      <button
                        type="button"
                        className={css.link}
                        onClick={() => setPending((all) => all.filter((x) => x.key !== p.key))}
                      >
                        bỏ
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </SortableContext>
        </DndContext>
        <label
          className={css.drop}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            void upload([...e.dataTransfer.files])
          }}
        >
          <input
            ref={input}
            type="file"
            multiple
            accept={ACCEPT}
            className="sr-only"
            aria-label="Chọn ảnh, video"
            disabled={room <= 0}
            onChange={(e) => {
              void upload([...(e.target.files ?? [])])
              e.target.value = ''
            }}
          />
          <Icon name="upload" size={24} />
          <b>Thả ảnh, video vào đây hoặc bấm để chọn</b>
          <span className="muted">
            JPEG, PNG, HEIC, MP4 · video ≤ 60 giây · tải tiếp được khi rớt mạng
          </span>
          {room <= 0 && (
            <span className={ui.error}>Đã đủ {LIMITS.stopMedia} ảnh/video cho điểm này.</span>
          )}
        </label>
      </section>
      <aside className={css.side}>
        <div className={ui.card}>
          <div className="eyebrow">Máy chủ làm gì với mỗi tệp</div>
          <ul className={css.list}>
            <li>
              Ảnh: xoay đúng chiều, cạnh dài ≤ 2560 px, JPEG 85, xóa EXIF/GPS; thêm bản 640 px.
            </li>
            <li>
              Video: từ chối khi dài hơn 60 giây; H.264 cạnh ngắn ≤ 720, ≤ 30 hình/giây, AAC, xóa
              siêu dữ liệu.
            </li>
            <li>Tệp gửi theo mảnh 8 MB; rớt mạng thì chọn lại tệp để tải tiếp phần còn thiếu.</li>
            <li>Điểm có ảnh chưa xử lý xong thì chưa xuất bản được.</li>
          </ul>
        </div>
      </aside>
    </div>
  )
}

const STATUS: Record<string, string> = {
  uploading: 'Đang tải lên',
  processing: 'Đang xử lý',
  failed: 'Lỗi xử lý',
}

function Tile(props: {
  id: string
  row: MediaOut | undefined
  first: boolean
  cover: boolean
  onCover: () => void
  onRemove: () => void
}) {
  const { row } = props
  const qc = useQueryClient()
  const { routeId } = useEditor()
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: props.id })
  const [credit, setCredit] = useState(row?.credit ?? '')
  const [saved, setSaved] = useState(row?.credit ?? '')
  const src = previewUrl(props.id, 'thumb', row)
  const video = row?.type === 'video'
  const status = row ? STATUS[row.status] : 'Không thấy tệp'

  const saveCredit = async () => {
    if (credit === saved) return
    await unwrap(
      api.PATCH('/admin/api/v1/media/{media_id}', {
        params: { path: { media_id: props.id } },
        body: { credit: credit.trim() || null },
      }),
    )
    setSaved(credit)
    void qc.invalidateQueries({ queryKey: keys.media(routeId) })
  }

  return (
    <div
      ref={setNodeRef}
      className={css.tile}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      data-testid="media-tile"
    >
      <div className={css.thumb} {...attributes} {...listeners}>
        {src ? (
          <img src={src} alt={row?.originalName ?? ''} />
        ) : (
          <Icon name={video ? 'video' : 'image'} size={32} />
        )}
        <span className={css.badgeTop}>
          {props.first && <Badge tone="dark">Ảnh bìa điểm</Badge>}
          {props.cover && <Badge tone="easy">Bìa lộ trình</Badge>}
          {!saved && <Badge tone="moderate">Thiếu nguồn ảnh</Badge>}
        </span>
        <span className={css.badgeBottom}>
          {video && row?.durationMs ? <Badge tone="dark">▶ {clock(row.durationMs)}</Badge> : null}
          {status && (
            <Badge tone={row?.status === 'failed' || !row ? 'hard' : 'moderate'}>{status}</Badge>
          )}
        </span>
      </div>
      <div className={css.tileName} title={row?.originalName ?? props.id}>
        {row?.originalName ?? props.id}
        {row?.bytes ? <span className="muted"> · {megabytes(row.bytes)}</span> : null}
      </div>
      {row?.error && <div className={css.tileErr}>{row.error}</div>}
      <input
        className={`${ui.input} ${css.credit}`}
        placeholder="Nguồn ảnh (tác giả)"
        aria-label="Nguồn ảnh"
        maxLength={200}
        value={credit}
        onChange={(e) => setCredit(e.target.value)}
        onBlur={() => void saveCredit()}
      />
      <div className={css.tileActions}>
        <button type="button" className={css.link} onClick={props.onCover}>
          {props.cover ? 'bỏ bìa lộ trình' : 'làm bìa lộ trình'}
        </button>
        <button type="button" className={css.linkDanger} onClick={props.onRemove}>
          xóa
        </button>
      </div>
    </div>
  )
}

function clock(ms: number): string {
  const s = Math.round(ms / 1000)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
