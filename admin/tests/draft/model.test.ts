import { describe, expect, it } from 'vitest'
import {
  addStop,
  groupByDay,
  localProblems,
  normalise,
  removeStop,
  reorder,
  totals,
  updateStop,
  type DraftBody,
  type Stop,
} from '../../src/draft/model'

function stop(id: string, day: number, extra: Partial<Stop> = {}): Stop {
  return {
    id,
    day,
    time: null,
    title: id,
    note: '',
    lat: 21,
    lng: 105,
    arrival: null,
    media: [],
    ...extra,
  }
}

function leg(to: string, distanceM = 1000) {
  return {
    to,
    profile: 'motorbike',
    usedProfile: null,
    source: 'routed',
    status: 'ok',
    distanceM,
    durationS: 60,
    path: '',
  }
}

function body(stops: Stop[], legs = stops.slice(1).map((s) => leg(s.id))): DraftBody {
  return {
    title: 'T',
    description: '',
    days: 1,
    cover: null,
    readyMade: null,
    credits: [],
    stops,
    legs,
  }
}

const ids = (b: DraftBody) => b.stops.map((s) => `${s.id}@${s.day}`)

describe('normalise', () => {
  it('fills what an empty draft lacks', () => {
    const b = normalise({ title: 'X', stops: [{ id: 'a', lat: 1, lng: 2 }] })
    expect(b.days).toBe(1)
    expect(b.stops[0]).toMatchObject({ id: 'a', day: 1, time: null, arrival: null, media: [] })
    expect(b.legs).toEqual([])
  })
  it('keeps an arrivalNote and leaves it absent when empty', () => {
    const b = normalise({
      stops: [
        { id: 'a', arrivalNote: '' },
        { id: 'b', arrivalNote: 'Đường dốc khó đi' },
        { id: 'c', arrivalNote: 7 },
      ],
    })
    expect(b.stops.map((s) => 'arrivalNote' in s)).toEqual([false, true, false])
    expect(b.stops[1]?.arrivalNote).toBe('Đường dốc khó đi')
  })
})

describe('updateStop arrivalNote', () => {
  it('sets the note and drops the key when it is cleared', () => {
    const b = body([stop('a', 1), stop('b', 1)])
    const withNote = updateStop(b, 'b', { arrivalNote: 'Gửi xe phía đối diện, 30k' })
    expect(withNote.stops[1]?.arrivalNote).toBe('Gửi xe phía đối diện, 30k')
    const cleared = updateStop(withNote, 'b', { arrivalNote: undefined })
    expect('arrivalNote' in (cleared.stops[1] as Stop)).toBe(false)
    expect(JSON.stringify(cleared)).toBe(JSON.stringify(b))
  })
  it('keeps the note on the stop when stops are reordered', () => {
    const b = body([stop('a', 1), stop('b', 1, { arrivalNote: 'dốc' }), stop('c', 1)])
    const r = reorder(b, 'b', 'c')
    expect(r.stops.map((s) => s.arrivalNote ?? null)).toEqual([null, null, 'dốc'])
  })
})

describe('addStop', () => {
  it('puts the new stop after the selected one, on its day, rounded to 6 decimals', () => {
    const b = body([stop('a', 1), stop('b', 2)])
    const r = addStop(b, { lng: 105.12345678, lat: 21.987654321 }, 'a', () => 0.5)
    expect(ids(r.body)).toEqual(['a@1', `${r.id}@1`, 'b@2'])
    expect(r.body.stops[1]).toMatchObject({ lat: 21.987654, lng: 105.123457 })
  })
  it('appends when nothing is selected', () => {
    const r = addStop(body([stop('a', 1)]), { lng: 1, lat: 2 }, null)
    expect(r.body.stops.at(-1)?.id).toBe(r.id)
  })
})

describe('reorder', () => {
  const b = body([stop('a', 1), stop('b', 1), stop('c', 2), stop('d', 2)])
  it('moves down onto a stop: lands after it and takes its day', () => {
    expect(ids(reorder(b, 'a', 'c'))).toEqual(['b@1', 'c@2', 'a@2', 'd@2'])
  })
  it('moves up onto a stop: lands before it', () => {
    expect(ids(reorder(b, 'd', 'b'))).toEqual(['a@1', 'd@1', 'b@1', 'c@2'])
  })
  it('onto a day header: last stop of that day', () => {
    expect(ids(reorder(b, 'a', 'day:2'))).toEqual(['b@1', 'c@2', 'd@2', 'a@2'])
    expect(ids(reorder(b, 'd', 'day:1'))).toEqual(['a@1', 'b@1', 'd@1', 'c@2'])
  })
  it('onto a new empty day raises the day count', () => {
    const r = reorder(b, 'd', 'day:3')
    expect(ids(r)).toEqual(['a@1', 'b@1', 'c@2', 'd@3'])
    expect(r.days).toBe(3)
  })
  it('ignores unknown targets', () => {
    expect(reorder(b, 'a', 'zz')).toBe(b)
    expect(reorder(b, 'a', 'day:0')).toBe(b)
  })
})

describe('removeStop', () => {
  it('drops the leg into it and the cover it held', () => {
    const b = {
      ...body([stop('a', 1), stop('b', 1, { media: ['m1'] }), stop('c', 1)]),
      cover: 'm1',
    }
    const r = removeStop(b, 'b')
    expect(r.stops.map((s) => s.id)).toEqual(['a', 'c'])
    expect(r.legs.map((l) => l.to)).toEqual(['c'])
    expect(r.cover).toBeNull()
  })
})

describe('groupByDay and totals', () => {
  it('has a group for every day, empty ones too', () => {
    const b = { ...body([stop('a', 1), stop('b', 3)]), days: 4 }
    expect(groupByDay(b).map((g) => [g.day, g.stops.map((s) => s.stop.id)])).toEqual([
      [1, ['a']],
      [2, []],
      [3, ['b']],
      [4, []],
    ])
  })
  it('sums leg distances', () => {
    const b = body([stop('a', 1), stop('b', 1), stop('c', 2)], [leg('b', 1500), leg('c', 2500)])
    expect(totals(b)).toEqual({ stops: 3, days: 2, distanceM: 4000 })
  })
})

describe('localProblems', () => {
  it('reports untitled stops, days going back and times going back within a day', () => {
    const b = body([
      stop('a', 2, { time: '09:00' }),
      stop('b', 1, { title: ' ' }),
      stop('c', 2, { time: '10:00' }),
      stop('d', 2, { time: '08:00' }),
    ])
    const p = localProblems(b)
    expect(p).toContain('Điểm 2 chưa có tên.')
    expect(p).toContain('Điểm 2: ngày 1 sau ngày 2.')
    expect(p).toContain('Điểm 4: 08:00 sớm hơn 10:00.')
  })
  it('reports an arrivalNote on the first stop', () => {
    const b = body([stop('a', 1, { arrivalNote: 'dốc' }), stop('b', 1)])
    expect(localProblems(b)).toEqual([
      'Điểm xuất phát không có chặng đến: hãy xóa ghi chú chặng của điểm 1.',
    ])
  })
  it('is empty for a good route', () => {
    expect(localProblems(body([stop('a', 1), stop('b', 1), stop('c', 2)]))).toEqual([])
  })
})
