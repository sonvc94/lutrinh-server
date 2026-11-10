import { describe, expect, it } from 'vitest'
import schema from '../../../spec/route.schema.json'
import { LIMITS } from '../../src/draft/limits'
import { stopSchema } from '../../src/editor/stopForm'

describe('LIMITS from spec/route.schema.json', () => {
  it('reads every limit as a number', () => {
    for (const [k, v] of Object.entries(LIMITS))
      if (k !== 'timePattern') expect(typeof v, k).toBe('number')
    expect(JSON.stringify(schema)).toContain(String(LIMITS.stopTitle))
  })
  it('drive the stop form', () => {
    const ok = { title: 'Cột cờ Lũng Cú', time: '07:30', day: 1, arrival: 'motorbike', note: '' }
    expect(stopSchema.safeParse(ok).success).toBe(true)
    expect(stopSchema.safeParse({ ...ok, title: 'x'.repeat(LIMITS.stopTitle + 1) }).success).toBe(
      false,
    )
    expect(stopSchema.safeParse({ ...ok, time: '7h30' }).success).toBe(false)
    expect(stopSchema.safeParse({ ...ok, day: LIMITS.daysMax + 1 }).success).toBe(false)
    expect(stopSchema.safeParse({ ...ok, arrival: 'rocket' }).success).toBe(false)
  })
})
