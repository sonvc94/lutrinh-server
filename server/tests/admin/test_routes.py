"""Routes, drafts, legs, trash, publish rules, media uploads, backup import, app shell."""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lutrinh.api.admin import PREFIX
from lutrinh.core import polyline
from lutrinh.db.engine import make_sessionmaker
from lutrinh.db.models import Job
from lutrinh.services import codes as code_service
from lutrinh.services.errors import ServiceError
from tests.admin.conftest import Admin
from tests.admin.helpers import import_file, upload


def _stop(
    sid: str, day: int, time: str | None, lat: float, lng: float, **kw: Any
) -> dict[str, Any]:
    return {
        "id": sid,
        "day": day,
        "time": time,
        "title": sid,
        "note": "",
        "lat": lat,
        "lng": lng,
        "arrival": kw.get("arrival"),
        "media": kw.get("media", []),
    }


def _new_route(c: TestClient, title: str = "Ninh Bình") -> str:
    r = c.post(f"{PREFIX}/routes", json={"title": title})
    assert r.status_code == 201, r.text
    route_id: str = r.json()["id"]
    return route_id


def _put(c: TestClient, route_id: str, body: dict[str, Any]) -> Any:
    etag = c.get(f"{PREFIX}/routes/{route_id}/draft").headers["ETag"]
    return c.put(f"{PREFIX}/routes/{route_id}/draft", json=body, headers={"If-Match": etag})


def _jobs(admin: Admin, kind: str) -> list[dict[str, Any]]:
    with make_sessionmaker(admin.app.state.engine)() as db:
        return [j.payload for j in db.query(Job).filter(Job.kind == kind).order_by(Job.id)]


def test_create_list_filter_and_trash(client: TestClient) -> None:
    a = _new_route(client, "Ninh Bình")
    b = _new_route(client, "Hà Giang")
    titles = {r["title"] for r in client.get(f"{PREFIX}/routes").json()}
    assert titles == {"Ninh Bình", "Hà Giang"}
    assert [r["id"] for r in client.get(f"{PREFIX}/routes", params={"q": "giang"}).json()] == [b]
    assert client.delete(f"{PREFIX}/routes/{a}").status_code == 204
    trash = client.get(f"{PREFIX}/routes", params={"status": "trash"}).json()
    assert [r["id"] for r in trash] == [a]
    assert client.get(f"{PREFIX}/routes", params={"status": "nope"}).status_code == 422
    body = client.get(f"{PREFIX}/routes/{a}/draft").json()["body"]
    assert _put(client, a, body).status_code == 409  # no edits in the trash
    assert client.post(f"{PREFIX}/routes/{a}/restore").json()["status"] == "draft"
    assert client.post(f"{PREFIX}/routes/{a}/restore").status_code == 409


def test_new_road_stops_and_moved_stops_queue_leg_jobs(admin: Admin, client: TestClient) -> None:
    rid = _new_route(client)
    body = client.get(f"{PREFIX}/routes/{rid}/draft").json()["body"]
    body["stops"] = [
        _stop("s_a", 1, "08:00", 20.25, 105.89),
        _stop("s_b", 1, "10:00", 20.22, 105.93, arrival="motorbike"),
        _stop("s_c", 1, "12:00", 20.21, 105.95, arrival="train"),
    ]
    r = _put(client, rid, body)
    assert r.status_code == 200, r.text
    assert len(r.json()["queuedJobs"]) == 1
    assert _jobs(admin, "legs.compute") == [{"routeId": rid, "toStop": "s_b"}]

    line = polyline.encode([(20.25, 105.89), (20.22, 105.93)])
    r = client.put(f"{PREFIX}/routes/{rid}/legs/s_b", json={"path": line, "durationS": 900})
    assert r.status_code == 200, r.text
    leg = r.json()["body"]["legs"][0]
    assert leg["source"] == "manual" and leg["distanceM"] > 4000 and leg["durationS"] == 900
    assert client.put(f"{PREFIX}/routes/{rid}/legs/s_c", json={"path": line}).status_code == 422
    assert client.put(f"{PREFIX}/routes/{rid}/legs/s_x", json={"path": line}).status_code == 404

    body = r.json()["body"]
    body["stops"][1]["lat"] = 20.20  # moved: the hand-drawn line is stale
    r = _put(client, rid, body)
    assert r.json()["body"]["legs"] == []
    r = client.post(f"{PREFIX}/routes/{rid}/legs/s_b/compute")
    assert r.status_code == 202
    job = client.get(f"{PREFIX}/jobs/{r.json()['jobId']}").json()
    assert job["kind"] == "legs.compute" and job["status"] == "queued"
    assert client.get(f"{PREFIX}/jobs/999").status_code == 404


def test_publish_rules_block_and_warn(client: TestClient) -> None:
    rid = _new_route(client)
    body = client.get(f"{PREFIX}/routes/{rid}/draft").json()["body"]
    body["stops"] = [
        _stop("s_a", 1, "10:00", 20.25, 105.89),
        _stop("s_b", 1, "09:00", 20.22, 105.93, arrival="train"),
    ]
    assert _put(client, rid, body).status_code == 200
    pre = client.get(f"{PREFIX}/routes/{rid}/publish").json()
    assert pre["canPublish"] is False
    assert [b["code"] for b in pre["blockers"]] == ["time_order"]
    r = client.post(f"{PREFIX}/routes/{rid}/publish", json={})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "publish_blocked"
    assert r.json()["error"]["problems"][0]["path"] == "/stops/1/time"
    assert client.get(f"{PREFIX}/routes/{rid}/versions").json() == []

    body["stops"][1]["time"] = "11:00"
    body["stops"][1]["arrival"] = "motorbike"
    assert _put(client, rid, body).status_code == 200
    pre = client.get(f"{PREFIX}/routes/{rid}/publish").json()
    assert pre["canPublish"] is True
    assert [w["code"] for w in pre["warnings"]] == ["leg_missing"]
    r = client.post(f"{PREFIX}/routes/{rid}/publish", json={"codePrefix": "HG"})
    assert r.status_code == 201
    assert r.json()["code"]["code"].startswith("HG")
    assert [w["code"] for w in r.json()["warnings"]] == ["leg_missing"]

    empty = _new_route(client)
    r = client.post(f"{PREFIX}/routes/{empty}/publish", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_package"
    assert client.post(f"{PREFIX}/routes/{empty}/unpublish").status_code == 409


def test_purge_retires_codes_for_ever(admin: Admin, client: TestClient) -> None:
    rid = _new_route(client)
    body = client.get(f"{PREFIX}/routes/{rid}/draft").json()["body"]
    body["stops"] = [_stop("s_a", 1, None, 20.25, 105.89), _stop("s_b", 1, None, 20.2, 105.9)]
    _put(client, rid, body)
    code = client.post(f"{PREFIX}/routes/{rid}/publish", json={}).json()["code"]["code"]
    assert client.delete(f"{PREFIX}/routes/{rid}", params={"purge": True}).status_code == 409
    assert client.delete(f"{PREFIX}/routes/{rid}").status_code == 204
    with make_sessionmaker(admin.app.state.engine)() as db, pytest.raises(ServiceError) as err:
        code_service.lookup(db, code)
    assert (err.value.status, err.value.code) == (410, "route_unpublished")
    assert client.delete(f"{PREFIX}/routes/{rid}", params={"purge": True}).status_code == 204
    assert client.get(f"{PREFIX}/routes/{rid}").status_code == 404
    assert _jobs(admin, "purge.trash") == [{"routeId": rid, "mediaIds": []}]
    with make_sessionmaker(admin.app.state.engine)() as db, pytest.raises(ServiceError) as err:
        code_service.lookup(db, code)
    assert (err.value.status, err.value.code) == (410, "route_unpublished")


def test_code_expiry_and_manual_issue(client: TestClient) -> None:
    rid = _new_route(client)
    r = client.post(f"{PREFIX}/routes/{rid}/codes", json={"prefix": "NB"})
    assert r.status_code == 201
    code = r.json()["code"]
    assert client.post(f"{PREFIX}/routes/{rid}/codes", json={}).status_code == 409
    r = client.patch(f"{PREFIX}/codes/{code}", json={"expiresAt": "2027-01-01T00:00:00Z"})
    assert r.status_code == 200 and r.json()["expiresAt"].startswith("2027-01-01")
    assert client.patch(f"{PREFIX}/codes/HG4N-7KQE", json={"expiresAt": None}).status_code in (
        400,
        404,
    )
    other = _new_route(client)
    assert client.post(f"{PREFIX}/routes/{other}/codes", json={"prefix": "O0"}).status_code == 422


def test_media_chunked_upload_queues_processing(admin: Admin, client: TestClient) -> None:
    rid = _new_route(client)
    data = bytes(range(200))
    r = client.post(
        f"{PREFIX}/media",
        json={"routeId": rid, "filename": "a.jpg", "contentType": "image/jpeg", "bytes": 200},
    )
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["type"] == "photo" and m["upload"]["chunks"] == 4 and m["upload"]["received"] == []
    mid = m["id"]
    chunk = f"{PREFIX}/media/{mid}/chunks"
    assert client.put(f"{chunk}/0", content=data[:10]).status_code == 422  # wrong size
    assert client.put(f"{chunk}/9", content=data[:64]).status_code == 422  # no such chunk
    assert client.put(f"{chunk}/0", content=bytes(65)).status_code == 413  # above one chunk
    assert client.put(f"{chunk}/0", content=data[:64]).status_code == 204
    missing = client.post(f"{PREFIX}/media/{mid}/complete")
    assert missing.status_code == 409 and missing.json()["error"]["missing"] == [1, 2, 3]
    assert client.get(f"{PREFIX}/media/{mid}").json()["upload"]["received"] == [0]
    upload(client, "media", mid, data, 64)
    r = client.post(f"{PREFIX}/media/{mid}/complete")
    assert r.status_code == 200, r.text
    assert r.json()["media"]["status"] == "processing"
    original = admin.settings.uploads_dir / mid / "original"
    assert original.read_bytes() == data
    assert _jobs(admin, "media.image") == [{"mediaId": mid, "path": f"uploads/{mid}/original"}]

    r = client.patch(f"{PREFIX}/media/{mid}", json={"credit": " Ảnh: Lữ Trình "})
    assert r.json()["credit"] == "Ảnh: Lữ Trình"
    body = client.get(f"{PREFIX}/routes/{rid}/draft").json()["body"]
    body["stops"] = [_stop("s_a", 1, None, 20.25, 105.89, media=[mid])]
    _put(client, rid, body)
    r = client.delete(f"{PREFIX}/media/{mid}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "media_in_use"
    assert [x["id"] for x in client.get(f"{PREFIX}/media", params={"routeId": rid}).json()] == [mid]
    bad = {"filename": "a.pdf", "contentType": "application/pdf", "bytes": 10}
    assert client.post(f"{PREFIX}/media", json=bad).status_code == 415
    big = {"filename": "v.mp4", "contentType": "video/mp4", "bytes": 300 * 1024 * 1024}
    assert client.post(f"{PREFIX}/media", json=big).status_code == 413


def _backup_zip(tmp: Path) -> bytes:
    db = tmp / "lutrinh.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE trips (id TEXT, title TEXT, description TEXT, start_date TEXT,
            end_date TEXT, cover_photo_id TEXT, created_at INTEGER);
        CREATE TABLE steps (id TEXT, trip_id TEXT, title TEXT, note TEXT, latitude REAL,
            longitude REAL, arrived_at TEXT, created_at INTEGER, is_draft INTEGER,
            transport_mode TEXT);
        CREATE TABLE photos (id TEXT, step_id TEXT, file_name TEXT, media_type TEXT,
            duration_ms INTEGER, position INTEGER, created_at INTEGER);
        INSERT INTO trips VALUES ('t1', 'Mù Cang Chải', 'Mùa lúa', '2026-09-20', '2026-09-21',
            'p1', 1);
        INSERT INTO steps VALUES
            ('a', 't1', 'Tú Lệ', '', 21.80, 104.30, '2026-09-20T09:00:00+07:00', 1, 0, NULL),
            ('b', 't1', 'Đèo Khau Phạ', 'Gió', 21.75, 104.25, '2026-09-20T11:30:00+07:00', 2, 0,
                'motorbike'),
            ('x', 't1', 'Nháp', '', 21.7, 104.2, '2026-09-20T12:00:00+07:00', 3, 1, NULL),
            ('c', 't1', 'La Pán Tẩn', '', 21.70, 104.15, '2026-09-21T08:00:00+07:00', 4, 0,
                'train');
        INSERT INTO photos VALUES ('p1', 'b', 'p1.jpg', 'photo', NULL, 0, 1),
            ('p2', 'b', 'v1.mp4', 'video', 12000, 1, 2),
            ('p3', 'c', 'gone.jpg', 'photo', NULL, 0, 3);
        """
    )
    conn.commit()
    conn.close()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        manifest = {"format": "lutrinh-backup", "formatVersion": 1, "schemaVersion": 10}
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.write(db, "lutrinh.db")
        zf.writestr("photos/p1.jpg", b"jpeg bytes")
        zf.writestr("photos/v1.mp4", b"mp4 bytes")
    return buf.getvalue()


def test_backup_import_makes_a_route_with_media_jobs(
    admin: Admin, client: TestClient, tmp_path: Path
) -> None:
    imp = import_file(client, "backup", "LuTrinh-saoluu.zip", _backup_zip(tmp_path))
    assert imp["status"] == "ready", imp
    (trip,) = imp["preview"]["trips"]
    assert trip["stops"] == 3 and trip["draftsSkipped"] == 1
    assert (trip["photos"], trip["videos"]) == (2, 1)
    assert client.post(f"{PREFIX}/imports/{imp['id']}/apply", json={}).status_code == 422
    r = client.post(f"{PREFIX}/imports/{imp['id']}/apply", json={"tripId": "nope"})
    assert r.status_code == 404
    r = client.post(f"{PREFIX}/imports/{imp['id']}/apply", json={"tripId": "t1"})
    assert r.status_code == 201, r.text
    rid = r.json()["routeId"]
    body = client.get(f"{PREFIX}/routes/{rid}/draft").json()["body"]
    assert [s["title"] for s in body["stops"]] == ["Tú Lệ", "Đèo Khau Phạ", "La Pán Tẩn"]
    assert [s["day"] for s in body["stops"]] == [1, 1, 2]
    assert len(body["stops"][1]["media"]) == 2 and body["stops"][2]["media"] == []
    assert body["cover"] == body["stops"][1]["media"][0]
    media = client.get(f"{PREFIX}/media", params={"routeId": rid}).json()
    assert sorted(m["type"] for m in media) == ["photo", "video"]
    assert len(_jobs(admin, "media.image")) == 1 and len(_jobs(admin, "media.video")) == 1
    stop_b = body["stops"][1]["id"]
    assert _jobs(admin, "legs.compute") == [{"routeId": rid, "toStop": stop_b}]


def test_import_failure_is_reported(client: TestClient) -> None:
    imp = import_file(client, "gpx", "bad.gpx", b"<html></html>")
    assert imp["status"] == "failed"
    assert imp["error"]["code"] == "not_gpx"
    assert client.post(f"{PREFIX}/imports/{imp['id']}/apply", json={}).status_code == 409


def test_error_envelope_shell_and_openapi(anon: TestClient, client: TestClient) -> None:
    r = client.get(f"{PREFIX}/nope")
    assert r.status_code == 404
    assert r.json() == {
        "error": {"code": "not_found", "retryAfterS": None, "detail": "/admin/api/v1/nope"}
    }
    r = client.post(f"{PREFIX}/routes", json={"title": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
    assert client.get(f"{PREFIX}/routes/rt_missing").json()["error"]["code"] == "route_not_found"
    page = anon.get("/admin")
    assert page.status_code == 200 and "Lữ Trình" in page.text
    assert anon.get("/admin/routes/rt_1").status_code == 200
    spec = anon.get("/openapi.json").json()
    assert f"{PREFIX}/routes/{{route_id}}/publish" in spec["paths"]
    assert "/admin" not in spec["paths"]


def test_admin_shell_serves_the_built_app(admin: Admin, anon: TestClient) -> None:
    dist = admin.settings.admin_dist_dir
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    assert anon.get("/admin/assets/app.js").text == "console.log(1)"
    assert anon.get("/admin/routes/rt_1").text == "<div id=root></div>"
    assert anon.get("/admin/../../etc/passwd").status_code in (200, 404)
    assert "root" in anon.get("/admin/%2e%2e/%2e%2e/etc/passwd").text


def test_route_summary_carries_the_draft_cover(client: TestClient) -> None:
    rid = _new_route(client)
    assert client.get(f"{PREFIX}/routes/{rid}").json()["cover"] is None
    body = client.get(f"{PREFIX}/routes/{rid}/draft").json()["body"]
    r = _put(client, rid, body | {"cover": "m_cover0000000"})
    assert r.status_code == 200, r.text
    listed = {x["id"]: x for x in client.get(f"{PREFIX}/routes").json()}
    assert listed[rid]["cover"] == "m_cover0000000"
