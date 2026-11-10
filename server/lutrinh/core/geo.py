"""Distances and line simplification on (lat, lng) points. Pure, no dependencies."""

from __future__ import annotations

import math
from collections.abc import Sequence

EARTH_RADIUS_M = 6_371_008.8

LatLng = tuple[float, float]


def haversine_m(a: LatLng, b: LatLng) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def length_m(points: Sequence[LatLng]) -> float:
    return sum(haversine_m(points[i - 1], points[i]) for i in range(1, len(points)))


def _project(p: LatLng, lat0: float) -> tuple[float, float]:
    """Local equirectangular metres around latitude ``lat0`` (good to a few km)."""
    k = math.pi / 180 * EARTH_RADIUS_M
    return (p[1] * k * math.cos(math.radians(lat0)), p[0] * k)


def _segment_distance(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 and dy == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def simplify(points: Sequence[LatLng], tolerance_m: float = 10.0) -> list[LatLng]:
    """Douglas-Peucker; keeps the first and last point (the app's ~10 m, R36)."""
    if len(points) <= 2:
        return list(points)
    lat0 = sum(p[0] for p in points) / len(points)
    xy = [_project(p, lat0) for p in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        best, index = 0.0, -1
        for i in range(first + 1, last):
            d = _segment_distance(xy[i], xy[first], xy[last])
            if d > best:
                best, index = d, i
        if index >= 0 and best > tolerance_m:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, k in zip(points, keep, strict=True) if k]
