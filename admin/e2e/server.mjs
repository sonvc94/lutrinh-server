#!/usr/bin/env node
/**
 * Playwright's web server: a fresh lutrinh server for one e2e run (never the dev data).
 * Data under /Volumes/wdblack/tmp/lutrinh-admin-web/e2e/<run>; the admin's password and TOTP
 * secret go to e2e/current.json there for the test. Serves admin/dist (run `npm run build` first).
 * Stopped by Playwright when the run ends. No worker: jobs stay queued (no router calls).
 */
import { execFileSync, spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = process.env.LUTRINH_E2E_ROOT ?? '/Volumes/wdblack/tmp/lutrinh-admin-web/e2e'
const TMP = '/Volumes/wdblack/tmp/lutrinh-server'
const PORT = process.env.LUTRINH_E2E_PORT ?? '8123'
const server = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'server')
const data = join(ROOT, new Date().toISOString().replace(/[:.]/g, '-'))
mkdirSync(join(data, 'db'), { recursive: true })
mkdirSync(join(TMP, 'tmp'), { recursive: true })

const env = {
  ...process.env,
  LUTRINH_DATA_DIR: data,
  TMPDIR: join(TMP, 'tmp'),
  UV_CACHE_DIR: join(TMP, 'uv-cache'),
  UV_PYTHON_INSTALL_DIR: join(TMP, 'python'),
  PATH: `${join(TMP, 'uv-venv', 'bin')}:${process.env.PATH}`,
}
const uv = (args, input) =>
  execFileSync('uv', ['run', ...args], { cwd: server, env, input, encoding: 'utf8' })

uv(['alembic', 'upgrade', 'head'])
const password = 'e2e-mat-khau-' + Math.random().toString(36).slice(2, 12)
const out = uv(['lutrinh', 'admin', 'create', '--password-stdin'], password + '\n')
const secret = /Khóa nhập tay: (\S+)/.exec(out)?.[1]
const backup = out
  .split('\n')
  .map((l) => l.trim())
  .filter((l) => /^[A-Za-z0-9-]{10,12}$/.test(l))
if (!secret) throw new Error('no TOTP secret in `lutrinh admin create` output')
writeFileSync(
  join(ROOT, 'current.json'),
  JSON.stringify({ data, password, secret, backup, port: PORT }),
)

const child = spawn('uv', ['run', 'lutrinh', 'serve', '--port', PORT], {
  cwd: server,
  env,
  stdio: 'inherit',
})
const stop = () => child.kill('SIGTERM')
process.on('SIGTERM', stop)
process.on('SIGINT', stop)
child.on('exit', (code) => process.exit(code ?? 0))
