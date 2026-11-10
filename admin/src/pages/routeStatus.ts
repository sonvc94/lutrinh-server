import type { RouteOut } from '../api/types'
import type { Tone } from '../ui/ui'

/** Three states only (page 04 A): Nháp, Đang chia sẻ, Đã gỡ; Xóa = Thùng rác. */
export const STATUS: Record<RouteOut['status'], { label: string; tone: Tone }> = {
  draft: { label: 'Nháp', tone: 'moderate' },
  shared: { label: 'Đang chia sẻ', tone: 'easy' },
  unpublished: { label: 'Đã gỡ', tone: 'hard' },
  trash: { label: 'Thùng rác', tone: 'neutral' },
}
