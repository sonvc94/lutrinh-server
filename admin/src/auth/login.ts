import { z } from 'zod'

/** Username + password; the code (6-digit TOTP or a 10-character backup code, hyphens/spaces
 * allowed, the server normalises) only while the server asks for it (`totpRequired`). */
export function makeLoginSchema(totpRequired: boolean) {
  return z.object({
    username: z.string().trim().min(1, 'Nhập tên đăng nhập').max(40),
    password: z.string().min(1, 'Nhập mật khẩu').max(1024),
    code: totpRequired
      ? z
          .string()
          .trim()
          .refine(
            (v) => /^\d{6}$/.test(v.replace(/\s/g, '')) || v.replace(/[\s-]/g, '').length === 10,
            { message: 'Mã 6 số, hoặc một mã dự phòng 10 ký tự' },
          )
      : z.string(),
  })
}

export type LoginForm = z.infer<ReturnType<typeof makeLoginSchema>>

/** Only same-app paths are followed after login (no open redirect via ?next=). */
export function safeNext(next: string | null): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/dang-nhap'))
    return '/lo-trinh'
  return next
}
