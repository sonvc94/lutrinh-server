"""App backup import (page 04 E): ``LuTrinh-saoluu-….zip`` → list trips → one trip as a draft.

The file format is the app's docs/02 "Backup file" (R26): ``manifest.json`` (format
``lutrinh-backup``, formatVersion 1, ``schemaVersion`` = Room version), ``lutrinh.db`` (SQLite)
and ``photos/<file_name>``. Schemas 7–11 are read; older ones are refused with a reason.

Mapping (page 02 "Ánh xạ", read backwards; page 04 E):

* published steps only (``is_draft = 0``, R20), in R2 order (``arrived_at``, ``created_at``);
* day = local date of ``arrived_at`` − trip ``start_date`` + 1, time = its ``HH:mm``;
* ``transport_mode`` → ``arrival`` (unknown codes → null, R12);
* ``arrival_note`` (schema 11, absent before) → ``arrivalNote``: trimmed, cut to 1000, absent
  when empty/NULL and dropped on the first stop (as ``arrival``);
* photos/videos by ``position`` (files re-processed by the media job, R11);
* ``leg_routes`` rows with status ``ok`` whose profile matches the leg and whose end points
  still match the two published steps (within 1e-4°, as the app) become legs; other road legs
  are listed in ``compute`` for the routing job;
* trip ``cover_photo_id`` → route cover when it is an imported photo.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from lutrinh.core import ids, polyline, rules

FORMAT = "lutrinh-backup"
MIN_SCHEMA = 7
MAX_SCHEMA = 11
MAX_DAYS = 30
MAX_STOPS = 200
MAX_MEDIA_PER_STOP = 30
COORD_MATCH_DEG = 1e-4
_PROFILES = {"motorbike", "car", "bus", "walk"}
_TRANSPORT = {"walk", "motorbike", "car", "bus", "train", "plane", "boat"}
_SOURCE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_FILE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,200}$")


class BackupError(ValueError):
    """``code``: not_zip, not_backup, unsupported_schema, bad_database, trip_not_found,
    day_out_of_range, too_many_stops, too_few_stops."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ImportedMedia:
    media_id: str
    file_name: str
    type: str  # photo | video
    duration_ms: int | None


@dataclass(frozen=True)
class TripDraft:
    draft: dict[str, Any]
    media: list[ImportedMedia]
    compute: list[str]


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def extract(zip_path: Path, work_dir: Path) -> dict[str, Any]:
    """Check the manifest and copy ``lutrinh.db`` to ``work_dir``; returns the manifest."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise BackupError("not_zip", str(exc)) from exc
    with zf:
        names = set(zf.namelist())
        if "manifest.json" not in names or "lutrinh.db" not in names:
            raise BackupError("not_backup", "manifest.json or lutrinh.db missing")
        try:
            manifest = json.loads(zf.read("manifest.json"))
        except ValueError as exc:
            raise BackupError("not_backup", "manifest.json is not JSON") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise BackupError("not_backup", "format is not lutrinh-backup")
        if manifest.get("formatVersion") != 1:
            raise BackupError("not_backup", f"formatVersion {manifest.get('formatVersion')}")
        schema = manifest.get("schemaVersion")
        if not isinstance(schema, int) or not MIN_SCHEMA <= schema <= MAX_SCHEMA:
            raise BackupError(
                "unsupported_schema",
                f"schemaVersion {schema}; this server reads {MIN_SCHEMA}–{MAX_SCHEMA}",
            )
        work_dir.mkdir(parents=True, exist_ok=True)
        with zf.open("lutrinh.db") as src, (work_dir / "lutrinh.db").open("wb") as dst:
            shutil.copyfileobj(src, dst)
    return manifest


def _steps(conn: sqlite3.Connection, trip_id: str) -> tuple[list[sqlite3.Row], int]:
    rows = conn.execute(
        "SELECT * FROM steps WHERE trip_id = ? ORDER BY arrived_at, created_at", (trip_id,)
    ).fetchall()
    published = [r for r in rows if not r["is_draft"]]
    return published, len(rows) - len(published)


def _photos(conn: sqlite3.Connection, step_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM photos WHERE step_id = ? ORDER BY position, created_at, id", (step_id,)
    ).fetchall()


def _leg_rows(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "leg_routes" not in tables:
        return {}
    return {r["to_step_id"]: r for r in conn.execute("SELECT * FROM leg_routes")}


def _arrival(code: Any) -> str | None:
    return code if code in _TRANSPORT else None


def _leg(row: sqlite3.Row | None, prev: sqlite3.Row, step: sqlite3.Row) -> dict[str, Any] | None:
    profile = rules.road_profile(_arrival(step["transport_mode"]))
    if row is None or profile is None or row["status"] != "ok" or row["profile"] != profile:
        return None
    if not _SOURCE.match(str(row["provider"] or "")):
        return None
    for a, b in (
        (row["from_lat"], prev["latitude"]),
        (row["from_lng"], prev["longitude"]),
        (row["to_lat"], step["latitude"]),
        (row["to_lng"], step["longitude"]),
    ):
        if abs(float(a) - float(b)) > COORD_MATCH_DEG:
            return None
    path = row["geometry"] or ""
    try:
        polyline.decode(path)
    except ValueError:
        return None
    used = row["used_profile"] if "used_profile" in row.keys() else None  # noqa: SIM118
    return {
        "to": step["id"],
        "profile": profile,
        "usedProfile": used if used in _PROFILES and used != profile else None,
        "source": row["provider"],
        "status": "ok",
        "distanceM": float(row["distance_m"]),
        "durationS": float(row["duration_s"]),
        "path": path,
    }


def list_trips(db_path: Path) -> list[dict[str, Any]]:
    """Trips for the import preview (page 04 E)."""
    try:
        conn = _connect(db_path)
        with conn:
            out = []
            legs = _leg_rows(conn)
            for trip in conn.execute("SELECT * FROM trips ORDER BY start_date, created_at"):
                steps, drafts = _steps(conn, trip["id"])
                photos = videos = 0
                for s in steps:
                    for p in _photos(conn, s["id"]):
                        if p["media_type"] == "video":
                            videos += 1
                        else:
                            photos += 1
                road = [
                    i
                    for i in range(1, len(steps))
                    if rules.road_profile(_arrival(steps[i]["transport_mode"])) is not None
                ]
                ok = sum(1 for i in road if _leg(legs.get(steps[i]["id"]), steps[i - 1], steps[i]))
                out.append(
                    {
                        "id": trip["id"],
                        "title": trip["title"],
                        "startDate": trip["start_date"],
                        "endDate": trip["end_date"],
                        "stops": len(steps),
                        "draftsSkipped": drafts,
                        "photos": photos,
                        "videos": videos,
                        "legsOk": ok,
                        "legsTotal": len(road),
                    }
                )
        conn.close()
        return out
    except sqlite3.Error as exc:
        raise BackupError("bad_database", str(exc)) from exc


def trip_draft(db_path: Path, trip_id: str) -> TripDraft:
    try:
        conn = _connect(db_path)
        try:
            return _trip_draft(conn, trip_id)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise BackupError("bad_database", str(exc)) from exc


def _trip_draft(conn: sqlite3.Connection, trip_id: str) -> TripDraft:
    trip = conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
    if trip is None:
        raise BackupError("trip_not_found", trip_id)
    steps, _ = _steps(conn, trip_id)
    if len(steps) < 2:
        raise BackupError("too_few_stops", f"{len(steps)} published stops; a route needs 2")
    if len(steps) > MAX_STOPS:
        raise BackupError("too_many_stops", f"{len(steps)} > {MAX_STOPS}")
    start = date.fromisoformat(trip["start_date"])
    legs_by_step = _leg_rows(conn)
    media: list[ImportedMedia] = []
    by_photo_id: dict[str, ImportedMedia] = {}
    stops: list[dict[str, Any]] = []
    legs: list[dict[str, Any]] = []
    compute: list[str] = []
    for i, step in enumerate(steps):
        arrived = datetime.fromisoformat(step["arrived_at"])
        day = (arrived.date() - start).days + 1
        if not 1 <= day <= MAX_DAYS:
            raise BackupError("day_out_of_range", f"step {step['title']!r}: day {day}")
        stop_media = []
        for p in _photos(conn, step["id"])[:MAX_MEDIA_PER_STOP]:
            if not _FILE_NAME.match(p["file_name"] or ""):
                continue
            item = ImportedMedia(
                ids.new_media_id(),
                p["file_name"],
                "video" if p["media_type"] == "video" else "photo",
                p["duration_ms"],
            )
            media.append(item)
            by_photo_id[p["id"]] = item
            stop_media.append(item.media_id)
        stop_id = ids.new_stop_id()
        stop: dict[str, Any] = {
            "id": stop_id,
            "day": day,
            "time": arrived.strftime("%H:%M"),
            "title": (step["title"] or "").strip()[:80].strip() or f"Điểm dừng {i + 1}",
            "note": (step["note"] or "").strip()[:2000].strip(),
            "lat": round(float(step["latitude"]), 6),
            "lng": round(float(step["longitude"]), 6),
            "arrival": _arrival(step["transport_mode"]) if i > 0 else None,
            "media": stop_media,
        }
        note = step["arrival_note"] if "arrival_note" in list(step.keys()) else None
        note = (note or "").strip()[:1000].strip() if isinstance(note, str) else ""
        if note and i > 0:
            stop["arrivalNote"] = note
        stops.append(stop)
        if i == 0 or rules.road_profile(_arrival(step["transport_mode"])) is None:
            continue
        leg = _leg(legs_by_step.get(step["id"]), steps[i - 1], step)
        if leg is None:
            compute.append(stop_id)
        else:
            leg["to"] = stop_id
            legs.append(leg)
    cover_item = by_photo_id.get(trip["cover_photo_id"] or "")
    cover = cover_item.media_id if cover_item and cover_item.type == "photo" else None
    draft = {
        "title": (trip["title"] or "").strip()[:60].strip() or "Lộ trình từ bản sao lưu",
        "description": (trip["description"] or "").strip()[:1000].strip(),
        "days": max(s["day"] for s in stops),
        "cover": cover,
        "readyMade": None,
        "credits": [],
        "stops": stops,
        "legs": legs,
    }
    return TripDraft(draft, media, compute)


def copy_media_file(zip_path: Path, file_name: str, dest: Path) -> bool:
    """Copy ``photos/<file_name>`` out of the backup; False when the file is missing."""
    if not _FILE_NAME.match(file_name):
        return False
    with zipfile.ZipFile(zip_path) as zf:
        try:
            info = zf.getinfo(f"photos/{file_name}")
        except KeyError:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, dest.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    return True
