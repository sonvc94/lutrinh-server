import { afterEach, describe, expect, it, vi } from 'vitest'
import { chunkRange, missingChunks, sendChunks } from '../../src/api/upload'

const state = (chunks: number, received: number[] = []) => ({
  bytes: 25,
  chunkBytes: 10,
  chunks,
  received,
  sha256: null,
  completedAt: null,
})

afterEach(() => vi.unstubAllGlobals())

describe('chunk plan', () => {
  it('lists the chunks the server lacks and their byte ranges', () => {
    expect(missingChunks({ chunkBytes: 10, chunks: 3, received: [1] })).toEqual([0, 2])
    expect(chunkRange({ chunkBytes: 10, chunks: 3, received: [] }, 2, 25)).toEqual([20, 25])
  })
})

describe('sendChunks', () => {
  it('sends only missing chunks, retries a network failure, reports progress', async () => {
    const calls: string[] = []
    let failOnce = true
    vi.stubGlobal(
      'fetch',
      vi.fn(async (req: Request) => {
        calls.push(
          `${req.method} ${new URL(req.url).pathname} ${(await req.arrayBuffer()).byteLength}`,
        )
        if (failOnce) {
          failOnce = false
          throw new TypeError('Failed to fetch')
        }
        return new Response(null, { status: 204 })
      }),
    )
    const progress: number[] = []
    await sendChunks({
      kind: 'media',
      id: 'm1',
      file: new Blob(['x'.repeat(25)]),
      state: state(3, [1]),
      onProgress: (f) => progress.push(f),
      backoffMs: 0,
    })
    expect(calls).toEqual([
      'PUT /admin/api/v1/media/m1/chunks/0 10',
      'PUT /admin/api/v1/media/m1/chunks/0 10',
      'PUT /admin/api/v1/media/m1/chunks/2 5',
    ])
    expect(progress.map((p) => p.toFixed(2))).toEqual(['0.33', '0.67', '1.00'])
  })

  it('does not retry a 4xx answer', async () => {
    const f = vi.fn(async () =>
      Response.json({ error: { code: 'too_large', retryAfterS: null } }, { status: 413 }),
    )
    vi.stubGlobal('fetch', f)
    await expect(
      sendChunks({
        kind: 'imports',
        id: 'i1',
        file: new Blob(['abc']),
        state: state(1),
        backoffMs: 0,
      }),
    ).rejects.toMatchObject({ status: 413, code: 'too_large' })
    expect(f).toHaveBeenCalledTimes(1)
  })
})
