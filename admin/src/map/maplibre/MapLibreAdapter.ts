/** The MapLibre GL JS adapter: the only module importing maplibre-gl (page 04 §F). */
import 'maplibre-gl/dist/maplibre-gl.css'
import {
  AttributionControl,
  LngLatBounds,
  Map as MlMap,
  Marker,
  NavigationControl,
  setWorkerUrl,
} from 'maplibre-gl'
import type { GeoJSONSource } from 'maplibre-gl'
// maplibre-gl 6 starts its worker from a sibling file next to its own module; the bundle has no
// such file (the request fell through to index.html: "Worker failed to load", no tiles, no lines).
// Emit the self-contained worker as an asset and point maplibre at it.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { OPENFREEMAP_CREDIT, OPENFREEMAP_STYLE, TOPO_PAINT } from '../basemap/openfreemap'
import {
  LABEL_MAX_ZOOM,
  LABEL_MIN_ZOOM,
  isLabelLayer,
  labelFilter,
  labelsGeoJson,
  labelText,
} from '../sovereignty'
import type {
  Bounds,
  LegLine,
  LngLat,
  MapAdapter,
  MountOptions,
  StopPin,
  Unsubscribe,
} from '../MapAdapter'
import type { Feature as GFeature, FeatureCollection, LineString, Point } from 'geojson'
import css from './pins.module.css'

setWorkerUrl(workerUrl)

const SIGNAL = '#E4572E'
const SIGNAL_DEEP = '#B83A16'
const FOREST = '#1F2A24'
const PIN_CLASS = 'lt-pin'
const SOVEREIGNTY_SOURCE = 'r30-archipelagos'
const SOVEREIGNTY_LAYER = 'r30-archipelago-labels'

type Feature = GFeature<LineString | Point>

function line(path: LngLat[], props: Record<string, unknown>): Feature {
  return {
    type: 'Feature',
    properties: props,
    geometry: { type: 'LineString', coordinates: path.map((p) => [p.lng, p.lat]) },
  }
}

export class MapLibreAdapter implements MapAdapter {
  private map: MlMap | null = null
  private ready = false
  private markers = new Map<string, { marker: Marker; el: HTMLDivElement; root: HTMLDivElement }>()
  private clickCbs = new Set<(p: LngLat) => void>()
  private pinClickCbs = new Set<(id: string) => void>()
  private dragCbs = new Set<(id: string, p: LngLat) => void>()
  private legs: { legs: LegLine[]; selected: string | undefined } = {
    legs: [],
    selected: undefined,
  }
  private sketch: LngLat[] | null = null
  private draggable = true

  mount(el: HTMLElement, o: MountOptions): void {
    const map = new MlMap({
      container: el,
      style: OPENFREEMAP_STYLE,
      center: [o.center.lng, o.center.lat],
      zoom: o.zoom,
      attributionControl: false,
    })
    map.addControl(new AttributionControl({ compact: true, customAttribution: OPENFREEMAP_CREDIT }))
    map.addControl(new NavigationControl({ showCompass: false }), 'bottom-right')
    map.on('load', () => {
      this.restyle(map)
      this.applySovereignty(map)
      this.addOverlay(map)
      this.ready = true
      this.drawLegs()
      this.drawSketch()
    })
    map.on('click', (e) => {
      const target = e.originalEvent.target as Element | null
      if (target?.closest(`.${PIN_CLASS}`)) return
      this.clickCbs.forEach((cb) => cb({ lng: e.lngLat.lng, lat: e.lngLat.lat }))
    })
    this.map = map
  }

  private restyle(map: MlMap): void {
    for (const layer of map.getStyle().layers ?? []) {
      const id = layer.id
      try {
        if (layer.type === 'background')
          map.setPaintProperty(id, 'background-color', TOPO_PAINT.background)
        else if (layer.type === 'fill' && /water/.test(id))
          map.setPaintProperty(id, 'fill-color', TOPO_PAINT.water)
        else if (layer.type === 'fill' && /park|wood|forest|grass|landcover/.test(id))
          map.setPaintProperty(id, 'fill-color', TOPO_PAINT.vegetation)
        else if (layer.type === 'fill' && /residential|landuse/.test(id))
          map.setPaintProperty(id, 'fill-color', TOPO_PAINT.residential)
        else if (layer.type === 'fill' && /building/.test(id))
          map.setPaintProperty(id, 'fill-color', TOPO_PAINT.building)
        else if (layer.type === 'symbol') {
          map.setPaintProperty(id, 'text-color', TOPO_PAINT.label)
          map.setPaintProperty(id, 'text-halo-color', TOPO_PAINT.halo)
        }
      } catch {
        // a layer without that paint property: keep the basemap's own value
      }
    }
  }

  /**
   * R30 (`../sovereignty.ts`, as the app's SovereigntyLayers.kt): every label layer shows
   * Vietnamese names first and hides the labels the rule hides; then our two archipelago labels
   * go on top of the basemap, below the route layers added after.
   */
  private applySovereignty(map: MlMap): void {
    for (const layer of map.getStyle().layers ?? []) {
      if (!isLabelLayer(layer)) continue
      map.setLayoutProperty(layer.id, 'text-field', labelText() as never)
      map.setFilter(layer.id, labelFilter(map.getFilter(layer.id)) as never)
    }
    map.addSource(SOVEREIGNTY_SOURCE, { type: 'geojson', data: labelsGeoJson() })
    map.addLayer({
      id: SOVEREIGNTY_LAYER,
      type: 'symbol',
      source: SOVEREIGNTY_SOURCE,
      minzoom: LABEL_MIN_ZOOM,
      maxzoom: LABEL_MAX_ZOOM,
      layout: {
        'text-field': ['get', 'name'],
        'text-font': ['Noto Sans Italic'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 4, 11, 8, 14],
        'text-letter-spacing': 0.05,
        'text-max-width': 7,
        'text-allow-overlap': true,
      },
      paint: {
        'text-color': TOPO_PAINT.label,
        'text-halo-color': TOPO_PAINT.halo,
        'text-halo-width': 1.2,
      },
    })
  }

  private addOverlay(map: MlMap): void {
    const empty: FeatureCollection = { type: 'FeatureCollection', features: [] }
    map.addSource('lt-legs', { type: 'geojson', data: empty })
    map.addSource('lt-sketch', { type: 'geojson', data: empty })
    const width = ['case', ['get', 'selected'], 7, 5] as unknown as number
    const color = ['case', ['get', 'selected'], SIGNAL_DEEP, SIGNAL] as unknown as string
    map.addLayer({
      id: 'lt-legs-casing',
      type: 'line',
      source: 'lt-legs',
      filter: ['!=', ['get', 'stroke'], 'straight'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#FFFFFF', 'line-width': ['case', ['get', 'selected'], 11, 9] },
    })
    map.addLayer({
      id: 'lt-legs-solid',
      type: 'line',
      source: 'lt-legs',
      filter: ['==', ['get', 'stroke'], 'solid'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': color, 'line-width': width },
    })
    map.addLayer({
      id: 'lt-legs-dots',
      type: 'line',
      source: 'lt-legs',
      filter: ['==', ['get', 'stroke'], 'dots'],
      layout: { 'line-cap': 'round' },
      paint: { 'line-color': color, 'line-width': width, 'line-dasharray': [0.1, 2] },
    })
    map.addLayer({
      id: 'lt-legs-dashed',
      type: 'line',
      source: 'lt-legs',
      filter: ['==', ['get', 'stroke'], 'dashed'],
      paint: { 'line-color': color, 'line-width': width, 'line-dasharray': [2, 1.5] },
    })
    // A road leg with no line yet: a thin dashed straight line (the leg is still to compute).
    map.addLayer({
      id: 'lt-legs-straight',
      type: 'line',
      source: 'lt-legs',
      filter: ['==', ['get', 'stroke'], 'straight'],
      paint: {
        'line-color': FOREST,
        'line-width': 2,
        'line-opacity': 0.5,
        'line-dasharray': [2, 2],
      },
    })
    map.addLayer({
      id: 'lt-sketch-line',
      type: 'line',
      source: 'lt-sketch',
      paint: { 'line-color': SIGNAL_DEEP, 'line-width': 3, 'line-dasharray': [1, 1] },
    })
    map.addLayer({
      id: 'lt-sketch-points',
      type: 'circle',
      source: 'lt-sketch',
      filter: ['==', ['geometry-type'], 'Point'],
      paint: {
        'circle-radius': 5,
        'circle-color': '#FFFFFF',
        'circle-stroke-color': SIGNAL_DEEP,
        'circle-stroke-width': 2,
      },
    })
  }

  setStops(stops: StopPin[], selectedId?: string): void {
    const map = this.map
    if (!map) return
    const seen = new Set<string>()
    for (const s of stops) {
      seen.add(s.id)
      let m = this.markers.get(s.id)
      if (!m) {
        // maplibre owns the root's classes (maplibregl-marker: position) and its transform;
        // our look goes on an inner element, or the pins drift out of place
        const root = document.createElement('div')
        root.classList.add(PIN_CLASS)
        const el = document.createElement('div')
        root.append(el)
        root.addEventListener('click', (ev) => {
          ev.stopPropagation()
          this.pinClickCbs.forEach((cb) => cb(s.id))
        })
        const marker = new Marker({ element: root, draggable: this.draggable })
          .setLngLat([s.at.lng, s.at.lat])
          .addTo(map)
        marker.on('dragend', () => {
          const p = marker.getLngLat()
          this.dragCbs.forEach((cb) => cb(s.id, { lng: p.lng, lat: p.lat }))
        })
        m = { marker, el, root }
        this.markers.set(s.id, m)
      }
      m.marker.setLngLat([s.at.lng, s.at.lat])
      const cls = [css.pin, css[s.kind]]
      if (s.id === selectedId) cls.push(css.selected)
      m.el.className = cls.filter(Boolean).join(' ')
      m.el.textContent = s.label
      m.root.title = s.title
      m.root.setAttribute('data-stop', s.id)
    }
    for (const [id, m] of this.markers) {
      if (!seen.has(id)) {
        m.marker.remove()
        this.markers.delete(id)
      }
    }
  }

  setPinsDraggable(on: boolean): void {
    this.draggable = on
    this.markers.forEach((m) => m.marker.setDraggable(on))
  }

  setLegs(legs: LegLine[], selectedTo?: string): void {
    this.legs = { legs, selected: selectedTo }
    this.drawLegs()
  }

  private drawLegs(): void {
    if (!this.ready || !this.map) return
    const src = this.map.getSource('lt-legs') as GeoJSONSource | undefined
    src?.setData({
      type: 'FeatureCollection',
      features: this.legs.legs
        .filter((l) => l.path.length >= 2)
        .map((l) =>
          line(l.path, { to: l.to, stroke: l.stroke, selected: l.to === this.legs.selected }),
        ),
    })
  }

  setSketch(points: LngLat[] | null): void {
    this.sketch = points
    this.drawSketch()
  }

  private drawSketch(): void {
    if (!this.ready || !this.map) return
    const src = this.map.getSource('lt-sketch') as GeoJSONSource | undefined
    const pts = this.sketch ?? []
    const features: Feature[] = pts.map((p) => ({
      type: 'Feature',
      properties: {},
      geometry: { type: 'Point', coordinates: [p.lng, p.lat] },
    }))
    if (pts.length >= 2) features.push(line(pts, {}))
    src?.setData({ type: 'FeatureCollection', features })
  }

  fitTo(b: Bounds, paddingPx: number): void {
    if (!this.map) return
    const bounds = new LngLatBounds([b.west, b.south], [b.east, b.north])
    this.map.fitBounds(bounds, { padding: paddingPx, maxZoom: 13, duration: 0 })
  }

  onMapClick(cb: (p: LngLat) => void): Unsubscribe {
    this.clickCbs.add(cb)
    return () => this.clickCbs.delete(cb)
  }

  onPinClick(cb: (id: string) => void): Unsubscribe {
    this.pinClickCbs.add(cb)
    return () => this.pinClickCbs.delete(cb)
  }

  onPinDrag(cb: (id: string, p: LngLat) => void): Unsubscribe {
    this.dragCbs.add(cb)
    return () => this.dragCbs.delete(cb)
  }

  destroy(): void {
    this.markers.forEach((m) => m.marker.remove())
    this.markers.clear()
    this.map?.remove()
    this.map = null
    this.ready = false
  }
}
