/** Vietnamese number/date formats (decimal comma, dd/mm, 24 h). */
const nf1 = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1, minimumFractionDigits: 1 })
const nf0 = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 })

export function km(meters: number): string {
  const k = meters / 1000
  return k >= 100 ? nf0.format(k) : nf1.format(k)
}

export function duration(seconds: number): string {
  const m = Math.round(seconds / 60)
  if (m < 60) return `${m} phút`
  const h = Math.floor(m / 60)
  const r = m % 60
  return r ? `${h} giờ ${r}` : `${h} giờ`
}

export function megabytes(bytes: number): string {
  return `${nf1.format(bytes / 1024 / 1024)} MB`
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

export function dayMonth(iso: string): string {
  const d = new Date(iso)
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}`
}

export function dateTime(iso: string): string {
  const d = new Date(iso)
  return `${dayMonth(iso)} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** "hôm nay 21:40", "hôm qua 21:40", else "12/11". */
export function lastEdited(iso: string, now: Date = new Date()): string {
  const d = new Date(iso)
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  if (d.getTime() >= startToday) return `hôm nay ${time}`
  if (d.getTime() >= startToday - 86_400_000) return `hôm qua ${time}`
  return dayMonth(iso)
}

export function count(n: number): string {
  return nf0.format(n)
}
