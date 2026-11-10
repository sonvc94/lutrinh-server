/** A plain RGB PNG encoder for test pictures (no image library in the e2e). */
import { crc32, deflateSync } from 'node:zlib'

function chunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4)
  len.writeUInt32BE(data.length)
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data])
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(body))
  return Buffer.concat([len, body, crc])
}

/** `w`×`h` picture: a sunset-like gradient with a dark diagonal band, easy to recognise. */
export function gradientPng(w: number, h: number): Buffer {
  const raw = Buffer.alloc((w * 3 + 1) * h)
  for (let y = 0; y < h; y++) {
    const row = y * (w * 3 + 1)
    raw[row] = 0 // filter: none
    for (let x = 0; x < w; x++) {
      const band = Math.abs(x - y * (w / h)) < w / 20
      const i = row + 1 + x * 3
      raw[i] = band ? 31 : 228
      raw[i + 1] = band ? 42 : Math.round(87 + (120 * y) / h)
      raw[i + 2] = band ? 36 : Math.round(46 + (150 * x) / w)
    }
  }
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(w, 0)
  ihdr.writeUInt32BE(h, 4)
  ihdr.set([8, 2, 0, 0, 0], 8) // 8-bit RGB
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0)),
  ])
}
