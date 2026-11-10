import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../src/api/errors'
import type { DraftBody, Leg } from '../../src/draft/model'
import { DraftSaver, rebaseLegs, type ServerDraft } from '../../src/draft/saver'

const stopA = {
  id: 'a',
  day: 1,
  time: null,
  title: 'A',
  note: '',
  lat: 21,
  lng: 105,
  arrival: null,
  media: [],
}
const stopB = { ...stopA, id: 'b', title: 'B', lat: 22 }
const legB: Leg = {
  to: 'b',
  profile: 'motorbike',
  usedProfile: null,
  source: 'routed',
  status: 'ok',
  distanceM: 5000,
  durationS: 600,
  path: 'abc',
}

function base(extra: Partial<DraftBody> = {}): DraftBody {
  return {
    title: 'T',
    description: '',
    days: 1,
    cover: null,
    readyMade: null,
    credits: [],
    stops: [stopA, stopB],
    legs: [],
    ...extra,
  }
}

function server(revision: number, body: DraftBody, queuedJobs: number[] = []): ServerDraft {
  return {
    revision,
    etag: `"r${revision}"`,
    body: body as unknown as Record<string, unknown>,
    queuedJobs,
  }
}

const conflict = () => new ApiError(412, { error: { code: 'draft_changed', retryAfterS: null } })

describe('DraftSaver', () => {
  it('saves an edit with the If-Match of the last read and takes the new ETag', async () => {
    const put = vi.fn(async (b: DraftBody, etag: string) =>
      server(Number(etag.slice(2, -1)) + 1, b),
    )
    const s = new DraftSaver(server(1, base()), put, vi.fn(), 0)
    s.edit((b) => ({ ...b, title: 'Mới' }))
    await s.flush()
    expect(put).toHaveBeenCalledTimes(1)
    expect(put.mock.calls[0]?.[1]).toBe('"r1"')
    expect(s.snapshot).toMatchObject({ status: 'saved', etag: '"r2"', revision: 2 })
    expect(s.snapshot.body.title).toBe('Mới')
  })

  it('does not save an edit that changes nothing', async () => {
    const put = vi.fn()
    const s = new DraftSaver(server(1, base()), put, vi.fn(), 0)
    s.edit((b) => ({ ...b }))
    await s.flush()
    expect(put).not.toHaveBeenCalled()
    expect(s.snapshot.canUndo).toBe(false)
  })

  it('sends edits made during a save in the next PUT', async () => {
    let release: () => void = () => {}
    const bodies: string[] = []
    const put = vi.fn(async (b: DraftBody, etag: string) => {
      bodies.push(b.title)
      if (bodies.length === 1) await new Promise<void>((r) => (release = r))
      return server(Number(etag.slice(2, -1)) + 1, b)
    })
    const s = new DraftSaver(server(1, base()), put, vi.fn(), 0)
    s.edit((b) => ({ ...b, title: 'one' }))
    await vi.waitFor(() => expect(put).toHaveBeenCalledTimes(1))
    s.edit((b) => ({ ...b, title: 'two' }))
    release()
    await s.flush()
    expect(bodies).toEqual(['one', 'two'])
    expect(put.mock.calls[1]?.[1]).toBe('"r2"')
    expect(s.snapshot.status).toBe('saved')
  })

  it('412 after a worker leg: rebases the edit on the new draft and saves it again', async () => {
    const withLeg = base({ legs: [legB] })
    const put = vi
      .fn<(b: DraftBody, etag: string) => Promise<ServerDraft>>()
      .mockRejectedValueOnce(conflict())
      .mockImplementation(async (b, etag) => server(Number(etag.slice(2, -1)) + 1, b))
    const get = vi.fn(async () => server(2, withLeg))
    const s = new DraftSaver(server(1, base()), put, get, 0)
    s.edit((b) => ({ ...b, title: 'Mới' }))
    await s.flush()
    expect(get).toHaveBeenCalledTimes(1)
    expect(put).toHaveBeenCalledTimes(2)
    expect(put.mock.calls[1]?.[1]).toBe('"r2"')
    const sent = put.mock.calls[1]?.[0]
    expect(sent?.title).toBe('Mới')
    expect(sent?.legs).toEqual([legB]) // the worker's line is kept, not overwritten
    expect(s.snapshot).toMatchObject({ status: 'saved', revision: 3 })
  })

  it('412 after a change elsewhere (not legs): stops with a conflict, never overwrites', async () => {
    const put = vi.fn().mockRejectedValue(conflict())
    const get = vi.fn(async () => server(2, base({ title: 'Tab khác' })))
    const s = new DraftSaver(server(1, base()), put, get, 0)
    s.edit((b) => ({ ...b, title: 'Mới' }))
    await s.flush()
    expect(put).toHaveBeenCalledTimes(1)
    expect(s.snapshot.status).toBe('conflict')
    s.edit((b) => ({ ...b, title: 'nữa' }))
    await s.flush()
    expect(put).toHaveBeenCalledTimes(1)
    s.reset(server(2, base({ title: 'Tab khác' })))
    expect(s.snapshot).toMatchObject({ status: 'saved', revision: 2 })
    expect(s.snapshot.body.title).toBe('Tab khác')
  })

  it('a network error keeps the edit and retries on demand', async () => {
    const put = vi
      .fn<(b: DraftBody, etag: string) => Promise<ServerDraft>>()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockImplementation(async (b) => server(2, b))
    const s = new DraftSaver(server(1, base()), put, vi.fn(), 0)
    s.edit((b) => ({ ...b, title: 'Mới' }))
    await s.flush()
    expect(s.snapshot.status).toBe('error')
    s.retry()
    await vi.waitFor(() => expect(s.snapshot.status).toBe('saved'))
    expect(put).toHaveBeenCalledTimes(2)
  })

  it('undo puts back the body before the last edit and saves it', async () => {
    const put = vi.fn(async (b: DraftBody, etag: string) =>
      server(Number(etag.slice(2, -1)) + 1, b),
    )
    const s = new DraftSaver(server(1, base()), put, vi.fn(), 0)
    s.edit((b) => ({ ...b, title: 'one' }))
    s.edit((b) => ({ ...b, title: 'two' }))
    s.undoLast()
    await s.flush()
    expect(s.snapshot.body.title).toBe('one')
    expect(put.mock.lastCall?.[0].title).toBe('one')
  })

  it('adopts a newer server draft only when nothing is pending', async () => {
    const put = vi.fn(async (b: DraftBody) => server(2, b))
    const s = new DraftSaver(server(1, base()), put, vi.fn(), 1000)
    s.edit((b) => ({ ...b, title: 'typing' }), false)
    expect(s.adopt(server(5, base({ legs: [legB] })))).toBe(false)
    await s.flush()
    expect(s.adopt(server(5, base({ title: 'typing', legs: [legB] })))).toBe(true)
    expect(s.snapshot.body.legs).toEqual([legB])
    expect(s.snapshot.revision).toBe(5)
  })
})

describe('rebaseLegs', () => {
  it('takes server legs the admin did not touch, keeps legs the admin changed, drops removed stops', () => {
    const stopC = { ...stopA, id: 'c' }
    const legC: Leg = { ...legB, to: 'c', source: 'manual', path: 'mine' }
    const b = base({ stops: [stopA, stopB, stopC] })
    const local = base({ stops: [stopA, stopC], legs: [legC] })
    const srv = base({ stops: [stopA, stopB, stopC], legs: [legB, { ...legC, path: 'worker' }] })
    expect(rebaseLegs(local, b, srv).legs).toEqual([legC])
    expect(rebaseLegs(base({ stops: [stopA, stopB, stopC] }), b, srv).legs).toEqual(srv.legs)
  })
})
