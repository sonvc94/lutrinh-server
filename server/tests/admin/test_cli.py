"""``lutrinh admin create|reset`` (page 06 §8)."""

from __future__ import annotations

import io
from pathlib import Path

import pyotp
import pytest
from sqlalchemy import select

from lutrinh import cli
from lutrinh.config import get_settings
from lutrinh.db.engine import make_engine, make_sessionmaker
from lutrinh.db.models import AdminUser, Base


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
