import { defineConfig, devices } from '@playwright/test'

const PORT = process.env.LUTRINH_E2E_PORT ?? '8123'

/**
 * End to end against a real lutrinh server started fresh by e2e/server.mjs (stopped after).
 * `localhost`, not 127.0.0.1: the `__Host-` session cookie is Secure; browsers accept that on
 * http://localhost only. Run `npm run build` first: the server serves admin/dist at /admin.
 */
export default defineConfig({
  testDir: 'e2e',
  outputDir: '/Volumes/wdblack/tmp/lutrinh-admin-web/test-results',
  timeout: 120_000,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${PORT}`,
    viewport: { width: 1440, height: 900 },
    locale: 'vi-VN',
    timezoneId: 'Asia/Ho_Chi_Minh',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
  ],
  webServer: {
    command: 'node e2e/server.mjs',
    url: `http://127.0.0.1:${PORT}/api/v1/meta`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
})
