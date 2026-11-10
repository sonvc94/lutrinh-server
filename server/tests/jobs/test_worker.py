"""The worker loop: claiming, retries, stale jobs, nightly purges, trash files, CLI."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from lutrinh.db.models import (
    AuditEntry,
    DownloadToken,
    IpEvent,
    IpLock,
    Job,
    Media,
    RetiredCode,
    Route,
    VersionMedia,
)
from lutrinh.jobs import PermanentError, worker
from lutrinh.services import jobs as job_service
from lutrinh.services import media as media_service
from lutrinh.services import publishing, routes
from tests.core.drafts import draft
from tests.jobs.conftest import Env
from tests.public.conftest import PHOTO, VIDEO, add_media


def queue(env: Env, kind: str = "purge.iplog", payload: dict[str, object] | None = None) -> int:
    with env.session() as s:
        job = job_service.enqueue(s, kind, payload or {})
        job.run_at = env.clock()
        s.commit()
        return job.id


def test_a_job_is_claimed_once(env: Env) -> None:
    jid = queue(env)
    with env.session() as a, env.session() as b:
        first = worker.claim(a, env.settings, env.clock())
        second = worker.claim(b, env.settings, env.clock())
    assert first is not None and first.id == jid and first.status == "running"
    assert first.attempts == 1 and second is None


def test_future_jobs_wait_for_run_at(env: Env) -> None:
    jid = queue(env)
    with env.session() as s:
        row = s.get(Job, jid)
        assert row is not None
        row.run_at = env.clock() + timedelta(minutes=5)
        s.commit()
    assert env.run() == 0
    env.clock.advance(minutes=5)
    assert env.run() == 1


def test_failures_back_off_then_fail_for_good(env: Env, monkeypatch: object) -> None:
    calls: list[int] = []

    def flaky(ctx: object, payload: object) -> dict[str, object]:
        calls.append(1)
        raise OSError("disk busy")

    worker.HANDLERS["purge.iplog"], saved = flaky, worker.HANDLERS["purge.iplog"]
    try:
        jid = queue(env)
        t0 = env.clock()
        env.run()
        job = env.jobs()[0]
        assert (job.status, job.attempts, job.run_at) == ("queued", 1, t0 + timedelta(seconds=30))
        assert job.error == "OSError: disk busy"
        env.clock.advance(seconds=30)
        env.run()
        assert env.jobs()[0].run_at == env.clock() + timedelta(seconds=60)
        env.clock.advance(seconds=60)
        env.run()
        job = env.jobs()[0]
        assert (job.id, job.status, job.attempts, len(calls)) == (jid, "failed", 3, 3)
        assert job.finished_at == env.clock()
    finally:
        worker.HANDLERS["purge.iplog"] = saved


def test_permanent_error_is_not_retried(env: Env) -> None:
    def refuse(ctx: object, payload: object) -> dict[str, object]:
        raise PermanentError("nope")

    worker.HANDLERS["purge.iplog"], saved = refuse, worker.HANDLERS["purge.iplog"]
    try:
        queue(env)
        env.run()
        job = env.jobs()[0]
        assert (job.status, job.attempts, job.error) == ("failed", 1, "nope")
    finally:
        worker.HANDLERS["purge.iplog"] = saved


def test_job_of_a_dead_worker_is_claimed_again(env: Env) -> None:
    jid = queue(env)
    with env.session() as s:
        assert worker.claim(s, env.settings, env.clock()) is not None  # then the worker dies
    assert env.run() == 0  # still running, not stale yet
    env.clock.advance(minutes=env.settings.job_stale_minutes + 1)
    assert env.run() == 1
    job = env.jobs()[0]
    assert (job.id, job.status, job.attempts) == (jid, "done", 2)


def test_failed_media_job_marks_the_media_failed(env: Env) -> None:
    mid = env.add_upload("broken.mov", b"\x00" * 300)
    env.run()
    assert env.media(mid).status == "failed"
    assert (env.media(mid).error or "").startswith("not_a_video")


def test_nightly_jobs_are_queued_once_per_night(env: Env) -> None:
    env.clock.now = datetime(2026, 11, 19, 19, 30, tzinfo=UTC)  # 02:30 in Hà Nội
    with env.session() as s:
        assert [j.kind for j in worker.schedule_nightly(s, env.settings, env.clock())] == [
            "purge.iplog",
            "purge.trash",
        ]
        s.commit()
        assert worker.schedule_nightly(s, env.settings, env.clock()) == []
        env.clock.advance(minutes=40)  # 03:10: a new night
        assert len(worker.schedule_nightly(s, env.settings, env.clock())) == 2
        s.commit()
        env.clock.advance(hours=20)
        assert worker.schedule_nightly(s, env.settings, env.clock()) == []


def published_route(env: Env) -> tuple[str, str]:
    """A published route (photo m_a + video m_b); returns its id and m_a's sha256."""
    with env.session() as s:
        route = routes.create(s, "Ninh Bình", draft())
        sha = add_media(s, env.settings, route, "m_a", "photo", PHOTO)
        add_media(s, env.settings, route, "m_b", "video", VIDEO)
        s.flush()
        publishing.publish(s, route.id, long_leg_km=150, now=env.clock())
        s.commit()
        return route.id, sha


def test_purge_iplog_forgets_ips_and_expired_tokens(env: Env) -> None:
    rid, _ = published_route(env)
    now = env.clock()
    with env.session() as s:
        s.add_all(
            [
                IpEvent(at=now - timedelta(days=15), ip="203.0.113.1", kind="lookup"),
                IpEvent(at=now - timedelta(days=13), ip="203.0.113.2", kind="lookup"),
                IpLock(ip="203.0.113.3", level=1, locked_at=now - timedelta(days=16),
                       locked_until=now - timedelta(days=15)),
            ]
        )  # fmt: skip
        for token, expires in (("tk_old", now - timedelta(days=2)), ("tk_new", now)):
            s.add(DownloadToken(token=token, code="2345", route_id=rid, version=1,
                                expires_at=expires, media_limit=1))  # fmt: skip
        s.commit()
    env.run(nightly=True)
    with env.session() as s:
        assert [e.ip for e in s.scalars(select(IpEvent))] == ["203.0.113.2"]
        assert list(s.scalars(select(IpLock))) == []
        assert [t.token for t in s.scalars(select(DownloadToken))] == ["tk_new"]
    assert {j.kind: j.status for j in env.jobs()} == {"purge.iplog": "done", "purge.trash": "done"}


def test_trash_sweep_purges_routes_after_30_days(env: Env) -> None:
    old, _ = published_route(env)
    with env.session() as s:
        recent = routes.create(s, "Mới xóa").id
        routes.trash(s, old, now=env.clock() - timedelta(days=31))
        routes.trash(s, recent, now=env.clock() - timedelta(days=29))
        s.commit()
    env.run(nightly=True)
    with env.session() as s:
        assert s.get(Route, old) is None and s.get(Route, recent) is not None
        assert [r.route_id for r in s.scalars(select(RetiredCode))] == [old]
        audit = s.scalars(select(AuditEntry).where(AuditEntry.action == "route.purge")).one()
        assert (audit.actor, audit.route_id) == ("worker", old)
        assert list(s.scalars(select(Media))) == []  # m_a, m_b removed by the follow-up job
    assert not list(env.settings.media_dir.rglob("*.*"))
    kinds = [(j.kind, j.payload.get("routeId"), j.status) for j in env.jobs("purge.trash")]
    assert kinds == [("purge.trash", None, "done"), ("purge.trash", old, "done")]


def test_purge_trash_keeps_files_still_in_use(env: Env) -> None:
    keep_rid, shared_sha = published_route(env)
    s_ = env.settings
    with env.session() as s:
        gone = routes.create(s, "Xóa hẳn")
        add_media(s, s_, gone, "m_q1", "photo", PHOTO)  # same file as the published m_a
        own = add_media(s, s_, gone, "m_q2", "photo", b"own photo")
        media_service.thumb_path(s_, own).write_bytes(b"preview")
        clip = add_media(s, s_, gone, "m_q3", "video", b"own video")
        add_media(s, s_, gone, "m_q4", "photo", b"used elsewhere")
        d = routes.get_draft(s, keep_rid)
        body = dict(d.body)
        body["stops"] = [dict(st) for st in body["stops"]]
        body["stops"][0]["media"] = [*body["stops"][0]["media"], "m_q4"]
        d.body = body
        s.flush()
        routes.trash(s, gone.id, now=env.clock())
        job = routes.purge(s, gone.id, now=env.clock())
        job.run_at = env.clock()
        s.commit()
    env.run()
    with env.session() as s:
        left = sorted(s.scalars(select(Media.id)))
        assert left == ["m_a", "m_b", "m_q4"]
        assert s.scalars(select(VersionMedia).where(VersionMedia.sha256 == shared_sha)).first()
    assert media_service.file_path(s_, shared_sha, "photo").is_file()
    assert not media_service.file_path(s_, own, "photo").exists()
    assert not media_service.thumb_path(s_, own).exists()
    assert not media_service.file_path(s_, clip, "video").exists()
    (done,) = env.jobs("purge.trash")
    assert done.status == "done" and done.result and sorted(done.result["media"]) == [
        "m_q1", "m_q2", "m_q3",
    ]  # fmt: skip


def test_cli_worker_once_on_an_empty_database(tmp_path: Path) -> None:
    from lutrinh.db.engine import make_engine
    from lutrinh.db.models import Base

    db = tmp_path / "lutrinh.sqlite"
    engine = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    engine.dispose()
    environ = dict(
        os.environ, LUTRINH_DATA_DIR=str(tmp_path), LUTRINH_DATABASE_URL=f"sqlite:///{db}"
    )
    done = subprocess.run(
        [sys.executable, "-m", "lutrinh.cli", "worker", "--once"],
        capture_output=True, text=True, env=environ, timeout=60,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert "worker stopped after 2 job(s)" in done.stderr  # the two nightly purges
