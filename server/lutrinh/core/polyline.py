"""Encoded polyline with precision 6 (``polyline6``), as stored in the app's ``leg_routes``."""

from __future__ import annotations

PRECISION = 6
_FACTOR = 10**PRECISION


def _encode_value(v: int, out: list[str]) -> None:
    v = ~(v << 1) if v < 0 else v << 1
    while v >= 0x20:
        out.append(chr((0x20 | (v & 0x1F)) + 63))
        v >>= 5
    out.append(chr(v + 63))


def encode(points: list[tuple[float, float]]) -> str:
    """``[(lat, lng), …]`` → polyline6 text."""
    out: list[str] = []
    prev_lat = prev_lng = 0
    for lat, lng in points:
        ilat, ilng = round(lat * _FACTOR), round(lng * _FACTOR)
        _encode_value(ilat - prev_lat, out)
        _encode_value(ilng - prev_lng, out)
        prev_lat, prev_lng = ilat, ilng
    return "".join(out)


def decode(text: str) -> list[tuple[float, float]]:
    """polyline6 text → ``[(lat, lng), …]``; raises ``ValueError`` on malformed input."""
    values: list[int] = []
    shift = acc = 0
    for ch in text:
        b = ord(ch) - 63
        if not 0 <= b < 64:
            raise ValueError(f"invalid polyline character {ch!r}")
        acc |= (b & 0x1F) << shift
        shift += 5
        if b < 0x20:
            values.append(~(acc >> 1) if acc & 1 else acc >> 1)
            shift = acc = 0
    if shift or len(values) % 2:
        raise ValueError("truncated polyline")
    points: list[tuple[float, float]] = []
    lat = lng = 0
    for i in range(0, len(values), 2):
        lat += values[i]
        lng += values[i + 1]
        points.append((lat / _FACTOR, lng / _FACTOR))
    return points
