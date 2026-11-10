/**
 * The map interface (page 04 §F, like the app's R35): the editor only talks to this. It knows
 * nothing about MapLibre; src/map/maplibre/ is the one place that imports maplibre-gl (ESLint
 * `no-restricted-imports`). Another library or provider = another adapter.
 */
import type { LngLat } from '../draft/model'

export type { LngLat }
export type Unsubscribe = () => void
export type BasemapId = 'openfreemap'

export interface Bounds {
  south: number
  west: number
  north: number
  east: number
}

export interface StopPin {
  id: string
  at: LngLat
  /** Number shown in the pin (1-based position). */
  label: string
  /** start: Trail disc · step: Waypoint disc · end: Forest disc (docs/08 §2 Map). */
  kind: 'start' | 'step' | 'end'
  title: string
}

/** How a leg is drawn: by stroke, never by hue (docs/08 "Leg mode"). */
export type LegStroke = 'solid' | 'dots' | 'dashed' | 'straight'

export interface LegLine {
  to: string
  path: LngLat[]
  stroke: LegStroke
}

export interface MountOptions {
  basemap: BasemapId
  center: LngLat
  zoom: number
}

export interface MapAdapter {
  mount(el: HTMLElement, o: MountOptions): void
  setStops(stops: StopPin[], selectedId?: string): void
  /** One orange line, stroke by mode; `selectedTo` drawn SignalDeep and wider. */
  setLegs(legs: LegLine[], selectedTo?: string): void
  /** The hand-drawn leg being sketched ("Vẽ tay"), or null. */
  setSketch(points: LngLat[] | null): void
  /** Pins can be dragged (false while sketching). */
  setPinsDraggable(on: boolean): void
  fitTo(b: Bounds, paddingPx: number): void
  onMapClick(cb: (p: LngLat) => void): Unsubscribe
  onPinClick(cb: (id: string) => void): Unsubscribe
  onPinDrag(cb: (id: string, p: LngLat) => void): Unsubscribe
  destroy(): void
}

export type MapAdapterFactory = () => Promise<MapAdapter>

export function boundsOf(points: LngLat[]): Bounds | null {
  if (!points.length) return null
  let south = 90
  let west = 180
  let north = -90
  let east = -180
  for (const p of points) {
    south = Math.min(south, p.lat)
    north = Math.max(north, p.lat)
    west = Math.min(west, p.lng)
    east = Math.max(east, p.lng)
  }
  return { south, west, north, east }
}
