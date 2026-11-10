"""``lutrinh admin create|reset|set-password`` (page 06 §8)."""

from __future__ import annotations

import io
from pathlib import Path

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from lutrinh import cli
from lutrinh.api.admin import PREFIX
from lutrinh.api.app import create_app
from lutrinh.config import get_settings
from lutrinh.db.engine import make_engine, make_sessionmaker
from lutrinh.db.models import AdminUser, Base
from tests.admin.conftest import BASE_URL


def test_admin_create_then_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    url = f"sqlite:///{tmp_path / 'cli.sqlite'}"
    monkeypatch.setenv("LUTRINH_DATABASE_URL", url)
    monkeypatch.setenv("LUTRINH_ARGON2_TIME_COST", "1")
    monkeypatch.setenv("LUTRINH_ARGON2_MEMORY_KIB", "1024")
    get_settings.cache_clear()
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    try:
        monkeypatch.setattr("sys.stdin", io.StringIO("mot-mat-khau-du-dai\n"))
        assert cli.main(["admin", "create", "--password-stdin"]) == 0
        out = capsys.readouterr().out
        uri = next(line for line in out.splitlines() if line.startswith("otpauth://"))
        assert "issuer=L%E1%BB%AF%20Tr%C3%ACnh" in uri
        assert sum(1 for line in out.splitlines() if line.startswith("  ")) == 10

        monkeypatch.setattr("sys.stdin", io.StringIO("mot-mat-khau-du-dai\n"))
        assert cli.main(["admin", "create", "--password-stdin"]) == 1
        assert "admin reset" in capsys.readouterr().err

        monkeypatch.setattr("sys.stdin", io.StringIO("ngan\n"))
        assert cli.main(["admin", "reset", "--password-stdin"]) == 1

        monkeypatch.setattr("sys.stdin", io.StringIO("mat-khau-moi-du-dai\n"))
        assert cli.main(["admin", "reset", "--password-stdin"]) == 0
        new_uri = next(
            line for line in capsys.readouterr().out.splitlines() if line.startswith("otpauth://")
        )
        assert pyotp.parse_uri(new_uri).secret != pyotp.parse_uri(uri).secret
        with make_sessionmaker(engine)() as db:
            assert len(db.scalars(select(AdminUser)).all()) == 1
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_admin_set_password_on_an_existing_install_keeps_the_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The test-phase login: ``admin`` / ``123456``, no TOTP, on a database that already has
    an admin (with a long password) and a route."""
    url = f"sqlite:///{tmp_path / 'cli.sqlite'}"
    monkeypatch.setenv("LUTRINH_DATABASE_URL", url)
    monkeypatch.setenv("LUTRINH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LUTRINH_ADMIN_DIST_DIR", str(tmp_path / "no-dist"))
    monkeypatch.setenv("LUTRINH_ARGON2_TIME_COST", "1")
    monkeypatch.setenv("LUTRINH_ARGON2_MEMORY_KIB", "1024")
    get_settings.cache_clear()
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    try:
        monkeypatch.setattr("sys.stdin", io.StringIO("mot-mat-khau-du-dai\n"))
        assert cli.main(["admin", "create", "--password-stdin"]) == 0
        with make_sessionmaker(engine)() as db:
            secret = db.scalars(select(AdminUser)).one().totp_secret
        capsys.readouterr()

        monkeypatch.setattr("sys.stdin", io.StringIO("123456\n"))
        assert cli.main(["admin", "set-password", "--username", "admin", "--password-stdin"]) == 0
        out = capsys.readouterr().out
        assert "otpauth://" not in out
        with make_sessionmaker(engine)() as db:
            assert db.scalars(select(AdminUser)).one().totp_secret == secret

        with TestClient(create_app(get_settings(), engine=engine), base_url=BASE_URL) as c:
            body = {"username": "admin", "password": "123456"}
            assert c.post(f"{PREFIX}/session", json=body).status_code == 200
            assert c.get(f"{PREFIX}/session").status_code == 200
            wrong = {"username": "admin", "password": "654321"}
            assert c.post(f"{PREFIX}/session", json=wrong).status_code == 401
            # the routes the admin made before are still there after the password change
            r = c.post(
                f"{PREFIX}/routes",
                json={},
                headers={"X-CSRF-Token": c.get(f"{PREFIX}/session").json()["csrfToken"]},
            )
            assert r.status_code == 201

        # a different username renames the one account; empty database → created
        monkeypatch.setattr("sys.stdin", io.StringIO("12345\n"))
        assert cli.main(["admin", "set-password", "--password-stdin"]) == 1  # shorter than 6
        monkeypatch.setattr("sys.stdin", io.StringIO("abcdef\n"))
        assert cli.main(["admin", "set-password", "--username", "boss", "--password-stdin"]) == 0
        with make_sessionmaker(engine)() as db:
            assert [u.username for u in db.scalars(select(AdminUser))] == ["boss"]
    finally:
        engine.dispose()
        get_settings.cache_clear()
