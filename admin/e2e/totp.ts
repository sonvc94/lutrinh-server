/** RFC 6238 TOTP (SHA-1, 6 digits, 30 s), what any authenticator app computes. */
import { createHmac } from 'node:crypto'

function base32(s: string): Buffer {
  const A = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  let bits = ''
  for (const c of s.replace(/=+$/, '').toUpperCase()) {
    const v = A.indexOf(c)
    if (v < 0) throw new Error(`not base32: ${c}`)
    bits += v.toString(2).padStart(5, '0')
  }
  const bytes = bits.match(/.{8}/g) ?? []
  return Buffer.from(bytes.map((b) => parseInt(b, 2)))
}

export function totp(secret: string, now = Date.now()): string {
  const counter = Buffer.alloc(8)
  counter.writeBigUInt64BE(BigInt(Math.floor(now / 1000 / 30)))
  const h = createHmac('sha1', base32(secret)).update(counter).digest()
  const off = h[h.length - 1]! & 0xf
  const n = (h.readUInt32BE(off) & 0x7fffffff) % 1_000_000
  return String(n).padStart(6, '0')
}
