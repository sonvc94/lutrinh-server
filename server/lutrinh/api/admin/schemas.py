"""Request/response bodies of the admin API (camelCase on the wire, for the React client).

The draft body is typed loosely on purpose: a draft may be incomplete while it is edited. The
package schema (``spec/route.schema.json``) and the publish rules are checked by
``GET /routes/{id}/publish`` and on publish. List sizes are capped here to bound requests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class Problem(Model):
    code: str
    path: str
    message: str


# --- session ---------------------------------------------------------------------------


class LoginIn(Model):
    password: str = Field(max_length=1024)
    # 6-digit TOTP, or one of the 10-character backup codes (hyphen/spaces allowed).
    code: str = Field(max_length=32)


class SessionOut(Model):
    csrf_token: str
    expires_at: datetime
    idle_expires_at: datetime


# --- drafts ----------------------------------------------------------------------------


class StopIn(Model):
    id: str = Field(max_length=40)
    day: int
    time: str | None = None
    title: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=4000)
    lat: float
    lng: float
    arrival: str | None = None
    media: list[str] = Field(default_factory=list, max_length=30)


class LegIn(Model):
    to: str = Field(max_length=40)
    profile: str
    used_profile: str | None = None
    source: str
    status: str
    distance_m: float
    duration_s: float
    path: str = Field(max_length=1_000_000)


class DraftBody(Model):
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=4000)
    days: int = 1
    cover: str | None = None
    ready_made: str | None = None
    credits: list[str] = Field(default_factory=list, max_length=50)
    stops: list[StopIn] = Field(default_factory=list, max_length=200)
    legs: list[LegIn] = Field(default_factory=list, max_length=199)

    def to_body(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)


class DraftOut(Model):
    route_id: str
    revision: int
    etag: str
    updated_at: datetime
    body: dict[str, Any]
    queued_jobs: list[int] = Field(default_factory=list)


class ManualLegIn(Model):
    path: str = Field(max_length=1_000_000)
    duration_s: float | None = Field(default=None, ge=0)


# --- routes ----------------------------------------------------------------------------


class RouteCreate(Model):
    title: str = Field(default="Lộ trình mới", min_length=1, max_length=60)


class RouteOut(Model):
    id: str
    title: str
    status: Literal["draft", "shared", "unpublished", "trash"]
    latest_version: int | None
    published_at: datetime | None
    draft_changed: bool
    code: str | None
    stops: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class JobOut(Model):
    id: int
    kind: str
    status: str
    progress: int | None
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class JobRef(Model):
    job_id: int


# --- publishing ------------------------------------------------------------------------


class PublishIn(Model):
    note: str | None = Field(default=None, max_length=1000)
    # Prefix for the code issued when the route has none (page 03 "tiền tố 2 ký tự").
    code_prefix: str | None = Field(default=None, max_length=2)


class RepublishIn(Model):
    note: str | None = Field(default=None, max_length=1000)


class PreflightOut(Model):
    next_version: int
    can_publish: bool
    blockers: list[Problem]
    warnings: list[Problem]
    media_bytes: int | None
    media_files: int | None


class VersionOut(Model):
    version: int
    sha256: str
    published_at: datetime
    note: str | None
    bytes: int
    media_bytes: int
    media_files: int
    source_version: int | None


class CodeOut(Model):
    code: str  # display form XXXX-XXXX
    route_id: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    revoke_reason: str | None
    live: bool


class PublishOut(Model):
    version: VersionOut
    code: CodeOut
    code_issued: bool
    warnings: list[Problem]


class CodeCreate(Model):
    prefix: str | None = Field(default=None, max_length=2)
    expires_at: datetime | None = None


class CodePatch(Model):
    expires_at: datetime | None


class RevokeIn(Model):
    reason: str | None = Field(default=None, max_length=500)
    # Issue a new code for the same route right away (page 04 "Thu hồi và tạo mã mới").
    reissue: bool = False
    prefix: str | None = Field(default=None, max_length=2)


class RevokeOut(Model):
    revoked: CodeOut
    new_code: CodeOut | None


# --- media and imports -----------------------------------------------------------------


class UploadState(Model):
    bytes: int
    chunk_bytes: int
    chunks: int
    received: list[int]
    sha256: str | None
    completed_at: datetime | None


class MediaCreate(Model):
    route_id: str | None = None
    filename: str = Field(min_length=1, max_length=255)
    content_type: str | None = Field(default=None, max_length=100)
    bytes: int = Field(gt=0)


class MediaOut(Model):
    id: str
    route_id: str | None
    type: str
    status: str
    sha256: str | None
    bytes: int | None
    width: int | None
    height: int | None
    duration_ms: int | None
    credit: str | None
    original_name: str | None
    error: str | None
    created_at: datetime
    upload: UploadState | None = None


class MediaPatch(Model):
    credit: str | None = Field(max_length=200)


class Completed(Model):
    media: MediaOut
    job_id: int


class ImportCreate(Model):
    kind: Literal["gpx", "backup"]
    filename: str = Field(min_length=1, max_length=255)
    bytes: int = Field(gt=0)


class ImportOut(Model):
    id: str
    kind: str
    status: str
    filename: str
    preview: dict[str, Any] | None
    error: dict[str, Any] | None
    route_id: str | None
    created_at: datetime
    applied_at: datetime | None
    upload: UploadState | None = None


class ImportApply(Model):
    trip_id: str | None = Field(default=None, max_length=64)


class RouteRef(Model):
    route_id: str


# --- stats and audit -------------------------------------------------------------------


class StatRow(Model):
    day: str
    route_id: str | None
    kind: str
    count: int


class AuditOut(Model):
    id: int
    at: datetime
    actor: str
    action: str
    route_id: str | None
    target: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
