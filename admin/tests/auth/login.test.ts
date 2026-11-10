import { describe, expect, it } from 'vitest'
import { makeLoginSchema, safeNext } from '../../src/auth/login'

describe('makeLoginSchema', () => {
  it('asks for username + password only while TOTP is off', () => {
    const s = makeLoginSchema(false)
    expect(s.safeParse({ username: 'admin', password: '123456', code: '' }).success).toBe(true)
    expect(s.safeParse({ username: '', password: '123456', code: '' }).success).toBe(false)
    expect(s.safeParse({ username: 'admin', password: '', code: '' }).success).toBe(false)
  })

  it('takes a 6-digit TOTP or a 10-character backup code while TOTP is on', () => {
    const s = makeLoginSchema(true)
    const ok = (code: string) => s.safeParse({ username: 'admin', password: 'p', code }).success
    expect(ok('123456')).toBe(true)
    expect(ok('ABCDE-FGHIJ')).toBe(true)
    expect(ok('12345')).toBe(false)
    expect(ok('')).toBe(false)
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
