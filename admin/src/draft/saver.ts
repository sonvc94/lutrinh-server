/**
 * Autosave of the draft (page 04 B "Lưu tự động mỗi thay đổi", §F "If-Match"): every edit is
 * applied locally at once and sent with `PUT /routes/{id}/draft` + `If-Match` (the ETag of the
 * last read). One PUT at a time; edits made meanwhile go in the next one.
 *
 * 412: the worker writes road legs into the draft and bumps its revision (compare-and-set), so an
 * old ETag is routine. The saver reads the draft again; when only `legs` changed on the server it
 * rebases the local edits onto it (`rebaseLegs`) and sends them again. Any other change on the
 * server (another tab) stops saving and shows "Bản nháp vừa đổi ở nơi khác · Tải lại" (never
 * overwrite). Undo ("Hoàn tác") puts back the body before the last edit and saves it.
 */
import { ApiError } from '../api/errors'
import type { DraftBody } from './model'
import { normalise } from './model'

export type SaveStatus = 'saved' | 'pending' | 'saving' | 'error' | 'conflict'

export interface ServerDraft {
  etag: string
  revision: number
  body: Record<string, unknown>
  queuedJobs?: number[]
}

export type PutDraft = (body: DraftBody, etag: string) => Promise<ServerDraft>
export type GetDraft = () => Promise<ServerDraft>

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

/** Everything but the legs: what only the admin writes. */
function nonLeg(b: DraftBody): Omit<DraftBody, 'legs'> {
  const { legs: _legs, ...rest } = b
  return rest
}

/**
 * Local edits onto a server draft whose legs changed (`server`), both from `base`: a leg the admin
 * did not touch takes the server's (new line, or dropped); a leg the admin changed stays theirs.
 * Only legs into stops the local body still has are kept, in stop order.
 */
export function rebaseLegs(local: DraftBody, base: DraftBody, server: DraftBody): DraftBody {
  const by = (b: DraftBody) => new Map(b.legs.map((l) => [l.to, l]))
  const L = by(local)
  const B = by(base)
  const S = by(server)
  const legs = []
  for (const stop of local.stops) {
    const l = L.get(stop.id)
    const pick = same(l, B.get(stop.id)) ? S.get(stop.id) : l
    if (pick) legs.push(pick)
  }
  return { ...local, legs }
}

export interface SaverState {
  body: DraftBody
  etag: string
  revision: number
  status: SaveStatus
  error: string | null
  canUndo: boolean
  queuedJobs: number[]
}

const UNDO_DEPTH = 50
/** 412s in a row rebased before giving up (the worker writes one leg per job). */
const REBASE_TRIES = 5

export class DraftSaver {
  private state: SaverState
  /** The body of the server revision `state.etag` names. */
  private base: DraftBody
  private undo: DraftBody[] = []
  private dirty = false
  private inFlight: Promise<void> | null = null
  private timer: ReturnType<typeof setTimeout> | null = null
  private listeners = new Set<() => void>()
  private readonly put: PutDraft
  private readonly get: GetDraft
  private readonly delayMs: number

  constructor(initial: ServerDraft, put: PutDraft, get: GetDraft, delayMs = 400) {
    this.put = put
    this.get = get
    this.delayMs = delayMs
    this.base = normalise(initial.body)
    this.state = {
      body: this.base,
      etag: initial.etag,
      revision: initial.revision,
      status: 'saved',
      error: null,
      canUndo: false,
      queuedJobs: initial.queuedJobs ?? [],
    }
  }

  get snapshot(): SaverState {
    return this.state
  }

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  private set(patch: Partial<SaverState>): void {
    this.state = { ...this.state, ...patch, canUndo: this.undo.length > 0 }
    this.listeners.forEach((fn) => fn())
  }

  /** Apply an edit. `immediate` saves now (structural edits); otherwise after a short pause. */
  edit(fn: (b: DraftBody) => DraftBody, immediate = true): void {
    if (this.state.status === 'conflict') return
    const next = fn(this.state.body)
    // a form that re-sends what the body already says is not an edit (no undo step, no PUT)
    if (next === this.state.body || same(next, this.state.body)) return
    this.undo.push(this.state.body)
    if (this.undo.length > UNDO_DEPTH) this.undo.shift()
    this.dirty = true
    this.set({ body: next, status: 'pending' })
    this.schedule(immediate ? 0 : this.delayMs)
  }

  undoLast(): void {
    const prev = this.undo.pop()
    if (!prev || this.state.status === 'conflict') return
    this.dirty = true
    this.set({ body: prev, status: 'pending' })
    this.schedule(0)
  }

  /** A newer draft from the server (manual leg, a finished job): taken only when nothing is pending. */
  adopt(server: ServerDraft): boolean {
    if (this.dirty || this.inFlight || this.timer) return false
    if (server.revision < this.state.revision) return false
    this.rebaseUndo(normalise(server.body))
    this.set({
      body: this.base,
      etag: server.etag,
      revision: server.revision,
      status: 'saved',
      error: null,
      queuedJobs: server.queuedJobs ?? this.state.queuedJobs,
    })
    return true
  }

  /** Throw away local edits and start again from `server` (after a conflict). */
  reset(server: ServerDraft): void {
    if (this.timer) clearTimeout(this.timer)
    this.undo = []
    this.dirty = false
    this.base = normalise(server.body)
    this.set({
      body: this.base,
      etag: server.etag,
      revision: server.revision,
      status: 'saved',
      error: null,
      queuedJobs: server.queuedJobs ?? [],
    })
  }

  /** Resolves when every edit made so far is on the server (or saving stopped). */
  async flush(): Promise<void> {
    if (this.timer) {
      clearTimeout(this.timer)
      this.timer = null
      await this.run()
    }
    while (this.inFlight) await this.inFlight
  }

  dispose(): void {
    if (this.timer) clearTimeout(this.timer)
    this.listeners.clear()
  }

  private schedule(ms: number): void {
    if (this.timer) clearTimeout(this.timer)
    this.timer = setTimeout(() => {
      this.timer = null
      void this.run()
    }, ms)
  }

  private async run(): Promise<void> {
    if (this.inFlight) return
    let release: () => void = () => {}
    this.inFlight = new Promise((r) => (release = r))
    try {
      let rebased = 0
      while (this.dirty && this.state.status !== 'conflict') {
        this.dirty = false
        const body = this.state.body
        this.set({ status: 'saving' })
        try {
          const res = await this.put(body, this.state.etag)
          const stored = normalise(res.body)
          this.base = stored
          rebased = 0
          this.set({
            // nothing typed meanwhile: show what the server kept (stale lines dropped)
            body: this.dirty ? this.state.body : stored,
            etag: res.etag,
            revision: res.revision,
            status: this.dirty ? 'pending' : 'saved',
            error: null,
            queuedJobs: res.queuedJobs ?? [],
          })
        } catch (e) {
          if (e instanceof ApiError && e.status === 412 && rebased < REBASE_TRIES) {
            rebased++
            if (!(await this.rebase())) return
            continue
          }
          this.dirty = true
          if (e instanceof ApiError && e.status === 412) {
            this.set({ status: 'conflict', error: 'Bản nháp vừa đổi ở nơi khác.' })
          } else {
            this.set({ status: 'error', error: e instanceof Error ? e.message : String(e) })
          }
          return
        }
      }
    } finally {
      this.inFlight = null
      release()
    }
  }

  /** Undo must not put back legs the server replaced since (a worker line would be lost). */
  private rebaseUndo(server: DraftBody): void {
    this.undo = this.undo.map((u) => rebaseLegs(u, this.base, server))
    this.base = server
  }

  /** After a 412: read the draft; rebase when only legs changed there, else stop (conflict). */
  private async rebase(): Promise<boolean> {
    let server: ServerDraft
    try {
      server = await this.get()
    } catch (e) {
      this.dirty = true
      this.set({ status: 'error', error: e instanceof Error ? e.message : String(e) })
      return false
    }
    const fresh = normalise(server.body)
    if (!same(nonLeg(fresh), nonLeg(this.base))) {
      this.dirty = true
      this.set({ status: 'conflict', error: 'Bản nháp vừa đổi ở nơi khác.' })
      return false
    }
    const body = rebaseLegs(this.state.body, this.base, fresh)
    this.rebaseUndo(fresh)
    this.dirty = true
    this.set({
      body,
      etag: server.etag,
      revision: server.revision,
      queuedJobs: server.queuedJobs ?? [],
    })
    return true
  }

  /** Jobs started outside a draft write ("Tính lại" a leg) to watch with the others. */
  addJobs(ids: number[]): void {
    const next = [...new Set([...this.state.queuedJobs, ...ids])]
    if (next.length !== this.state.queuedJobs.length) this.set({ queuedJobs: next })
  }

  /** Try again after an error (network). */
  retry(): void {
    if (this.state.status === 'error') this.schedule(0)
  }
}
