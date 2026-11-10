import { describe, expect, it } from 'vitest'
import sample from '../../../spec/samples/ha-giang-4n/route.json'
import { decode, encode } from '../../src/map/polyline'

describe('polyline', () => {
  it('reads the reference example (precision 5)', () => {
    const pts = decode('_p~iF~ps|U_ulLnnqC_mqNvxq`@', 5)
    expect(pts).toEqual([
      { lat: 38.5, lng: -120.2 },
      { lat: 40.7, lng: -120.95 },
      { lat: 43.252, lng: -126.453 },
    ])
    expect(encode(pts, 5)).toBe('_p~iF~ps|U_ulLnnqC_mqNvxq`@')
  })

  it('reads every leg of the spec sample: from stop to stop, and writes the same bytes back', () => {
    const stops = new Map(sample.stops.map((s) => [s.id, s]))
    const ids = sample.stops.map((s) => s.id)
    for (const leg of sample.legs) {
      if (!leg.path) continue
      const pts = decode(leg.path)
      expect(encode(pts)).toBe(leg.path)
      const to = stops.get(leg.to)!
      const from = stops.get(ids[ids.indexOf(leg.to) - 1]!)!
      const near = (a: { lat: number; lng: number }, b: { lat: number; lng: number }) =>
        Math.abs(a.lat - b.lat) < 0.01 && Math.abs(a.lng - b.lng) < 0.01
      expect(near(pts[0]!, from)).toBe(true)
      expect(near(pts.at(-1)!, to)).toBe(true)
    }
  })

  it('refuses a truncated line', () => {
    expect(() => decode('_p~iF~ps|U_')).toThrow()
  })
})
