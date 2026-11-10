"""``/stats`` (daily lookups/downloads, D-14 A) and ``/audit`` (the admin's own writes)."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from lutrinh.api.admin import schemas as s
from lutrinh.api.deps import AdminDep, DbDep
from lutrinh.db.models import AuditEntry, DailyCount, utcnow

router = APIRouter()


@router.get("/stats", response_model=list[s.StatRow])
def stats(
    _: AdminDep,
    db: DbDep,
    days: Annotated[int, Query(ge=1, le=400)] = 30,
    route_id: Annotated[str | None, Query(alias="routeId")] = None,
) -> list[s.StatRow]:
    since = (utcnow() - timedelta(days=days - 1)).date().isoformat()
    stmt = select(DailyCount).where(DailyCount.day >= since)
    if route_id is not None:
        stmt = stmt.where(DailyCount.route_id == route_id)
    stmt = stmt.order_by(DailyCount.day, DailyCount.route_id, DailyCount.kind)
    return [
        s.StatRow(day=r.day, route_id=r.route_id or None, kind=r.kind, count=r.count)
        for r in db.scalars(stmt)
    ]


@router.get("/audit", response_model=list[s.AuditOut])
def audit_log(
    _: AdminDep,
    db: DbDep,
    route_id: Annotated[str | None, Query(alias="routeId")] = None,
    before_id: Annotated[int | None, Query(alias="beforeId")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[s.AuditOut]:
    stmt = select(AuditEntry)
    if route_id is not None:
        stmt = stmt.where(AuditEntry.route_id == route_id)
    if before_id is not None:
        stmt = stmt.where(AuditEntry.id < before_id)
    stmt = stmt.order_by(AuditEntry.id.desc()).limit(limit)
    return [
        s.AuditOut(
            id=e.id,
            at=e.at,
            actor=e.actor,
            action=e.action,
            route_id=e.route_id,
            target=e.target,
            before=e.before,
            after=e.after,
        )
        for e in db.scalars(stmt)
    ]
