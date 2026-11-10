"""Stays on a track: the app's stop-suggestion detection (R17, ``StopRules``), ported.

* A stay: from an anchor point, the following points while each is within 150 m of the anchor;
  if the last of them is ≥ 20 min after the anchor, those points are a stay and the scan
  continues after them, else it moves to the next point.
* Two consecutive stays whose centres are ≤ 150 m apart with ≤ 10 min between them are merged.
* A stay is not suggested when a stop lies within 300 m of its centre and that stop's time is
  within its window widened by 60 min on both sides.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from lutrinh.core.geo import haversine_m

RADIUS_M = 150.0
MIN_DWELL = timedelta(minutes=20)
MERGE_MAX_GAP = timedelta(minutes=10)
STEP_MATCH_RADIUS_M = 300.0
STEP_MATCH_TIME = timedelta(minutes=60)


@dataclass(frozen=True)
class TimedPoint:
    lat: float
    lng: float
    at: datetime


@dataclass(frozen=True)
class Stay:
    start: datetime
    end: datetime
    lat: float
    lng: float
    points: int


def _stay(points: Sequence[TimedPoint]) -> Stay:
    return Stay(
        start=points[0].at,
        end=points[-1].at,
        lat=sum(p.lat for p in points) / len(points),
        lng=sum(p.lng for p in points) / len(points),
        points=len(points),
    )


def _merge(a: Stay, b: Stay) -> Stay:
    n = a.points + b.points
    return Stay(
        start=a.start,
        end=b.end,
        lat=(a.lat * a.points + b.lat * b.points) / n,
        lng=(a.lng * a.points + b.lng * b.points) / n,
        points=n,
    )


def detect(points: Sequence[TimedPoint]) -> list[Stay]:
    """Stays of one track, points in recorded order."""
    raw: list[Stay] = []
    i, n = 0, len(points)
    while i < n:
        anchor = (points[i].lat, points[i].lng)
        j = i + 1
        while j < n and haversine_m(anchor, (points[j].lat, points[j].lng)) <= RADIUS_M:
            j += 1
        last = j - 1
        if last > i and points[last].at - points[i].at >= MIN_DWELL:
            raw.append(_stay(points[i : last + 1]))
            i = last + 1
        else:
            i += 1
    merged: list[Stay] = []
    for stay in raw:
        if merged:
            prev = merged[-1]
            close = haversine_m((prev.lat, prev.lng), (stay.lat, stay.lng)) <= RADIUS_M
            if close and stay.start - prev.end <= MERGE_MAX_GAP:
                merged[-1] = _merge(prev, stay)
                continue
        merged.append(stay)
    return merged


def matches_stop(stay: Stay, lat: float, lng: float, at: datetime | None) -> bool:
    """True when a stop at (lat, lng, at) already covers this stay."""
    if at is None:
        return False
    if haversine_m((stay.lat, stay.lng), (lat, lng)) > STEP_MATCH_RADIUS_M:
        return False
    return stay.start - STEP_MATCH_TIME <= at <= stay.end + STEP_MATCH_TIME
