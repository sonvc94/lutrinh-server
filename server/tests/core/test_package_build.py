from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from lutrinh.core import canonical_json, package
from tests.core.drafts import draft, media_infos

WHEN = datetime(2026, 11, 20, 10, 0, 5, tzinfo=timezone(timedelta(hours=7)))


def build(d: dict | None = None) -> package.BuiltPackage:  # type: ignore[type-arg]
    return package.build(
        d or draft(), route_id="rt_0a1b2c3d", version=1, published_at=WHEN, media=media_infos()
    )


def test_build_produces_valid_canonical_package() -> None:
    built = build()
    doc = json.loads(built.route_json)
    assert package.check(doc) == []
    assert canonical_json.dumps(doc) == built.route_json
    assert built.sha256 == hashlib.sha256(built.route_json).hexdigest()
    assert doc["route"]["publishedAt"] == "2026-11-20T03:00:05Z"
    assert doc["route"]["title"] == "Ninh Bình 2 ngày"
    assert doc["stops"][0]["lat"] == 20.254123
    assert [m["id"] for m in doc["media"]] == ["m_a", "m_b"]
    assert doc["media"][0]["credit"] == "Ảnh: Lữ Trình"
    assert doc["size"] == {"media": 6000, "files": 2}
    # bounds cover the leg path, which goes north of both stops
    assert doc["route"]["region"]["bounds"]["north"] == 20.3
    assert doc["route"]["region"]["bounds"]["east"] == 105.95


def test_build_is_deterministic() -> None:
    assert build().route_json == build().route_json


def test_legs_put_in_stop_order() -> None:
    d = draft()
    d["stops"].append(
        {
            "id": "s_c",
            "day": 2,
            "time": "15:00",
            "title": "Bái Đính",
            "note": "",
            "lat": 20.27,
            "lng": 105.86,
            "arrival": "car",
            "media": [],
        }
    )
    d["legs"].insert(
        0,
        {
            "to": "s_c",
            "profile": "car",
            "usedProfile": None,
            "source": "osrm",
            "status": "no_route",
            "distanceM": 0,
            "durationS": 0,
            "path": "",
        },
    )
    assert [leg["to"] for leg in build(d).document["legs"]] == ["s_b", "s_c"]


def test_missing_media_row_is_reported() -> None:
    d = draft()
    d["stops"][0]["media"].append("m_gone")
    with pytest.raises(package.PackageError) as err:
        build(d)
    assert [p.code for p in err.value.problems] == ["unknown_media"]


def test_media_without_credit_blocks_build() -> None:
    infos = media_infos()
    infos["m_a"] = package.MediaInfo("m_a", infos["m_a"].sha256, "photo", 1, 10, 10, None, None)
    with pytest.raises(package.PackageError) as err:
        package.build(draft(), route_id="rt_0a1b2c3d", version=1, published_at=WHEN, media=infos)
    assert {p.code for p in err.value.problems} == {"schema"}


def test_rule_violations_are_all_listed() -> None:
    d = draft()
    d["title"] = ""
    d["stops"] = d["stops"][:1]
    with pytest.raises(package.PackageError) as err:
        build(d)
    paths = {p.path for p in err.value.problems}
    assert "/route/title" in paths and "/stops" in paths


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError):
        package.format_timestamp(datetime(2026, 1, 1))  # noqa: DTZ001


def test_read_rejects_bad_json_and_newer_format() -> None:
    with pytest.raises(package.PackageError) as err:
        package.read(b"{")
    assert err.value.problems[0].code == "bad_json"
    doc = build().document | {"formatVersion": 2}
    with pytest.raises(package.PackageError) as err:
        package.read(canonical_json.dumps(doc))
    assert err.value.problems[0].code == "format_unsupported"


def test_utc_constant_used() -> None:
    assert package.format_timestamp(datetime(2026, 1, 1, tzinfo=UTC)) == "2026-01-01T00:00:00Z"


def test_arrival_note_trimmed_and_absent_when_empty() -> None:
    plain = build()
    d = draft()
    d["stops"][1]["arrivalNote"] = "  Gửi xe phía đối diện, 30k \n"
    doc = build(d).document
    assert doc["stops"][1]["arrivalNote"] == "Gửi xe phía đối diện, 30k"
    assert "arrivalNote" not in doc["stops"][0]
    for empty in ("", "   ", None):
        d["stops"][1]["arrivalNote"] = empty
        assert build(d).route_json == plain.route_json  # no note → same bytes as before
