/**
 * Where a tile's picture comes from: `GET /admin/api/v1/media/{id}/file` (admin session cookie,
 * same origin). `thumb` asks for the worker's ≤ 640 px preview (`?size=640`; the server falls back
 * to the original when there is none), `full` for the processed file itself.
 * The server answers 404 until the worker has processed the upload, so callers that know the row
 * use `previewUrl` with it; a file uploaded in this tab shows its local copy meanwhile.
 */
export type MediaSize = 'thumb' | 'full'

const BASE = '/admin/api/v1/media'

export function mediaUrl(id: string, size: MediaSize): string {
  const file = `${BASE}/${encodeURIComponent(id)}/file`
  return size === 'thumb' ? `${file}?size=640` : file
}

const local = new Map<string, string>()

/** Keep an object URL of a file just uploaded from this browser (until the page is closed). */
export function rememberLocal(id: string, file: Blob): void {
  if (local.has(id) || typeof URL.createObjectURL !== 'function') return
  local.set(id, URL.createObjectURL(file))
}

/** What an `<img>` shows for a media row: the local copy, else the server's once it is a ready photo. */
export function previewUrl(
  id: string,
  size: MediaSize,
  row?: { status: string; type: string },
): string | null {
  const own = local.get(id)
  if (own) return own
  return row?.status === 'ready' && row.type === 'photo' ? mediaUrl(id, size) : null
}
