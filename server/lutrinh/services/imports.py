"""Imports (page 03 ``/imports``, page 04 E): GPX or an app backup → preview → a new route.

Upload the file in chunks (``services.uploads``), complete it (the file is read and a preview
stored, or the import is marked ``failed`` with the reader's error), then apply it: a new route
whose draft is the preview's (GPX) or the chosen trip's (backup). Missing road legs are queued
for ``legs.compute``; backup photos/videos become media rows queued for processing.
Route packages (``.zip``) are not imported yet (Mate decision 1C).
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from lutrinh.config import Settings
from lutrinh.core import backup, gpx
from lutrinh.db.models import Import, Media, Route, utcnow
from lutrinh.services import media as media_service
from lutrinh.services import routes, uploads
from lutrinh.services.errors import ServiceError, not_found

KINDS = ("gpx", "backup")
# A GPX file is read in memory; R25 files are a few MB. Backups use ``import_max_bytes``.
GPX_MAX_BYTES = 50 * 1024 * 1024
WORK = "work"


def get(session: Session, import_id: str) -> Import:
    row = session.get(Import, import_id)
    if row is None:
        raise not_found("import", import_id)
    return row


def create(session: Session, settings: Settings, *, kind: str, filename: str, size: int) -> Import:
    if kind not in KINDS:
        raise ServiceError(422, "invalid_request", f"kind must be one of {', '.join(KINDS)}")
    row = Import(id="imp_" + secrets.token_hex(6), kind=kind, status="uploading", filename=filename)
    session.add(row)
    session.flush()
    uploads.start(
        session,
        settings,
        upload_id=row.id,
        purpose="import",
        filename=filename,
        content_type=None,
        size=size,
        max_bytes=GPX_MAX_BYTES if kind == "gpx" else settings.import_max_bytes,
    )
    return row


def _gpx_preview(settings: Settings, row: Import) -> dict[str, Any]:
    data = uploads.original_path(settings, row.id).read_bytes()
    result = gpx.to_draft(gpx.parse(data), row.filename, ZoneInfo(settings.local_tz))
    d = result.draft
    return {
        "title": d["title"],
        "days": d["days"],
        "stops": len(d["stops"]),
        "stopsFrom": result.stops_from,
        "legsFromTrack": result.legs_from_track,
        "legsToCompute": len(result.compute),
        "draft": d,
    }


def _backup_preview(settings: Settings, row: Import) -> dict[str, Any]:
    folder = uploads.directory(settings, row.id)
    manifest = backup.extract(uploads.original_path(settings, row.id), folder / WORK)
    trips = backup.list_trips(folder / WORK / "lutrinh.db")
    return {
        "schemaVersion": manifest.get("schemaVersion"),
        "appVersion": manifest.get("appVersion"),
        "trips": trips,
    }


def complete(
    session: Session, settings: Settings, import_id: str, *, now: datetime | None = None
) -> Import:
    """Join the chunks and read the file. A file the reader refuses gives ``failed``."""
    row = get(session, import_id)
    if row.status != "uploading":
        raise ServiceError(409, "upload_complete", import_id)
    uploads.complete(session, settings, uploads.get(session, import_id), now=now)
    try:
        row.preview = (
            _gpx_preview(settings, row) if row.kind == "gpx" else _backup_preview(settings, row)
        )
        row.status = "ready"
    except (gpx.GpxError, backup.BackupError) as exc:
        row.status = "failed"
        row.error = {"code": exc.code, "detail": exc.detail}
    session.flush()
    return row


def preview_summary(row: Import) -> dict[str, Any] | None:
    """The preview without the stored draft body."""
    if row.preview is None:
        return None
    return {k: v for k, v in row.preview.items() if k != "draft"}


def apply(
    session: Session,
    settings: Settings,
    import_id: str,
    *,
    trip_id: str | None = None,
    now: datetime | None = None,
) -> Route:
    row = get(session, import_id)
    if row.status == "applied":
        raise ServiceError(409, "import_applied", import_id, routeId=row.route_id)
    if row.status != "ready" or row.preview is None:
        raise ServiceError(409, "import_not_ready", row.status)
    if row.kind == "gpx":
        body = row.preview["draft"]
        route = routes.create(session, body["title"], body)
    else:
        if not trip_id:
            raise ServiceError(422, "invalid_request", "tripId is required for a backup")
        route = _apply_backup(session, settings, row, trip_id)
    row.status = "applied"
    row.route_id = route.id
    row.applied_at = now or utcnow()
    session.flush()
    return route


def _apply_backup(session: Session, settings: Settings, row: Import, trip_id: str) -> Route:
    folder = uploads.directory(settings, row.id)
    try:
        trip = backup.trip_draft(folder / WORK / "lutrinh.db", trip_id)
    except backup.BackupError as exc:
        status = 404 if exc.code == "trip_not_found" else 422
        raise ServiceError(status, exc.code, exc.detail) from exc
    zip_path = uploads.original_path(settings, row.id)
    body = trip.draft
    copied = set()
    for item in trip.media:
        dest = uploads.original_path(settings, item.media_id)
        if backup.copy_media_file(zip_path, item.file_name, dest):
            copied.add(item.media_id)
    for stop in body["stops"]:
        stop["media"] = [m for m in stop["media"] if m in copied]
    if body.get("cover") not in copied:
        body["cover"] = None
    route = routes.create(session, body["title"], body)
    for item in trip.media:
        if item.media_id not in copied:
            continue
        m = Media(
            id=item.media_id,
            route_id=route.id,
            type=item.type,
            status="processing",
            original_name=item.file_name,
            duration_ms=item.duration_ms,
        )
        session.add(m)
        session.flush()
        media_service.queue_processing(session, settings, m)
    return route
