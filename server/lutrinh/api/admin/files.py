"""``/media`` and ``/imports``: chunked uploads (8 MB chunks; no request body above one chunk)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import FileResponse

from lutrinh.api.admin import schemas as s
from lutrinh.api.admin import views
from lutrinh.api.deps import AdminDep, DbDep, SettingsDep
from lutrinh.config import Settings
from lutrinh.services import audit, imports, uploads
from lutrinh.services import media as media_service
from lutrinh.services.errors import ServiceError

router = APIRouter()

_CHUNK_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}


async def _read_chunk(request: Request, settings: Settings) -> bytes:
    """The raw body, refusing anything larger than one chunk before reading it all."""
    limit = settings.upload_chunk_bytes
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise ServiceError(413, "too_large", f"chunk > {limit} bytes", maxBytes=limit)
    data = bytearray()
    async for part in request.stream():
        data.extend(part)
        if len(data) > limit:
            raise ServiceError(413, "too_large", f"chunk > {limit} bytes", maxBytes=limit)
    return bytes(data)


# --- media -----------------------------------------------------------------------------


@router.post("/media", response_model=s.MediaOut, status_code=201)
def create_media(body: s.MediaCreate, _: AdminDep, db: DbDep, settings: SettingsDep) -> s.MediaOut:
    row = media_service.create(
        db,
        settings,
        route_id=body.route_id,
        filename=body.filename,
        content_type=body.content_type,
        size=body.bytes,
    )
    audit.record(db, "media.create", route_id=row.route_id, target=row.id)
    db.commit()
    return views.media_out(db, settings, row)


@router.get("/media", response_model=list[s.MediaOut])
def list_media(
    _: AdminDep,
    db: DbDep,
    settings: SettingsDep,
    route_id: Annotated[str | None, Query(alias="routeId")] = None,
) -> list[s.MediaOut]:
    return [views.media_out(db, settings, m) for m in media_service.list_media(db, route_id)]


@router.get("/media/{media_id}", response_model=s.MediaOut)
def get_media(media_id: str, _: AdminDep, db: DbDep, settings: SettingsDep) -> s.MediaOut:
    return views.media_out(db, settings, media_service.get(db, media_id))


_FILE_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "The processed file (or its ≤ 640 px preview); Range answers 206.",
        "content": {
            "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
            "video/mp4": {"schema": {"type": "string", "format": "binary"}},
        },
    }
}


@router.get("/media/{media_id}/file", response_class=FileResponse, responses=_FILE_RESPONSES)
def get_media_file(
    media_id: str,
    _: AdminDep,
    db: DbDep,
    settings: SettingsDep,
    size: Annotated[int | None, Query(description="640 → the photo's preview")] = None,
) -> FileResponse:
    """The bytes of a processed media row for the admin web (tiles, covers). ``?size=640`` →
    the worker's ≤ 640 px preview of a photo when it exists, else the file itself. Range is
    answered by ``FileResponse`` (206), like the public media endpoint."""
    if size not in (None, 640):
        raise ServiceError(422, "invalid_request", "size must be 640")
    row = media_service.get(db, media_id)
    if row.status != "ready" or row.sha256 is None:
        raise ServiceError(404, "not_found", f"media {media_id}: not processed ({row.status})")
    path = media_service.find_file(settings, row.sha256)
    if path is None:
        raise ServiceError(404, "not_found", f"media {media_id}: file missing on disk")
    if size == 640 and path.suffix == ".jpg":
        thumb = media_service.thumb_path(settings, row.sha256)
        if thumb.is_file():
            path = thumb
    thumb_served = path.name.endswith(media_service.THUMB_SUFFIX)
    etag = f'"{row.sha256}-w640"' if thumb_served else f'"{row.sha256}"'
    # The id → sha256 link never changes once processed, but the bytes are admin-only.
    headers = {"Cache-Control": "private, max-age=86400", "ETag": etag}
    return FileResponse(path, media_type=media_service.CONTENT_TYPE[path.suffix], headers=headers)


@router.put("/media/{media_id}/chunks/{n}", status_code=204, openapi_extra=_CHUNK_BODY)
async def put_media_chunk(
    media_id: str, n: int, request: Request, _: AdminDep, db: DbDep, settings: SettingsDep
) -> Response:
    row = media_service.get(db, media_id)
    if row.status != "uploading":
        raise ServiceError(409, "upload_complete", media_id)
    data = await _read_chunk(request, settings)
    uploads.put_chunk(settings, uploads.get(db, media_id), n, data)
    return Response(status_code=204)


@router.post("/media/{media_id}/complete", response_model=s.Completed)
def complete_media(media_id: str, _: AdminDep, db: DbDep, settings: SettingsDep) -> s.Completed:
    row, job = media_service.complete(db, settings, media_id)
    audit.record(db, "media.upload", route_id=row.route_id, target=row.id, after={"jobId": job.id})
    db.commit()
    return s.Completed(media=views.media_out(db, settings, row), job_id=job.id)


@router.patch("/media/{media_id}", response_model=s.MediaOut)
def patch_media(
    media_id: str, body: s.MediaPatch, _: AdminDep, db: DbDep, settings: SettingsDep
) -> s.MediaOut:
    before = {"credit": media_service.get(db, media_id).credit}
    row = media_service.set_credit(db, media_id, body.credit)
    audit.record(
        db,
        "media.credit",
        route_id=row.route_id,
        target=row.id,
        before=before,
        after={"credit": row.credit},
    )
    db.commit()
    return views.media_out(db, settings, row)


@router.delete("/media/{media_id}", status_code=204)
def delete_media(media_id: str, _: AdminDep, db: DbDep, settings: SettingsDep) -> Response:
    route_id = media_service.get(db, media_id).route_id
    media_service.remove(db, settings, media_id)
    audit.record(db, "media.delete", route_id=route_id, target=media_id)
    db.commit()
    return Response(status_code=204)


# --- imports ---------------------------------------------------------------------------


@router.post("/imports", response_model=s.ImportOut, status_code=201)
def create_import(
    body: s.ImportCreate, _: AdminDep, db: DbDep, settings: SettingsDep
) -> s.ImportOut:
    row = imports.create(db, settings, kind=body.kind, filename=body.filename, size=body.bytes)
    audit.record(db, "import.create", target=row.id, after={"kind": row.kind})
    db.commit()
    return views.import_out(db, settings, row)


@router.get("/imports/{import_id}", response_model=s.ImportOut)
def get_import(import_id: str, _: AdminDep, db: DbDep, settings: SettingsDep) -> s.ImportOut:
    return views.import_out(db, settings, imports.get(db, import_id))


@router.put("/imports/{import_id}/chunks/{n}", status_code=204, openapi_extra=_CHUNK_BODY)
async def put_import_chunk(
    import_id: str, n: int, request: Request, _: AdminDep, db: DbDep, settings: SettingsDep
) -> Response:
    row = imports.get(db, import_id)
    if row.status != "uploading":
        raise ServiceError(409, "upload_complete", import_id)
    data = await _read_chunk(request, settings)
    uploads.put_chunk(settings, uploads.get(db, import_id), n, data)
    return Response(status_code=204)


@router.post("/imports/{import_id}/complete", response_model=s.ImportOut)
def complete_import(import_id: str, _: AdminDep, db: DbDep, settings: SettingsDep) -> s.ImportOut:
    row = imports.complete(db, settings, import_id)
    audit.record(db, "import.read", target=row.id, after={"status": row.status})
    db.commit()
    return views.import_out(db, settings, row)


@router.post("/imports/{import_id}/apply", response_model=s.RouteRef, status_code=201)
def apply_import(
    import_id: str, body: s.ImportApply, _: AdminDep, db: DbDep, settings: SettingsDep
) -> s.RouteRef:
    route = imports.apply(db, settings, import_id, trip_id=body.trip_id)
    audit.record(
        db, "import.apply", route_id=route.id, target=import_id, after={"tripId": body.trip_id}
    )
    db.commit()
    return s.RouteRef(route_id=route.id)
