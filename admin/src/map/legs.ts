/** Draft stops/legs → what the map draws (pure; the editor's map view model). */
import type { DraftBody } from '../draft/model'
import type { LegLine, LegStroke, StopPin } from './MapAdapter'
import { decode } from './polyline'

export function strokeFor(arrival: string | null): LegStroke {
  if (arrival === 'walk') return 'dots'
  if (arrival === 'train' || arrival === 'plane' || arrival === 'boat') return 'dashed'
  return 'solid'
}

export function pinsOf(body: DraftBody): StopPin[] {
  const n = body.stops.length
  return body.stops.map((s, i) => ({
    id: s.id,
    at: { lng: s.lng, lat: s.lat },
    label: String(i + 1),
    kind: i === 0 ? 'start' : i === n - 1 ? 'end' : 'step',
    title: s.title,
  }))
}

/** One line per stop after the first: the leg's path, or a straight line when there is none. */
export function linesOf(body: DraftBody): LegLine[] {
  const byTo = new Map(body.legs.map((l) => [l.to, l]))
  const out: LegLine[] = []
  for (let i = 1; i < body.stops.length; i++) {
    const a = body.stops[i - 1]!
    const b = body.stops[i]!
    const leg = byTo.get(b.id)
    const stroke = strokeFor(b.arrival)
    let path = null
    if (leg?.path) {
      try {
        path = decode(leg.path)
      } catch {
        path = null
      }
    }
    if (path && path.length >= 2) out.push({ to: b.id, path, stroke })
    else
      out.push({
        to: b.id,
        path: [
          { lng: a.lng, lat: a.lat },
          { lng: b.lng, lat: b.lat },
        ],
        stroke: stroke === 'dashed' ? 'dashed' : 'straight',
      })
  }
  return out
}
