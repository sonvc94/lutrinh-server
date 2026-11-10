"""``purge.trash`` and ``purge.iplog`` (page 06 §3, page 04 "Thùng rác", D-14).

* ``purge.trash {routeId, mediaIds}`` (queued by "xóa hẳn", ``services.routes.purge``): the
  route's rows are already gone; this removes its media rows that no draft uses and every file
  (photo, preview, video, leftover upload) whose sha256 no media row and no published version
  (``version_media``) still names.
* ``purge.trash {sweep: true}`` (nightly): routes in the trash for ``trash_days`` are purged as
  "xóa hẳn" does (codes retired, audit ``route.purge`` by ``worker``), which queues the above.
* ``purge.iplog {}`` (nightly): IP events and locks after ``iplog_days``, download tokens a day
  after they expired (``services.limits.purge_old``).
"""

from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from lutrinh.db.models import Media, Route, Upload, VersionMedia
from lutrinh.jobs import Context, Payload, Result
from lutrinh.services import audit, limits, uploads
from lutrinh.services import media as media_service
from lutrinh.services import routes as route_service

ACTOR = "worker"


def handle_iplog(ctx: Context, payload: Payload) -> Result:
    now = ctx.clock()
    with ctx.sessions() as session:
        limits.purge_old(session, ctx.settings, now)
        session.commit()
    return {"before": (now - timedelta(days=ctx.settings.iplog_days)).isoformat()}


def sweep(ctx: Context) -> Result:
    now = ctx.clock()
    cutoff = now - timedelta(days=ctx.settings.trash_days)
    purged = []
    with ctx.sessions() as session:
        ids = session.scalars(
            select(Route.id).where(Route.deleted_at.is_not(None), Route.deleted_at < cutoff)
        ).all()
        for route_id in ids:
            job = route_service.purge(session, route_id, now=now)
            job.created_at = job.run_at = now
            audit.record(
                session,
                "route.purge",
                route_id=route_id,
                actor=ACTOR,
                after={"jobId": job.id, "trashDays": ctx.settings.trash_days},
                now=now,
            )
            purged.append(route_id)
        session.commit()
    return {"purged": purged}


def remove_media(ctx: Context, media_ids: list[str]) -> Result:
    settings = ctx.settings
    removed: list[str] = []
    files: list[Path] = []
    with ctx.sessions() as session:
        candidates: dict[str, str] = {}
        for media_id in media_ids:
            row = session.get(Media, media_id)
            if row is None or media_service.used_by(session, media_id):
                continue
            if row.sha256:
                candidates[row.sha256] = row.type
            upload = session.get(Upload, media_id)
            if upload is not None:
                session.delete(upload)
            session.delete(row)
            removed.append(media_id)
        session.flush()
        for sha, kind in candidates.items():
            in_media = session.scalars(select(Media.id).where(Media.sha256 == sha).limit(1))
            in_version = session.scalars(
                select(VersionMedia.sha256).where(VersionMedia.sha256 == sha).limit(1)
            )
            if in_media.first() is None and in_version.first() is None:
                files.append(media_service.file_path(settings, sha, kind))
                if kind == "photo":
                    files.append(media_service.thumb_path(settings, sha))
        session.commit()
    for path in files:
        path.unlink(missing_ok=True)
    for media_id in removed:
        shutil.rmtree(uploads.directory(settings, media_id), ignore_errors=True)
    return {"media": removed, "files": [p.name for p in files]}


def handle_trash(ctx: Context, payload: Payload) -> Result:
    if payload.get("sweep"):
        return sweep(ctx)
    return remove_media(ctx, [str(m) for m in payload.get("mediaIds") or []])
