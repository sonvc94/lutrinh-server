/** The server's error envelope (page 03 "Bảng lỗi"): `{"error": {"code", "retryAfterS", …}}`. */
export interface Problem {
  code: string
  path: string
  message: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: string | undefined
  readonly retryAfterS: number | null
  readonly problems: Problem[]
  readonly body: Record<string, unknown>

  constructor(status: number, body: unknown) {
    const err = readEnvelope(body)
    super(`${status} ${err.code}${err.detail ? `: ${err.detail}` : ''}`)
    this.name = 'ApiError'
    this.status = status
    this.code = err.code
    this.detail = err.detail
    this.retryAfterS = err.retryAfterS
    this.problems = err.problems
    this.body = err.raw
  }
}

function readEnvelope(body: unknown): {
  code: string
  detail: string | undefined
  retryAfterS: number | null
  problems: Problem[]
  raw: Record<string, unknown>
} {
  const raw =
    body &&
    typeof body === 'object' &&
    'error' in body &&
    body.error &&
    typeof body.error === 'object'
      ? (body.error as Record<string, unknown>)
      : {}
  return {
    code: typeof raw.code === 'string' ? raw.code : 'http_error',
    detail: typeof raw.detail === 'string' ? raw.detail : undefined,
    retryAfterS: typeof raw.retryAfterS === 'number' ? raw.retryAfterS : null,
    problems: Array.isArray(raw.problems) ? (raw.problems as Problem[]) : [],
    raw,
  }
}

/** Vietnamese text for an error the admin can act on. */
export function errorText(e: unknown): string {
  if (!(e instanceof ApiError)) return e instanceof Error ? e.message : String(e)
  switch (e.code) {
    case 'bad_credentials':
      return 'Mật khẩu hoặc mã không đúng.'
    case 'rate_limited':
      return `Đã khoá do sai nhiều lần. Thử lại sau ${Math.ceil((e.retryAfterS ?? 900) / 60)} phút.`
    case 'unauthenticated':
      return 'Phiên đã hết, hãy đăng nhập lại.'
    case 'draft_changed':
      return 'Bản nháp vừa đổi ở nơi khác.'
    case 'publish_blocked':
      return 'Còn lỗi chặn xuất bản.'
    case 'media_not_ready':
      return 'Còn ảnh/video đang xử lý.'
    case 'invalid_request':
      return e.problems.length
        ? `Dữ liệu không hợp lệ: ${e.problems.map((p) => `${p.path} ${p.message}`).join('; ')}`
        : 'Dữ liệu không hợp lệ.'
    case 'too_large':
      return 'Tệp quá lớn.'
    case 'not_found':
      return 'Không tìm thấy.'
    default:
      return e.detail ? `${e.code}: ${e.detail}` : e.code
  }
}
