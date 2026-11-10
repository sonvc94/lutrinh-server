/**
 * Chunked, resumable upload (page 03 `/media`, `/imports`; 8 MB chunks): create → PUT each
 * missing chunk → complete. A chunk that fails is retried; after that the upload stops and can
 * resume later from `upload.received` (GET /media/{id} or /imports/{id}).
 */
import { adminFetch, API } from './client'
import { ApiError } from './errors'
import type { UploadState } from './types'

export type UploadKind = 'media' | 'imports'

export interface ChunkPlan {
  chunkBytes: number
  chunks: number
  received: number[]
}

export function missingChunks(plan: ChunkPlan): number[] {
  const have = new Set(plan.received)
  const out: number[] = []
  for (let n = 0; n < plan.chunks; n++) if (!have.has(n)) out.push(n)
  return out
}

export function chunkRange(plan: ChunkPlan, n: number, size: number): [number, number] {
  const start = n * plan.chunkBytes
  return [start, Math.min(size, start + plan.chunkBytes)]
}

export interface UploadOptions {
  kind: UploadKind
  id: string
  file: Blob
  state: UploadState
  onProgress?: (fraction: number) => void
  signal?: AbortSignal
  retries?: number
  /** Wait between retries (tests pass 0). */
  backoffMs?: number
}

async function putChunk(kind: UploadKind, id: string, n: number, body: Blob, signal?: AbortSignal) {
  const req = new Request(`${location.origin}${API}/${kind}/${id}/chunks/${n}`, {
    method: 'PUT',
    body,
    headers: { 'Content-Type': 'application/octet-stream' },
    credentials: 'same-origin',
    signal: signal ?? null,
  })
  const res = await adminFetch(req)
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null))
}

/** Send every chunk the server does not have yet. Resolves when all are on the server. */
export async function sendChunks(o: UploadOptions): Promise<void> {
  const plan: ChunkPlan = {
    chunkBytes: o.state.chunkBytes,
    chunks: o.state.chunks,
    received: o.state.received,
  }
  const todo = missingChunks(plan)
  let done = plan.chunks - todo.length
  o.onProgress?.(plan.chunks ? done / plan.chunks : 1)
  for (const n of todo) {
    const [a, b] = chunkRange(plan, n, o.file.size)
    let attempt = 0
    for (;;) {
      try {
        await putChunk(o.kind, o.id, n, o.file.slice(a, b), o.signal)
        break
      } catch (e) {
        attempt++
        const permanent = e instanceof ApiError && e.status >= 400 && e.status < 500
        if (permanent || attempt > (o.retries ?? 3) || o.signal?.aborted) throw e
        await new Promise((r) => setTimeout(r, (o.backoffMs ?? 1000) * attempt))
      }
    }
    done++
    o.onProgress?.(done / plan.chunks)
  }
}
