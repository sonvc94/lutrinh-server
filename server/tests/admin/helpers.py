"""Small builders shared by the admin API tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from lutrinh.api.admin import PREFIX

# Three stops in Hà Giang, local times 08:00, 10:00, 13:00 (+07:00) on 2026-11-20.
STOPS = [
    ("Cổng trời Quản Bạ", 23.0650, 104.9850, datetime(2026, 11, 20, 1, 0, tzinfo=UTC)),
    ("Yên Minh", 23.1200, 105.1400, datetime(2026, 11, 20, 3, 0, tzinfo=UTC)),
    ("Đồng Văn", 23.2780, 105.3600, datetime(2026, 11, 20, 6, 0, tzinfo=UTC)),
]


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def gpx_three_stops() -> bytes:
    wpts = "".join(
        f'<wpt lat="{lat}" lon="{lng}"><name>{name}</name><time>{_iso(t)}</time></wpt>'
        for name, lat, lng, t in STOPS
    )
    points = []
    for (_, la, lo, ta), (_, lb, lob, tb) in zip(STOPS, STOPS[1:], strict=False):
        for i in range(20):
            f = i / 20
            t = ta + (tb - ta) * f
            points.append((la + (lb - la) * f, lo + (lob - lo) * f, t))
    _, lat, lng, t = STOPS[-1]
    points.append((lat, lng, t))
    trkpts = "".join(
        f'<trkpt lat="{la:.6f}" lon="{lo:.6f}"><time>{_iso(t)}</time></trkpt>'
        for la, lo, t in points
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        "<metadata><name>Hà Giang 1 ngày</name><desc>Thử nghiệm</desc></metadata>"
        f"{wpts}<trk><name>track</name><trkseg>{trkpts}</trkseg></trk></gpx>"
    ).encode()


def upload(c: TestClient, kind_path: str, ident: str, data: bytes, chunk: int) -> None:
    for n in range(0, max(1, -(-len(data) // chunk))):
        r = c.put(
            f"{PREFIX}/{kind_path}/{ident}/chunks/{n}",
            content=data[n * chunk : (n + 1) * chunk],
            headers={"Content-Type": "application/octet-stream"},
        )
        assert r.status_code == 204, r.text


def import_file(c: TestClient, kind: str, filename: str, data: bytes) -> dict[str, Any]:
    r = c.post(f"{PREFIX}/imports", json={"kind": kind, "filename": filename, "bytes": len(data)})
    assert r.status_code == 201, r.text
    body = r.json()
    upload(c, "imports", body["id"], data, body["upload"]["chunkBytes"])
    r = c.post(f"{PREFIX}/imports/{body['id']}/complete")
    assert r.status_code == 200, r.text
    result: dict[str, Any] = r.json()
    return result


def later(t: datetime, minutes: int) -> datetime:
    return t + timedelta(minutes=minutes)
