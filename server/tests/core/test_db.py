from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from lutrinh.db.engine import make_engine, make_sessionmaker
from lutrinh.db.models import Base, Code, Route

SERVER_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture
def migrated_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{tmp_path / 'migrated.sqlite'}"
    monkeypatch.setenv("LUTRINH_DATABASE_URL", url)
    from lutrinh.config import get_settings

    get_settings.cache_clear()
    command.upgrade(Config(str(SERVER_DIR / "alembic.ini")), "head")
    get_settings.cache_clear()
    return url


def test_migrations_match_models(migrated_url: str) -> None:
    engine = make_engine(migrated_url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        assert compare_metadata(ctx, Base.metadata) == []
        tables = set(inspect(conn).get_table_names())
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
    engine.dispose()
    assert {
        "routes",
        "drafts",
        "route_versions",
        "version_media",
        "codes",
        "media",
        "jobs",
    } <= tables
    assert mode == "wal"


def test_one_live_code_per_route_and_revoked_codes_stay(migrated_url: str) -> None:
    from datetime import UTC, datetime

    engine = make_engine(migrated_url)
    with make_sessionmaker(engine)() as s:
        s.add(Route(id="rt_aaaaaaaa"))
        s.add(Code(code="HG4N7KQX", route_id="rt_aaaaaaaa"))
        s.commit()
        s.add(Code(code="HG4N7KQY", route_id="rt_aaaaaaaa"))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        old = s.get(Code, "HG4N7KQX")
        assert old is not None
        old.revoked_at = datetime.now(UTC)
        s.add(Code(code="HG4N7KQY", route_id="rt_aaaaaaaa"))
        s.commit()
        assert {c.code for c in s.query(Code)} == {"HG4N7KQX", "HG4N7KQY"}
    engine.dispose()
