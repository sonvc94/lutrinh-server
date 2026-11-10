"""Route codes (page 02 "Mã lộ trình", D-1…D-3 A).

* One live code per route, always pointing at the route's latest version (D-2 A).
* No expiry by default; the admin may set one per code (D-3 A, page 03 ``PATCH /codes``).
* Revoking is immediate; a revoked code is kept for ever and never issued again (also after its
  route is purged: ``retired_codes``). A new code can be issued after a revoke.
* ``lookup`` is the rule the public API (later task) answers with: revoked → 410
  ``code_revoked``, expired → 410 ``code_expired``, route unpublished or in the trash → 410
  ``route_unpublished``. Versions and copies already downloaded are not touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from lutrinh.core import codes
from lutrinh.db.models import Code, RetiredCode, Route, RouteVersion, utcnow
from lutrinh.services.errors import ServiceError, not_found

_MAX_TRIES = 50


def live_code(session: Session, route_id: str) -> Code | None:
    return session.scalar(select(Code).where(Code.route_id == route_id, Code.revoked_at.is_(None)))


def _taken(session: Session, code: str) -> bool:
    return session.get(Code, code) is not None or session.get(RetiredCode, code) is not None


def issue(
    session: Session,
    route_id: str,
    *,
    prefix: str | None = None,
    expires_at: datetime | None = None,
    now: datetime | None = None,
) -> Code:
    """New live code for a route that has none. Caller commits."""
    route = session.get(Route, route_id)
    if route is None:
        raise not_found("route", route_id)
    if route.deleted_at is not None:
        raise ServiceError(409, "route_deleted", route_id)
    if live_code(session, route_id) is not None:
        raise ServiceError(409, "code_exists", "revoke the live code first")
    try:
        for _ in range(_MAX_TRIES):
            candidate = codes.generate(prefix)
            if not _taken(session, candidate):
                break
        else:
            raise ServiceError(409, "code_space_exhausted", f"prefix {prefix}")
    except ValueError as exc:
        raise ServiceError(422, "bad_prefix", str(exc)) from exc
    row = Code(code=candidate, route_id=route_id, created_at=now or utcnow(), expires_at=expires_at)
    session.add(row)
    session.flush()
    return row


def get(session: Session, raw: str) -> Code:
    try:
        code = codes.parse(raw)
    except codes.CodeError as exc:
        raise ServiceError(400, exc.kind, str(exc)) from exc
    row = session.get(Code, code)
    if row is None:
        raise not_found("code", raw)
    return row


def revoke(
    session: Session, raw: str, *, reason: str | None = None, now: datetime | None = None
) -> Code:
    row = get(session, raw)
    if row.revoked_at is not None:
        raise ServiceError(409, "code_revoked", codes.display(row.code))
    row.revoked_at = now or utcnow()
    row.revoke_reason = reason
    session.flush()
    return row


def set_expiry(session: Session, raw: str, expires_at: datetime | None) -> Code:
    row = get(session, raw)
    if row.revoked_at is not None:
        raise ServiceError(409, "code_revoked", codes.display(row.code))
    row.expires_at = expires_at
    session.flush()
    return row


def retire_route_codes(session: Session, route_id: str, *, now: datetime | None = None) -> None:
    """Before a route is purged: remember its codes so they are never issued again."""
    for row in session.scalars(select(Code).where(Code.route_id == route_id)):
        session.add(RetiredCode(code=row.code, route_id=route_id, retired_at=now or utcnow()))
    session.flush()


@dataclass(frozen=True)
class Lookup:
    code: Code
    version: RouteVersion


def lookup(session: Session, raw: str, *, now: datetime | None = None) -> Lookup:
    """Resolve a typed code to the route's latest version, or raise the public error."""
    now = now or utcnow()
    try:
        code = codes.parse(raw)
    except codes.CodeError as exc:
        raise ServiceError(400, exc.kind, str(exc)) from exc
    row = session.get(Code, code)
    if row is None:
        if session.get(RetiredCode, code) is not None:
            raise ServiceError(410, "route_unpublished", codes.display(code))
        raise ServiceError(404, "code_not_found", codes.display(code))
    if row.revoked_at is not None:
        raise ServiceError(410, "code_revoked", codes.display(code))
    if row.expires_at is not None and row.expires_at <= now:
        raise ServiceError(410, "code_expired", codes.display(code))
    route = row.route
    if route.deleted_at is not None or route.unpublished_at is not None:
        raise ServiceError(410, "route_unpublished", codes.display(code))
    version = session.scalar(
        select(RouteVersion)
        .where(RouteVersion.route_id == route.id)
        .order_by(RouteVersion.version.desc())
        .limit(1)
    )
    if version is None:
        raise ServiceError(410, "route_unpublished", codes.display(code))
    return Lookup(row, version)
