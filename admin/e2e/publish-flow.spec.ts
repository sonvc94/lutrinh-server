/**
 * The acceptance flow (task server-admin-web): log in with username + password, import a 3-stop GPX,
 * publish, read the code, and look it up on the public API (what the app does) with curl; upload a
 * photo, process it like the worker and see it come back from the server (tile, list cover); and
 * the map over Hoàng Sa / Trường Sa (R30).
 * Screenshots of each screen go to /Volumes/wdblack/tmp/lutrinh-admin-web/screens/.
 */
import { expect, test, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { gradientPng } from './png'

const ROOT = process.env.LUTRINH_E2E_ROOT ?? '/Volumes/wdblack/tmp/lutrinh-admin-web/e2e'
const SCREENS = '/Volumes/wdblack/tmp/lutrinh-admin-web/screens'
const GPX = join(import.meta.dirname, 'fixtures', 'ba-diem-ha-noi.gpx')
const ARCHIPELAGOS = join(import.meta.dirname, 'fixtures', 'hoang-sa-truong-sa.gpx')
const TITLE = 'Ba điểm quanh Hồ Gươm'
const LEG_NOTE = 'Đường dốc khó đi. Gửi xe phía đối diện, 30k'

interface Creds {
  data: string
  username: string
  password: string
  port: string
}

const creds = (): Creds => JSON.parse(readFileSync(join(ROOT, 'current.json'), 'utf8')) as Creds

async function shot(page: Page, name: string) {
  mkdirSync(SCREENS, { recursive: true })
  await page.screenshot({ path: join(SCREENS, `${name}.png`) })
}

const SERVER = join(import.meta.dirname, '..', '..', 'server')
const TMP = '/Volumes/wdblack/tmp/lutrinh-server'

/** What the worker does with the queued jobs (media for real, routers offline). */
function processJobs(c: Creds): string {
  return execFileSync('uv', ['run', 'python', join(import.meta.dirname, 'process_jobs.py')], {
    cwd: SERVER,
    encoding: 'utf8',
    env: {
      ...process.env,
      LUTRINH_DATA_DIR: c.data,
      TMPDIR: join(TMP, 'tmp'),
      UV_CACHE_DIR: join(TMP, 'uv-cache'),
      UV_PYTHON_INSTALL_DIR: join(TMP, 'python'),
      PATH: `${join(TMP, 'uv-venv', 'bin')}:${process.env.PATH}`,
    },
  })
}

test('log in, import a 3-stop GPX, publish, and the code finds the route', async ({ page }) => {
  const c = creds()
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => {
    if (m.type() === 'error' && /worker/i.test(m.text())) errors.push(m.text())
  })

  // G: login
  await page.goto('/admin/')
  await expect(page).toHaveURL(/\/admin\/dang-nhap/)
  await expect(page.getByRole('heading', { name: 'Đăng nhập' })).toBeVisible()
  await shot(page, 'login')
  await page.getByLabel('Tên đăng nhập').fill(c.username)
  await page.getByLabel('Mật khẩu').fill(c.password)
  await expect(page.getByLabel('Mã 6 số từ ứng dụng xác thực')).toHaveCount(0)
  await page.getByRole('button', { name: 'Đăng nhập' }).click()

  // A: route list (empty on a fresh server)
  await expect(page.getByRole('heading', { name: 'Lộ trình', exact: true })).toBeVisible()
  await shot(page, 'list-empty')

  // E: import the GPX
  await page.getByRole('link', { name: /Nhập/ }).first().click()
  await expect(page).toHaveURL(/\/admin\/nhap/)
  await page.getByLabel('Chọn tệp GPX').setInputFiles(GPX)
  const preview = page.getByTestId('import-preview')
  await expect(preview).toBeVisible()
  await expect(page.getByTestId('preview-stops')).toHaveText('3')
  await expect(preview).toContainText(TITLE)
  await shot(page, 'import')
  await page.getByRole('button', { name: 'Tạo lộ trình nháp' }).click()

  // B: editor, stops by day
  await expect(page).toHaveURL(/\/admin\/lo-trinh\/[^/]+\/diem-dung/)
  await expect(page.getByTestId('editor-title')).toHaveText(TITLE)
  await expect(page.getByTestId('stop-row')).toHaveCount(3)
  await expect(page.getByTestId('save-status')).toHaveAttribute('data-status', 'saved')
  // the map fills its column (maplibre's own CSS must not shrink the container)
  const canvas = await page.getByTestId('route-map').locator('canvas').boundingBox()
  expect(canvas?.height ?? 0).toBeGreaterThan(400)
  // pins are maplibre markers (absolutely placed), one per stop
  const pins = page.locator('.maplibregl-marker[data-stop]')
  await expect(pins).toHaveCount(3)
  expect(await pins.evaluateAll((els) => els.map((e) => getComputedStyle(e).position))).toEqual([
    'absolute',
    'absolute',
    'absolute',
  ])
  // basemap tiles come from tiles.openfreemap.org; let some land before the picture
  await page
    .waitForResponse((r) => r.url().includes('openfreemap.org') && r.url().endsWith('.pbf'), {
      timeout: 15_000,
    })
    .catch(() => console.log('no basemap tile within 15 s (offline?)'))
  await page.waitForTimeout(3000)
  expect(errors, 'map worker / page errors').toEqual([])
  await shot(page, 'editor')

  // B: a note on the travel into stop 2 (arrivalNote), saved with the draft and read back
  await page.getByTestId('stop-row').nth(1).locator('button[aria-expanded]').click()
  await page.getByLabel(/^Ghi chú chặng/).fill(LEG_NOTE)
  await expect(page.getByTestId('save-status')).toHaveAttribute('data-status', 'saved')
  await page.reload()
  await expect(page.getByTestId('leg-note')).toHaveText(LEG_NOTE)
  await page.getByTestId('stop-row').nth(1).locator('button[aria-expanded]').click()
  await expect(page.getByLabel(/^Ghi chú chặng/)).toHaveValue(LEG_NOTE)
  // the first stop has no travel into it, so no field there
  await page.getByTestId('stop-row').nth(0).locator('button[aria-expanded]').click()
  await expect(page.getByLabel(/^Ghi chú chặng/)).toHaveCount(0)
  await page.getByTestId('stop-row').nth(1).locator('button[aria-expanded]').click()
  await page.waitForTimeout(500)
  await shot(page, 'stops-leg-note')

  // D: publish
  await page.getByRole('link', { name: 'Xuất bản & mã' }).click()
  const publish = page.getByRole('button', { name: /^Xuất bản v1/ })
  await expect(publish).toBeEnabled()
  await page.locator('#pub-note').fill('Bản đầu tiên')
  await publish.click()
  await expect(page.getByRole('status').filter({ hasText: 'Đã xuất bản v1' })).toBeVisible()
  const codeCard = page.getByTestId('share-code')
  await expect(codeCard).toContainText(/[0-9A-Z]{4}-[0-9A-Z]{4}/)
  const code = /[0-9A-Z]{4}-[0-9A-Z]{4}/.exec((await codeCard.textContent()) ?? '')?.[0]
  expect(code).toBeTruthy()
  await shot(page, 'publish')

  // what the app does: the public lookup by code, outside the browser
  const out = execFileSync(
    'curl',
    [
      '-s',
      '-H',
      'Accept: application/vnd.lutrinh.route+json;v=1',
      `http://127.0.0.1:${c.port}/api/v1/codes/${code}`,
    ],
    { encoding: 'utf8' },
  )
  const summary = JSON.parse(out) as { title?: string; stops?: number }
  console.log(`curl /api/v1/codes/${code} → title "${summary.title}", stops ${summary.stops}`)
  expect(summary.title).toBe(TITLE)
  // …and the downloaded route.json carries the leg note on stop 2 only
  const token = (JSON.parse(out) as { downloadToken: string }).downloadToken
  const routeJson = JSON.parse(
    execFileSync(
      'curl',
      [
        '-s',
        '-H',
        'Accept: application/vnd.lutrinh.route+json;v=1',
        `http://127.0.0.1:${c.port}/api/v1/dl/${token}/route`,
      ],
      { encoding: 'utf8' },
    ),
  ) as { stops: { arrivalNote?: string }[] }
  console.log(
    `route.json stops[1].arrivalNote → ${JSON.stringify(routeJson.stops[1]?.arrivalNote)}`,
  )
  expect(routeJson.stops.map((s) => s.arrivalNote ?? null)).toEqual([null, LEG_NOTE, null])

  // C: media; the worker step (offline routers, e2e/process_jobs.py) turns it into a server file
  await page.getByRole('link', { name: 'Ảnh/video' }).click()
  await page.getByLabel('Chọn ảnh, video').setInputFiles({
    name: 'hoang-hon.png',
    mimeType: 'image/png',
    buffer: gradientPng(1200, 800),
  })
  const tile = page.getByTestId('media-tile')
  await expect(tile).toHaveCount(1)
  await expect(tile).toContainText('Đang xử lý')
  console.log(processJobs(c).trim())
  await expect(tile).not.toContainText('Đang xử lý', { timeout: 10_000 })
  // a reload drops this tab's local copy: what shows now comes from the server
  await page.reload()
  const img = page.getByTestId('media-tile').locator('img')
  await expect(img).toHaveAttribute('src', /\/admin\/api\/v1\/media\/[^/]+\/file\?size=640$/)
  await expect.poll(() => img.evaluate((e: HTMLImageElement) => e.naturalWidth)).toBe(640)
  await shot(page, 'media')
  await page.getByRole('button', { name: 'làm bìa lộ trình' }).click()
  await expect(page.getByTestId('save-status')).toHaveAttribute('data-status', 'saved')

  // A again: the list with the shared route, its code and its cover from the server
  await page.goto('/admin/lo-trinh')
  await expect(page.getByText(TITLE)).toBeVisible()
  await expect(page.getByText(code!)).toBeVisible()
  const cover = page.getByTestId('route-cover')
  await expect(cover).toHaveCount(1)
  await expect.poll(() => cover.evaluate((e: HTMLImageElement) => e.naturalWidth)).toBe(640)
  await shot(page, 'list')

  // R30: a route over Hoàng Sa and Trường Sa; the editor map fits both archipelagos
  await page.getByRole('link', { name: /Nhập/ }).first().click()
  await page.getByLabel('Chọn tệp GPX').setInputFiles(ARCHIPELAGOS)
  await expect(page.getByTestId('preview-stops')).toHaveText('2')
  await page.getByRole('button', { name: 'Tạo lộ trình nháp' }).click()
  await expect(page.getByTestId('editor-title')).toHaveText('Hoàng Sa và Trường Sa')
  await expect(page.locator('.maplibregl-marker[data-stop]')).toHaveCount(2)
  await page
    .waitForResponse((r) => r.url().includes('openfreemap.org') && r.url().endsWith('.pbf'), {
      timeout: 15_000,
    })
    .catch(() => console.log('no basemap tile within 15 s (offline?)'))
  const settle = () => page.waitForTimeout(4000)
  await settle()
  await shot(page, 'r30-archipelagos')
  await page.getByRole('button', { name: 'Zoom out' }).click()
  await settle()
  await shot(page, 'r30-overview')
  // closer over Hoàng Sa (Đảo Phú Lâm, pin 1), where the tiles carry Chinese admin names
  const pin = await page.locator('.maplibregl-marker[data-stop]').first().boundingBox()
  await page.mouse.move((pin?.x ?? 0) + (pin?.width ?? 0) / 2, (pin?.y ?? 0) + (pin?.height ?? 0))
  for (let i = 0; i < 6; i++) {
    await page.mouse.wheel(0, -400)
    await page.waitForTimeout(400)
  }
  await settle()
  await shot(page, 'r30-hoang-sa')
  expect(errors, 'map worker / page errors').toEqual([])
})
