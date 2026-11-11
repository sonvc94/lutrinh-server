/** Page 04 B "Điểm dừng": the map (left) and the stops by day (right), legs between them. */
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect, useMemo, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useSearchParams } from 'react-router'
import { api, unwrap } from '../api/client'
import { ApiError, errorText } from '../api/errors'
import { ARRIVAL_LABEL, ARRIVALS, LIMITS, type Arrival } from '../draft/limits'
import {
  addStop,
  groupByDay,
  legInto,
  moveStopTo,
  removeStop,
  reorder,
  totals,
  updateStop,
  type DraftBody,
  type LngLat,
  type Stop,
} from '../draft/model'
import { linesOf, pinsOf } from '../map/legs'
import { boundsOf } from '../map/MapAdapter'
import { encode } from '../map/polyline'
import { RouteMap } from '../map/RouteMap'
import { Icon } from '../ui/Icon'
import { Button, Field, ui } from '../ui/ui'
import { duration, km } from '../util/format'
import { useEditor } from './context'
import { draftGetter } from './putDraft'
import { stopSchema, type StopFormIn, type StopFormOut } from './stopForm'
import css from './StopsTab.module.css'

const ROAD = new Set<string | null>([null, 'motorbike', 'car', 'bus', 'walk'])
const SOURCE: Record<string, string> = {
  routed: 'máy chủ tính',
  manual: 'vẽ tay',
  track: 'từ track GPX',
  app: 'từ app',
}

type Tool = 'none' | 'add' | 'sketch'

export function StopsTab() {
  const { routeId, saver, state } = useEditor()
  const body = state.body
  const [params, setParams] = useSearchParams()
  const [selected, setSelected] = useState<string | null>(body.stops[0]?.id ?? null)
  const [tool, setTool] = useState<Tool>(params.get('them') === '1' ? 'add' : 'none')
  const [sketch, setSketch] = useState<LngLat[]>([])
  const [fitTick, setFitTick] = useState(0)
  const [legError, setLegError] = useState<string | null>(null)

  const pins = useMemo(() => pinsOf(body), [body])
  const lines = useMemo(() => linesOf(body), [body])
  const index = body.stops.findIndex((s) => s.id === selected)
  const stop = index >= 0 ? body.stops[index] : undefined
  const prev = index > 0 ? body.stops[index - 1] : undefined
  const fitBounds = useMemo(() => boundsOf(pins.map((p) => p.at)), [pins])

  const setAddTool = (on: boolean) => {
    setTool(on ? 'add' : 'none')
    if (!on && params.has('them')) {
      params.delete('them')
      setParams(params, { replace: true })
    }
  }

  const onMapClick = (p: LngLat) => {
    if (tool === 'add') {
      if (body.stops.length >= LIMITS.stopsMax) return
      let id = ''
      saver.edit((b) => {
        const r = addStop(b, p, selected)
        id = r.id
        return r.body
      })
      setSelected(id)
    } else if (tool === 'sketch') {
      setSketch((s) => [...s, p])
    }
  }

  const sketchLine = stop && prev && tool === 'sketch' ? [at(prev), ...sketch, at(stop)] : null

  const saveSketch = async () => {
    if (!stop || !sketchLine) return
    setLegError(null)
    try {
      await saver.flush()
      const send = () =>
        unwrap(
          api.PUT('/admin/api/v1/routes/{route_id}/legs/{to_stop}', {
            params: {
              path: { route_id: routeId, to_stop: stop.id },
              header: { 'If-Match': saver.snapshot.etag },
            },
            body: {
              path: encode(sketchLine),
              durationS: legInto(body, stop.id)?.durationS ?? null,
            },
          }),
        )
      let res
      try {
        res = await send()
      } catch (e) {
        // a worker leg landed since the last read: read again, then send once more
        if (!(e instanceof ApiError && e.status === 412)) throw e
        saver.adopt(await draftGetter(routeId)())
        res = await send()
      }
      saver.adopt(res)
      setTool('none')
      setSketch([])
    } catch (e) {
      setLegError(errorText(e))
    }
  }

  const recompute = async () => {
    if (!stop) return
    setLegError(null)
    try {
      await saver.flush()
      const ref = await unwrap(
        api.POST('/admin/api/v1/routes/{route_id}/legs/{to_stop}/compute', {
          params: { path: { route_id: routeId, to_stop: stop.id } },
        }),
      )
      saver.addJobs([ref.jobId])
    } catch (e) {
      setLegError(errorText(e))
    }
  }

  return (
    <div className={css.layout}>
      <div className={css.mapCol}>
        <RouteMap
          pins={pins}
          lines={lines}
          selectedId={selected ?? undefined}
          selectedLegTo={prev ? (selected ?? undefined) : undefined}
          sketch={sketchLine}
          draggable={tool !== 'sketch'}
          fit={{ key: `${routeId}:${fitTick}`, bounds: fitBounds }}
          onMapClick={onMapClick}
          onPinClick={setSelected}
          onPinDrag={(id, p) => saver.edit((b) => moveStopTo(b, id, p))}
        />
        <div className={css.tools} role="toolbar" aria-label="Công cụ bản đồ">
          <button
            type="button"
            className={tool === 'add' ? `${css.tool} ${css.toolOn}` : css.tool}
            aria-pressed={tool === 'add'}
            title="Thêm điểm"
            onClick={() => setAddTool(tool !== 'add')}
          >
            <Icon name="pin" title="Thêm điểm" />
          </button>
          <button
            type="button"
            className={css.tool}
            title="Vừa khung"
            onClick={() => setFitTick((n) => n + 1)}
          >
            <Icon name="fit" title="Vừa khung" />
          </button>
        </div>
        <div className={css.hint}>
          {tool === 'add'
            ? 'Bấm lên bản đồ để thêm điểm sau điểm đang chọn · kéo ghim để dời'
            : tool === 'sketch'
              ? 'Bấm lên bản đồ để thêm điểm gãy của chặng · Xong để lưu'
              : 'Chọn ghim để sửa · kéo ghim để dời · công cụ ghim để thêm điểm'}
        </div>
        {stop && prev && (
          <LegPanel
            body={body}
            from={index}
            prev={prev}
            stop={stop}
            sketching={tool === 'sketch'}
            sketchPoints={sketch.length}
            error={legError}
            onSketch={() => {
              setSketch([])
              setTool('sketch')
            }}
            onSketchCancel={() => {
              setSketch([])
              setTool('none')
            }}
            onSketchSave={() => void saveSketch()}
            onRecompute={() => void recompute()}
            onArrival={(a) => saver.edit((b) => updateStop(b, stop.id, { arrival: a }))}
          />
        )}
      </div>
      <StopList
        body={body}
        selected={selected}
        onSelect={setSelected}
        onAdd={() => setAddTool(true)}
      />
    </div>
  )
}

function at(s: Stop): LngLat {
  return { lng: s.lng, lat: s.lat }
}

function LegPanel(props: {
  body: DraftBody
  from: number
  prev: Stop
  stop: Stop
  sketching: boolean
  sketchPoints: number
  error: string | null
  onSketch: () => void
  onSketchCancel: () => void
  onSketchSave: () => void
  onRecompute: () => void
  onArrival: (a: Arrival | null) => void
}) {
  const { stop } = props
  const leg = legInto(props.body, stop.id)
  const road = ROAD.has(stop.arrival)
  const mode = stop.arrival ? ARRIVAL_LABEL[stop.arrival] : `${ARRIVAL_LABEL.none} (xe máy)`
  return (
    <section className={css.legPanel} aria-label="Chặng">
      <div className="eyebrow">
        Chặng {props.from} → {props.from + 1} · {mode}
      </div>
      <div className={css.legTitle}>
        {props.prev.title} → {stop.title}
      </div>
      {road ? (
        leg ? (
          <div className={css.legNums}>
            <span>
              <b className="num">{km(leg.distanceM)}</b> km
            </span>
            <span>
              <b className="num">{duration(leg.durationS)}</b>
            </span>
            <span className="muted">
              {SOURCE[leg.source] ?? leg.source}
              {leg.usedProfile && leg.usedProfile !== leg.profile
                ? ` · tính bằng ${leg.usedProfile}`
                : ''}
              {leg.status !== 'ok' ? ` · ${leg.status}` : ''}
            </span>
          </div>
        ) : (
          <p className="muted">Chưa có đường bộ: máy chủ sẽ tính (đang vẽ đường thẳng).</p>
        )
      ) : (
        <p className="muted">Tàu, máy bay, thuyền: không có đường bộ, vẽ nét đứt thẳng.</p>
      )}
      {stop.arrivalNote && <p className={css.legNote}>{stop.arrivalNote}</p>}
      {props.error && (
        <div className={ui.notice} role="alert">
          {props.error}
        </div>
      )}
      <div className={css.legActions}>
        {props.sketching ? (
          <>
            <span className="muted">{props.sketchPoints} điểm gãy</span>
            <Button small onClick={props.onSketchCancel}>
              Hủy
            </Button>
            <Button small variant="primary" onClick={props.onSketchSave}>
              Xong
            </Button>
          </>
        ) : (
          <>
            <Button small disabled={!road} onClick={props.onRecompute}>
              Tính lại
            </Button>
            <Button small disabled={!road} onClick={props.onSketch}>
              Vẽ tay
            </Button>
            <label className={css.arrival}>
              <span className="sr-only">Đổi phương tiện</span>
              <select
                className={ui.input}
                value={stop.arrival ?? ''}
                onChange={(e) => props.onArrival((e.target.value || null) as Arrival | null)}
              >
                <option value="">{ARRIVAL_LABEL.none}</option>
                {ARRIVALS.map((a) => (
                  <option key={a} value={a}>
                    {ARRIVAL_LABEL[a]}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}
      </div>
    </section>
  )
}

function StopList(props: {
  body: DraftBody
  selected: string | null
  onSelect: (id: string) => void
  onAdd: () => void
}) {
  const { saver } = useEditor()
  const { body } = props
  const groups = groupByDay(body)
  const t = totals(body)
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
  const onDragEnd = (e: DragEndEvent) => {
    if (e.over) saver.edit((b) => reorder(b, String(e.active.id), String(e.over!.id)))
  }
  return (
    <aside className={css.listCol}>
      <div className={css.listHead}>
        <div className="eyebrow" data-testid="stops-total">
          {t.stops} điểm · {t.days} ngày · {km(t.distanceM)} km
        </div>
        <div className={css.listButtons}>
          <Button
            small
            disabled={body.days >= LIMITS.daysMax}
            onClick={() => saver.edit((b) => ({ ...b, days: Math.max(b.days, groups.length) + 1 }))}
          >
            + Ngày
          </Button>
          <Button small variant="primary" onClick={props.onAdd}>
            + Điểm
          </Button>
        </div>
      </div>
      {body.stops.length === 0 && (
        <p className={css.empty}>Chưa có điểm dừng. Bấm “+ Điểm” rồi bấm lên bản đồ.</p>
      )}
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={body.stops.map((s) => s.id)} strategy={verticalListSortingStrategy}>
          {groups.map((g) => (
            <DayGroupView
              key={g.day}
              day={g.day}
              canDrop={g.day === groups.length && g.stops.length === 0 && g.day > 1}
              onRemoveDay={() => saver.edit((b) => ({ ...b, days: Math.max(1, b.days - 1) }))}
            >
              {g.stops.map(({ stop, index }) => (
                <StopRow
                  key={stop.id}
                  body={body}
                  stop={stop}
                  index={index}
                  selected={stop.id === props.selected}
                  onSelect={() => props.onSelect(stop.id)}
                  onRemove={() => {
                    const next = body.stops[index + 1] ?? body.stops[index - 1]
                    saver.edit((b) => removeStop(b, stop.id))
                    if (next) props.onSelect(next.id)
                  }}
                />
              ))}
            </DayGroupView>
          ))}
        </SortableContext>
      </DndContext>
    </aside>
  )
}

function DayGroupView(props: {
  day: number
  canDrop: boolean
  onRemoveDay: () => void
  children: React.ReactNode
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `day:${props.day}` })
  return (
    <section ref={setNodeRef} className={isOver ? `${css.day} ${css.dayOver}` : css.day}>
      <div className={css.dayHead}>
        <span className="eyebrow">Ngày {props.day}</span>
        {props.canDrop && (
          <button type="button" className={css.linkButton} onClick={props.onRemoveDay}>
            bỏ ngày trống
          </button>
        )}
      </div>
      {props.children}
    </section>
  )
}

function StopRow(props: {
  body: DraftBody
  stop: Stop
  index: number
  selected: boolean
  onSelect: () => void
  onRemove: () => void
}) {
  const { stop, index } = props
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: stop.id,
  })
  const leg = index > 0 ? legInto(props.body, stop.id) : undefined
  const n = props.body.stops.length
  const disc = index === 0 ? css.discStart : index === n - 1 ? css.discEnd : css.discStep
  const meta = [
    stop.time,
    index > 0 ? (stop.arrival ? ARRIVAL_LABEL[stop.arrival] : null) : 'Xuất phát',
    stop.media.length ? `${stop.media.length} ảnh/video` : null,
  ].filter(Boolean)
  return (
    <div
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.6 : 1,
      }}
    >
      {index > 0 && (
        <div className={css.legChip}>
          {leg
            ? `${km(leg.distanceM)} km · ~${duration(leg.durationS)}`
            : ROAD.has(stop.arrival)
              ? 'chưa có đường'
              : 'không đường bộ'}
        </div>
      )}
      {stop.arrivalNote && (
        <div className={css.legNote} data-testid="leg-note">
          {stop.arrivalNote}
        </div>
      )}
      <div className={props.selected ? `${css.row} ${css.rowOn}` : css.row} data-testid="stop-row">
        <button
          type="button"
          className={css.grip}
          aria-label={`Kéo để đổi thứ tự ${stop.title}`}
          {...attributes}
          {...listeners}
        >
          <Icon name="grip" size={16} />
        </button>
        <button
          type="button"
          className={css.rowMain}
          onClick={props.onSelect}
          aria-expanded={props.selected}
        >
          <span className={`${css.disc} ${disc}`}>{index + 1}</span>
          <span className={css.rowText}>
            <span className={css.rowTitle}>{stop.title || 'Chưa có tên'}</span>
            <span className={css.rowMeta}>{meta.join(' · ')}</span>
          </span>
        </button>
      </div>
      {props.selected && <StopForm stop={stop} index={index} onRemove={props.onRemove} />}
    </div>
  )
}

function toForm(s: Stop): StopFormIn {
  return {
    title: s.title,
    time: s.time ?? '',
    day: s.day,
    arrival: s.arrival ?? '',
    arrivalNote: s.arrivalNote ?? '',
    note: s.note,
  }
}

function StopForm({ stop, index, onRemove }: { stop: Stop; index: number; onRemove: () => void }) {
  const { saver } = useEditor()
  const form = useForm<StopFormIn, unknown, StopFormOut>({
    resolver: zodResolver(stopSchema),
    mode: 'onChange',
    defaultValues: toForm(stop),
  })
  const { register, subscribe, reset, getValues, formState } = form

  // Typing: a valid form is saved after a short pause (DraftSaver.edit, not immediate).
  useEffect(() => {
    return subscribe({
      formState: { values: true },
      callback: ({ values }) => {
        const ok = stopSchema.safeParse(values)
        if (!ok.success) return
        const v = ok.data
        saver.edit(
          (b) =>
            updateStop(b, stop.id, {
              title: v.title,
              time: v.time || null,
              day: v.day,
              arrival: (v.arrival || null) as Arrival | null,
              arrivalNote: v.arrivalNote || undefined,
              note: v.note,
            }),
          false,
        )
      },
    })
  }, [subscribe, saver, stop.id])

  // Undo or a server read changed the stop: show it (unless that is what the form already says).
  useEffect(() => {
    const now = toForm(stop)
    const cur = getValues()
    const same =
      cur.title.trim() === now.title &&
      cur.time === now.time &&
      Number(cur.day) === now.day &&
      cur.arrival === now.arrival &&
      cur.arrivalNote.trim() === now.arrivalNote &&
      cur.note === now.note
    if (!same) reset(now)
  }, [stop, getValues, reset])

  const e = formState.errors
  const id = (f: string) => `stop-${stop.id}-${f}`
  return (
    <form className={css.form} onSubmit={(ev) => ev.preventDefault()} aria-label="Sửa điểm dừng">
      <Field label="Tên điểm" htmlFor={id('title')} error={e.title?.message}>
        <input
          id={id('title')}
          className={ui.input}
          aria-invalid={!!e.title}
          {...register('title')}
        />
      </Field>
      <div className={css.formRow}>
        <Field label="Giờ" htmlFor={id('time')} error={e.time?.message}>
          <input
            id={id('time')}
            className={ui.input}
            placeholder="07:30"
            aria-invalid={!!e.time}
            {...register('time')}
          />
        </Field>
        <Field label="Ngày" htmlFor={id('day')} error={e.day?.message}>
          <input
            id={id('day')}
            type="number"
            min={1}
            max={LIMITS.daysMax}
            className={ui.input}
            aria-invalid={!!e.day}
            {...register('day')}
          />
        </Field>
        {index > 0 && (
          <Field label="Đến bằng" htmlFor={id('arrival')}>
            <select id={id('arrival')} className={ui.input} {...register('arrival')}>
              <option value="">{ARRIVAL_LABEL.none}</option>
              {ARRIVALS.map((a) => (
                <option key={a} value={a}>
                  {ARRIVAL_LABEL[a]}
                </option>
              ))}
            </select>
          </Field>
        )}
      </div>
      {(index > 0 || stop.arrivalNote) && (
        <Field
          label="Ghi chú chặng (đường từ điểm trước đến đây)"
          htmlFor={id('arrivalNote')}
          error={
            e.arrivalNote?.message ??
            (index === 0 ? 'Điểm xuất phát không có chặng đến: hãy xóa ghi chú này.' : undefined)
          }
        >
          <textarea
            id={id('arrivalNote')}
            className={ui.input}
            rows={2}
            placeholder="Ví dụ: Đường dốc khó đi · Gửi xe phía đối diện, 30k"
            aria-invalid={!!e.arrivalNote || index === 0}
            {...register('arrivalNote')}
          />
        </Field>
      )}
      <Field label="Ghi chú" htmlFor={id('note')} error={e.note?.message}>
        <textarea
          id={id('note')}
          className={ui.input}
          rows={3}
          aria-invalid={!!e.note}
          {...register('note')}
        />
      </Field>
      <div className={css.formFoot}>
        <span className="muted num">
          {stop.lat.toFixed(5)}, {stop.lng.toFixed(5)}
        </span>
        <Button small variant="danger" onClick={onRemove}>
          <Icon name="trash" size={16} /> Xóa điểm
        </Button>
      </div>
    </form>
  )
}
