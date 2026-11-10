"""A small valid draft + its media rows, for core tests."""

from __future__ import annotations

import hashlib
from typing import Any

from lutrinh.core import polyline
from lutrinh.core.package import MediaInfo


def sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def media_infos() -> dict[str, MediaInfo]:
    return {
        "m_a": MediaInfo("m_a", sha("a"), "photo", 1000, 2560, 1707, None, " Ảnh: Lữ Trình "),
        "m_b": MediaInfo("m_b", sha("b"), "video", 5000, 1280, 720, 30000, "Video: Lữ Trình"),
    }


def draft() -> dict[str, Any]:
    return {
        "title": " Ninh Bình 2 ngày ",
        "description": "Tràng An, Hang Múa",
        "days": 2,
        "cover": "m_a",
        "readyMade": None,
        "credits": [],
        "stops": [
            {
                "id": "s_a",
                "day": 1,
                "time": "08:00",
                "title": "Tràng An",
                "note": "",
                "lat": 20.2541234567,
                "lng": 105.8901,
                "arrival": None,
                "media": ["m_a"],
            },
            {
                "id": "s_b",
                "day": 2,
                "time": None,
                "title": "Hang Múa",
                "note": "Leo 500 bậc",
                "lat": 20.2425,
                "lng": 105.9248,
                "arrival": "motorbike",
                "media": ["m_b"],
            },
        ],
        "legs": [
            {
                "to": "s_b",
                "profile": "motorbike",
                "usedProfile": None,
                "source": "valhalla",
                "status": "ok",
                "distanceM": 4200,
                "durationS": 600,
                "path": polyline.encode(
                    [(20.254123, 105.8901), (20.30, 105.95), (20.2425, 105.9248)]
                ),
            },
        ],
    }
