/** TanStack Query hooks over the admin API (cache, retry, polling of background jobs). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from './client'

export const keys = {
  routes: (status?: string, q?: string) => ['routes', status ?? 'all', q ?? ''] as const,
  route: (id: string) => ['route', id] as const,
  draft: (id: string) => ['draft', id] as const,
  preflight: (id: string) => ['preflight', id] as const,
  versions: (id: string) => ['versions', id] as const,
  codes: (id: string) => ['codes', id] as const,
  media: (id: string) => ['media', id] as const,
  stats: (id?: string) => ['stats', id ?? 'all'] as const,
  job: (id: number) => ['job', id] as const,
}

export function useRoutes(status?: string, q?: string) {
  return useQuery({
    queryKey: keys.routes(status, q),
    queryFn: () =>
      unwrap(
        api.GET('/admin/api/v1/routes', {
          params: { query: { ...(status ? { status } : {}), ...(q ? { q } : {}) } },
        }),
      ),
  })
}

export function useRoute(id: string) {
  return useQuery({
    queryKey: keys.route(id),
    queryFn: () =>
      unwrap(api.GET('/admin/api/v1/routes/{route_id}', { params: { path: { route_id: id } } })),
  })
}

export function useDraftQuery(id: string) {
  return useQuery({
    queryKey: keys.draft(id),
    queryFn: () =>
      unwrap(
        api.GET('/admin/api/v1/routes/{route_id}/draft', { params: { path: { route_id: id } } }),
      ),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
}

/** Downloads/lookups per route over the last `days` days (D-14 A: daily totals only). */
export function useStats(routeId?: string, days = 30) {
  return useQuery({
    queryKey: keys.stats(routeId),
    queryFn: () =>
      unwrap(
        api.GET('/admin/api/v1/stats', {
          params: { query: { days, ...(routeId ? { routeId } : {}) } },
        }),
      ),
  })
}

export function sumStats(
  rows: { routeId?: string | null; kind: string; count: number }[] | undefined,
  kind: string,
  routeId?: string,
): number {
  return (rows ?? [])
    .filter((r) => r.kind === kind && (routeId === undefined || r.routeId === routeId))
    .reduce((n, r) => n + r.count, 0)
}

export function useMedia(routeId: string) {
  return useQuery({
    queryKey: keys.media(routeId),
    queryFn: () => unwrap(api.GET('/admin/api/v1/media', { params: { query: { routeId } } })),
    // the worker resizes / transcodes; the page asks again every 2 s while one is processing
    refetchInterval: (q) =>
      q.state.data?.some((m) => m.status === 'processing' || m.status === 'uploading')
        ? 2000
        : false,
  })
}

const DONE = new Set(['done', 'failed'])

export function useJob(id: number | null) {
  return useQuery({
    queryKey: keys.job(id ?? -1),
    enabled: id !== null,
    queryFn: () =>
      unwrap(api.GET('/admin/api/v1/jobs/{job_id}', { params: { path: { job_id: id! } } })),
    refetchInterval: (q) => (q.state.data && DONE.has(q.state.data.status) ? false : 2000),
  })
}

export function isJobDone(status: string | undefined): boolean {
  return status !== undefined && DONE.has(status)
}

/** Invalidate what a route-level write changes. */
export function useInvalidateRoute() {
  const qc = useQueryClient()
  return (id: string) =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ['routes'] }),
      qc.invalidateQueries({ queryKey: keys.route(id) }),
      qc.invalidateQueries({ queryKey: keys.preflight(id) }),
      qc.invalidateQueries({ queryKey: keys.versions(id) }),
      qc.invalidateQueries({ queryKey: keys.codes(id) }),
    ])
}

export function useCreateRoute() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (title?: string) =>
      unwrap(api.POST('/admin/api/v1/routes', { body: { title: title ?? 'Lộ trình mới' } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['routes'] }),
  })
}
