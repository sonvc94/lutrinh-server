/** Encoded polyline, precision 6 (`polyline6`, as in the package `legs[].path`, spec/README). */
import type { LngLat } from '../draft/model'

export function decode(path: string, precision = 6): LngLat[] {
  const factor = 10 ** precision
  const out: LngLat[] = []
  let i = 0
  let lat = 0
  let lng = 0
  const next = (): number => {
    let result = 0
    let shift = 0
    let b: number
    do {
      if (i >= path.length) throw new Error('truncated polyline')
      b = path.charCodeAt(i++) - 63
      result |= (b & 0x1f) << shift
      shift += 5
    } while (b >= 0x20)
    return result & 1 ? ~(result >> 1) : result >> 1
  }
  while (i < path.length) {
    lat += next()
    lng += next()
    out.push({ lat: lat / factor, lng: lng / factor })
  }
  return out
}

function encodeValue(v: number): string {
  let x = v < 0 ? ~(v << 1) : v << 1
  let s = ''
  while (x >= 0x20) {
    s += String.fromCharCode((0x20 | (x & 0x1f)) + 63)
    x >>>= 5
  }
  return s + String.fromCharCode(x + 63)
}

export function encode(points: LngLat[], precision = 6): string {
  const factor = 10 ** precision
  let lat = 0
  let lng = 0
  let s = ''
  for (const p of points) {
    const la = Math.round(p.lat * factor)
    const ln = Math.round(p.lng * factor)
    s += encodeValue(la - lat) + encodeValue(ln - lng)
    lat = la
    lng = ln
  }
  return s
}
