/**
 * Limits from spec/route.schema.json, the same rule as the server and the app (D-23). Read from
 * the schema file at build time so a change there reaches the forms.
 */
import schema from '../../../spec/route.schema.json'

type Json = Record<string, unknown>
const defs = schema.$defs as unknown as Json

function at(obj: Json, ...keys: string[]): Json {
  let cur: unknown = obj
  for (const k of keys) cur = (cur as Json)[k]
  return cur as Json
}

function maxLength(node: Json): number {
  const all = (node.allOf as Json[] | undefined) ?? [node]
  for (const n of all) if (typeof n.maxLength === 'number') return n.maxLength
  throw new Error('maxLength missing in spec/route.schema.json')
}

const route = at(defs, 'route', 'properties')
const stop = at(defs, 'stop', 'properties')

export const LIMITS = {
  routeTitle: maxLength(at(route, 'title')),
  routeDescription: maxLength(at(route, 'description')),
  daysMax: at(route, 'days').maximum as number,
  stopTitle: maxLength(at(stop, 'title')),
  stopNote: maxLength(at(stop, 'note')),
  arrivalNote: maxLength(at(stop, 'arrivalNote')),
  stopMedia: at(stop, 'media').maxItems as number,
  stopsMin: at(schema as unknown as Json, 'properties', 'stops').minItems as number,
  stopsMax: at(schema as unknown as Json, 'properties', 'stops').maxItems as number,
  timePattern: new RegExp(((at(stop, 'time').oneOf as Json[])[0] as Json).pattern as string),
} as const

export const ARRIVALS = ['motorbike', 'car', 'bus', 'walk', 'train', 'plane', 'boat'] as const
export type Arrival = (typeof ARRIVALS)[number]

export const ARRIVAL_LABEL: Record<Arrival | 'none', string> = {
  none: 'Chưa chọn',
  motorbike: 'Xe máy',
  car: 'Ô tô',
  bus: 'Xe khách',
  walk: 'Đi bộ',
  train: 'Tàu hoả',
  plane: 'Máy bay',
  boat: 'Thuyền',
}
