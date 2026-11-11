"""Regenerate spec/samples/ha-giang-4n/ (route.json + expected.json) through lutrinh.core.package.

Run only when the sample itself must change: ``uv run python scripts/make_spec_sample.py``.
Committed bytes are the contract for the app; a change here is a spec change.
Coordinates and media are illustrative (media hashes are of placeholder strings).
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from lutrinh.core import package, polyline

OUT = Path(__file__).resolve().parents[2] / "spec" / "samples" / "ha-giang-4n"

STOPS = [
    # id, day, time, title, note, lat, lng, arrival, n_photos, video_ms
    (
        "s1",
        1,
        "07:30",
        "TP Hà Giang",
        "Thuê xe máy ở phố Nguyễn Thái Học.\nĐổ đầy xăng trước khi đi.",
        22.8233,
        104.9836,
        None,
        2,
        None,
    ),
    (
        "s2",
        1,
        "10:00",
        "Cổng Trời Quản Bạ",
        "Núi Đôi nhìn từ điểm dừng chân.",
        23.064,
        104.993,
        "motorbike",
        2,
        None,
    ),
    ("s3", 1, "15:30", "Yên Minh", "", 23.122, 105.143, "motorbike", 1, None),
    (
        "s4",
        2,
        "08:30",
        "Dinh thự họ Vương",
        "Vé 20.000 ₫, mở cửa 7:00–17:00.",
        23.237,
        105.249,
        "motorbike",
        2,
        None,
    ),
    (
        "s5",
        2,
        "11:30",
        "Cột cờ Lũng Cú",
        'Leo 389 bậc thang "lên đỉnh".',
        23.363,
        105.316,
        "motorbike",
        1,
        None,
    ),
    (
        "s6",
        2,
        "17:00",
        "Phố cổ Đồng Văn",
        "Chợ phiên sáng Chủ nhật.",
        23.279,
        105.36,
        "motorbike",
        1,
        42000,
    ),
    (
        "s7",
        3,
        "08:00",
        "Đèo Mã Pí Lèng",
        "Đi chậm, nhiều xe tải ở khúc cua.",
        23.244,
        105.418,
        "motorbike",
        1,
        58000,
    ),
    ("s8", 3, None, "Du Già", "Homestay bên suối.", 22.908, 105.219, "motorbike", 2, None),
    ("s9", 4, "14:00", "Về TP Hà Giang", "Trả xe.", 22.8233, 104.9836, "car", 0, None),
]

# stop id → arrivalNote (note on the travel into that stop; never on the first stop)
ARRIVAL_NOTES = {"s5": "Đường dốc khó đi. Gửi xe phía đối diện, 30.000 ₫."}


def _sha(label: str) -> str:
    return hashlib.sha256(f"lutrinh-sample:{label}".encode()).hexdigest()


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371008.8
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((la2 - la1) / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(h))


def _path(a: tuple[float, float], b: tuple[float, float], seed: int) -> list[tuple[float, float]]:
    n = 12
    pts = []
    for i in range(n + 1):
        t = i / n
        wiggle = 0.01 * math.sin(t * math.pi * 3 + seed) * math.sin(t * math.pi)
        pts.append(
            (
                round(a[0] + (b[0] - a[0]) * t + wiggle, 6),
                round(a[1] + (b[1] - a[1]) * t - wiggle, 6),
            )
        )
    return pts


def main() -> None:
    media: dict[str, package.MediaInfo] = {}
    stops = []
    n = 0
    for sid, day, time, title, note, lat, lng, arrival, photos, video_ms in STOPS:
        ids = []
        for _ in range(photos):
            n += 1
            mid = f"m_p{n:02d}"
            portrait = n % 3 == 0
            media[mid] = package.MediaInfo(
                id=mid,
                sha256=_sha(mid),
                type="photo",
                bytes=300_000 + n * 17_389,
                w=1707 if portrait else 2560,
                h=2560 if portrait else 1707,
                duration_ms=None,
                credit="Hoach Le Dinh, CC0" if n % 4 == 0 else "Ảnh: Lữ Trình",
            )
            ids.append(mid)
        if video_ms:
            n += 1
            mid = f"m_v{n:02d}"
            media[mid] = package.MediaInfo(
                id=mid,
                sha256=_sha(mid),
                type="video",
                bytes=video_ms * 350,
                w=1280,
                h=720,
                duration_ms=video_ms,
                credit="Video: Lữ Trình",
            )
            ids.append(mid)
        stop = {
            "id": sid,
            "day": day,
            "time": time,
            "title": title,
            "note": note,
            "lat": lat,
            "lng": lng,
            "arrival": arrival,
            "media": ids,
        }
        if sid in ARRIVAL_NOTES:
            stop["arrivalNote"] = ARRIVAL_NOTES[sid]
        stops.append(stop)

    legs = []
    for i in range(1, len(stops)):
        a, b = stops[i - 1], stops[i]
        pts = _path((a["lat"], a["lng"]), (b["lat"], b["lng"]), seed=i)
        dist = round(sum(_haversine(pts[k], pts[k + 1]) for k in range(len(pts) - 1)))
        profile = "car" if b["arrival"] == "car" else "motorbike"
        legs.append(
            {
                "to": b["id"],
                "profile": profile,
                # leg 7 → 8 is the car fallback (R36), leg 8 → 9 drawn by hand in the admin
                "usedProfile": "car" if i == 7 else None,
                "source": "manual" if i == 8 else "valhalla",
                "status": "ok",
                "distanceM": dist,
                "durationS": round(dist / 9.5),
                "path": polyline.encode(pts),
            }
        )

    draft = {
        "title": "Vòng cung Hà Giang 4 ngày",
        "description": "Xe máy, cao nguyên đá Đồng Văn, đèo Mã Pí Lèng, Du Già.",
        "days": 4,
        "cover": "m_p01",
        "readyMade": "ha-giang",
        "credits": ["Ảnh: Hoach Le Dinh, CC0", "Đường đi: © OpenStreetMap (ODbL)"],
        "stops": stops,
        "legs": legs,
    }
    built = package.build(
        draft,
        route_id="rt_5f3c9a1e",
        version=3,
        published_at=datetime(2026, 11, 20, 3, 0, tzinfo=UTC),
        media=media,
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "route.json").write_bytes(built.route_json)
    doc = built.document
    expected = {
        "sha256": built.sha256,
        "bytes": len(built.route_json),
        "stops": len(doc["stops"]),
        "legs": len(doc["legs"]),
        "photos": sum(1 for m in doc["media"] if m["type"] == "photo"),
        "videos": sum(1 for m in doc["media"] if m["type"] == "video"),
        "sizeMedia": doc["size"]["media"],
        "sizeFiles": doc["size"]["files"],
    }
    (OUT / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(expected))


if __name__ == "__main__":
    main()
