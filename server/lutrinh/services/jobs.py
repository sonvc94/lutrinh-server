"""Background jobs: the API only enqueues rows; ``lutrinh.jobs.worker`` (later) runs them.

Kinds (page 06 §3): ``media.image``, ``media.video``, ``legs.compute``, ``purge.trash``,
``purge.iplog``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lutrinh.db.models import Job

KINDS = frozenset({"media.image", "media.video", "legs.compute", "purge.trash", "purge.iplog"})


def enqueue(session: Session, kind: str, payload: dict[str, Any], *, dedupe: bool = False) -> Job:
    """Add a queued job (caller commits). ``dedupe``: reuse a queued job with the same payload."""
    if kind not in KINDS:
        raise ValueError(f"unknown job kind {kind}")
    if dedupe:
        for job in session.scalars(select(Job).where(Job.kind == kind, Job.status == "queued")):
            if job.payload == payload:
                return job
    job = Job(kind=kind, payload=payload, status="queued")
    session.add(job)
    session.flush()
    return job
