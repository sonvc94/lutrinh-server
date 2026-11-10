# lutrinh-server

Route server for the Lữ Trình app. The admin writes routes, publishes them as immutable
versions, and each route gets one code `XXXX-XXXX`; app users type the code to download the
route onto their phone.

| Path | What | State |
| --- | --- | --- |
| `spec/` | The `lutrinh-route` package format (formatVersion 1): JSON Schema, code vectors, canonical-JSON vectors, package vectors, a sample package. The Android app and the server both test against it. | done |
| `server/` | Python 3.12 + uv: settings, SQLAlchemy models + Alembic, `core/` (codes, package, canonical JSON, polyline6, rules, GPX, app backup), services, admin API (`/admin/api/v1`), public API (`/api/v1`), job worker (`lutrinh worker`: photos, videos, road legs, purges), `lutrinh` CLI. | admin API, public API, worker done |
| `admin/` | Admin web: TypeScript + React + MapLibre (Vite SPA, built to `admin/dist`, served at `/admin`): login, route list, editor, media, publish/code, import, trash. | done (media thumbnails wait for a server bytes endpoint) |
| `deploy/` | Docker Compose (app, worker, Caddy; cloudflared/restic profiles), Caddyfile (domain HTTPS / LAN http / Cloudflare Tunnel), `bootstrap.sh`, `backup.sh` (restic), runbook `deploy/README.md` (Vietnamese). | done locally; host details pending |

Approved design: the review set `lutrinh-route-server-design` (pages 02 data, 03 API, 06 stack,
07 decisions). Build/test commands and traps: `AGENTS.md`. Package format: `spec/README.md`.
