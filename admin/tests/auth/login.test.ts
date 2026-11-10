import { describe, expect, it } from 'vitest'
import { loginSchema, safeNext } from '../../src/auth/login'

describe('loginSchema', () => {
  it('takes a 6-digit TOTP or a 10-character backup code', () => {
    expect(loginSchema.safeParse({ password: 'p', code: '123456' }).success).toBe(true)
    expect(loginSchema.safeParse({ password: 'p', code: 'ABCDE-FGHIJ' }).success).toBe(true)
    expect(loginSchema.safeParse({ password: 'p', code: '12345' }).success).toBe(false)
    expect(loginSchema.safeParse({ password: '', code: '123456' }).success).toBe(false)
  })
})

describe('safeNext', () => {
  it('follows app paths only', () => {
    expect(safeNext('/lo-trinh/rt_1/xuat-ban')).toBe('/lo-trinh/rt_1/xuat-ban')
    expect(safeNext('//evil.example')).toBe('/lo-trinh')
    expect(safeNext('https://evil.example')).toBe('/lo-trinh')
    expect(safeNext('/dang-nhap')).toBe('/lo-trinh')
    expect(safeNext(null)).toBe('/lo-trinh')
  })
})
