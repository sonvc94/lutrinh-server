"""Public API under ``/api/v1`` (page 03 "Công khai /api/v1"): no login, rate limited.

* ``GET /codes/{code}`` → summary + a 2-hour ``downloadToken``.
* ``GET /dl/{token}/route`` → that version's ``route.json`` (ETag = its sha256).
* ``GET /dl/{token}/media/{sha256}`` → one file of that version, with Range (206) and
  ``Cache-Control: immutable``; ``?w=640`` → the ≤ 640 px preview when there is one. With
  ``media_accel`` on, Python only checks the token and answers ``X-Accel-Redirect`` for
  Caddy/Nginx (page 06 §4); otherwise it sends the file itself.
* ``POST /updates`` → status of ≤ 50 downloaded routes.
* ``GET /meta`` → format versions, minimum app versions, maintenance (stays 200 in maintenance;
  every other route then answers 503 ``maintenance``).

Limits and counters: ``services.limits``. Errors use the envelope of ``api.errors``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from lutrinh.api.deps import DbDep, MailerDep, SettingsDep
from lutrinh.config import Settings
from lutrinh.core import canonical_json
from lutrinh.db.models import VersionMedia
from lutrinh.services import codes as code_service
from lutrinh.services import downloads, limits, media
from lutrinh.services.errors import ServiceError

PREFIX = "/api/v1"
IMMUTABLE = "public, max-age=31536000, immutable"
_SHA = re.compile(r"^[0-9a-f]{64}$")

router = APIRouter(prefix=PREFIX, tags=["public"])


def _now(request: Request) -> datetime:
    clock: Callable[[], datetime] = request.app.state.clock
    return clock()


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _open(settings: Settings) -> None:
    if settings.maintenance:
        raise ServiceError(503, "maintenance", settings.maintenance_message or "")


NowDep = Annotated[datetime, Depends(_now)]
IpDep = Annotated[str, Depends(_ip)]
AcceptDep = Annotated[str | None, Header()]


@router.get("/meta")
def meta(settings: SettingsDep) -> dict[str, Any]:
    return {
        "formatVersions": downloads.FORMAT_VERSIONS,
        "minAppVersion": {"android": settings.min_app_android, "ios": settings.min_app_ios},
        "maintenance": settings.maintenance,
        "message": settings.maintenance_message,
    }


@router.get("/codes/{code}")
def lookup_code(
    code: str,
    db: DbDep,
    settings: SettingsDep,
    mailer: MailerDep,
    now: NowDep,
    ip: IpDep,
    accept: AcceptDep = None,
) -> dict[str, Any]:
    _open(settings)
    limits.check_lookup(db, settings, ip, now)
    try:
        found = code_service.lookup(db, code, now=now)
    except ServiceError as exc:
        failed = exc.status in (400, 404)
        limits.record_lookup(db, settings, mailer, ip, now, failed=failed, route_id=None)
        db.commit()
        raise
    limits.record_lookup(
        db, settings, mailer, ip, now, failed=False, route_id=found.version.route_id
    )
    db.commit()
    downloads.check_format(
        canonical_json.loads(found.version.route_json), downloads.accepted_format(accept)
    )
    token = downloads.issue_token(db, settings, found, now)
    body = downloads.summary(found, token, settings)
    db.commit()
    return body


@router.get("/dl/{token}/route")
def download_route(
    token: str,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    mailer: MailerDep,
    now: NowDep,
    ip: IpDep,
    accept: AcceptDep = None,
) -> Response:
    _open(settings)
    limits.check_quota(db, settings, now)
    opened = downloads.open_token(db, token, now)
    version = opened.version
    document = canonical_json.loads(version.route_json)
    downloads.check_format(document, downloads.accepted_format(accept))
    limits.record_route_download(db, settings, ip, opened.token.code, now)
    etag = f'"{version.sha256}"'
    if request.headers.get("if-none-match") == etag:
        db.commit()
        return Response(status_code=304, headers={"ETag": etag})
    limits.count_day(db, "download", version.route_id, now)
    limits.add_bytes(db, settings, mailer, len(version.route_json), now)
    db.commit()
    return Response(
        version.route_json,
        media_type=f"{downloads.ROUTE_MEDIA_TYPE};v={document['formatVersion']}",
        headers={"ETag": etag},
    )


def _range_length(header: str | None, size: int) -> int:
    """Bytes a single ``Range: bytes=a-b`` asks for; anything else counts as the whole file."""
    m = re.fullmatch(r"\s*bytes=(\d*)-(\d*)\s*", header or "")
    if m is None or (not m.group(1) and not m.group(2)):
        return size
    if not m.group(1):
        return min(int(m.group(2)), size)
    start = int(m.group(1))
    end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
    return max(0, end - start + 1)


@router.get("/dl/{token}/media/{sha256}")
def download_media(
    token: str,
    sha256: str,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    mailer: MailerDep,
    now: NowDep,
    w: Annotated[int | None, Query()] = None,
) -> Response:
    _open(settings)
    limits.check_quota(db, settings, now)
    opened = downloads.open_token(db, token, now)
    row = opened.token
    belongs = _SHA.fullmatch(sha256) is not None and db.scalar(
        select(VersionMedia.sha256).where(
            VersionMedia.route_id == row.route_id,
            VersionMedia.version == row.version,
            VersionMedia.sha256 == sha256,
        )
    )
    if not belongs:
        raise ServiceError(404, "not_found", sha256)
    if row.media_used >= row.media_limit:
        db.rollback()
        raise ServiceError(429, "rate_limited", "token used up: look the code up again")
    row.media_used += 1

    path = media.find_file(settings, sha256)
    if path is None:
        db.commit()
        raise ServiceError(404, "not_found", f"{sha256}: file missing on disk")
    if w == 640 and path.suffix == ".jpg":
        thumb = media.thumb_path(settings, sha256)
        if thumb.is_file():
            path = thumb
    size = path.stat().st_size
    limits.add_bytes(db, settings, mailer, _range_length(request.headers.get("range"), size), now)
    db.commit()

    thumb_served = path.name.endswith(media.THUMB_SUFFIX)
    headers = {
        "Cache-Control": IMMUTABLE,
        "ETag": f'"{sha256}-w640"' if thumb_served else f'"{sha256}"',
    }
    content_type = media.CONTENT_TYPE[path.suffix]
    if settings.media_accel:
        rel = path.relative_to(settings.media_dir).as_posix()
        return Response(headers=headers | {"X-Accel-Redirect": f"/{rel}"}, media_type=content_type)
    return FileResponse(path, media_type=content_type, headers=headers)


class UpdateLink(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: str = Field(max_length=32)
    route_id: str = Field(alias="routeId", max_length=40)
    version: int = Field(ge=1)


@router.post("/updates")
def updates(links: list[UpdateLink], db: DbDep, settings: SettingsDep, now: NowDep) -> JSONResponse:
    _open(settings)
    if len(links) > downloads.MAX_UPDATE_LINKS:
        raise ServiceError(400, "too_many", f"at most {downloads.MAX_UPDATE_LINKS} links")
    results = [downloads.check_update(db, x.code, x.route_id, x.version, now) for x in links]
    return JSONResponse({"results": results})
