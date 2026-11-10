import { api, unwrap } from '../api/client'
import type { DraftBodyIn } from '../api/types'
import type { DraftBody } from '../draft/model'
import type { GetDraft, PutDraft, ServerDraft } from '../draft/saver'

export function draftPutter(routeId: string): PutDraft {
  return (body: DraftBody, etag: string): Promise<ServerDraft> =>
    unwrap(
      api.PUT('/admin/api/v1/routes/{route_id}/draft', {
        params: { path: { route_id: routeId }, header: { 'If-Match': etag } },
        body: body as unknown as DraftBodyIn,
      }),
    )
}

export function draftGetter(routeId: string): GetDraft {
  return () =>
    unwrap(
      api.GET('/admin/api/v1/routes/{route_id}/draft', { params: { path: { route_id: routeId } } }),
    )
}
