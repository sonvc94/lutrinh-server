"""The worker process (page 06 §3): ``lutrinh worker`` or ``python -m lutrinh.jobs.worker``.

It runs next to ``lutrinh serve`` on the same SQLite file and does one job at a time, which
also keeps router calls one per second. Claiming is a compare-and-set ``UPDATE`` on the row
(``queued`` → ``running``), so a second worker by mistake never runs the same job twice. A job
left ``running`` for ``job_stale_minutes`` (the worker died) is claimed again. Failures are
retried after ``job_backoff_seconds × 2^(attempt-1)`` (capped) until ``max_attempts``; then the
job is ``failed`` with its error, and a media row it was processing is marked ``failed`` too.

Nightly (after ``nightly_hour`` local time) the worker queues ``purge.iplog`` (IPs after 14 days,
tokens a day after expiry) and the ``purge.trash`` sweep (routes 30 days in the trash).
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from types import FrameType
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from lutrinh.adapters import routing
from lutrinh.config import Settings, get_settings
from lutrinh.db.engine import make_engine, make_sessionmaker
from lutrinh.db.models import Job
from lutrinh.jobs import Context, Payload, PermanentError, Result, legs, media, purge
from lutrinh.services import jobs as job_service

log = logging.getLogger("lutrinh.worker")

Handler = Callable[[Context, Payload], Result]

HANDLERS: dict[str, Handler] = {
    "media.image": media.handle_image,
    "media.video": media.handle_video,
    "legs.compute": legs.handle,
    "purge.trash": purge.handle_trash,
    "purge.iplog": purge.handle_iplog,
}
# Called once a job has failed for good (no more retries).
ON_FAILED: dict[str, Callable[[Context, Payload, str], None]] = {
    "media.image": media.mark_failed,
    "media.video": media.mark_failed,
}
NIGHTLY: tuple[tuple[str, Payload], ...] = (
    ("purge.iplog", {}),
    ("purge.trash", {"sweep": True}),
)


def _claimable(now: datetime, stale_before: datetime) -> Any:
    return or_(
        and_(Job.status == "queued", Job.run_at <= now),
        and_(Job.status == "running", Job.started_at < stale_before),
    )


def claim(session: Session, settings: Settings, now: datetime) -> Job | None:
    """Take the next due job (oldest ``run_at`` first) and mark it running; None when idle."""
    stale_before = now - timedelta(minutes=settings.job_stale_minutes)
    for _ in range(5):
        job_id = session.scalars(
            select(Job.id)
            .where(_claimable(now, stale_before))
            .order_by(Job.run_at, Job.id)
            .limit(1)
        ).first()
        if job_id is None:
            session.rollback()
            return None
        taken = session.execute(
            update(Job)
            .where(Job.id == job_id, _claimable(now, stale_before))
            .values(status="running", attempts=Job.attempts + 1, started_at=now)
            .execution_options(synchronize_session=False)
        )
        session.commit()
        if getattr(taken, "rowcount", 0) == 1:
            job = session.get(Job, job_id, populate_existing=True)
            assert job is not None
            return job
    return None


def backoff(settings: Settings, attempt: int) -> timedelta:
    seconds = settings.job_backoff_seconds * 2 ** max(0, attempt - 1)
    return timedelta(seconds=min(seconds, settings.job_backoff_max_seconds))


def _record_failure(ctx: Context, job: Job, message: str, *, permanent: bool) -> None:
    now = ctx.clock()
    final = permanent or job.attempts >= job.max_attempts
    with ctx.sessions() as session:
        row = session.get(Job, job.id)
        assert row is not None
        row.error = message[:4000]
        if final:
            row.status, row.finished_at = "failed", now
        else:
            row.status, row.run_at = "queued", now + backoff(ctx.settings, job.attempts)
        session.commit()
    if final:
        log.warning("job %s %s failed: %s", job.id, job.kind, message)
        hook = ON_FAILED.get(job.kind)
        if hook is not None:
            hook(ctx, job.payload, message)
    else:
        log.info(
            "job %s %s attempt %s failed, retrying: %s", job.id, job.kind, job.attempts, message
        )


def execute(ctx: Context, job: Job) -> str:
    """Run one claimed job; returns its new status (``done``, ``queued`` again, ``failed``)."""
    handler = HANDLERS.get(job.kind)
    if handler is None:
        _record_failure(ctx, job, f"unknown job kind {job.kind}", permanent=True)
        return "failed"
    if job.attempts > job.max_attempts:  # claimed again after its worker died on the last try
        _record_failure(ctx, job, "worker stopped while running the last attempt", permanent=True)
        return "failed"
    try:
        result = handler(ctx, dict(job.payload))
    except PermanentError as exc:
        _record_failure(ctx, job, str(exc), permanent=True)
        return "failed"
    except Exception as exc:  # noqa: BLE001 - any other failure is retried
        log.exception("job %s %s raised", job.id, job.kind)
        _record_failure(ctx, job, f"{type(exc).__name__}: {exc}", permanent=False)
        with ctx.sessions() as session:
            row = session.get(Job, job.id)
            return row.status if row is not None else "failed"
    with ctx.sessions() as session:
        row = session.get(Job, job.id)
        assert row is not None
        row.status, row.result, row.error = "done", result, None
        row.progress, row.finished_at = 100, ctx.clock()
        session.commit()
    log.info("job %s %s done: %s", job.id, job.kind, result)
    return "done"


def last_nightly(settings: Settings, now: datetime) -> datetime:
    """The latest ``nightly_hour`` local time at or before ``now`` (UTC)."""
    local = now.astimezone(ZoneInfo(settings.local_tz))
    due = local.replace(hour=settings.nightly_hour, minute=0, second=0, microsecond=0)
    if local < due:
        due -= timedelta(days=1)
    return due.astimezone(now.tzinfo)


def schedule_nightly(session: Session, settings: Settings, now: datetime) -> list[Job]:
    """Queue each nightly job not yet queued since the last nightly hour (caller commits)."""
    since = last_nightly(settings, now)
    queued = []
    for kind, payload in NIGHTLY:
        recent = session.scalars(select(Job).where(Job.kind == kind, Job.created_at >= since))
        if not any(job.payload == payload for job in recent):
            job = job_service.enqueue(session, kind, payload)
            job.created_at = job.run_at = now
            queued.append(job)
    return queued


def run(
    ctx: Context,
    *,
    once: bool = False,
    nightly: bool = True,
    stop: threading.Event | None = None,
) -> int:
    """Run jobs until ``stop`` is set; ``once``: until no job is due. Returns jobs run."""
    stop = stop or threading.Event()
    done = 0
    while not stop.is_set():
        now = ctx.clock()
        with ctx.sessions() as session:
            if nightly:
                schedule_nightly(session, ctx.settings, now)
                session.commit()
            job = claim(session, ctx.settings, now)
        if job is None:
            if once:
                break
            stop.wait(ctx.settings.worker_poll_seconds)
            continue
        log.info("job %s %s attempt %s: %s", job.id, job.kind, job.attempts, job.payload)
        execute(ctx, job)
        done += 1
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lutrinh worker", description=__doc__)
    parser.add_argument("--once", action="store_true", help="run the due jobs, then exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    engine = make_engine(settings.db_url)
    stop = threading.Event()

    def _stop(signum: int, _frame: FrameType | None) -> None:
        log.info("signal %s: stopping after the current job", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    ctx = Context(settings, make_sessionmaker(engine), routing.from_settings(settings))
    log.info("worker on %s (poll %s s)", settings.db_url, settings.worker_poll_seconds)
    try:
        n = run(ctx, once=args.once, stop=stop)
    finally:
        engine.dispose()
    log.info("worker stopped after %s job(s)", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
