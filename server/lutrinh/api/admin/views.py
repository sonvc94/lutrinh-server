"""Row → response model conversions shared by the admin routers."""

from __future__ import annotations

from sqlalchemy.orm import Session

from lutrinh.api.admin import schemas as s
from lutrinh.config import Settings
from lutrinh.core import codes
from lutrinh.core.package import Problem
from lutrinh.db.models import Code, Import, Job, Media, RouteVersion, Upload
from lutrinh.services import routes, uploads
from lutrinh.services.imports import preview_summary


def problems(items: list[Problem]) -> list[s.Problem]:
    return [s.Problem(code=p.code, path=p.path, message=p.message) for p in items]


def route_out(session: Session, route_id: str) -> s.RouteOut:
    return summary_out(routes.summarise(session, routes.get(session, route_id)))


def summary_out(sm: routes.Summary) -> s.RouteOut:
    r = sm.route
    return s.RouteOut(
        id=r.id,
        title=sm.title,
        status=sm.status,  # type: ignore[arg-type]
        latest_version=sm.latest_version,
        published_at=sm.published_at,
        draft_changed=sm.draft_changed,
        code=codes.display(sm.code) if sm.code else None,
        stops=sm.stops,
        created_at=r.created_at,
        updated_at=r.updated_at,
        deleted_at=r.deleted_at,
    )


def job_out(job: Job) -> s.JobOut:
    return s.JobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,
        progress=job.progress,
        result=job.result,
        error=job.error,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


def version_out(v: RouteVersion) -> s.VersionOut:
    return s.VersionOut(
        version=v.version,
        sha256=v.sha256,
        published_at=v.published_at,
        note=v.note,
        bytes=len(v.route_json),
        media_bytes=v.media_bytes,
        media_files=v.media_files,
        source_version=v.source_version,
    )


def code_out(c: Code) -> s.CodeOut:
    return s.CodeOut(
        code=codes.display(c.code),
        route_id=c.route_id,
        created_at=c.created_at,
        expires_at=c.expires_at,
        revoked_at=c.revoked_at,
        revoke_reason=c.revoke_reason,
        live=c.revoked_at is None,
    )


def upload_state(settings: Settings, up: Upload | None) -> s.UploadState | None:
    if up is None:
        return None
    return s.UploadState(
        bytes=up.bytes,
        chunk_bytes=up.chunk_bytes,
        chunks=uploads.chunk_count(up),
        received=uploads.received(settings, up),
        sha256=up.sha256,
        completed_at=up.completed_at,
    )


def media_out(session: Session, settings: Settings, m: Media) -> s.MediaOut:
    up = session.get(Upload, m.id)
    return s.MediaOut(
        id=m.id,
        route_id=m.route_id,
        type=m.type,
        status=m.status,
        sha256=m.sha256,
        bytes=m.bytes,
        width=m.width,
        height=m.height,
        duration_ms=m.duration_ms,
        credit=m.credit,
        original_name=m.original_name,
        error=m.error,
        created_at=m.created_at,
        upload=upload_state(settings, up) if m.status == "uploading" else None,
    )


def import_out(session: Session, settings: Settings, row: Import) -> s.ImportOut:
    up = session.get(Upload, row.id)
    return s.ImportOut(
        id=row.id,
        kind=row.kind,
        status=row.status,
        filename=row.filename,
        preview=preview_summary(row),
        error=row.error,
        route_id=row.route_id,
        created_at=row.created_at,
        applied_at=row.applied_at,
        upload=upload_state(settings, up) if row.status == "uploading" else None,
    )
