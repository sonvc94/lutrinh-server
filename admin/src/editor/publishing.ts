import { useQuery } from '@tanstack/react-query'
import { api, unwrap } from '../api/client'
import { keys } from '../api/hooks'

export function usePreflight(routeId: string) {
  return useQuery({
    queryKey: keys.preflight(routeId),
    queryFn: () =>
      unwrap(
        api.GET('/admin/api/v1/routes/{route_id}/publish', {
          params: { path: { route_id: routeId } },
        }),
      ),
  })
}

export function useVersions(routeId: string) {
  return useQuery({
    queryKey: keys.versions(routeId),
    queryFn: () =>
      unwrap(
        api.GET('/admin/api/v1/routes/{route_id}/versions', {
          params: { path: { route_id: routeId } },
        }),
      ),
  })
}

export function useCodes(routeId: string) {
  return useQuery({
    queryKey: keys.codes(routeId),
    queryFn: () =>
      unwrap(
        api.GET('/admin/api/v1/routes/{route_id}/codes', {
          params: { path: { route_id: routeId } },
        }),
      ),
  })
}

/** Vietnamese for the server's preflight problems (core/rules.py); unknown codes show the message. */
export const PROBLEM_TEXT: Record<string, string> = {
  day_order: 'Thứ tự ngày của các điểm bị lùi.',
  time_order: 'Giờ trong một ngày bị lùi.',
  route_json_too_large: 'route.json quá lớn.',
  package_too_large: 'Gói tải về quá lớn.',
  media_not_ready: 'Còn ảnh/video chưa xử lý xong.',
  invalid_package: 'Gói không hợp lệ.',
  package_large: 'Gói tải về khá lớn.',
  leg_missing: 'Có chặng chưa có đường bộ (app vẽ đường thẳng).',
  leg_not_ok: 'Có chặng máy chủ không tìm được đường.',
  leg_car_fallback: 'Có chặng xe máy phải tính bằng đường ô tô.',
  leg_long: 'Có chặng rất dài.',
}
