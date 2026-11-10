# AGENTS.md — lutrinh-server

Route server for the Lữ Trình app (Python). Read `README.md` for the layout, `spec/README.md`
for the package/code rules. The approved design (D-1…D-23) is the review set
`/Volumes/wdblack/tmp/lutrinh-route-server-design/` (02 data, 03 API, 06 stack, 07 decisions and
the build split `#build`); the app's data model is `polarsteps-clone-native/docs/02-data-model.md`.

## Setup (macOS dev machine)

All build output, caches and scratch go under `/Volumes/wdblack/tmp`, never `/tmp` or
`~/.cache`. uv is not installed system-wide; it lives in a venv under `/Volumes/wdblack/tmp`.

```sh
export LUTRINH_TMP=/Volumes/wdblack/tmp/lutrinh-server && mkdir -p $LUTRINH_TMP/tmp
export TMPDIR=$LUTRINH_TMP/tmp UV_CACHE_DIR=$LUTRINH_TMP/uv-cache UV_PYTHON_INSTALL_DIR=$LUTRINH_TMP/python
# uv once, if `uv` is not on PATH (no sudo):
[ -x $LUTRINH_TMP/uv-venv/bin/uv ] || { python3 -m venv $LUTRINH_TMP/uv-venv && $LUTRINH_TMP/uv-venv/bin/pip install -q uv; }
export PATH=$LUTRINH_TMP/uv-venv/bin:$PATH
cd server && uv sync          # downloads Python 3.12 into UV_PYTHON_INSTALL_DIR, venv in server/.venv (gitignored)
```

## Gate (run from `server/`)

```sh
uv run pytest -q                       # everything: tests/spec (spec vectors) + tests/core
uv run pytest tests/spec tests/core -q # the same, explicit
uv run ruff check . && uv run ruff format --check . && uv run mypy
# migrations on a fresh file (a directory, not a `check.sqlite*` glob: zsh aborts on no match):
rm -rf $LUTRINH_TMP/check && mkdir -p $LUTRINH_TMP/check && export LUTRINH_DATABASE_URL=sqlite:///$LUTRINH_TMP/check/lutrinh.sqlite
uv run alembic upgrade head && uv run alembic check   # → "No new upgrade operations detected."
unset LUTRINH_DATABASE_URL
```

## Layout (server/)

- `lutrinh/config.py` — `LUTRINH_DATA_DIR` (default `/var/lib/lutrinh`), `LUTRINH_DATABASE_URL`, `LUTRINH_SPEC_DIR` (default repo `spec/`).
- `lutrinh/core/` — pure, no DB: `codes.py` (generate/normalise/parse, Luhn mod 30), `canonical_json.py` (RFC 8785), `package.py` (draft → `route.json`, schema + integrity check, `read`), `polyline.py`, `ids.py`.
- `lutrinh/db/` — `models.py` (routes, drafts, route_versions, version_media, codes, media, jobs; public API: download_tokens, ip_events, ip_locks, alarms, monthly_bytes, daily_counts), `engine.py` (SQLite WAL + foreign keys), `migrations/` (Alembic; `alembic.ini` in `server/`).
- `lutrinh/core/` also: `rules.py` (publish blockers/warnings, size limits), `gpx.py` (defusedxml reader → draft), `dwell.py` (stays in a track), `backup.py` (app backup → draft), `geo.py`.
- `lutrinh/services/` — `publishing.py` (`publish_draft`, `preflight`, `publish`, `unpublish`, `republish`), `codes.py` (issue/revoke/reissue/`lookup`), `routes.py` (CRUD, draft If-Match, legs, trash/purge), `uploads.py` + `media.py` + `imports.py` (chunked upload → media/GPX/backup), `auth.py` (Argon2id + TOTP + backup codes, sessions, lockout), `audit.py`, `jobs.py` (enqueue only), `errors.py` (`ServiceError`). Public side: `downloads.py` (tokens, summary, update check, Accept `v=`), `limits.py` (IP rate limits + lock ladder, alarm, bandwidth, daily counts, 14-day purge), `seed.py` (`seed-sample`: spec sample + ffmpeg placeholder media → published route).
- `lutrinh/api/` — `app.py` (`create_app`; `/openapi.json`; `/admin` serves `admin_dist_dir` or a placeholder), `deps.py` (session cookie `__Host-lt_session`, CSRF), `errors.py` (error envelope), `admin/` (routers under `/admin/api/v1`), `public.py` (`/api/v1`: meta, codes, dl route/media with Range, updates). `lutrinh/cli.py` — `uv run lutrinh admin create|reset` (prints TOTP URI + backup codes), `seed-sample`, `serve [--host --port]`.
- `lutrinh/adapters/mail/` — `Mailer` + log-only adapter. `adapters/routing/` — `Router` protocol, `Routers` (Valhalla first, OSRM car-only fallback when Valhalla is unavailable) + `Throttle` (≥ 1 s between calls); `valhalla.py`, `osrm.py` are the only modules that know those APIs; URLs/User-Agent in `config.py`. Later: `adapters/storage/` (page 06 §1).
- `lutrinh/jobs/` — `worker.py` (`lutrinh worker [--once]` = `python -m lutrinh.jobs.worker`: compare-and-set claim, retry 30 s × 2ⁿ ≤ 10 min up to `jobs.max_attempts`, `PermanentError` = no retry, stale `running` reclaimed after 60 min, nightly `purge.iplog` + trash sweep), `media.py` (Pillow: upright, ≤ 2560 px, JPEG 85, no EXIF/GPS/XMP, `.w640.jpg`; ffprobe/ffmpeg: > 60 s refused, H.264 short side ≤ 720, ≤ 30 fps, AAC, faststart, metadata stripped, no poster), `legs.py` (R36: car fallback → `usedProfile: car`, 500 m / 5× guard → `too_far`, ~10 m simplify, CAS on `drafts.revision`), `purge.py` (media rows/files no draft/version uses; 30-day trash sweep; IPs/tokens).
- `tests/spec/` read the `spec/` files; `tests/core/` test the modules; `tests/admin/` drive the API with `TestClient`; `tests/public/` the public API and CLI. `scripts/make_spec_sample.py` regenerates the sample package.

## Chạy thử trên máy (localhost)

Run from `server/` after Setup. The public API contract and the Mate decisions behind it are in
`spec/README.md` "Public API `/api/v1`". `seed-sample` needs `ffmpeg` on PATH (placeholder media).

```sh
export LUTRINH_DATA_DIR=$LUTRINH_TMP/local && mkdir -p $LUTRINH_DATA_DIR/db   # db/ is not created for you
uv run alembic upgrade head
uv run lutrinh admin create            # once; prints the TOTP URI + backup codes (admin UI not built yet)
uv run lutrinh seed-sample             # prints "Mã: XXXX-XXXX"; each run adds a new published route
uv run lutrinh serve                   # 127.0.0.1:8000; Android emulator: --host 0.0.0.0 → http://10.0.2.2:8000
```

```sh
A='Accept: application/vnd.lutrinh.route+json;v=1'
curl -s localhost:8000/api/v1/meta
curl -s -H "$A" localhost:8000/api/v1/codes/XXXX-XXXX          # → summary + "downloadToken" (2 h)
curl -s -H "$A" localhost:8000/api/v1/dl/<token>/route -o route.json
curl -s -H 'Range: bytes=0-99' localhost:8000/api/v1/dl/<token>/media/<sha256> -o part  # 206
curl -s -X POST -H 'Content-Type: application/json' localhost:8000/api/v1/updates \
  -d '[{"code":"XXXX-XXXX","routeId":"<routeId>","version":1}]'
```

The worker is a second process on the same `LUTRINH_DATA_DIR` (photos, videos, road legs, nightly
purges); without it uploads stay `processing` and legs are never computed. It needs `ffmpeg` and
`ffprobe` on PATH and calls the FOSSGIS routers (Valhalla, OSRM) for legs.

```sh
uv run lutrinh worker                  # second terminal, same exports; Ctrl-C stops after the current job
uv run lutrinh worker --once           # run what is due, then exit
```

Rate limits apply to localhost too (10 failed lookups/hour → 429 lock); delete
`$LUTRINH_DATA_DIR` and start again to reset.

## Rules and traps

- `spec/` is the contract with the app. Changing a vector, the schema or the sample is a spec change; regenerate with the scripts, never hand-edit `samples/*/route.json` (it must stay canonical bytes; the test `test_sample_read_then_write_is_byte_identical` catches drift).
- `route_versions` rows are immutable (ORM `before_update` raises `ImmutableVersionError`); republishing an old version means a new row.
- Datetimes are aware UTC (`UTCDateTime`); a naive datetime raises on bind.
- Migrations never import models (`env.py` renders `UTCDateTime` as `sa.DateTime()`); after a model change: `uv run alembic revision --autogenerate -m "…"`, review, then `alembic check` must say "No new upgrade operations detected." Never write destructive migrations.
- Media rows need an ORM `relationship` to `Route`; without one SQLAlchemy may insert the child first and SQLite's foreign key check fails.
- Canonical JSON reads numbers as doubles: an integer beyond 2^53−1 reads as a float. The server must not write such integers (`dumps` raises).
- `codes` keeps revoked codes for ever (never reissued); a partial unique index allows one live code per route.
- Admin tests use `base_url="https://testserver"`: the `__Host-` cookie is Secure and httpx drops it over http. Argon2 cost is lowered via settings in tests only.
- FastAPI ≥0.16x wraps included routers in `_IncludedRouter` inside `app.routes`; the 401 walker in `tests/admin/test_auth.py` expands them via `effective_route_contexts()` (private API — recheck on upgrades).
- A purged route's codes move to `retired_codes` so a code is never issued twice. Zip package export/import is deferred (Mate decision 1C).
- Worker tests (`tests/jobs/`) use `FakeRouter` (no network) and a `Clock` an hour ahead of real time, because jobs queued by services get `run_at = utcnow()`. `LUTRINH_LIVE_ROUTER=1 uv run pytest tests/jobs -k live` makes one real call to each FOSSGIS router.
- Job handlers open their own short sessions; never hold a transaction across Pillow/ffmpeg/router calls (the API writes the same SQLite file). Draft writes from the worker are compare-and-set on `drafts.revision` and bump it, so an admin holding an old ETag gets 412 after a leg lands.
- Public tests pass `TestClient(app, client=(ip, port))` to vary the IP, and move time through `app.state.clock` (the routers read it; default `utcnow`). Tests mutate the `Settings` object in place to change limits.
