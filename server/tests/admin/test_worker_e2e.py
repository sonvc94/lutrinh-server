"""Admin API → jobs → worker: an uploaded photo becomes ready, without EXIF, job pollable."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lutrinh.adapters.routing import Routers, Throttle
from lutrinh.api.admin import PREFIX
from lutrinh.db.engine import make_sessionmaker
from lutrinh.jobs import Context, worker
from lutrinh.services import media as media_service
from tests.admin.conftest import Admin
from tests.admin.helpers import upload
from tests.jobs.conftest import FakeRouter
from tests.jobs.test_media import phone_jpeg


def test_uploaded_photo_is_processed_by_the_worker(admin: Admin, client: TestClient) -> None:
    rid = client.post(f"{PREFIX}/routes", json={"title": "Hà Giang"}).json()["id"]
    data = phone_jpeg((1200, 900))
    r = client.post(
        f"{PREFIX}/media",
        json={"routeId": rid, "filename": "IMG_1.JPG", "contentType": "image/jpeg",
              "bytes": len(data)},
    )  # fmt: skip
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    upload(client, "media", mid, data, r.json()["upload"]["chunkBytes"])
    done = client.post(f"{PREFIX}/media/{mid}/complete").json()
    assert done["media"]["status"] == "processing"
    job_id = done["jobId"]

    ctx = Context(
        admin.settings,
        make_sessionmaker(admin.app.state.engine),
        Routers(FakeRouter(), None, Throttle(0)),
    )
    assert worker.run(ctx, once=True, nightly=False) == 1

    m = client.get(f"{PREFIX}/media/{mid}").json()
    assert m["status"] == "ready" and (m["width"], m["height"]) == (900, 1200)
    stored = media_service.file_path(admin.settings, m["sha256"], "photo").read_bytes()
    assert b"Exif" not in stored and len(stored) == m["bytes"]
    job = client.get(f"{PREFIX}/jobs/{job_id}").json()
    assert job["status"] == "done"


def test_media_file_serves_the_preview_and_the_original_once_processed(
    admin: Admin, client: TestClient
) -> None:
    rid = client.post(f"{PREFIX}/routes", json={"title": "Hà Giang"}).json()["id"]
    data = phone_jpeg((2000, 1500))
    r = client.post(
        f"{PREFIX}/media",
        json={"routeId": rid, "filename": "IMG_2.JPG", "contentType": "image/jpeg",
              "bytes": len(data)},
    )  # fmt: skip
    mid = r.json()["id"]
    upload(client, "media", mid, data, r.json()["upload"]["chunkBytes"])
    client.post(f"{PREFIX}/media/{mid}/complete")
    pending = client.get(f"{PREFIX}/media/{mid}/file")
    assert pending.status_code == 404 and pending.json()["error"]["code"] == "not_found"

    ctx = Context(
        admin.settings,
        make_sessionmaker(admin.app.state.engine),
        Routers(FakeRouter(), None, Throttle(0)),
    )
    assert worker.run(ctx, once=True, nightly=False) == 1
    sha = client.get(f"{PREFIX}/media/{mid}").json()["sha256"]

    full = client.get(f"{PREFIX}/media/{mid}/file")
    assert full.status_code == 200 and full.headers["content-type"] == "image/jpeg"
    assert full.content == media_service.file_path(admin.settings, sha, "photo").read_bytes()
    assert full.headers["etag"] == f'"{sha}"'
    assert full.headers["cache-control"].startswith("private")

    small = client.get(f"{PREFIX}/media/{mid}/file", params={"size": 640})
    assert small.status_code == 200
    assert small.content == media_service.thumb_path(admin.settings, sha).read_bytes()
    assert small.headers["etag"] == f'"{sha}-w640"'
    assert len(small.content) < len(full.content)

    part = client.get(f"{PREFIX}/media/{mid}/file", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and part.content == full.content[:100]
    assert part.headers["content-range"] == f"bytes 0-99/{len(full.content)}"

    assert client.get(f"{PREFIX}/media/{mid}/file", params={"size": 320}).status_code == 422
    assert client.get(f"{PREFIX}/media/m_nothere00000/file").status_code == 404


def test_media_file_without_a_preview_serves_the_original(admin: Admin, client: TestClient) -> None:
    rid = client.post(f"{PREFIX}/routes", json={"title": "Mộc Châu"}).json()["id"]
    data = phone_jpeg((800, 600))
    r = client.post(
        f"{PREFIX}/media",
        json={"routeId": rid, "filename": "IMG_3.JPG", "contentType": "image/jpeg",
              "bytes": len(data)},
    )  # fmt: skip
    mid = r.json()["id"]
    upload(client, "media", mid, data, r.json()["upload"]["chunkBytes"])
    client.post(f"{PREFIX}/media/{mid}/complete")
    ctx = Context(
        admin.settings,
        make_sessionmaker(admin.app.state.engine),
        Routers(FakeRouter(), None, Throttle(0)),
    )
    assert worker.run(ctx, once=True, nightly=False) == 1
    sha = client.get(f"{PREFIX}/media/{mid}").json()["sha256"]
    media_service.thumb_path(admin.settings, sha).unlink(missing_ok=True)
    small = client.get(f"{PREFIX}/media/{mid}/file", params={"size": 640})
    assert small.status_code == 200 and small.headers["etag"] == f'"{sha}"'
