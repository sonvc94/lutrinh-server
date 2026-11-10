/**
 * R30 (app docs/04-business-rules.md "Hoàng Sa and Trường Sa labels"): the map never shows Chinese
 * administrative names for Vietnam's Hoàng Sa (Paracel) and Trường Sa (Spratly) archipelagos, and
 * labels both in Vietnamese. A port of the app's `map/SovereigntyLabels.kt` (lists copied as they
 * are) and of the filter in `map/maplibre/SovereigntyLayers.kt`; no maplibre import here, the
 * adapter in `maplibre/` applies it. Keep the lists in step with the app.
 *
 * On every basemap label layer a label whose point lies in one of `AREAS` is hidden when
 * - any of its `NAME_FIELDS` is in `BLOCKED_NAMES`, or
 * - a Vietnamese/Latin name contains a Chinese admin name (`BLOCKED_SUBSTRINGS`), or
 * - (claimants) it is an administrative place label (`ADMIN_CLASSES`) whose `name` is not one of
 *   the Vietnamese units `VIETNAMESE_ADMIN`, or
 * - its local `name` is in a non-Latin script (`name:nonlatin`), unless it is a natural feature
 *   (`NATURAL_CLASSES`) with a Vietnamese `name:vi`, which is what the label shows (`LABEL_FIELD`).
 * Then "Quần đảo Hoàng Sa" / "Quần đảo Trường Sa" are drawn at zoom 3 up to, not including, 11.
 */

export interface Box {
  south: number
  west: number
  north: number
  east: number
}

export interface Archipelago {
  label: string
  at: { lat: number; lng: number }
  area: Box
}

/** Paracels; the box also covers the open sea south and west where the tiles name seamounts in Chinese only. */
export const HOANG_SA: Archipelago = {
  label: 'Quần đảo Hoàng Sa',
  at: { lat: 16.45, lng: 111.95 },
  area: { south: 12.2, west: 110.0, north: 17.4, east: 113.2 },
}

/** Spratlys; east edge 116.3 E keeps Palawan/Balabac and Sabah out. */
export const TRUONG_SA: Archipelago = {
  label: 'Quần đảo Trường Sa',
  at: { lat: 10.0, lng: 114.3 },
  area: { south: 6.8, west: 110.0, north: 12.2, east: 116.3 },
}

export const ARCHIPELAGOS: readonly Archipelago[] = [HOANG_SA, TRUONG_SA]
export const AREAS: readonly Box[] = ARCHIPELAGOS.map((a) => a.area)

export const NAME_FIELDS = [
  'name',
  'name:vi',
  'name:latin',
  'name_en',
  'name:en',
  'name_int',
  'name:zh',
] as const

/** Chinese administrative names over the archipelagos (every script seen in the tiles) and other claimants' Latin names. */
export const BLOCKED_NAMES: readonly string[] = [
  '三沙市', '三沙', 'Tam Sa', 'Thành phố Tam Sa', 'Sansha', 'Sansha City',
  '西沙区', '西沙', 'Quận Tây Sa', 'Tây Sa', 'Xisha', 'Xisha District',
  '南沙区', '南沙', 'Quận Nam Sa', 'Nam Sa', 'Nansha', 'Nansha District',
  '永兴镇', 'Yongxing', '永乐群岛', 'Yongle Qundao', '七连屿', 'Qilianyu', '渚碧岛', 'Zhubi',
  'Kalayaan', 'Pag-asa', 'Pag-asa Island Harbor', 'Rancudo Airfield', 'Layang-Layang',
] // prettier-ignore

/** Chinese admin names that may be embedded in a longer Vietnamese/Latin name ("Hố Rồng (Tam Sa Vĩnh Lạc Long Động)"). */
export const BLOCKED_SUBSTRINGS = [
  'Tam Sa',
  'Tây Sa',
  'Nam Sa',
  'Sansha',
  'Xisha',
  'Nansha',
] as const
export const SUBSTRING_FIELDS = ['name:vi', 'name:latin', 'name_en', 'name:en'] as const

/** `place` classes that are administrative/populated-place labels (not islands or water). */
export const ADMIN_CLASSES: readonly string[] = [
  'country', 'state', 'province', 'region', 'county', 'district', 'municipality', 'city', 'town',
  'village', 'hamlet', 'suburb', 'quarter', 'neighbourhood', 'isolated_dwelling',
] // prettier-ignore

/** The Vietnamese administrative units drawn in the tiles; the only admin names kept. */
export const VIETNAMESE_ADMIN: readonly string[] = [
  'Trường Sa', 'Hoàng Sa', 'An Bang', 'Sinh Tồn', 'Song Tử Tây', 'Thuyền Chài D', 'Thuyền Chài E', 'Đá Tây A',
] // prettier-ignore

/** Natural-feature classes that keep a Vietnamese `name:vi`. */
export const NATURAL_CLASSES: readonly string[] = [
  'island',
  'ocean',
  'sea',
  'bay',
  'strait',
  'lake',
]

export const LABEL_MIN_ZOOM = 3
export const LABEL_MAX_ZOOM = 11

/** Label layers of the OpenFreeMap Positron style (place, road, water, airport names), as the app's `Positron.LABEL_LAYER_PREFIXES`. */
export const LABEL_LAYER_PREFIXES = [
  'label_',
  'water_name',
  'waterway_line_label',
  'highway-name',
  'airport',
] as const

/** Feature properties tried in order for a label: Vietnamese, then Latin script, then local. */
export const LABEL_FIELD = ['name:vi', 'name:latin', 'name'] as const

export function isLabelLayer(layer: { id: string; type: string }): boolean {
  return layer.type === 'symbol' && LABEL_LAYER_PREFIXES.some((p) => layer.id.startsWith(p))
}

export function inAreas(p: { lat: number; lng: number }): boolean {
  return AREAS.some(
    (b) => p.lat >= b.south && p.lat <= b.north && p.lng >= b.west && p.lng <= b.east,
  )
}

type Props = Record<string, unknown>

/** True when a basemap label with these feature `props` at `p` must be hidden (the rule above). */
export function hides(props: Props, p: { lat: number; lng: number }): boolean {
  if (!inAreas(p)) return false
  if (NAME_FIELDS.some((f) => BLOCKED_NAMES.includes(props[f] as string))) return true
  const embedded = SUBSTRING_FIELDS.some((f) => {
    const v = props[f]
    return typeof v === 'string' && BLOCKED_SUBSTRINGS.some((s) => v.includes(s))
  })
  if (embedded) return true
  const cls = props.class as string
  if (ADMIN_CLASSES.includes(cls) && !VIETNAMESE_ADMIN.includes(props.name as string)) return true
  const keptNatural = NATURAL_CLASSES.includes(cls) && props['name:vi'] != null
  return props['name:nonlatin'] != null && !keptNatural
}

/** A MapLibre style expression (plain JSON). */
export type Expr = unknown[]

function boxPolygon(b: Box) {
  return {
    type: 'Polygon',
    coordinates: [
      [
        [b.west, b.south],
        [b.east, b.south],
        [b.east, b.north],
        [b.west, b.north],
        [b.west, b.south],
      ],
    ],
  }
}

const literal = (xs: readonly string[]): Expr => ['literal', [...xs]]

/** `hides()` as a style expression: true for a label to hide. */
export function hiddenExpression(): Expr {
  const inAreasExpr = ['any', ...AREAS.map((b) => ['within', boxPolygon(b)])]
  const blockedName = ['any', ...NAME_FIELDS.map((f) => ['in', ['get', f], literal(BLOCKED_NAMES)])]
  const embedded = [
    'any',
    ...BLOCKED_SUBSTRINGS.flatMap((s) =>
      SUBSTRING_FIELDS.map((f) => ['in', s, ['to-string', ['get', f]]]),
    ),
  ]
  const foreignAdmin = [
    'all',
    ['in', ['get', 'class'], literal(ADMIN_CLASSES)],
    ['!', ['in', ['get', 'name'], literal(VIETNAMESE_ADMIN)]],
  ]
  const keptNatural = [
    'all',
    ['in', ['get', 'class'], literal(NATURAL_CLASSES)],
    ['has', 'name:vi'],
  ]
  return [
    'all',
    inAreasExpr,
    [
      'any',
      blockedName,
      embedded,
      foreignAdmin,
      ['all', ['has', 'name:nonlatin'], ['!', keptNatural]],
    ],
  ]
}

/** A label layer's filter with R30 added: keeps the layer's own filter (an expression) and hides what `hides()` hides. */
export function labelFilter(own: unknown): Expr {
  const shown = ['!', hiddenExpression()]
  return own == null ? shown : ['all', own, shown]
}

/** The text of a label layer: Vietnamese first (`LABEL_FIELD`), as the app. */
export function labelText(): Expr {
  return ['coalesce', ...LABEL_FIELD.map((f) => ['get', f])]
}

/** `ARCHIPELAGOS` as a GeoJSON FeatureCollection of points with a `name` property. */
export function labelsGeoJson() {
  return {
    type: 'FeatureCollection' as const,
    features: ARCHIPELAGOS.map((a) => ({
      type: 'Feature' as const,
      properties: { name: a.label },
      geometry: { type: 'Point' as const, coordinates: [a.at.lng, a.at.lat] },
    })),
  }
}
