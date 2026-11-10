"""core.rules (publish blockers/warnings), core.gpx (R25 reader → draft), core.dwell (R17)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from lutrinh.core import dwell, gpx, rules

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
T0 = datetime(2026, 11, 20, 1, 0, tzinfo=UTC)  # 08:00 local


def _doc(stops: list[dict[str, Any]], legs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"stops": stops, "legs": legs or [], "size": {"media": 0}}


def _s(sid: str, day: int, time: str | None, arrival: str | None = None) -> dict[str, Any]:
    return {"id": sid, "day": day, "time": time, "arrival": arrival}


def _leg(to: str, km: float, **kw: Any) -> dict[str, Any]:
    leg = {"to": to, "profile": "motorbike", "usedProfile": None, "status": "ok"}
    leg["distanceM"] = km * 1000
    leg.update(kw)
    return leg


def test_blockers_day_and_time_order() -> None:
    doc = _doc([_s("a", 1, "09:00"), _s("b", 1, "08:59"), _s("c", 2, "07:00"), _s("d", 1, None)])
    codes = [(p.code, p.path) for p in rules.check_blockers(doc, 100)]
    assert codes == [("time_order", "/stops/1/time"), ("day_order", "/stops/3/day")]
    ok = _doc([_s("a", 1, "09:00"), _s("b", 1, None), _s("c", 1, "09:00"), _s("d", 2, "06:00")])
    assert rules.check_blockers(ok, 100) == []


def test_blockers_sizes() -> None:
    doc = _doc([_s("a", 1, None)])
    assert rules.check_blockers(doc, rules.ROUTE_JSON_MAX_BYTES) == []
    over = rules.check_blockers(doc, rules.ROUTE_JSON_MAX_BYTES + 1)
    assert [p.code for p in over] == ["route_json_too_large"]
    doc["size"]["media"] = rules.PACKAGE_MAX_BYTES
    assert [p.code for p in rules.check_blockers(doc, 10)] == ["package_too_large"]


def test_warnings() -> None:
    stops = [
        _s("a", 1, None),
        _s("b", 1, None),  # no leg: missing
        _s("c", 1, None, "train"),  # no road leg needed
        _s("d", 1, None, "car"),
        _s("e", 1, None),
        _s("f", 2, None),
    ]
    legs = [
        _leg("d", 10, status="no_route"),
        _leg("e", 151, usedProfile="car"),
        _leg("f", 400),  # long, but across days
    ]
    doc = _doc(stops, legs)
    doc["size"]["media"] = rules.PACKAGE_WARN_BYTES
    got = [p.code for p in rules.check_warnings(doc, 10, long_leg_km=150)]
    assert got == ["package_large", "leg_missing", "leg_not_ok", "leg_car_fallback", "leg_long"]


def test_road_profile() -> None:
    assert rules.road_profile(None) == "motorbike"
    assert rules.road_profile("unknown") == "motorbike"
    assert rules.road_profile("bus") == "bus"
    assert rules.road_profile("plane") is None


def _track(points: list[tuple[float, float, datetime]]) -> str:
    pts = "".join(
        f'<trkpt lat="{la}" lon="{lo}"><time>{t.isoformat()}</time></trkpt>' for la, lo, t in points
    )
    return f"<trk><name>Ngày 1</name><trkseg>{pts}</trkseg></trk>"


def _gpx(inner: str, ns: str = "http://www.topografix.com/GPX/1/1") -> bytes:
    return f'<?xml version="1.0"?><gpx version="1.1" xmlns="{ns}">{inner}</gpx>'.encode()


def test_gpx_waypoints_become_stops_with_local_day_and_time() -> None:
    inner = (
        '<wpt lat="21.0" lon="105.8"><name>Hà Nội</name><desc>Xuất phát</desc>'
        "<time>2026-11-20T01:00:00Z</time></wpt>"
        '<wpt lat="20.25" lon="105.97"><cmt>ghi chú</cmt>'
        "<time>2026-11-20T18:30:00+00:00</time></wpt>"
        '<wpt lat="20.2" lon="105.9"></wpt>'
    )
    result = gpx.to_draft(gpx.parse(_gpx(inner)), "ninh-binh.gpx", TZ)
    d = result.draft
    assert d["title"] == "ninh-binh"
    assert [(s["day"], s["time"], s["title"]) for s in d["stops"]] == [
        (1, "08:00", "Hà Nội"),
        (2, "01:30", "Điểm dừng 01:30"),
        (1, None, "Điểm dừng 3"),
    ]
    assert d["stops"][0]["note"] == "Xuất phát" and d["stops"][1]["note"] == "ghi chú"
    assert d["days"] == 2
    assert result.stops_from == "waypoints" and result.legs_from_track == 0
    assert result.compute == [d["stops"][1]["id"], d["stops"][2]["id"]]


def test_gpx_without_waypoints_uses_start_stays_and_end() -> None:
    pts = [(21.0 + i * 0.01, 105.8, T0 + timedelta(minutes=i)) for i in range(10)]
    stay_at = pts[-1][2]
    pts += [(21.09, 105.8001, stay_at + timedelta(minutes=m)) for m in range(1, 31)]
    end_t = stay_at + timedelta(minutes=40)
    pts += [(21.09 + i * 0.01, 105.8, end_t + timedelta(minutes=i)) for i in range(1, 10)]
    result = gpx.to_draft(
        gpx.parse(_gpx(_track(pts), ns="http://www.topografix.com/GPX/1/0")), "", TZ
    )
    stops = result.draft["stops"]
    assert result.stops_from == "track"
    assert len(stops) == 3
    assert stops[1]["time"] == "08:09"
    assert result.draft["title"] == "Ngày 1"
    assert result.legs_from_track == 2
    assert all(leg["source"] == "gpx" and leg["durationS"] > 0 for leg in result.draft["legs"])


def test_gpx_refuses_dtds_and_non_gpx() -> None:
    evil = b'<?xml version="1.0"?><!DOCTYPE gpx [<!ENTITY x "y">]><gpx>&x;</gpx>'
    with pytest.raises(gpx.GpxError) as err:
        gpx.parse(evil)
    assert err.value.code == "not_xml"
    for data, code in (
        (b"<kml/>", "not_gpx"),
        (b"not xml", "not_xml"),
        (_gpx(""), "empty"),
        (_gpx('<wpt lat="91" lon="0"/>'), "bad_point"),
    ):
        with pytest.raises(gpx.GpxError) as err:
            gpx.parse(data)
        assert err.value.code == code


def test_dwell_detects_and_merges_stays() -> None:
    def p(lat: float, minutes: int) -> dwell.TimedPoint:
        return dwell.TimedPoint(lat, 105.0, T0 + timedelta(minutes=minutes))

    points = [p(21.0, 0), p(21.0, 10), p(21.0, 25), p(21.05, 30)]  # 25 min within 150 m
    points += [p(21.05, 31)]  # 1 min: too short
    stays = dwell.detect(points)
    assert len(stays) == 1 and stays[0].points == 3
    # 21.0014 is 155 m from the first anchor (a new stay) but ~117 m from the first centre.
    two = [p(21.0, 0), p(21.0007, 21), p(21.0014, 23), p(21.0014, 45)]
    merged = dwell.detect(two)
    assert len(merged) == 1 and merged[0].points == 4
    assert dwell.matches_stop(stays[0], 21.001, 105.0, T0 + timedelta(minutes=80))
    assert not dwell.matches_stop(stays[0], 21.001, 105.0, T0 + timedelta(minutes=90))
    assert not dwell.matches_stop(stays[0], 21.01, 105.0, T0)
    assert not dwell.matches_stop(stays[0], 21.0, 105.0, None)
