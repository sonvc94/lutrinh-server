"""Public API ``/api/v1`` (page 03): lookups, tokens, downloads, limits, updates, meta."""

from __future__ import annotations

import hashlib
from datetime import timedelta

from sqlalchemy import func, select

from lutrinh.core import codes
from lutrinh.db.models import DailyCount, Draft, IpEvent, RouteVersion
from lutrinh.services import codes as code_service
from lutrinh.services import media as media_service
from lutrinh.services import publishing
from tests.public.conftest import PHOTO, VIDEO, Public

ACCEPT = {"Accept": "application/vnd.lutrinh.route+json;v=1"}


def unknown_code(p: Public) -> str:
    while True:
        c = codes.generate()
        if c != p.code:
            return c


def lookup(p: Public, ip: str = "203.0.113.7") -> dict[str, object]:
    r = p.client(ip).get(f"/api/v1/codes/{codes.display(p.code)}", headers=ACCEPT)
    assert r.status_code == 200, r.text
    body: dict[str, object] = r.json()
    return body


def test_meta(pub: Public) -> None:
    r = pub.client().get("/api/v1/meta")
    assert r.status_code == 200
    assert r.json() == {
        "formatVersions": [1],
        "minAppVersion": {"android": "0.0.0", "ios": "0.0.0"},
        "maintenance": False,
        "message": None,
    }


def test_lookup_returns_summary_and_token(pub: Public) -> None:
    body = lookup(pub)
    token = body.pop("downloadToken")
    assert isinstance(token, str) and token.startswith("tk_") and len(token) > 40
    sha_photo = hashlib.sha256(PHOTO).hexdigest()
    assert body.pop("overview")
    assert body.pop("region") == {
        "bounds": {"east": 105.95, "north": 20.3, "south": 20.2425, "west": 105.8901},
        "readyMade": None,
    }
    assert body == {
        "code": codes.display(pub.code),
        "routeId": pub.route_id,
        "version": 1,
        "formatVersion": 1,
        "title": "Ninh Bình 2 ngày",
        "description": "Tràng An, Hang Múa",
        "days": 2,
        "stops": 2,
        "distanceM": 4200,
        "photos": 1,
        "videos": 1,
        "bytes": len(PHOTO) + len(VIDEO),
        "files": 2,
        "cover": f"/api/v1/dl/{token}/media/{sha_photo}?w=640",
        "tokenExpiresAt": "2026-11-20T10:00:00Z",
    }


def test_lookup_accepts_typed_forms(pub: Public) -> None:
    typed = codes.display(pub.code).lower().replace("-", " ")
    assert pub.client().get(f"/api/v1/codes/{typed}").status_code == 200


def test_unknown_code_is_404(pub: Public) -> None:
    r = pub.client().get(f"/api/v1/codes/{unknown_code(pub)}")
    assert r.status_code == 404
    assert r.json() == {
        "error": {
            "code": "code_not_found",
            "retryAfterS": None,
            "detail": r.json()["error"]["detail"],
        }
    }


def test_bad_format_and_bad_check_are_400(pub: Public) -> None:
    c = pub.client()
    assert c.get("/api/v1/codes/ABC").json()["error"]["code"] == "bad_format"
    wrong = pub.code[:7] + ("2" if pub.code[7] != "2" else "3")
    r = c.get(f"/api/v1/codes/{wrong}")
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_check"


def test_revoked_code_is_410(pub: Public) -> None:
    with pub.session() as s:
        code_service.revoke(s, pub.code)
        s.commit()
    r = pub.client().get(f"/api/v1/codes/{pub.code}")
    assert r.status_code == 410 and r.json()["error"]["code"] == "code_revoked"


def test_unpublished_route_is_410(pub: Public) -> None:
    with pub.session() as s:
        publishing.unpublish(s, pub.route_id)
        s.commit()
    r = pub.client().get(f"/api/v1/codes/{pub.code}")
    assert r.status_code == 410 and r.json()["error"]["code"] == "route_unpublished"


def test_eleventh_failed_lookup_in_an_hour_is_429(pub: Public) -> None:
    c = pub.client()
    for _ in range(10):
        assert c.get(f"/api/v1/codes/{unknown_code(pub)}").status_code == 404
    r = c.get(f"/api/v1/codes/{unknown_code(pub)}")
    assert r.status_code == 429
    assert r.json()["error"] == {"code": "rate_limited", "retryAfterS": 3600}
    assert r.headers["Retry-After"] == "3600"
    # The lock covers real codes too; another IP is not affected.
    assert c.get(f"/api/v1/codes/{pub.code}").status_code == 429
    assert pub.client("198.51.100.1").get(f"/api/v1/codes/{pub.code}").status_code == 200
    pub.clock.advance(hours=1, seconds=1)
    assert c.get(f"/api/v1/codes/{pub.code}").status_code == 200


def test_bad_format_counts_as_a_failure(pub: Public) -> None:
    c = pub.client()
    for _ in range(10):
        assert c.get("/api/v1/codes/ABC").status_code == 400
    assert c.get(f"/api/v1/codes/{pub.code}").status_code == 429


def test_revoked_lookups_are_not_failures(pub: Public) -> None:
    with pub.session() as s:
        code_service.revoke(s, pub.code)
        s.commit()
    c = pub.client()
    for _ in range(12):
        assert c.get(f"/api/v1/codes/{pub.code}").status_code == 410


def test_lock_ladder_1h_4h_24h_then_resets(pub: Public) -> None:
    c = pub.client()

    def fail_until_locked() -> int:
        for _ in range(10):
            assert c.get(f"/api/v1/codes/{unknown_code(pub)}").status_code == 404
        r = c.get(f"/api/v1/codes/{unknown_code(pub)}")
        assert r.status_code == 429
        retry: int = r.json()["error"]["retryAfterS"]
        pub.clock.advance(seconds=retry + 1)
        return retry

    assert fail_until_locked() == 3600
    assert fail_until_locked() == 4 * 3600
    assert fail_until_locked() == 24 * 3600
    assert fail_until_locked() == 24 * 3600
    pub.clock.advance(hours=24, seconds=1)
    assert fail_until_locked() == 3600


def test_thirty_lookups_an_hour(pub: Public) -> None:
    c = pub.client()
    for _ in range(30):
        assert c.get(f"/api/v1/codes/{pub.code}").status_code == 200
        pub.clock.advance(seconds=60)
    r = c.get(f"/api/v1/codes/{pub.code}")
    assert r.status_code == 429
    # 30 lookups over the last 30 minutes: the first leaves the hour in 30 minutes.
    assert r.json()["error"]["retryAfterS"] == 1800
    pub.clock.advance(seconds=1801)
    assert c.get(f"/api/v1/codes/{pub.code}").status_code == 200


def test_system_alarm_mails_and_tightens(pub: Public) -> None:
    pub.settings.alarm_bad_lookups_per_hour = 6
    for n in range(3):
        c = pub.client(f"192.0.2.{n}")
        for _ in range(2):
            assert c.get(f"/api/v1/codes/{unknown_code(pub)}").status_code == 404
    assert [s for s, _ in pub.mailer.sent] == ["Lữ Trình: nhiều lần tra mã sai"]
    c = pub.client("192.0.2.99")
    for _ in range(3):
        assert c.get(f"/api/v1/codes/{unknown_code(pub)}").status_code == 404
    assert c.get(f"/api/v1/codes/{pub.code}").status_code == 429
    assert len(pub.mailer.sent) == 1
    pub.clock.advance(hours=25)
    c = pub.client("192.0.2.100")
    for _ in range(4):
        assert c.get(f"/api/v1/codes/{unknown_code(pub)}").status_code == 404


def test_route_download_is_the_previewed_version(pub: Public) -> None:
    token = lookup(pub)["downloadToken"]
    with pub.session() as s:
        publishing.republish(s, pub.route_id, 1)  # v2 published while the user downloads
        s.commit()
        v1 = s.get(RouteVersion, (pub.route_id, 1))
        assert v1 is not None
    c = pub.client()
    r = c.get(f"/api/v1/dl/{token}/route", headers=ACCEPT)
    assert r.status_code == 200
    assert r.content == v1.route_json
    assert r.headers["ETag"] == f'"{hashlib.sha256(r.content).hexdigest()}"'
    assert r.headers["Content-Type"] == "application/vnd.lutrinh.route+json;v=1"
    r = c.get(f"/api/v1/dl/{token}/route", headers={"If-None-Match": r.headers["ETag"]})
    assert r.status_code == 304


def test_route_downloads_per_code_per_ip(pub: Public) -> None:
    token = lookup(pub)["downloadToken"]
    c = pub.client()
    for _ in range(10):
        assert c.get(f"/api/v1/dl/{token}/route").status_code == 200
    r = c.get(f"/api/v1/dl/{token}/route")
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert pub.client("198.51.100.2").get(f"/api/v1/dl/{token}/route").status_code == 200


def test_media_range_206_reassembles_to_sha256(pub: Public) -> None:
    token = lookup(pub)["downloadToken"]
    sha = hashlib.sha256(VIDEO).hexdigest()
    url = f"/api/v1/dl/{token}/media/{sha}"
    c = pub.client()
    parts = []
    for rng in ("bytes=0-499999", "bytes=500000-999999", "bytes=1000000-"):
        r = c.get(url, headers={"Range": rng})
        assert r.status_code == 206, r.text
        assert r.headers["Cache-Control"] == "public, max-age=31536000, immutable"
        parts.append(r.content)
    assert r.headers["Content-Range"] == f"bytes 1000000-{len(VIDEO) - 1}/{len(VIDEO)}"
    assert hashlib.sha256(b"".join(parts)).hexdigest() == sha


def test_media_whole_file_and_preview(pub: Public) -> None:
    token = lookup(pub)["downloadToken"]
    sha = hashlib.sha256(PHOTO).hexdigest()
    c = pub.client()
    r = c.get(f"/api/v1/dl/{token}/media/{sha}")
    assert r.status_code == 200 and r.content == PHOTO
    assert r.headers["Content-Type"] == "image/jpeg" and r.headers["ETag"] == f'"{sha}"'
    # No 640 px preview on disk yet (the worker makes it): the full photo.
    assert c.get(f"/api/v1/dl/{token}/media/{sha}?w=640").content == PHOTO
    media_service.thumb_path(pub.settings, sha).write_bytes(b"small")
    r = c.get(f"/api/v1/dl/{token}/media/{sha}?w=640")
    assert r.content == b"small" and r.headers["ETag"] == f'"{sha}-w640"'


def test_media_outside_the_version_is_404(pub: Public) -> None:
    token = lookup(pub)["downloadToken"]
    c = pub.client()
    assert c.get(f"/api/v1/dl/{token}/media/{'0' * 64}").status_code == 404
    assert c.get(f"/api/v1/dl/{token}/media/..%2F..%2Fetc").status_code == 404


def test_media_requests_per_token(pub: Public) -> None:
    token = lookup(pub)["downloadToken"]
    sha = hashlib.sha256(PHOTO).hexdigest()
    c = pub.client()
    for _ in range(6):  # 2 files × 3
        assert c.get(f"/api/v1/dl/{token}/media/{sha}").status_code == 200
    r = c.get(f"/api/v1/dl/{token}/media/{sha}")
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


def test_token_expires_after_two_hours(pub: Public) -> None:
    token = lookup(pub)["downloadToken"]
    c = pub.client()
    pub.clock.advance(hours=2)
    r = c.get(f"/api/v1/dl/{token}/route")
    assert r.status_code == 401 and r.json()["error"]["code"] == "token_expired"
    assert c.get("/api/v1/dl/tk_nope/route").status_code == 401


def test_token_dies_with_the_route(pub: Public) -> None:
    token = lookup(pub)["downloadToken"]
    with pub.session() as s:
        publishing.unpublish(s, pub.route_id)
        s.commit()
    sha = hashlib.sha256(PHOTO).hexdigest()
    r = pub.client().get(f"/api/v1/dl/{token}/media/{sha}")
    assert r.status_code == 410 and r.json()["error"]["code"] == "route_unpublished"


def test_x_accel_redirect(pub: Public) -> None:
    pub.settings.media_accel = True
    token = lookup(pub)["downloadToken"]
    sha = hashlib.sha256(VIDEO).hexdigest()
    r = pub.client().get(f"/api/v1/dl/{token}/media/{sha}")
    assert r.status_code == 200 and r.content == b""
    assert r.headers["X-Accel-Redirect"] == f"/{sha[:2]}/{sha[2:4]}/{sha}.mp4"
    assert r.headers["Content-Type"] == "video/mp4"


def test_old_app_gets_406(pub: Public) -> None:
    old = {"Accept": "application/vnd.lutrinh.route+json;v=0"}
    r = pub.client().get(f"/api/v1/codes/{pub.code}", headers=old)
    assert r.status_code == 406 and r.json()["error"]["code"] == "format_unsupported"
    token = lookup(pub)["downloadToken"]
    assert pub.client().get(f"/api/v1/dl/{token}/route", headers=old).status_code == 406


def test_maintenance(pub: Public) -> None:
    pub.settings.maintenance = True
    pub.settings.maintenance_message = "Bảo trì đến 22:00"
    c = pub.client()
    meta = c.get("/api/v1/meta").json()
    assert meta["maintenance"] is True and meta["message"] == "Bảo trì đến 22:00"
    r = c.get(f"/api/v1/codes/{pub.code}")
    assert r.status_code == 503 and r.json()["error"]["code"] == "maintenance"
    assert c.post("/api/v1/updates", json=[]).status_code == 503


def test_bandwidth_warning_and_cap(pub: Public) -> None:
    pub.settings.bandwidth_month_bytes = len(VIDEO) * 2
    token = lookup(pub)["downloadToken"]
    sha = hashlib.sha256(VIDEO).hexdigest()
    c = pub.client()
    assert (
        c.get(f"/api/v1/dl/{token}/media/{sha}", headers={"Range": "bytes=0-99"}).status_code == 206
    )
    assert pub.mailer.sent == []
    assert c.get(f"/api/v1/dl/{token}/media/{sha}").status_code == 200
    assert c.get(f"/api/v1/dl/{token}/media/{sha}").status_code == 200
    assert [s for s, _ in pub.mailer.sent] == ["Lữ Trình: băng thông tháng"]
    r = c.get(f"/api/v1/dl/{token}/media/{sha}")
    assert r.status_code == 503 and r.json()["error"]["code"] == "quota"


def test_update_check_reports_newer_after_republish(pub: Public) -> None:
    c = pub.client()
    link = {"code": pub.code, "routeId": pub.route_id, "version": 1}
    r = c.post("/api/v1/updates", json=[link])
    assert r.json() == {
        "results": [{"code": pub.code, "routeId": pub.route_id, "status": "current", "version": 1}]
    }
    with pub.session() as s:
        publishing.republish(s, pub.route_id, 1, note="Sửa giờ")
        s.commit()
    r = c.post("/api/v1/updates", json=[link])
    assert r.status_code == 200
    (result,) = r.json()["results"]
    assert result["status"] == "newer" and result["version"] == 2 and result["note"] == "Sửa giờ"
    assert result["changes"] == {
        "stopsAdded": [],
        "stopsRemoved": [],
        "stopsEdited": 0,
        "mediaAdded": 0,
        "bytes": 0,
    }


def test_update_changes_list_stops_and_media(pub: Public) -> None:
    with pub.session() as s:
        d = s.get(Draft, pub.route_id)
        assert d is not None
        body = dict(d.body)
        body["stops"] = [
            body["stops"][0] | {"note": "Đi sớm", "media": []},
            {**body["stops"][1], "id": "s_c", "title": "Hang Múa mới"},
        ]
        body["cover"] = None
        body["legs"] = [body["legs"][0] | {"to": "s_c"}]
        d.body = body
        s.flush()
        publishing.publish(s, pub.route_id, long_leg_km=150)
        s.commit()
    r = pub.client().post(
        "/api/v1/updates", json=[{"code": pub.code, "routeId": pub.route_id, "version": 1}]
    )
    (result,) = r.json()["results"]
    assert result["status"] == "newer"
    assert result["changes"] == {
        "stopsAdded": ["s_c"],
        "stopsRemoved": ["s_b"],
        "stopsEdited": 1,
        "mediaAdded": 0,
        "bytes": 0,
    }


def test_update_statuses(pub: Public) -> None:
    other = unknown_code(pub)
    links = [
        {"code": pub.code, "routeId": "rt_other", "version": 1},
        {"code": other, "routeId": pub.route_id, "version": 1},
        {"code": "nonsense", "routeId": pub.route_id, "version": 1},
    ]
    c = pub.client()
    statuses = [x["status"] for x in c.post("/api/v1/updates", json=links).json()["results"]]
    assert statuses == ["unpublished", "unpublished", "unpublished"]
    with pub.session() as s:
        code_service.set_expiry(s, pub.code, pub.clock.now - timedelta(minutes=1))
        s.commit()
    link = {"code": pub.code, "routeId": pub.route_id, "version": 1}
    assert c.post("/api/v1/updates", json=[link]).json()["results"][0]["status"] == "expired"
    with pub.session() as s:
        code_service.set_expiry(s, pub.code, None)
        code_service.revoke(s, pub.code)
        s.commit()
    assert c.post("/api/v1/updates", json=[link]).json()["results"][0]["status"] == "revoked"
    r = c.post("/api/v1/updates", json=[link] * 51)
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_many"
    assert c.post("/api/v1/updates", json=[{"code": 1}]).status_code == 422


def test_daily_counts_and_ip_retention(pub: Public) -> None:
    token = lookup(pub)["downloadToken"]
    c = pub.client()
    c.get(f"/api/v1/codes/{unknown_code(pub)}")
    c.get(f"/api/v1/dl/{token}/route")
    with pub.session() as s:
        rows = {(r.route_id, r.kind): r.count for r in s.scalars(select(DailyCount))}
        assert rows == {
            (pub.route_id, "lookup"): 1,
            ("", "bad_lookup"): 1,
            (pub.route_id, "download"): 1,
        }
        assert s.scalar(select(func.count()).select_from(IpEvent)) == 4
    pub.clock.advance(days=14, seconds=1)
    lookup(pub, "198.51.100.3")
    with pub.session() as s:
        ips = set(s.scalars(select(IpEvent.ip)))
        assert ips == {"198.51.100.3"}
