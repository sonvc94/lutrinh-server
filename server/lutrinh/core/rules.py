"""Publish rules beyond the package schema and integrity checks (``core.package``).

Blockers (publishing is refused; page 02 "Kiểm tra giống app", page 03 "Kích thước"):

* ``day_order``: a stop's ``day`` is lower than the previous stop's (the app orders stops by
  arrival time, R2, so the package order must be chronological);
* ``time_order``: within one day, a stop's ``time`` is earlier than an earlier stop's time
  (stops without a time are skipped; equal times are allowed, R2 then keeps file order);
* ``route_json_too_large``: ``route.json`` > 2 MB;
* ``package_too_large``: ``route.json`` + media > 300 MB.

Warnings (shown, never blocking; page 04 D): ``package_large`` (> 150 MB), ``leg_missing`` (a
road leg without a line), ``leg_not_ok`` (router answered ``no_route`` / ``too_far``),
``leg_car_fallback`` ("tuyến ô tô"), ``leg_long`` (a leg within one day longer than the
configured threshold, default 150 km).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lutrinh.core.package import Problem

ROUTE_JSON_MAX_BYTES = 2 * 1024 * 1024
PACKAGE_MAX_BYTES = 300 * 1024 * 1024
PACKAGE_WARN_BYTES = 150 * 1024 * 1024

# Stop ``arrival`` (app TransportMode) → road profile of the leg into it. Train, plane and boat
# legs have no road line; "Chưa chọn" (null) routes as motorbike (R36).
_ROAD_PROFILE: dict[str | None, str] = {
    None: "motorbike",
    "motorbike": "motorbike",
    "car": "car",
    "bus": "bus",
    "walk": "walk",
}


def road_profile(arrival: str | None) -> str | None:
    """Road profile for a leg arriving with ``arrival``; None = no road leg (train/plane/boat)."""
    if arrival not in _ROAD_PROFILE and arrival not in ("train", "plane", "boat"):
        arrival = None  # unknown codes read as "not set" (R12)
    return _ROAD_PROFILE.get(arrival)


def check_blockers(document: Mapping[str, Any], route_json_bytes: int) -> list[Problem]:
    """Rules on a schema-valid ``route.json`` document that refuse publishing."""
    out: list[Problem] = []
    prev_day = 0
    last_time: str | None = None
    for i, stop in enumerate(document["stops"]):
        day = stop["day"]
        if day < prev_day:
            out.append(Problem("day_order", f"/stops/{i}/day", f"day {day} after day {prev_day}"))
        if day != prev_day:
            last_time = None
        prev_day = max(prev_day, day)
        time = stop["time"]
        if time is not None:
            if last_time is not None and time < last_time:
                out.append(Problem("time_order", f"/stops/{i}/time", f"{time} before {last_time}"))
            last_time = max(time, last_time or time)
    if route_json_bytes > ROUTE_JSON_MAX_BYTES:
        out.append(
            Problem("route_json_too_large", "/", f"{route_json_bytes} > {ROUTE_JSON_MAX_BYTES}")
        )
    total = route_json_bytes + int(document["size"]["media"])
    if total > PACKAGE_MAX_BYTES:
        out.append(Problem("package_too_large", "/size/media", f"{total} > {PACKAGE_MAX_BYTES}"))
    return out


def check_warnings(
    document: Mapping[str, Any], route_json_bytes: int, *, long_leg_km: float
) -> list[Problem]:
    """Rules on a schema-valid ``route.json`` document that only warn."""
    out: list[Problem] = []
    total = route_json_bytes + int(document["size"]["media"])
    if total > PACKAGE_WARN_BYTES:
        out.append(Problem("package_large", "/size/media", f"{total} > {PACKAGE_WARN_BYTES}"))
    stops = document["stops"]
    legs = {leg["to"]: (i, leg) for i, leg in enumerate(document["legs"])}
    for i in range(1, len(stops)):
        stop = stops[i]
        found = legs.get(stop["id"])
        if found is None:
            if road_profile(stop["arrival"]) is not None:
                out.append(Problem("leg_missing", f"/stops/{i}", stop["id"]))
            continue
        j, leg = found
        if leg["status"] != "ok":
            out.append(Problem("leg_not_ok", f"/legs/{j}/status", leg["status"]))
            continue
        if leg["usedProfile"] == "car" and leg["profile"] != "car":
            out.append(Problem("leg_car_fallback", f"/legs/{j}/usedProfile", stop["id"]))
        if stops[i - 1]["day"] == stop["day"] and leg["distanceM"] > long_leg_km * 1000:
            km = round(leg["distanceM"] / 1000)
            out.append(Problem("leg_long", f"/legs/{j}/distanceM", f"{km} km in one day"))
    return out
