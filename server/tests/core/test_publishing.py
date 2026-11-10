from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from lutrinh.core import package
from lutrinh.db.engine import make_engine, make_sessionmaker
from lutrinh.db.models import (
    Base,
    Draft,
    ImmutableVersionError,
    Media,
    Route,
    RouteVersion,
    VersionMedia,
)
from lutrinh.services.publishing import PublishError, publish_draft
from tests.core.drafts import draft, media_infos

T1 = datetime(2026, 11, 20, 3, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 21, 3, 0, tzinfo=UTC)


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = make_engine(f"sqlite:///{tmp_path / 'test.sqlite'}")
    Base.metadata.create_all(engine)
    with make_sessionmaker(engine)() as s:
        yield s
    engine.dispose()


def _seed(session: Session) -> None:
    session.add(Route(id="rt_0a1b2c3d"))
    for info in media_infos().values():
        session.add(
            Media(
                id=info.id,
                route_id="rt_0a1b2c3d",
                type=info.type,
                status="ready",
                sha256=info.sha256,
                bytes=info.bytes,
                width=info.w,
                height=info.h,
                duration_ms=info.duration_ms,
                credit=info.credit,
            )
        )
    session.add(Draft(route_id="rt_0a1b2c3d", body=draft()))
    session.commit()


def test_publishing_twice_makes_v1_and_v2_and_v1_is_unchanged(session: Session) -> None:
    _seed(session)
    v1 = publish_draft(session, "rt_0a1b2c3d", note="first", now=T1)
    session.commit()
    v1_bytes, v1_sha = v1.route_json, v1.sha256

    d = session.get(Draft, "rt_0a1b2c3d")
    assert d is not None
    body = draft()
    body["stops"][1]["note"] = "Leo 500 bậc, mang nước"
    d.body = body
    d.revision += 1
    session.commit()

    v2 = publish_draft(session, "rt_0a1b2c3d", now=T2)
    session.commit()
    session.expire_all()

    rows = session.scalars(select(RouteVersion).order_by(RouteVersion.version)).all()
    assert [r.version for r in rows] == [1, 2]
    assert rows[0].route_json == v1_bytes
    assert rows[0].sha256 == v1_sha == package.sha256_hex(rows[0].route_json)
    assert rows[1].sha256 != v1_sha
    assert package.read(rows[0].route_json)["route"]["version"] == 1
    assert package.read(rows[1].route_json)["route"]["version"] == 2
    assert v2.published_at == T2
    files = session.scalars(select(VersionMedia.sha256).where(VersionMedia.version == 2)).all()
    assert sorted(files) == sorted(m.sha256 for m in media_infos().values())


def test_version_rows_cannot_be_updated(session: Session) -> None:
    _seed(session)
    v1 = publish_draft(session, "rt_0a1b2c3d", now=T1)
    session.commit()
    v1.note = "edited later"
    with pytest.raises(ImmutableVersionError):
        session.commit()


def test_media_not_ready_blocks_publish(session: Session) -> None:
    _seed(session)
    m = session.get(Media, "m_b")
    assert m is not None
    m.status = "processing"
    session.commit()
    with pytest.raises(PublishError) as err:
        publish_draft(session, "rt_0a1b2c3d", now=T1)
    assert err.value.code == "media_not_ready"


def test_invalid_draft_publishes_nothing(session: Session) -> None:
    _seed(session)
    d = session.get(Draft, "rt_0a1b2c3d")
    assert d is not None
    body = draft()
    body["days"] = 1  # stop s_b is on day 2
    d.body = body
    session.commit()
    with pytest.raises(PublishError) as err:
        publish_draft(session, "rt_0a1b2c3d", now=T1)
    assert err.value.code == "invalid_package"
    assert [p.code for p in err.value.problems] == ["day_after_end"]
    session.rollback()
    assert session.scalars(select(RouteVersion)).all() == []


def test_missing_route_draft_and_trash(session: Session) -> None:
    with pytest.raises(PublishError) as err:
        publish_draft(session, "rt_nope0000")
    assert err.value.code == "route_not_found"
    session.add(Route(id="rt_11111111"))
    session.commit()
    with pytest.raises(PublishError) as err:
        publish_draft(session, "rt_11111111")
    assert err.value.code == "no_draft"
    r = session.get(Route, "rt_11111111")
    assert r is not None
    r.deleted_at = T1
    session.commit()
    with pytest.raises(PublishError) as err:
        publish_draft(session, "rt_11111111")
    assert err.value.code == "route_deleted"
