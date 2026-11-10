"""Worker fixtures: a data dir + SQLite file, a fake router (no network), a movable clock."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from lutrinh.adapters.routing import Answer, LatLng, Routers, RouterUnavailable, Throttle
from lutrinh.config import Settings
from lutrinh.db.engine import make_engine, make_sessionmaker
from lutrinh.db.models import Base, Job, Media, utcnow
from lutrinh.jobs import Context, worker
from lutrinh.services import media as media_service
from lutrinh.services import uploads


@dataclass
class Clock:
    # An hour ahead of the real time: jobs that services queue (run_at = utcnow()) are due.
    now: datetime = field(default_factory=lambda: utcnow() + timedelta(hours=1))

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


def line(a: LatLng, b: LatLng, n: int = 20) -> list[LatLng]:
    """A road line from a to b with a bend (so simplification keeps some points)."""
    pts = []
    for i in range(n + 1):
        t = i / n
        bend = 0.002 * (1 - abs(2 * t - 1))
        pts.append((a[0] + (b[0] - a[0]) * t + bend, a[1] + (b[1] - a[1]) * t))
    return pts


@dataclass
class Call:
    a: LatLng
    b: LatLng
    profile: str
    at: float  # time.monotonic()


@dataclass
class FakeRouter:
    """Answers along a straight-ish line; ``answer`` overrides per call (profile → Answer)."""

    id: str = "valhalla"
    profiles: tuple[str, ...] = ("motorbike", "car", "bus", "walk")
    calls: list[Call] = field(default_factory=list)
    answer: Callable[[LatLng, LatLng, str], Answer] | None = None

    def supports(self, profile: str) -> bool:
        return profile in self.profiles

    def route(self, a: LatLng, b: LatLng, profile: str) -> Answer:
        self.calls.append(Call(a, b, profile, time.monotonic()))
        if self.answer is not None:
            return self.answer(a, b, profile)
        return ok_answer(self.id, a, b)


def ok_answer(source: str, a: LatLng, b: LatLng, factor: float = 1.3) -> Answer:
    from lutrinh.core import geo

    pts = line(a, b)
    return Answer("ok", source, pts, distance_m=geo.haversine_m(a, b) * factor, duration_s=600.4)


def unavailable(a: LatLng, b: LatLng, profile: str) -> Answer:
    raise RouterUnavailable("valhalla: HTTP 503")


@dataclass
class Env:
    settings: Settings
    engine: Engine
    ctx: Context
    clock: Clock
    valhalla: FakeRouter
    osrm: FakeRouter

    def session(self) -> Session:
        return self.ctx.sessions()

    def run(self, **kw: Any) -> int:
        kw.setdefault("nightly", False)
        return worker.run(self.ctx, once=True, **kw)

    def jobs(self, kind: str | None = None) -> list[Job]:
        with self.session() as s:
            stmt = select(Job).order_by(Job.id)
            if kind:
                stmt = stmt.where(Job.kind == kind)
            return list(s.scalars(stmt))

    def media(self, media_id: str) -> Media:
        with self.session() as s:
            row = s.get(Media, media_id)
            assert row is not None
            return row

    def add_upload(self, filename: str, data: bytes) -> str:
        """A media row whose upload is complete, as ``POST /media/{id}/complete`` leaves it."""
        with self.session() as s:
            row = media_service.create(
                s, self.settings, route_id=None, filename=filename, content_type=None,
                size=len(data),
            )  # fmt: skip
            row_id = row.id
            path = uploads.original_path(self.settings, row_id)
            path.write_bytes(data)
            up = uploads.get(s, row_id)
            up.completed_at = self.clock()
            job = media_service.queue_processing(s, self.settings, row)
            job.run_at = job.created_at = self.clock()
            s.commit()
            return row_id


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'lutrinh.sqlite'}",
        admin_dist_dir=tmp_path / "no-dist",
        router_min_interval_seconds=0.01,
    )
    engine = make_engine(settings.db_url)
    Base.metadata.create_all(engine)
    clock = Clock()
    valhalla, osrm = FakeRouter(), FakeRouter(id="osrm", profiles=("car",))
    routers = Routers(valhalla, osrm, Throttle(settings.router_min_interval_seconds))
    ctx = Context(settings, make_sessionmaker(engine), routers, clock)
    yield Env(settings, engine, ctx, clock, valhalla, osrm)
    engine.dispose()


def ffmpeg(*args: str) -> None:
    done = subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def ffprobe(path: Path) -> dict[str, Any]:
    import json

    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
    done = subprocess.run([*cmd, str(path)], capture_output=True, text=True, check=True)
    info: dict[str, Any] = json.loads(done.stdout)
    return info
