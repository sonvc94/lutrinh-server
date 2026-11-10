import { api, unwrap } from '../api/client'
import type { MediaOut } from '../api/types'
import { sendChunks } from '../api/upload'
import { rememberLocal } from './mediaUrl'

export const ACCEPT =
  'image/jpeg,image/png,image/heic,image/heif,video/mp4,video/quicktime,.heic,.heif'

/** POST /media → chunks → complete (page 03). Resolves with the row (status `processing`). */
export async function uploadMedia(
  routeId: string,
  file: File,
  onProgress: (f: number) => void,
  onCreated?: (row: MediaOut) => void,
): Promise<MediaOut> {
  const row = await unwrap(
    api.POST('/admin/api/v1/media', {
      body: { routeId, filename: file.name, contentType: file.type || null, bytes: file.size },
    }),
  )
  onCreated?.(row)
  if (!row.upload) throw new Error('server sent no upload plan')
  if (file.type.startsWith('image/')) rememberLocal(row.id, file)
  await sendChunks({ kind: 'media', id: row.id, file, state: row.upload, onProgress })
  const done = await unwrap(
    api.POST('/admin/api/v1/media/{media_id}/complete', { params: { path: { media_id: row.id } } }),
  )
  return done.media
}
