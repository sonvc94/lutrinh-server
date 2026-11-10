/**
 * The acceptance flow (task server-admin-web): log in with password + TOTP, import a 3-stop GPX,
 * publish, read the code, and look it up on the public API (what the app does) with curl.
 * Screenshots of each screen go to /Volumes/wdblack/tmp/lutrinh-admin-web/screens/.
 */
import { expect, test, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { totp } from './totp'

const ROOT = process.env.LUTRINH_E2E_ROOT ?? '/Volumes/wdblack/tmp/lutrinh-admin-web/e2e'
const SCREENS = '/Volumes/wdblack/tmp/lutrinh-admin-web/screens'
const GPX = join(import.meta.dirname, 'fixtures', 'ba-diem-ha-noi.gpx')
const TITLE = 'Ba điểm quanh Hồ Gươm'

interface Creds {
  password: string
  secret: string
  port: string
}

const creds = (): Creds => JSON.parse(readFileSync(join(ROOT, 'current.json'), 'utf8')) as Creds

async function shot(page: Page, name: string) {
  mkdirSync(SCREENS, { recursive: true })
  await page.screenshot({ path: join(SCREENS, `${name}.png`) })
}

/** A tiny valid PNG (1×1, orange), so the upload needs no file on disk. */
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFhAJ/wlseKgAAAABJRU5ErkJggg==',
  'base64',
)

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
  await page.getByLabel('Mật khẩu').fill(c.password)
  await page.getByLabel('Mã 6 số từ ứng dụng xác thực').fill(totp(c.secret))
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

  // C: media (upload stays "processing": no worker in this run)
  await page.getByRole('link', { name: 'Ảnh/video' }).click()
  await page.getByLabel('Chọn ảnh, video').setInputFiles({
    name: 'thap-rua.png',
    mimeType: 'image/png',
    buffer: PNG,
  })
  await expect(page.getByTestId('media-tile')).toHaveCount(1)
  await shot(page, 'media')

  // A again: the list with the shared route and its code
  await page.goto('/admin/lo-trinh')
  await expect(page.getByText(TITLE)).toBeVisible()
  await expect(page.getByText(code!)).toBeVisible()
  await shot(page, 'list')
})
