"""GPX import (page 04 E, the app's R25 reader) → a route draft.

Reading follows R25: GPX 1.0 and 1.1, elements matched by local name in any namespace; ``wpt``,
``trk``/``trkseg``/``trkpt``, ``rte``/``rtept``; ``name``, ``desc`` (else ``cmt``), ``time``;
everything else ignored. A time without an offset is UTC. External DTDs and entities are never
loaded (``defusedxml``, DTDs refused).

Mapping to a draft (page 04 E):

* route title = metadata ``name``, else the first track/route name, else the file name without
  extension, else "Lộ trình từ GPX" (≤ 60); description = metadata ``desc`` (≤ 1000);
* stops = ``wpt`` in file order (title = ``name`` ≤ 80, else "Điểm dừng HH:mm", else
  "Điểm dừng N"; note = ``desc``/``cmt`` ≤ 2000). Without any ``wpt``: the first track point,
  the stays found on the tracks (R17, ``core.dwell``) and the last track point;
* day/time: times are turned into the local zone (setting ``local_tz``); day 1 = the local date
  of the earliest time in the file; a stop without a time gets day 1 and no time;
* legs: the track (all ``trk`` and ``rte`` points in file order) is cut at the point nearest
  each stop, searching forward; a stop farther than 500 m from the track (the R36 off-road
  guard) gets no cut. Each cut piece becomes a leg (source ``gpx``, simplified to ~10 m).
  Legs that cannot be cut are listed in ``compute`` for the routing job.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any
from zoneinfo import ZoneInfo

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

from lutrinh.core import dwell, geo, ids, polyline, rules

TITLE_MAX = 60
DESCRIPTION_MAX = 1000
STOP_TITLE_MAX = 80
NOTE_MAX = 2000
MAX_STOPS = 200
MAX_DAYS = 30
CUT_MAX_DISTANCE_M = 500.0
DEFAULT_TITLE = "Lộ trình từ GPX"


class GpxError(ValueError):
    """``code``: not_xml, not_gpx, bad_point, empty, too_many_stops, too_many_days."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Point:
    lat: float
    lng: float
    at: datetime | None
    name: str = ""
    note: str = ""


@dataclass
class Gpx:
    name: str = ""
    description: str = ""
    waypoints: list[Point] = field(default_factory=list)
    # One entry per trk / rte in file order; each a list of non-empty segments.
    tracks: list[tuple[str, list[list[Point]]]] = field(default_factory=list)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(el: ET.Element, name: str) -> str:
    for child in el:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _time(text: str) -> datetime | None:
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text.replace("z", "Z"))
    except ValueError:
        return None
    return when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)


def _point(el: ET.Element) -> Point:
    try:
        lat = float(el.attrib["lat"])
        lng = float(el.attrib["lon"])
    except (KeyError, ValueError) as exc:
        raise GpxError("bad_point", f"<{_local(el.tag)}> without a valid lat/lon") from exc
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise GpxError("bad_point", f"<{_local(el.tag)}> lat/lon out of range")
    note = _child_text(el, "desc") or _child_text(el, "cmt")
    return Point(lat, lng, _time(_child_text(el, "time")), _child_text(el, "name"), note)


def _fill_times(points: list[Point]) -> list[Point]:
    """R25: a point without a time takes the previous one's (the first ones: the first time)."""
    first = next((p.at for p in points if p.at is not None), None)
    out, last = [], first
    for p in points:
        if p.at is None:
            out.append(Point(p.lat, p.lng, last, p.name, p.note))
        else:
            last = p.at
            out.append(p)
    return out


def parse(data: bytes) -> Gpx:
    try:
        root = fromstring(data, forbid_dtd=True)
    except ET.ParseError as exc:
        raise GpxError("not_xml", f"line {exc.position[0]}") from exc
    except DefusedXmlException as exc:
        raise GpxError("not_xml", "DTDs and entities are not allowed") from exc
    if _local(root.tag) != "gpx":
        raise GpxError("not_gpx", f"root is <{_local(root.tag)}>")
    gpx = Gpx()
    for el in root:
        name = _local(el.tag)
        if name == "metadata":
            gpx.name = _child_text(el, "name")
            gpx.description = _child_text(el, "desc")
        elif name == "name" and not gpx.name:  # GPX 1.0 keeps these on the root
            gpx.name = (el.text or "").strip()
        elif name == "desc" and not gpx.description:
            gpx.description = (el.text or "").strip()
        elif name == "wpt":
            gpx.waypoints.append(_point(el))
        elif name == "trk":
            segments = []
            for seg in el:
                if _local(seg.tag) == "trkseg":
                    pts = [_point(p) for p in seg if _local(p.tag) == "trkpt"]
                    if pts:
                        segments.append(pts)
            if segments:
                gpx.tracks.append((_child_text(el, "name"), segments))
        elif name == "rte":
            pts = [_point(p) for p in el if _local(p.tag) == "rtept"]
            if pts:
                gpx.tracks.append((_child_text(el, "name"), [pts]))
    if not gpx.waypoints and not gpx.tracks:
        raise GpxError("empty", "no wpt, trkpt or rtept")
    filled = []
    for track_name, segments in gpx.tracks:
        flat = _fill_times([p for seg in segments for p in seg])
        it = iter(flat)
        filled.append((track_name, [[next(it) for _ in seg] for seg in segments]))
    gpx.tracks = filled
    return gpx


def _clip(text: str, limit: int) -> str:
    return text.strip()[:limit].strip()


def _title_from_file(filename: str) -> str:
    stem = PurePath(filename).stem if filename else ""
    return re.sub(r"\s+", " ", stem).strip()


@dataclass(frozen=True)
class GpxDraft:
    draft: dict[str, Any]
    # Stop ids whose leg must be computed by the routing job.
    compute: list[str]
    stops_from: str  # waypoints | track
    legs_from_track: int


def _stop_candidates(gpx: Gpx) -> tuple[list[Point], str]:
    if gpx.waypoints:
        return gpx.waypoints, "waypoints"
    track_points = [p for _, segs in gpx.tracks for seg in segs for p in seg]
    start, end = track_points[0], track_points[-1]
    out = [start]
    for _, segs in gpx.tracks:
        timed = [dwell.TimedPoint(p.lat, p.lng, p.at) for seg in segs for p in seg if p.at]
        for stay in dwell.detect(timed):
            if any(dwell.matches_stop(stay, s.lat, s.lng, s.at) for s in (start, end)):
                continue
            out.append(Point(stay.lat, stay.lng, stay.start))
    if len(track_points) > 1:
        out.append(end)
    return out, "track"


def to_draft(gpx: Gpx, filename: str, tz: ZoneInfo) -> GpxDraft:
    candidates, stops_from = _stop_candidates(gpx)
    if len(candidates) > MAX_STOPS:
        raise GpxError("too_many_stops", f"{len(candidates)} > {MAX_STOPS}")
    times = [p.at for p in candidates if p.at] + [
        p.at for _, segs in gpx.tracks for seg in segs for p in seg if p.at
    ]
    first_date = min(times).astimezone(tz).date() if times else None

    stops: list[dict[str, Any]] = []
    for n, p in enumerate(candidates, start=1):
        day, hhmm = 1, None
        if p.at is not None and first_date is not None:
            local = p.at.astimezone(tz)
            day = (local.date() - first_date).days + 1
            hhmm = local.strftime("%H:%M")
        if day > MAX_DAYS:
            raise GpxError("too_many_days", f"day {day} > {MAX_DAYS}")
        title = _clip(p.name, STOP_TITLE_MAX) or (f"Điểm dừng {hhmm}" if hhmm else f"Điểm dừng {n}")
        stops.append(
            {
                "id": ids.new_stop_id(),
                "day": day,
                "time": hhmm,
                "title": title,
                "note": _clip(p.note, NOTE_MAX),
                "lat": round(p.lat, 6),
                "lng": round(p.lng, 6),
                "arrival": None,
                "media": [],
            }
        )

    track = [p for _, segs in gpx.tracks for seg in segs for p in seg]
    legs = _cut_legs(stops, track)
    cut = {leg["to"] for leg in legs}
    compute = [s["id"] for s in stops[1:] if s["id"] not in cut]
    title = (
        _clip(gpx.name, TITLE_MAX)
        or next((_clip(n, TITLE_MAX) for n, _ in gpx.tracks if n.strip()), "")
        or _clip(_title_from_file(filename), TITLE_MAX)
        or DEFAULT_TITLE
    )
    draft = {
        "title": title,
        "description": _clip(gpx.description, DESCRIPTION_MAX),
        "days": max((s["day"] for s in stops), default=1),
        "cover": None,
        "readyMade": None,
        "credits": [],
        "stops": stops,
        "legs": legs,
    }
    return GpxDraft(draft, compute, stops_from, len(legs))


def _cut_legs(stops: list[dict[str, Any]], track: list[Point]) -> list[dict[str, Any]]:
    if len(track) < 2:
        return []
    cuts: list[int | None] = []
    start = 0
    for s in stops:
        best_i, best_d = -1, float("inf")
        for i in range(start, len(track)):
            d = geo.haversine_m((s["lat"], s["lng"]), (track[i].lat, track[i].lng))
            if d < best_d:
                best_i, best_d = i, d
        if best_i < 0 or best_d > CUT_MAX_DISTANCE_M:
            cuts.append(None)
        else:
            cuts.append(best_i)
            start = best_i
    legs = []
    for k in range(1, len(stops)):
        a, b = cuts[k - 1], cuts[k]
        profile = rules.road_profile(stops[k]["arrival"])
        if a is None or b is None or b <= a or profile is None:
            continue
        piece = track[a : b + 1]
        line = geo.simplify([(p.lat, p.lng) for p in piece])
        t0, t1 = piece[0].at, piece[-1].at
        duration = (t1 - t0).total_seconds() if t0 and t1 and t1 > t0 else 0
        legs.append(
            {
                "to": stops[k]["id"],
                "profile": profile,
                "usedProfile": None,
                "source": "gpx",
                "status": "ok",
                "distanceM": round(geo.length_m([(p.lat, p.lng) for p in piece])),
                "durationS": round(duration),
                "path": polyline.encode(line),
            }
        )
    return legs
