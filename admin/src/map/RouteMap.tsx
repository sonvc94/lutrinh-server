/** The editor map as a React component; it only calls MapAdapter (page 04 §F). */
import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { LngLat } from '../draft/model'
import { VIETNAM_CENTER } from './basemap/openfreemap'
import type { Bounds, LegLine, MapAdapter, MapAdapterFactory, StopPin } from './MapAdapter'
import css from './RouteMap.module.css'

const defaultFactory: MapAdapterFactory = () =>
  import('./maplibre').then((m) => m.createMapLibreAdapter())

export const MapAdapterContext = createContext<MapAdapterFactory>(defaultFactory)

export interface RouteMapProps {
  pins: StopPin[]
  lines: LegLine[]
  selectedId?: string | undefined
  selectedLegTo?: string | undefined
  sketch?: LngLat[] | null
  /** Pins draggable (off while sketching a leg). */
  draggable?: boolean
  /** Fit the view when this changes (first load, a new route). */
  fit?: { key: string; bounds: Bounds | null }
  onMapClick?: (p: LngLat) => void
  onPinClick?: (id: string) => void
  onPinDrag?: (id: string, p: LngLat) => void
  className?: string
}

export function RouteMap(props: RouteMapProps) {
  const factory = useContext(MapAdapterContext)
  const el = useRef<HTMLDivElement>(null)
  const [adapter, setAdapter] = useState<MapAdapter | null>(null)
  const [failed, setFailed] = useState(false)
  const cbs = useRef(props)
  useLayoutEffect(() => {
    cbs.current = props
  })

  useEffect(() => {
    let live = true
    let made: MapAdapter | null = null
    factory()
      .then((a) => {
        if (!live || !el.current) return
        a.mount(el.current, { basemap: 'openfreemap', center: VIETNAM_CENTER, zoom: 6 })
        made = a
        setAdapter(a)
      })
      .catch(() => live && setFailed(true))
    return () => {
      live = false
      made?.destroy()
    }
  }, [factory])

  useEffect(() => {
    if (!adapter) return
    const offs = [
      adapter.onMapClick((p) => cbs.current.onMapClick?.(p)),
      adapter.onPinClick((id) => cbs.current.onPinClick?.(id)),
      adapter.onPinDrag((id, p) => cbs.current.onPinDrag?.(id, p)),
    ]
    return () => offs.forEach((off) => off())
  }, [adapter])

  useEffect(() => {
    adapter?.setStops(props.pins, props.selectedId)
  }, [adapter, props.pins, props.selectedId])

  useEffect(() => {
    adapter?.setLegs(props.lines, props.selectedLegTo)
  }, [adapter, props.lines, props.selectedLegTo])

  useEffect(() => {
    adapter?.setSketch(props.sketch ?? null)
  }, [adapter, props.sketch])

  useEffect(() => {
    adapter?.setPinsDraggable(props.draggable ?? true)
  }, [adapter, props.draggable])

  const fitKey = props.fit?.key
  useEffect(() => {
    const b = cbs.current.fit?.bounds
    if (adapter && b) adapter.fitTo(b, 64)
  }, [adapter, fitKey])

  return (
    <div className={`${css.wrap} ${props.className ?? ''}`} data-testid="route-map">
      <div ref={el} className={css.map} />
      {failed && <div className={css.failed}>Không tải được bản đồ.</div>}
    </div>
  )
}
