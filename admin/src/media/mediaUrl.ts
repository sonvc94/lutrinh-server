/**
 * Where a tile's picture comes from. The admin API has no endpoint that returns media bytes yet
 * (Mate decision: tiles without server images for now). When `GET /admin/api/v1/media/{id}/file`
 * lands, `mediaUrl` is the one place to change; until then it returns null and a tile shows the
 * local preview of a file uploaded in this tab, or a type icon + name + status.
 */
export type MediaSize = 'thumb' | 'full'

export function mediaUrl(_id: string, _size: MediaSize): string | null {
  return null
}

const local = new Map<string, string>()

/** Keep an object URL of a file just uploaded from this browser (until the page is closed). */
export function rememberLocal(id: string, file: Blob): void {
  if (local.has(id) || typeof URL.createObjectURL !== 'function') return
  local.set(id, URL.createObjectURL(file))
}

export function previewUrl(id: string, size: MediaSize): string | null {
  return local.get(id) ?? mediaUrl(id, size)
}
