"""Admin API fixtures: an app on a temp data dir, an enrolled admin, a logged-in client.

The client talks to ``https://testserver``: the session cookie is ``Secure`` (``__Host-``), so
an ``http://`` base URL would never send it back.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pyotp
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lutrinh.adapters.mail import LogMailer
from lutrinh.api.admin import PREFIX
from lutrinh.api.app import create_app
from lutrinh.config import Settings
from lutrinh.db.engine import make_engine, make_sessionmaker
from lutrinh.db.models import Base
from lutrinh.services import auth

PASSWORD = "dung-quen-mat-khau-nay"
BASE_URL = "https://testserver"


@dataclass
class Admin:
    app: FastAPI
    settings: Settings
    mailer: LogMailer
    totp: pyotp.TOTP
    backup_codes: list[str]


@pytest.fixture
def admin(tmp_path: Path) -> Iterator[Admin]:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'lutrinh.sqlite'}",
        admin_dist_dir=tmp_path / "no-dist",
        argon2_time_cost=1,
        argon2_memory_kib=1024,
        upload_chunk_bytes=64,
    )
    engine = make_engine(settings.db_url)
    Base.metadata.create_all(engine)
    with make_sessionmaker(engine)() as session:
        enrolment = auth.enrol(session, settings, PASSWORD)
        session.commit()
    mailer = LogMailer()
    app = create_app(settings, engine=engine, mailer=mailer)
    yield Admin(app, settings, mailer, pyotp.TOTP(enrolment.totp_secret), enrolment.backup_codes)
    engine.dispose()


@pytest.fixture
def anon(admin: Admin) -> Iterator[TestClient]:
    with TestClient(admin.app, base_url=BASE_URL) as client:
        yield client


@pytest.fixture
def client(admin: Admin) -> Iterator[TestClient]:
    """Logged in; sends ``X-CSRF-Token`` on every request."""
    with TestClient(admin.app, base_url=BASE_URL) as c:
        r = c.post(f"{PREFIX}/session", json={"password": PASSWORD, "code": admin.totp.now()})
        assert r.status_code == 200, r.text
        c.headers["X-CSRF-Token"] = r.json()["csrfToken"]
        yield c
