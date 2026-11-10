"""Publish a route's draft as the next immutable version (v1…vN); unpublish; republish.

* ``publish``: draft → package (schema + integrity, ``core.package``) → publish rules
  (``core.rules``) → version max+1; clears "unpublished"; issues a code when the route has no
  live one (Mate decision 4A).
* ``preflight``: the same checks without writing (page 04 D "Kiểm tra trước khi xuất bản").
* ``unpublish``: the route stops being shared; its code lookups answer 410 ``route_unpublished``
  until the next publish. Versions and codes are kept.
* ``republish``: an older version's content becomes version max+1 ("quay lại v2" → v4,
  ``source_version`` = 2). The draft is left as it is (Mate decision 5A).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lutrinh.core import canonical_json, package, rules
from lutrinh.core.package import Problem
from lutrinh.db.models import Code, Draft, Media, Route, RouteVersion, VersionMedia
from lutrinh.services import codes as code_service


class PublishError(ValueError):
    """``code``: route_not_found, route_deleted, no_draft, media_not_ready, invalid_package,
    publish_blocked (``core.rules``), not_published, version_not_found."""

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


@dataclass(frozen=True)
class _Prepared:
    route: Route
    draft: Draft
    version: int
    published_at: datetime
    built: package.BuiltPackage


def _route(session: Session, route_id: str) -> Route:
    route = session.get(Route, route_id)
    if route is None:
        raise PublishError("route_not_found", route_id)
    if route.deleted_at is not None:
        raise PublishError("route_deleted", route_id)
    return route


def _next_version(session: Session, route_id: str) -> int:
    current = session.scalar(
        select(func.max(RouteVersion.version)).where(RouteVersion.route_id == route_id)
    )
    return (current or 0) + 1


def _prepare(session: Session, route_id: str, now: datetime | None) -> _Prepared:
    route = _route(session, route_id)
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
        raise PublishError(
            "media_not_ready",
            ", ".join(not_ready),
            [Problem("media_not_ready", "/media", mid) for mid in not_ready],
        )

    version = _next_version(session, route_id)
    published_at = (now or datetime.now(UTC)).replace(microsecond=0)
    try:
        built = package.build(
            draft.body, route_id=route_id, version=version, published_at=published_at, media=infos
        )
    except package.PackageError as exc:
        raise PublishError("invalid_package", str(exc), exc.problems) from exc
    return _Prepared(route, draft, version, published_at, built)


def _insert(session: Session, p: _Prepared, note: str | None) -> RouteVersion:
    version_row = RouteVersion(
        route_id=p.route.id,
        version=p.version,
        route_json=p.built.route_json,
        sha256=p.built.sha256,
        published_at=p.published_at,
        note=note,
        media_bytes=p.built.media_bytes,
        media_files=p.built.media_files,
    )
    session.add(version_row)
    for sha in sorted({m.sha256 for m in p.built.media}):
        session.add(VersionMedia(route_id=p.route.id, version=p.version, sha256=sha))
    session.flush()
    return version_row


def publish_draft(
    session: Session, route_id: str, *, note: str | None = None, now: datetime | None = None
) -> RouteVersion:
    """Build the draft into ``route.json`` and store it as version max+1. Caller commits.

    Earlier versions are never touched: their bytes and sha256 stay as published. Package checks
    only; ``publish`` adds the publish rules, the route state and the code.
    """
    return _insert(session, _prepare(session, route_id, now), note)


@dataclass(frozen=True)
class Preflight:
    version: int
    blockers: list[Problem]
    warnings: list[Problem]
    media_bytes: int | None
    media_files: int | None


def preflight(
    session: Session, route_id: str, *, long_leg_km: float, now: datetime | None = None
) -> Preflight:
    """What publishing now would refuse or warn about. Writes nothing."""
    try:
        p = _prepare(session, route_id, now)
    except PublishError as exc:
        if exc.code in ("route_not_found", "route_deleted", "no_draft"):
            raise
        problems = exc.problems or [Problem(exc.code, "/", str(exc))]
        return Preflight(_next_version(session, route_id), problems, [], None, None)
    size = len(p.built.route_json)
    return Preflight(
        p.version,
        rules.check_blockers(p.built.document, size),
        rules.check_warnings(p.built.document, size, long_leg_km=long_leg_km),
        p.built.media_bytes,
        p.built.media_files,
    )


@dataclass(frozen=True)
class Published:
    version: RouteVersion
    code: Code
    code_issued: bool
    warnings: list[Problem]


def _share(
    session: Session, route: Route, code_prefix: str | None, now: datetime | None
) -> tuple[Code, bool]:
    route.unpublished_at = None
    live = code_service.live_code(session, route.id)
    if live is not None:
        return live, False
    return code_service.issue(session, route.id, prefix=code_prefix, now=now), True


def publish(
    session: Session,
    route_id: str,
    *,
    long_leg_km: float,
    note: str | None = None,
    code_prefix: str | None = None,
    now: datetime | None = None,
) -> Published:
    """Publish the draft as the next version and share the route. Caller commits."""
    p = _prepare(session, route_id, now)
    size = len(p.built.route_json)
    blockers = rules.check_blockers(p.built.document, size)
    if blockers:
        raise PublishError("publish_blocked", "; ".join(b.code for b in blockers), blockers)
    row = _insert(session, p, note)
    p.route.published_revision = p.draft.revision
    code, issued = _share(session, p.route, code_prefix, now)
    warnings = rules.check_warnings(p.built.document, size, long_leg_km=long_leg_km)
    return Published(row, code, issued, warnings)


def unpublish(session: Session, route_id: str, *, now: datetime | None = None) -> Route:
    route = _route(session, route_id)
    if _next_version(session, route_id) == 1:
        raise PublishError("not_published", route_id)
    if route.unpublished_at is None:
        route.unpublished_at = now or datetime.now(UTC)
    session.flush()
    return route


def republish(
    session: Session,
    route_id: str,
    source_version: int,
    *,
    note: str | None = None,
    now: datetime | None = None,
) -> Published:
    """Publish an older version's content again as version max+1. Caller commits."""
    route = _route(session, route_id)
    source = session.get(RouteVersion, (route_id, source_version))
    if source is None:
        raise PublishError("version_not_found", f"{route_id} v{source_version}")
    version = _next_version(session, route_id)
    published_at = (now or datetime.now(UTC)).replace(microsecond=0)
    document = canonical_json.loads(source.route_json)
    document["route"]["version"] = version
    document["route"]["publishedAt"] = package.format_timestamp(published_at)
    data = canonical_json.dumps(document)
    row = RouteVersion(
        route_id=route_id,
        version=version,
        route_json=data,
        sha256=package.sha256_hex(data),
        published_at=published_at,
        note=note,
        media_bytes=source.media_bytes,
        media_files=source.media_files,
        source_version=source_version,
    )
    session.add(row)
    for f in source.files:
        session.add(VersionMedia(route_id=route_id, version=version, sha256=f.sha256))
    session.flush()
    route.published_revision = None  # the live version no longer matches the draft
    code, issued = _share(session, route, None, now)
    return Published(row, code, issued, [])
