// @vitest-environment node
/**
 * R30 on the admin map: the rule (`hides`, the app's SovereigntyLabelsTest cases) and the style
 * filter the adapter sets on every label layer, evaluated by MapLibre's own filter engine
 * (`@maplibre/maplibre-gl-style-spec`, the code maplibre-gl runs) on features placed in tiles.
 */
import { featureFilter } from '@maplibre/maplibre-gl-style-spec'
import positronLayers from './positron-label-layers.json'
import { describe, expect, it } from 'vitest'
import {
  HOANG_SA,
  TRUONG_SA,
  hides,
  isLabelLayer,
  labelFilter,
  labelsGeoJson,
  labelText,
} from '../../src/map/sovereignty'

type P = { lat: number; lng: number }
type Props = Record<string, string | number>

const PARACEL: P = { lat: 16.83, lng: 112.33 } // Phú Lâm / Woody Island
const SPRATLY: P = { lat: 10.38, lng: 114.36 } // Ba Bình / Itu Aba
const OUTSIDE_GUANGZHOU: P = { lat: 22.8, lng: 113.5 }
const PALAWAN: P = { lat: 9.8, lng: 118.7 }

const EXTENT = 8192
const Z = 8

/** The feature as maplibre's worker sees it: tile id + point in tile coordinates. */
function tileFeature(props: Props, p: P) {
  const n = 2 ** Z
  const x = ((p.lng + 180) / 360) * n
  const lat = (p.lat * Math.PI) / 180
  const y = ((1 - Math.log(Math.tan(lat) + 1 / Math.cos(lat)) / Math.PI) / 2) * n
  const canonical = { z: Z, x: Math.floor(x), y: Math.floor(y) }
  const pt = {
    x: Math.round((x - canonical.x) * EXTENT),
    y: Math.round((y - canonical.y) * EXTENT),
  }
  return { feature: { type: 1 as const, properties: props, geometry: [[pt]] }, canonical }
}

/** True when the label stays on the map with R30's filter added to `own`. */
function shown(props: Props, p: P, own: unknown = null): boolean {
  const f = featureFilter(labelFilter(own) as never, 'layers[0].filter')
  const { feature, canonical } = tileFeature(props, p)
  return f.filter({ zoom: Z }, feature as never, canonical as never)
}

const CASES: [string, Props, P, boolean][] = [
  ['Chinese city in both scripts', { class: 'city', name: '三沙市', 'name:vi': 'Tam Sa', 'name:nonlatin': '三沙市' }, PARACEL, true],
  ['district by Latin name', { class: 'district', name: 'Xisha', 'name:latin': 'Xisha' }, PARACEL, true],
  ['town 永兴镇', { class: 'town', name: '永兴镇', 'name:nonlatin': '永兴镇' }, PARACEL, true],
  ['Chinese village not in the list', { class: 'village', name: '甘泉社区', 'name:vi': 'Xã khu Cam Tuyền', 'name:nonlatin': '甘泉社区' }, PARACEL, true],
  ['Chinese airport (non-Latin, not natural)', { class: 'airport', name: '三沙永兴机场', 'name:vi': 'Sân bay Tam Sa Vĩnh Hưng', 'name:nonlatin': '三沙永兴机场' }, PARACEL, true],
  ['embedded Tam Sa in a water name', { class: 'sea', name: 'Dragon Hole', 'name:vi': 'Hố Rồng (Tam Sa Vĩnh Lạc Long Động)' }, PARACEL, true],
  ['Chinese-only seamount', { class: 'strait', name: '晋卿西海山', 'name:nonlatin': '晋卿西海山' }, { lat: 15.3, lng: 112.5 }, true],
  ['Philippine municipality Kalayaan', { class: 'municipality', name: 'Kalayaan' }, SPRATLY, true],
  ['quarter Pag-asa', { class: 'quarter', name: 'Pag-asa' }, SPRATLY, true],
  ['Malaysian village (any foreign admin)', { class: 'village', name: 'Kampung Terumbu' }, SPRATLY, true],
  ['Rancudo Airfield', { class: 'airport', name: 'Rancudo Airfield' }, SPRATLY, true],
  ['Vietnamese admin Trường Sa', { class: 'town', name: 'Trường Sa' }, SPRATLY, false],
  ['Vietnamese admin Song Tử Tây', { class: 'village', name: 'Song Tử Tây' }, SPRATLY, false],
  ['island with name:vi (永兴岛 → Đảo Phú Lâm)', { class: 'island', name: '永兴岛', 'name:vi': 'Đảo Phú Lâm', 'name:nonlatin': '永兴岛' }, PARACEL, false],
  ['island with name:vi (太平島 → Đảo Thái Bình)', { class: 'island', name: '太平島', 'name:vi': 'Đảo Thái Bình', 'name:nonlatin': '太平島' }, SPRATLY, false],
  ['Vietnamese harbour', { class: 'harbor', name: 'Âu tàu Trường Sa' }, SPRATLY, false],
  ['Sân bay Trường Sa', { class: 'airport', name: 'Sân bay Trường Sa' }, SPRATLY, false],
  ['outside: Guangzhou 南沙区 keeps its label', { class: 'district', name: '南沙区', 'name:nonlatin': '南沙区' }, OUTSIDE_GUANGZHOU, false],
  ['outside: Palawan town', { class: 'town', name: 'Puerto Princesa' }, PALAWAN, false],
] // prettier-ignore

describe('R30 rule', () => {
  it.each(CASES)('%s', (_name, props, p, hidden) => {
    expect(hides(props, p)).toBe(hidden)
  })

  it('our labels lie in their areas, in Vietnamese only', () => {
    for (const a of [HOANG_SA, TRUONG_SA]) {
      expect(a.at.lat).toBeGreaterThan(a.area.south)
      expect(a.at.lat).toBeLessThan(a.area.north)
      expect(a.at.lng).toBeGreaterThan(a.area.west)
      expect(a.at.lng).toBeLessThan(a.area.east)
    }
    expect(labelsGeoJson().features.map((f) => f.properties.name)).toEqual([
      'Quần đảo Hoàng Sa',
      'Quần đảo Trường Sa',
    ])
  })
})

describe('R30 style filter (maplibre filter engine)', () => {
  it.each(CASES)('%s: the filter is the same rule', (_name, props, p, hidden) => {
    expect(shown(props, p)).toBe(!hidden)
  })

  it("keeps the layer's own filter", () => {
    const own = ['==', ['get', 'class'], 'town']
    expect(shown({ class: 'town', name: 'Trường Sa' }, SPRATLY, own)).toBe(true)
    expect(shown({ class: 'village', name: 'Song Tử Tây' }, SPRATLY, own)).toBe(false)
    expect(shown({ class: 'town', name: 'Kalayaan' }, SPRATLY, own)).toBe(false)
  })

  it('covers every label layer of OpenFreeMap Positron, whose filters it wraps without breaking', () => {
    const labels = positronLayers.filter(isLabelLayer)
    expect(labels.map((l) => l.id)).toEqual([
      'waterway_line_label',
      'water_name_point_label',
      'water_name_line_label',
      'highway-name-path',
      'highway-name-minor',
      'highway-name-major',
      'airport',
      'label_other',
      'label_village',
      'label_town',
      'label_state',
      'label_city',
      'label_city_capital',
      'label_country_3',
      'label_country_2',
      'label_country_1',
    ]) // prettier-ignore — the app's Positron.LABEL_LAYER_IDS
    const city = labels.find((l) => l.id === 'label_city')
    const { feature, canonical } = tileFeature(
      { class: 'city', name: '三沙市', capital: 0 },
      PARACEL,
    )
    const f = featureFilter(labelFilter(city?.filter) as never, 'layers[0].filter')
    expect(f.filter({ zoom: Z }, feature as never, canonical as never)).toBe(false)
    const hanoi = tileFeature(
      { class: 'city', name: 'Hà Nội', capital: 0 },
      { lat: 21.03, lng: 105.85 },
    )
    expect(f.filter({ zoom: Z }, hanoi.feature as never, hanoi.canonical as never)).toBe(true)
  })

  it('shows Vietnamese first', () => {
    expect(labelText()).toEqual([
      'coalesce',
      ['get', 'name:vi'],
      ['get', 'name:latin'],
      ['get', 'name'],
    ])
  })
})
