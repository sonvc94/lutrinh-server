"""FastAPI app factory: the admin API, the admin web app's files and ``/openapi.json``.

``/admin`` serves the built React app (``admin/dist``, setting ``admin_dist_dir``; a later
task) with ``index.html`` for every client-side path; until it is built a placeholder page is
served. ``/openapi.json`` is the contract the React client is generated from. The public API
(``/api/v1``) is a later task.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy import Engine

from lutrinh.adapters.mail import LogMailer, Mailer
from lutrinh.api import errors
from lutrinh.api.admin import PREFIX, build_router
from lutrinh.config import Settings, get_settings
from lutrinh.db.engine import make_engine, make_sessionmaker
from lutrinh.services.errors import ServiceError

PLACEHOLDER = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><title>Lữ Trình – quản trị</title></head>
<body><h1>Lữ Trình – quản trị</h1>
<p>Web quản trị chưa được build (admin/dist). API: <code>/admin/api/v1</code>,
mô tả: <code>/openapi.json</code>.</p></body></html>
"""


def _admin_file(dist: Path, path: str) -> Response:
    if path.startswith("api/") or path == "api":
        raise ServiceError(404, "not_found", f"/admin/{path}")
    index = dist / "index.html"
    if not index.is_file():
        return HTMLResponse(PLACEHOLDER)
    root = dist.resolve()
    target = (root / path).resolve()
    if path and target.is_relative_to(root) and target.is_file():
        return FileResponse(target)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app(
    settings: Settings | None = None,
    *,
    engine: Engine | None = None,
    mailer: Mailer | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    engine = engine or make_engine(settings.db_url)
    app = FastAPI(
        title="Lữ Trình route server",
        version="1",
        openapi_url="/openapi.json",
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.mailer = mailer or LogMailer()
    errors.install(app)
    app.include_router(build_router())

    @app.get("/admin", include_in_schema=False)
    def admin_index() -> Response:
        return _admin_file(settings.admin_dist_dir, "")

    @app.get("/admin/{path:path}", include_in_schema=False)
    def admin_files(path: str) -> Response:
        return _admin_file(settings.admin_dist_dir, path)

    return app


__all__ = ["PREFIX", "create_app"]
