/**
 * The draft body as the server stores it (camelCase; page 02) and the pure edits the editor
 * makes on it. The server reconciles legs on PUT (stale lines dropped, missing ones queued), so
 * edits here never invent leg lines; they only drop legs into stops that no longer exist.
 */
import type { Arrival } from './limits'
import { LIMITS } from './limits'

export interface Stop {
  id: string
  day: number
  time: string | null
  title: string
  note: string
  lat: number
  lng: number
  arrival: Arrival | null
  /** Note on the travel from the previous stop to this one; absent (never '') when there is none. */
  arrivalNote?: string
  media: string[]
}

export interface Leg {
  to: string
  profile: string
  usedProfile: string | null
  source: string
  status: string
  distanceM: number
  durationS: number
  path: string
}

export interface DraftBody {
  title: string
  description: string
  days: number
  cover: string | null
  readyMade: string | null
  credits: string[]
  stops: Stop[]
  legs: Leg[]
}

export interface LngLat {
  lng: number
  lat: number
}

function str(v: unknown, d = ''): string {
  return typeof v === 'string' ? v : d
}

function num(v: unknown, d = 0): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : d
}

/** Read a stored body (possibly incomplete while it is edited) with defaults for what is missing. */
export function normalise(raw: Record<string, unknown>): DraftBody {
  const stops = Array.isArray(raw.stops) ? (raw.stops as Record<string, unknown>[]) : []
  const legs = Array.isArray(raw.legs) ? (raw.legs as Record<string, unknown>[]) : []
  return {
    title: str(raw.title),
    description: str(raw.description),
    days: Math.max(1, num(raw.days, 1)),
    cover: typeof raw.cover === 'string' ? raw.cover : null,
    readyMade: typeof raw.readyMade === 'string' ? raw.readyMade : null,
    credits: Array.isArray(raw.credits) ? raw.credits.filter((c) => typeof c === 'string') : [],
    stops: stops.map((s) => ({
      id: str(s.id),
      day: Math.max(1, num(s.day, 1)),
      time: typeof s.time === 'string' ? s.time : null,
      title: str(s.title),
      note: str(s.note),
      lat: num(s.lat),
      lng: num(s.lng),
      arrival: typeof s.arrival === 'string' ? (s.arrival as Arrival) : null,
      ...(typeof s.arrivalNote === 'string' && s.arrivalNote.trim()
        ? { arrivalNote: s.arrivalNote }
        : {}),
      media: Array.isArray(s.media) ? s.media.filter((m) => typeof m === 'string') : [],
    })),
    legs: legs.map((l) => ({
      to: str(l.to),
      profile: str(l.profile),
      usedProfile: typeof l.usedProfile === 'string' ? l.usedProfile : null,
      source: str(l.source),
      status: str(l.status),
      distanceM: num(l.distanceM),
      durationS: num(l.durationS),
      path: str(l.path),
    })),
  }
}

export function newStopId(taken: Iterable<string>, random: () => number = Math.random): string {
  const used = new Set(taken)
  for (;;) {
    const id = 'st_' + Math.floor(random() * 0xffffffff).toString(36)
    if (!used.has(id)) return id
  }
}

export interface DayGroup {
  day: number
  stops: { stop: Stop; index: number }[]
}

/** Stops grouped by day for the timeline; every day 1…max(days, last stop day) has a group. */
export function groupByDay(body: DraftBody): DayGroup[] {
  const last = body.stops.reduce((m, s) => Math.max(m, s.day), 0)
  const n = Math.max(body.days, last, 1)
  const groups: DayGroup[] = Array.from({ length: n }, (_, i) => ({ day: i + 1, stops: [] }))
  body.stops.forEach((stop, index) => groups[stop.day - 1]?.stops.push({ stop, index }))
  return groups
}

function withStops(body: DraftBody, stops: Stop[]): DraftBody {
  const ids = new Set(stops.map((s) => s.id))
  const days = Math.max(body.days, ...stops.map((s) => s.day))
  return { ...body, days, stops, legs: body.legs.filter((l) => ids.has(l.to)) }
}

export function updateStop(
  body: DraftBody,
  id: string,
  patch: Partial<Omit<Stop, 'id'>>,
): DraftBody {
  return withStops(
    body,
    body.stops.map((s) => (s.id === id ? withoutEmptyNote({ ...s, ...patch }) : s)),
  )
}

/** `arrivalNote` is absent, never '' or undefined-valued, so the stored body keeps its shape. */
function withoutEmptyNote(s: Stop): Stop {
  if (s.arrivalNote) return s
  const { arrivalNote: _, ...rest } = s
  return rest
}

export function removeStop(body: DraftBody, id: string): DraftBody {
  const cover = body.stops.find((s) => s.id === id)?.media.includes(body.cover ?? '')
  return {
    ...withStops(
      body,
      body.stops.filter((s) => s.id !== id),
    ),
    cover: cover ? null : body.cover,
  }
}

/** A new stop after `afterId` (or at the end), on that stop's day; returns the body and its id. */
export function addStop(
  body: DraftBody,
  at: LngLat,
  afterId: string | null,
  random?: () => number,
): { body: DraftBody; id: string } {
  const id = newStopId(
    body.stops.map((s) => s.id),
    random,
  )
  const i = afterId ? body.stops.findIndex((s) => s.id === afterId) : -1
  const pos = i >= 0 ? i + 1 : body.stops.length
  const prev = body.stops[pos - 1]
  const stop: Stop = {
    id,
    day: prev?.day ?? 1,
    time: null,
    title: `Điểm ${body.stops.length + 1}`,
    note: '',
    lat: round6(at.lat),
    lng: round6(at.lng),
    arrival: null,
    media: [],
  }
  const stops = [...body.stops.slice(0, pos), stop, ...body.stops.slice(pos)]
  return { body: withStops(body, stops), id }
}

export function round6(x: number): number {
  return Math.round(x * 1e6) / 1e6
}

export function moveStopTo(body: DraftBody, id: string, at: LngLat): DraftBody {
  return updateStop(body, id, { lat: round6(at.lat), lng: round6(at.lng) })
}

/**
 * Drag-and-drop in the timeline: `activeId` lands where `overId` is. Over a stop: take its place
 * and its day. Over a day header (`day:N`): last stop of day N (after earlier days' stops).
 */
export function reorder(body: DraftBody, activeId: string, overId: string): DraftBody {
  if (activeId === overId) return body
  const from = body.stops.findIndex((s) => s.id === activeId)
  if (from < 0) return body
  const moving = body.stops[from] as Stop
  const rest = body.stops.filter((s) => s.id !== activeId)
  let to: number
  let day: number
  if (overId.startsWith('day:')) {
    day = Number(overId.slice(4))
    if (!Number.isInteger(day) || day < 1) return body
    const after = rest.findLastIndex((s) => s.day <= day)
    to = after + 1
  } else {
    const overIndex = body.stops.findIndex((s) => s.id === overId)
    if (overIndex < 0) return body
    const over = body.stops[overIndex] as Stop
    day = over.day
    // Moving down: land after `over`; moving up: before it (dnd-kit sortable semantics).
    to = rest.findIndex((s) => s.id === overId) + (from < overIndex ? 1 : 0)
  }
  const stops = [...rest.slice(0, to), { ...moving, day }, ...rest.slice(to)]
  return withStops(body, stops)
}

export function legInto(body: DraftBody, stopId: string): Leg | undefined {
  return body.legs.find((l) => l.to === stopId)
}

export function totals(body: DraftBody): { stops: number; days: number; distanceM: number } {
  return {
    stops: body.stops.length,
    days: groupByDay(body).length,
    distanceM: body.legs.reduce((sum, l) => sum + l.distanceM, 0),
  }
}

/** Form-level checks the editor shows before the server's preflight (schema limits, R2 order). */
export function localProblems(body: DraftBody): string[] {
  const out: string[] = []
  if (body.stops.length < LIMITS.stopsMin) out.push(`Cần ít nhất ${LIMITS.stopsMin} điểm dừng.`)
  let prevDay = 0
  let lastTime: string | null = null
  body.stops.forEach((s, i) => {
    if (!s.title.trim()) out.push(`Điểm ${i + 1} chưa có tên.`)
    if (i === 0 && s.arrivalNote)
      out.push('Điểm xuất phát không có chặng đến: hãy xóa ghi chú chặng của điểm 1.')
    if (s.day < prevDay) out.push(`Điểm ${i + 1}: ngày ${s.day} sau ngày ${prevDay}.`)
    if (s.day !== prevDay) lastTime = null
    prevDay = Math.max(prevDay, s.day)
    if (s.time) {
      if (lastTime && s.time < lastTime) out.push(`Điểm ${i + 1}: ${s.time} sớm hơn ${lastTime}.`)
      lastTime = lastTime && lastTime > s.time ? lastTime : s.time
    }
  })
  return out
}
