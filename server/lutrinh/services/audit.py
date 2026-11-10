"""Audit log: every admin write (who, when, which route, before/after; page 03, page 06 §8)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from lutrinh.db.models import AuditEntry, utcnow

ACTOR = "admin"  # one account (D-7 A)


def record(
    session: Session,
    action: str,
    *,
    route_id: str | None = None,
    target: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    actor: str = ACTOR,
    now: datetime | None = None,
) -> AuditEntry:
    entry = AuditEntry(
        at=now or utcnow(),
        actor=actor,
        action=action,
        route_id=route_id,
        target=target,
        before=before,
        after=after,
    )
    session.add(entry)
    return entry
