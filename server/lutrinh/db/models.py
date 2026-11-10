"""Tables named by the design (page 02 versions/codes, page 06 §3 jobs, §4 media).

* ``routes``: one row per route; status is derived (draft = no version yet, shared, unpublished),
  trash = ``deleted_at`` set (purged after 30 days by a later job).
* ``drafts``: the single working copy of a route, a JSON document written whole (If-Match on
  ``revision``).
* ``route_versions``: immutable published snapshots v1…vN, with the canonical ``route.json`` bytes
  and their sha256. Never updated in place (enforced in ``_forbid_version_update``).
* ``version_media``: which media files (by sha256) belong to a version (download token check).
* ``codes``: route codes; revoked codes stay for ever so they are never issued again; at most one
  live (non-revoked) code per route.
* ``media``: uploaded/processed photos and videos; files live on disk under ``media/ab/cd/<sha>``.
* ``jobs``: background work queue read by the worker process.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Text,
    event,
    text,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UTCDateTime(TypeDecorator[datetime]):
    """Aware UTC datetimes in, aware UTC datetimes out (SQLite stores naive text)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; use datetime.now(UTC)")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    unpublished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    draft: Mapped[Draft | None] = relationship(back_populates="route", cascade="all, delete-orphan")
    versions: Mapped[list[RouteVersion]] = relationship(
        back_populates="route", order_by="RouteVersion.version"
    )
    codes: Mapped[list[Code]] = relationship(back_populates="route")


class Draft(Base):
    __tablename__ = "drafts"

    route_id: Mapped[str] = mapped_column(
        ForeignKey("routes.id", ondelete="CASCADE"), primary_key=True
    )
    body: Mapped[dict[str, Any]] = mapped_column(JSON)
    # Bumped on every write; the admin API's ETag / If-Match.
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    route: Mapped[Route] = relationship(back_populates="draft")


class RouteVersion(Base):
    __tablename__ = "route_versions"
    __table_args__ = (CheckConstraint("version >= 1", name="version_positive"),)

    route_id: Mapped[str] = mapped_column(
        ForeignKey("routes.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_json: Mapped[bytes] = mapped_column(LargeBinary)
    sha256: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # "Ghi chú phiên bản", shown to app users when an update is offered.
    note: Mapped[str | None] = mapped_column(Text)
    media_bytes: Mapped[int] = mapped_column(Integer)
    media_files: Mapped[int] = mapped_column(Integer)
    # Set when this version re-publishes an older one ("quay lại v2" → v4).
    source_version: Mapped[int | None] = mapped_column(Integer)

    route: Mapped[Route] = relationship(back_populates="versions")
    files: Mapped[list[VersionMedia]] = relationship(back_populates="route_version")


class VersionMedia(Base):
    __tablename__ = "version_media"
    __table_args__ = (
        ForeignKeyConstraint(
            ["route_id", "version"],
            ["route_versions.route_id", "route_versions.version"],
            ondelete="CASCADE",
        ),
        Index(None, "sha256"),
    )

    route_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)

    route_version: Mapped[RouteVersion] = relationship(back_populates="files")


class Code(Base):
    __tablename__ = "codes"
    __table_args__ = (
        # One live code per route (D-2 A); revoked rows are kept and never reissued.
        Index(
            "uq_codes_live_route",
            "route_id",
            unique=True,
            sqlite_where=text("revoked_at IS NULL"),
        ),
        CheckConstraint("length(code) = 8", name="code_length"),
    )

    # Canonical form: 8 characters, no hyphen (core.codes.parse).
    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # Null = never expires (D-3 A); the admin may set one.
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoke_reason: Mapped[str | None] = mapped_column(Text)

    route: Mapped[Route] = relationship(back_populates="codes")


class Media(Base):
    __tablename__ = "media"
    __table_args__ = (
        CheckConstraint("type IN ('photo', 'video')", name="type"),
        CheckConstraint("status IN ('uploading', 'processing', 'ready', 'failed')", name="status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    # Route it was uploaded for (admin "Ảnh/video" tab); files are shared by sha256.
    route_id: Mapped[str | None] = mapped_column(
        ForeignKey("routes.id", ondelete="SET NULL"), index=True
    )
    type: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="uploading")
    # Set once processed; names the file on disk. Not unique: two rows may share a file.
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    bytes: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    credit: Mapped[str | None] = mapped_column(Text)
    original_name: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    route: Mapped[Route | None] = relationship()


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name="status"),
        Index(None, "status", "run_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # media.image, media.video, legs.compute, purge.trash, purge.iplog
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    # Earliest time the worker may pick it up (backoff between retries).
    run_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    progress: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ImmutableVersionError(RuntimeError):
    pass


@event.listens_for(RouteVersion, "before_update")
@event.listens_for(VersionMedia, "before_update")
def _forbid_version_update(mapper: Any, connection: Any, target: Any) -> None:
    raise ImmutableVersionError(f"{type(target).__name__} rows are immutable")
