"""Chunked uploads (page 03: 8 MB chunks behind a 10 MB proxy body limit, resumable).

``POST`` creates the upload with its total size; ``PUT …/chunks/{n}`` stores chunk ``n``
(0-based, every chunk ``chunk_bytes`` long except the last); ``GET`` lists what arrived so a
client can resume; ``POST …/complete`` joins the chunks into ``uploads/<id>/original`` and
records its sha256. Media and imports use the same id as their upload.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from lutrinh.config import Settings
from lutrinh.db.models import Upload, utcnow
from lutrinh.services.errors import ServiceError, not_found

ORIGINAL = "original"


def directory(settings: Settings, upload_id: str) -> Path:
    return settings.uploads_dir / upload_id


def original_path(settings: Settings, upload_id: str) -> Path:
    return directory(settings, upload_id) / ORIGINAL


def chunk_count(upload: Upload) -> int:
    return max(1, -(-upload.bytes // upload.chunk_bytes))


def start(
    session: Session,
    settings: Settings,
    *,
    upload_id: str,
    purpose: str,
    filename: str,
    content_type: str | None,
    size: int,
    max_bytes: int,
) -> Upload:
    if size <= 0:
        raise ServiceError(422, "invalid_request", "bytes must be > 0")
    if size > max_bytes:
        raise ServiceError(413, "too_large", f"{size} > {max_bytes}", maxBytes=max_bytes)
    row = Upload(
        id=upload_id,
        purpose=purpose,
        filename=filename,
        content_type=content_type,
        bytes=size,
        chunk_bytes=settings.upload_chunk_bytes,
    )
    session.add(row)
    session.flush()
    directory(settings, upload_id).mkdir(parents=True, exist_ok=True)
    return row


def get(session: Session, upload_id: str) -> Upload:
    row = session.get(Upload, upload_id)
    if row is None:
        raise not_found("upload", upload_id)
    return row


def _expected(upload: Upload, n: int) -> int:
    count = chunk_count(upload)
    if not 0 <= n < count:
        raise ServiceError(422, "bad_chunk", f"chunk {n} not in 0…{count - 1}")
    if n < count - 1:
        return upload.chunk_bytes
    return upload.bytes - upload.chunk_bytes * (count - 1)


def put_chunk(settings: Settings, upload: Upload, n: int, data: bytes) -> None:
    if upload.completed_at is not None:
        raise ServiceError(409, "upload_complete", upload.id)
    want = _expected(upload, n)
    if len(data) != want:
        raise ServiceError(422, "bad_chunk", f"chunk {n} has {len(data)} bytes, expected {want}")
    folder = directory(settings, upload.id)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{n}.part.tmp"
    tmp.write_bytes(data)
    os.replace(tmp, folder / f"{n}.part")


def received(settings: Settings, upload: Upload) -> list[int]:
    folder = directory(settings, upload.id)
    if upload.completed_at is not None:
        return list(range(chunk_count(upload)))
    return [n for n in range(chunk_count(upload)) if (folder / f"{n}.part").is_file()]


def complete(
    session: Session, settings: Settings, upload: Upload, *, now: datetime | None = None
) -> Upload:
    if upload.completed_at is not None:
        return upload
    count = chunk_count(upload)
    have = set(received(settings, upload))
    missing = [n for n in range(count) if n not in have]
    if missing:
        raise ServiceError(409, "chunks_missing", f"{len(missing)} missing", missing=missing)
    folder = directory(settings, upload.id)
    digest = hashlib.sha256()
    tmp = folder / f"{ORIGINAL}.tmp"
    with tmp.open("wb") as out:
        for n in range(count):
            data = (folder / f"{n}.part").read_bytes()
            digest.update(data)
            out.write(data)
    os.replace(tmp, folder / ORIGINAL)
    for n in range(count):
        (folder / f"{n}.part").unlink(missing_ok=True)
    upload.sha256 = digest.hexdigest()
    upload.completed_at = now or utcnow()
    session.flush()
    return upload


def remove(session: Session, settings: Settings, upload_id: str) -> None:
    row = session.get(Upload, upload_id)
    if row is not None:
        session.delete(row)
    shutil.rmtree(directory(settings, upload_id), ignore_errors=True)
