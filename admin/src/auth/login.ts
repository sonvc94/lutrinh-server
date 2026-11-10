import { z } from 'zod'

/** 6-digit TOTP, or a 10-character backup code (hyphens/spaces allowed; server normalises). */
export const loginSchema = z.object({
  password: z.string().min(1, 'Nhập mật khẩu').max(1024),
  code: z
    .string()
    .trim()
    .refine((v) => /^\d{6}$/.test(v.replace(/\s/g, '')) || v.replace(/[\s-]/g, '').length === 10, {
      message: 'Mã 6 số, hoặc một mã dự phòng 10 ký tự',
    }),
})

export type LoginForm = z.infer<typeof loginSchema>

/** Only same-app paths are followed after login (no open redirect via ?next=). */
export function safeNext(next: string | null): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/dang-nhap'))
    return '/lo-trinh'
  return next
}
