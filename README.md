# lutrinh-server

Route server for the Lữ Trình app. The admin writes routes, publishes them as immutable
versions, and each route gets one code `XXXX-XXXX`; app users type the code to download the
route onto their phone.

| Path | What | State |
| --- | --- | --- |
| `spec/` | The `lutrinh-route` package format (formatVersion 1): JSON Schema, code vectors, canonical-JSON vectors, package vectors, a sample package. The Android app and the server both test against it. | done |
| `server/` | Python 3.12 + uv: settings, SQLAlchemy models + Alembic, `core/` (codes, package, canonical JSON, polyline6), publishing service. | core only; no HTTP API, auth or worker yet |
| `admin/` | Admin web: TypeScript + React + MapLibre | not started |
| `deploy/` | Docker Compose + Caddy, backups | not started |

Approved design: the review set `lutrinh-route-server-design` (pages 02 data, 03 API, 06 stack,
07 decisions). Build/test commands and traps: `AGENTS.md`. Package format: `spec/README.md`.
