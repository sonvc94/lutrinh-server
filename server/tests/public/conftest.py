"""Public API fixtures: an app on a temp data dir, a published route with real files on disk,
and a clock the tests move by hand."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from lutrinh.adapters.mail import LogMailer
from lutrinh.api.app import create_app
from lutrinh.config import Settings
from lutrinh.db.engine import make_engine, make_sessionmaker
from lutrinh.db.models import Base, Media
from lutrinh.services import media as media_service
from lutrinh.services import publishing, routes
from tests.core.drafts import draft

T0 = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
PHOTO = bytes(range(256)) * 1200  # 307 200 bytes
VIDEO = hashlib.sha256(b"video").digest() * 40_000  # 1 280 000 bytes


@dataclass
class Clock:
    now: datetime = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


@dataclass
class Public:
    app: FastAPI
    settings: Settings
    engine: Engine
    mailer: LogMailer
    clock: Clock
    route_id: str = ""
    code: str = ""
    files: dict[str, bytes] = field(default_factory=dict)  # sha256 → bytes

    def session(self) -> Session:
        return make_sessionmaker(self.engine)()

    def client(self, ip: str = "203.0.113.7") -> TestClient:
        return TestClient(self.app, client=(ip, 50000))


def add_media(
    session: Session, settings: Settings, route: object, mid: str, kind: str, data: bytes
) -> str:
    sha = hashlib.sha256(data).hexdigest()
    path = media_service.file_path(settings, sha, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    session.add(
        Media(
            id=mid,
            route=route,
            type=kind,
            status="ready",
            sha256=sha,
            bytes=len(data),
            width=2560 if kind == "photo" else 1280,
            height=1707 if kind == "photo" else 720,
            duration_ms=30_000 if kind == "video" else None,
            credit="Ảnh: Lữ Trình",
        )
    )
    return sha


@pytest.fixture
def pub(tmp_path: Path) -> Iterator[Public]:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'lutrinh.sqlite'}",
        admin_dist_dir=tmp_path / "no-dist",
    )
    engine = make_engine(settings.db_url)
    Base.metadata.create_all(engine)
    mailer = LogMailer()
    clock = Clock()
    app = create_app(settings, engine=engine, mailer=mailer)
    app.state.clock = clock
    p = Public(app, settings, engine, mailer, clock)
    with p.session() as s:
        route = routes.create(s, "Ninh Bình", draft())
        p.files[add_media(s, settings, route, "m_a", "photo", PHOTO)] = PHOTO
        p.files[add_media(s, settings, route, "m_b", "video", VIDEO)] = VIDEO
        s.flush()
        published = publishing.publish(s, route.id, long_leg_km=150, now=T0 - timedelta(days=1))
        s.commit()
        p.route_id, p.code = route.id, published.code.code
    yield p
    engine.dispose()
