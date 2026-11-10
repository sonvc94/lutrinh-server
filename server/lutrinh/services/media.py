"""Photos and videos (page 03 ``/media``, page 04 "Ảnh/video").

An upload creates a media row (``uploading``); completing it queues ``media.image`` or
``media.video`` (status ``processing``). The worker (a later task) strips EXIF/GPS, resizes or
transcodes, stores ``media/ab/cd/<sha256>`` and marks the row ``ready``. A media row used by a
draft cannot be removed; published versions keep their files by sha256 (``version_media``).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from lutrinh.config import Settings
from lutrinh.core import ids, package
from lutrinh.db.models import Draft, Job, Media, Route
from lutrinh.services import jobs, uploads
from lutrinh.services.errors import ServiceError, not_found

_PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
_VIDEO_EXT = {".mp4", ".mov", ".m4v", ".3gp", ".webm"}
# Processed files on disk (page 06 §4): photos are JPEG, videos H.264 MP4.
FILE_EXT = {"photo": ".jpg", "video": ".mp4"}
CONTENT_TYPE = {".jpg": "image/jpeg", ".mp4": "video/mp4"}
THUMB_SUFFIX = ".w640.jpg"


def relative_path(sha256: str, ext: str) -> str:
    """``ab/cd/<sha256><ext>`` under ``media/`` (two directory levels, page 06 §4)."""
    return f"{sha256[:2]}/{sha256[2:4]}/{sha256}{ext}"


def file_path(settings: Settings, sha256: str, kind: str) -> Path:
    return settings.media_dir / relative_path(sha256, FILE_EXT[kind])


def thumb_path(settings: Settings, sha256: str) -> Path:
    """The ≤ 640 px preview of a photo (made by the worker, or by ``seed-sample``)."""
    return settings.media_dir / relative_path(sha256, THUMB_SUFFIX)


def find_file(settings: Settings, sha256: str) -> Path | None:
    """The processed file of ``sha256`` (photo or video), or None when it is not on disk."""
    for ext in FILE_EXT.values():
        path = settings.media_dir / relative_path(sha256, ext)
        if path.is_file():
            return path
    return None


def media_type(filename: str, content_type: str | None) -> str:
    ct = (content_type or "").lower()
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ct.startswith("image/") or (not ct and ext in _PHOTO_EXT):
        return "photo"
    if ct.startswith("video/") or (not ct and ext in _VIDEO_EXT):
        return "video"
    raise ServiceError(415, "unsupported_media_type", content_type or filename)


def get(session: Session, media_id: str) -> Media:
    row = session.get(Media, media_id)
    if row is None:
        raise not_found("media", media_id)
    return row


def create(
    session: Session,
    settings: Settings,
    *,
    route_id: str | None,
    filename: str,
    content_type: str | None,
    size: int,
) -> Media:
    if route_id is not None:
        route = session.get(Route, route_id)
        if route is None:
            raise not_found("route", route_id)
        if route.deleted_at is not None:
            raise ServiceError(409, "route_deleted", route_id)
    kind = media_type(filename, content_type)
    row = Media(
        id=ids.new_media_id(),
        route_id=route_id,
        type=kind,
        status="uploading",
        original_name=filename,
    )
    session.add(row)
    session.flush()
    uploads.start(
        session,
        settings,
        upload_id=row.id,
        purpose="media",
        filename=filename,
        content_type=content_type,
        size=size,
        max_bytes=settings.media_max_bytes,
    )
    return row


def queue_processing(session: Session, settings: Settings, row: Media) -> Job:
    row.status = "processing"
    path = uploads.original_path(settings, row.id).relative_to(settings.data_dir)
    kind = "media.video" if row.type == "video" else "media.image"
    return jobs.enqueue(session, kind, {"mediaId": row.id, "path": str(path)}, dedupe=True)


def complete(
    session: Session, settings: Settings, media_id: str, *, now: datetime | None = None
) -> tuple[Media, Job]:
    row = get(session, media_id)
    if row.status != "uploading":
        raise ServiceError(409, "upload_complete", media_id)
    uploads.complete(session, settings, uploads.get(session, media_id), now=now)
    return row, queue_processing(session, settings, row)


def list_media(session: Session, route_id: str | None) -> list[Media]:
    stmt = select(Media).order_by(Media.created_at)
    if route_id is not None:
        stmt = stmt.where(Media.route_id == route_id)
    return list(session.scalars(stmt))


def set_credit(session: Session, media_id: str, credit: str | None) -> Media:
    row = get(session, media_id)
    row.credit = credit.strip() or None if credit is not None else None
    session.flush()
    return row


def used_by(session: Session, media_id: str) -> list[str]:
    """Routes whose draft uses this media (stop media or cover)."""
    return [
        d.route_id
        for d in session.scalars(select(Draft))
        if media_id in package.referenced_media_ids(d.body)
    ]


def remove(session: Session, settings: Settings, media_id: str) -> None:
    row = get(session, media_id)
    users = used_by(session, media_id)
    if users:
        raise ServiceError(409, "media_in_use", ", ".join(users), routes=users)
    session.delete(row)
    uploads.remove(session, settings, media_id)
    session.flush()
