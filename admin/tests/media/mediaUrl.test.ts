import { describe, expect, it } from 'vitest'
import { mediaUrl, previewUrl } from '../../src/media/mediaUrl'

describe('mediaUrl', () => {
  it('points at the admin media file endpoint, the preview for thumbs', () => {
    expect(mediaUrl('m_abc', 'thumb')).toBe('/admin/api/v1/media/m_abc/file?size=640')
    expect(mediaUrl('m_abc', 'full')).toBe('/admin/api/v1/media/m_abc/file')
  })

  it('previews only processed photos from the server', () => {
    expect(previewUrl('m_1', 'thumb', { status: 'ready', type: 'photo' })).toBe(
      '/admin/api/v1/media/m_1/file?size=640',
    )
    expect(previewUrl('m_1', 'thumb', { status: 'processing', type: 'photo' })).toBeNull()
    expect(previewUrl('m_1', 'thumb', { status: 'ready', type: 'video' })).toBeNull()
    expect(previewUrl('m_1', 'thumb')).toBeNull()
  })
})
