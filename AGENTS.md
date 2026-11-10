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
- `lutrinh/db/` — `models.py` (routes, drafts, route_versions, version_media, codes, media, jobs), `engine.py` (SQLite WAL + foreign keys), `migrations/` (Alembic; `alembic.ini` in `server/`).
- `lutrinh/services/publishing.py` — `publish_draft(session, route_id)` → next immutable version.
- Later tasks plug in as `lutrinh/api/{public,admin}.py`, `lutrinh/jobs/worker.py`, `lutrinh/adapters/{routing,storage,mail}/` (page 06 §1).
- `tests/spec/` read the `spec/` files; `tests/core/` test the modules. `scripts/make_spec_sample.py` regenerates the sample package.

## Rules and traps

- `spec/` is the contract with the app. Changing a vector, the schema or the sample is a spec change; regenerate with the scripts, never hand-edit `samples/*/route.json` (it must stay canonical bytes; the test `test_sample_read_then_write_is_byte_identical` catches drift).
- `route_versions` rows are immutable (ORM `before_update` raises `ImmutableVersionError`); republishing an old version means a new row.
- Datetimes are aware UTC (`UTCDateTime`); a naive datetime raises on bind.
- Migrations never import models (`env.py` renders `UTCDateTime` as `sa.DateTime()`); after a model change: `uv run alembic revision --autogenerate -m "…"`, review, then `alembic check` must say "No new upgrade operations detected." Never write destructive migrations.
- Media rows need an ORM `relationship` to `Route`; without one SQLAlchemy may insert the child first and SQLite's foreign key check fails.
- Canonical JSON reads numbers as doubles: an integer beyond 2^53−1 reads as a float. The server must not write such integers (`dumps` raises).
- `codes` keeps revoked codes for ever (never reissued); a partial unique index allows one live code per route.
