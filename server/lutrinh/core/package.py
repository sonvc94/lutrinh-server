"""``lutrinh-route`` package, formatVersion 1: build ``route.json`` from a draft and check it.

Pure functions, no database. The publish service (``lutrinh.services.publishing``) feeds a draft
and the media rows it references; the result is the immutable canonical bytes and their sha256.

Draft document (``drafts.body``; the admin API writes it whole)::

    {"title", "description", "days", "cover": media id | null, "readyMade": key | null,
     "credits": [str],
     "stops": [{"id", "day", "time", "title", "note", "lat", "lng", "arrival", "media": [ids]}],
     "legs":  [{"to", "profile", "usedProfile", "source", "status", "distanceM", "durationS",
                "path"}]}

What the build adds: route id/version/publishedAt, media entries (sha256, size, dimensions,
credit) from the media rows, ``region.bounds`` (box around the stops and the ``ok`` leg paths),
``size``. Text is trimmed, coordinates are rounded to 6 decimals, legs are put in stop order.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from lutrinh.config import get_settings
from lutrinh.core import canonical_json, polyline

FORMAT = "lutrinh-route"
FORMAT_VERSION = 1
COORD_DECIMALS = 6


@dataclass(frozen=True)
class MediaInfo:
    """A processed media file as the package needs it (from the ``media`` table)."""

    id: str
    sha256: str
    type: str  # photo | video
    bytes: int
    w: int
    h: int
    duration_ms: int | None
    credit: str | None


@dataclass(frozen=True)
class Problem:
    """Why a package is invalid. ``code`` is ``schema`` or an integrity code (spec/README.md)."""

    code: str
    path: str
    message: str


class PackageError(ValueError):
    def __init__(self, problems: list[Problem]) -> None:
        super().__init__("; ".join(f"{p.code} at {p.path}: {p.message}" for p in problems))
        self.problems = problems


@dataclass(frozen=True)
class BuiltPackage:
    document: dict[str, Any]
    route_json: bytes
    sha256: str
    media: list[MediaInfo]

    @property
    def media_bytes(self) -> int:
        return int(self.document["size"]["media"])

    @property
    def media_files(self) -> int:
        return int(self.document["size"]["files"])


# --- schema + integrity -------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _validator(spec_dir: Path) -> Draft202012Validator:
    schema = json.loads((spec_dir / "route.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def schema_validator() -> Draft202012Validator:
    return _validator(get_settings().spec_dir)


def _ptr(parts: Iterable[Any]) -> str:
    return "/" + "/".join(str(p) for p in parts)


def check(document: Any) -> list[Problem]:
    """All problems of a parsed ``route.json``; empty list = valid package."""
    problems = [
        Problem("schema", _ptr(err.absolute_path), err.message)
        for err in sorted(schema_validator().iter_errors(document), key=lambda e: list(e.path))
    ]
    if problems:
        return problems  # integrity rules assume the shape is right
    return check_integrity(document)


def check_integrity(doc: Mapping[str, Any]) -> list[Problem]:
    """Cross-reference rules that JSON Schema cannot express (listed in spec/README.md)."""
    out: list[Problem] = []
    route, stops, legs, media = doc["route"], doc["stops"], doc["legs"], doc["media"]

    media_by_id: dict[str, Mapping[str, Any]] = {}
    for i, m in enumerate(media):
        if m["id"] in media_by_id:
            out.append(Problem("duplicate_media_id", f"/media/{i}/id", m["id"]))
        media_by_id[m["id"]] = m

    stop_index: dict[str, int] = {}
    referenced: set[str] = set()
    for i, s in enumerate(stops):
        if s["id"] in stop_index:
            out.append(Problem("duplicate_stop_id", f"/stops/{i}/id", s["id"]))
        stop_index.setdefault(s["id"], i)
        if s["day"] > route["days"]:
            out.append(Problem("day_after_end", f"/stops/{i}/day", f"{s['day']} > {route['days']}"))
        for j, mid in enumerate(s["media"]):
            referenced.add(mid)
            if mid not in media_by_id:
                out.append(Problem("unknown_media", f"/stops/{i}/media/{j}", mid))

    cover = route["cover"]
    if cover is not None:
        referenced.add(cover)
        if cover not in media_by_id:
            out.append(Problem("unknown_media", "/route/cover", cover))
        elif media_by_id[cover]["type"] != "photo":
            out.append(Problem("cover_not_photo", "/route/cover", cover))

    for i, m in enumerate(media):
        if m["id"] not in referenced:
            out.append(Problem("orphan_media", f"/media/{i}", m["id"]))

    seen_to: set[str] = set()
    last_pos = 0
    for i, leg in enumerate(legs):
        to = leg["to"]
        pos = stop_index.get(to)
        if pos is None:
            out.append(Problem("unknown_stop", f"/legs/{i}/to", to))
            continue
        if pos == 0:
            out.append(Problem("leg_to_first_stop", f"/legs/{i}/to", to))
        if to in seen_to:
            out.append(Problem("duplicate_leg", f"/legs/{i}/to", to))
        elif pos < last_pos:
            out.append(Problem("leg_order", f"/legs/{i}/to", "legs must follow stop order"))
        seen_to.add(to)
        last_pos = max(last_pos, pos)
        if leg["path"]:
            try:
                polyline.decode(leg["path"])
            except ValueError as exc:
                out.append(Problem("bad_path", f"/legs/{i}/path", str(exc)))

    total = sum(int(m["bytes"]) for m in media)
    if doc["size"]["media"] != total:
        out.append(Problem("size_mismatch", "/size/media", f"expected {total}"))
    if doc["size"]["files"] != len(media):
        out.append(Problem("size_mismatch", "/size/files", f"expected {len(media)}"))
    return out


# --- build --------------------------------------------------------------------------------------


def _text(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _coord(value: Any) -> Any:
    return round(float(value), COORD_DECIMALS) if isinstance(value, (int, float)) else value


def _bounds(stops: list[dict[str, Any]], legs: list[dict[str, Any]]) -> dict[str, float]:
    points = [(s["lat"], s["lng"]) for s in stops]
    for leg in legs:
        if leg.get("status") == "ok" and leg.get("path"):
            points.extend(polyline.decode(leg["path"]))
    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    return {
        "south": round(min(lats), COORD_DECIMALS),
        "west": round(min(lngs), COORD_DECIMALS),
        "north": round(max(lats), COORD_DECIMALS),
        "east": round(max(lngs), COORD_DECIMALS),
    }


def format_timestamp(when: datetime) -> str:
    if when.tzinfo is None:
        raise ValueError("naive datetime")
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def referenced_media_ids(draft: Mapping[str, Any]) -> list[str]:
    """Media ids in package order: stop by stop, then the cover if no stop uses it."""
    ids: list[str] = []
    for stop in draft.get("stops") or []:
        for mid in stop.get("media") or []:
            if mid not in ids:
                ids.append(mid)
    cover = draft.get("cover")
    if cover is not None and cover not in ids:
        ids.append(cover)
    return ids


def build(
    draft: Mapping[str, Any],
    *,
    route_id: str,
    version: int,
    published_at: datetime,
    media: Mapping[str, MediaInfo],
) -> BuiltPackage:
    """Draft → canonical ``route.json``. Raises ``PackageError`` listing every problem."""
    stops = [
        {
            "id": s.get("id"),
            "day": s.get("day"),
            "time": s.get("time"),
            "title": _text(s.get("title")),
            "note": _text(s.get("note", "")),
            "lat": _coord(s.get("lat")),
            "lng": _coord(s.get("lng")),
            "arrival": s.get("arrival"),
            "media": list(s.get("media") or []),
        }
        for s in draft.get("stops") or []
    ]
    order = {s["id"]: i for i, s in enumerate(stops)}
    legs = sorted(
        (
            {
                k: leg.get(k)
                for k in (
                    "to",
                    "profile",
                    "usedProfile",
                    "source",
                    "status",
                    "distanceM",
                    "durationS",
                    "path",
                )
            }
            for leg in draft.get("legs") or []
        ),
        key=lambda leg: order.get(leg["to"], len(order)),
    )

    entries: list[MediaInfo] = []
    missing: list[Problem] = []
    for mid in referenced_media_ids(draft):
        info = media.get(mid)
        if info is None:
            missing.append(Problem("unknown_media", "/media", mid))
        else:
            entries.append(info)
    if missing:
        raise PackageError(missing)

    media_json = [
        {
            "id": m.id,
            "sha256": m.sha256,
            "type": m.type,
            "bytes": m.bytes,
            "w": m.w,
            "h": m.h,
            "durationMs": m.duration_ms,
            "credit": _text(m.credit),
        }
        for m in entries
    ]
    try:
        bounds = _bounds(stops, legs)
    except (TypeError, ValueError):
        # No stops, a bad coordinate or a bad path: check() below reports the real problem.
        bounds = {"south": 0.0, "west": 0.0, "north": 0.0, "east": 0.0}

    document: dict[str, Any] = {
        "format": FORMAT,
        "formatVersion": FORMAT_VERSION,
        "route": {
            "id": route_id,
            "version": version,
            "publishedAt": format_timestamp(published_at),
            "title": _text(draft.get("title")),
            "description": _text(draft.get("description", "")),
            "days": draft.get("days"),
            "cover": draft.get("cover"),
            "region": {"bounds": bounds, "readyMade": draft.get("readyMade")},
            "credits": [_text(c) for c in draft.get("credits") or []],
        },
        "stops": stops,
        "legs": legs,
        "media": media_json,
        "size": {"media": sum(m.bytes for m in entries), "files": len(entries)},
    }
    problems = check(document)
    if problems:
        raise PackageError(problems)
    data = canonical_json.dumps(document)
    return BuiltPackage(document, data, sha256_hex(data), entries)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(data: bytes) -> dict[str, Any]:
    """Parse and check a ``route.json``; raises ``PackageError``. Formats newer than 1 are
    reported as ``format_unsupported`` (the app shows "Hãy cập nhật ứng dụng")."""
    try:
        doc = canonical_json.loads(data)
    except ValueError as exc:
        raise PackageError([Problem("bad_json", "/", str(exc))]) from exc
    if (
        isinstance(doc, dict)
        and isinstance(doc.get("formatVersion"), int)
        and (doc["formatVersion"] > FORMAT_VERSION)
    ):
        raise PackageError([Problem("format_unsupported", "/formatVersion", "newer format")])
    problems = check(doc)
    if problems:
        raise PackageError(problems)
    assert isinstance(doc, dict)
    return doc
