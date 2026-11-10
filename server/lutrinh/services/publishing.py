"""Publish a route's draft as the next immutable version (v1…vN)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lutrinh.core import package
from lutrinh.db.models import Draft, Media, Route, RouteVersion, VersionMedia


class PublishError(ValueError):
    """``code``: route_not_found, route_deleted, no_draft, media_not_ready, invalid_package."""

    def __init__(self, code: str, detail: str = "", problems: list[package.Problem] | None = None):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.problems = problems or []


def _media_info(row: Media) -> package.MediaInfo | None:
    if row.status != "ready" or row.sha256 is None or row.bytes is None:
        return None
    if row.width is None or row.height is None:
        return None
    return package.MediaInfo(
        id=row.id,
        sha256=row.sha256,
        type=row.type,
        bytes=row.bytes,
        w=row.width,
        h=row.height,
        duration_ms=row.duration_ms,
        credit=row.credit,
    )


def publish_draft(
    session: Session, route_id: str, *, note: str | None = None, now: datetime | None = None
) -> RouteVersion:
    """Build the draft into ``route.json`` and store it as version max+1. Caller commits.

    Earlier versions are never touched: their bytes and sha256 stay as published.
    """
    route = session.get(Route, route_id)
    if route is None:
        raise PublishError("route_not_found", route_id)
    if route.deleted_at is not None:
        raise PublishError("route_deleted", route_id)
    draft = session.get(Draft, route_id)
    if draft is None:
        raise PublishError("no_draft", route_id)

    wanted = package.referenced_media_ids(draft.body)
    rows = (
        {m.id: m for m in session.scalars(select(Media).where(Media.id.in_(wanted))).all()}
        if wanted
        else {}
    )
    infos: dict[str, package.MediaInfo] = {}
    not_ready = []
    for mid in wanted:
        row = rows.get(mid)
        info = _media_info(row) if row is not None else None
        if row is not None and info is None:
            not_ready.append(mid)
        elif info is not None:
            infos[mid] = info
    if not_ready:
        raise PublishError("media_not_ready", ", ".join(not_ready))

    current = session.scalar(
        select(func.max(RouteVersion.version)).where(RouteVersion.route_id == route_id)
    )
    version = (current or 0) + 1
    published_at = (now or datetime.now(UTC)).replace(microsecond=0)
    try:
        built = package.build(
            draft.body, route_id=route_id, version=version, published_at=published_at, media=infos
        )
    except package.PackageError as exc:
        raise PublishError("invalid_package", str(exc), exc.problems) from exc

    version_row = RouteVersion(
        route_id=route_id,
        version=version,
        route_json=built.route_json,
        sha256=built.sha256,
        published_at=published_at,
        note=note,
        media_bytes=built.media_bytes,
        media_files=built.media_files,
    )
    session.add(version_row)
    for sha in sorted({m.sha256 for m in built.media}):
        session.add(VersionMedia(route_id=route_id, version=version, sha256=sha))
    session.flush()
    return version_row
