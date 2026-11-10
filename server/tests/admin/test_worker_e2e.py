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
