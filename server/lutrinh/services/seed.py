"""``lutrinh seed-sample``: the spec sample as a published route, for trying the server locally.

The sample's media hashes are of placeholder strings (``scripts/make_spec_sample.py``), so no
real files match them. Instead (Mate decision server-public-api 1B) the sample's text, stops and
legs become a new route's draft, every media item gets a generated placeholder file (ffmpeg test
pattern: JPEG 1280 px wide + its 640 px preview, H.264 MP4 of 5 s), and the draft is published
the normal way (``publishing.publish``), which issues the code. The published ``route.json``
therefore has its own hashes and sizes; ``spec/`` is not touched. Each run adds a new route.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from lutrinh.config import Settings
from lutrinh.core import ids, package
from lutrinh.db.models import Media
from lutrinh.services import audit, publishing, routes
from lutrinh.services import media as media_service

PHOTO_WIDTH = 1280
VIDEO_SIZE = (1280, 720)
VIDEO_SECONDS = 5


class SeedError(RuntimeError):
    pass


@dataclass(frozen=True)
class Generated:
    sha256: str
    bytes: int
    width: int
    height: int
    duration_ms: int | None


def _run(cmd: list[str]) -> None:
    done = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise SeedError(f"ffmpeg failed: {' '.join(cmd)}\n{done.stderr.strip()}")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _store(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():  # same sha256 = same bytes; files of a version are never rewritten
        shutil.copyfile(src, dest)


def _make(ffmpeg: str, settings: Settings, item: dict[str, Any], n: int, work: Path) -> Generated:
    hue = (n * 29) % 360  # a different colour per file, so every file has its own sha256
    if item["type"] == "photo":
        w = PHOTO_WIDTH
        h = round(w * item["h"] / item["w"] / 2) * 2
        out, thumb = work / f"{n}.jpg", work / f"{n}.w640.jpg"
        source = f"testsrc2=s={w}x{h}:r=1"
        _run(
            [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", source]
            + ["-vf", f"hue=h={hue}", "-frames:v", "1", "-q:v", "4", str(out)]
        )
        _run(
            [ffmpeg, "-v", "error", "-y", "-i", str(out)]
            + ["-vf", "scale=640:-2", "-q:v", "5", str(thumb)]
        )
        sha = _sha256(out)
        _store(out, media_service.file_path(settings, sha, "photo"))
        _store(thumb, media_service.thumb_path(settings, sha))
        return Generated(sha, out.stat().st_size, w, h, None)
    w, h = VIDEO_SIZE
    out = work / f"{n}.mp4"
    source = f"testsrc2=s={w}x{h}:r=25:d={VIDEO_SECONDS}"
    _run(
        [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", source, "-vf", f"hue=h={hue}"]
        + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(out)]
    )
    sha = _sha256(out)
    _store(out, media_service.file_path(settings, sha, "video"))
    return Generated(sha, out.stat().st_size, w, h, VIDEO_SECONDS * 1000)


def seed_sample(
    session: Session,
    settings: Settings,
    sample_dir: Path,
    *,
    ffmpeg: str = "ffmpeg",
    now: datetime | None = None,
) -> publishing.Published:
    """Create, fill and publish a route from ``sample_dir/route.json``. Caller commits."""
    doc = package.read((sample_dir / "route.json").read_bytes())
    ffmpeg_bin = shutil.which(ffmpeg)
    if ffmpeg_bin is None:
        raise SeedError("ffmpeg not found on PATH (needed for the sample's placeholder media)")

    meta = doc["route"]
    new_ids = {m["id"]: ids.new_media_id() for m in doc["media"]}
    body = {
        "title": meta["title"],
        "description": meta["description"],
        "days": meta["days"],
        "cover": new_ids.get(meta["cover"]) if meta.get("cover") else None,
        "readyMade": meta["region"]["readyMade"],
        "credits": list(meta["credits"]),
        "stops": [s | {"media": [new_ids[m] for m in s["media"]]} for s in doc["stops"]],
        "legs": [dict(leg) for leg in doc["legs"]],
    }
    route = routes.create(session, meta["title"], body)

    with tempfile.TemporaryDirectory(dir=_scratch(settings)) as tmp:
        for n, item in enumerate(doc["media"]):
            made = _make(ffmpeg_bin, settings, item, n, Path(tmp))
            ext = media_service.FILE_EXT[item["type"]]
            session.add(
                Media(
                    id=new_ids[item["id"]],
                    route=route,
                    type=item["type"],
                    status="ready",
                    sha256=made.sha256,
                    bytes=made.bytes,
                    width=made.width,
                    height=made.height,
                    duration_ms=made.duration_ms,
                    credit=item["credit"],
                    original_name=f"sample-{item['id']}{ext}",
                )
            )
    session.flush()
    published = publishing.publish(
        session, route.id, long_leg_km=settings.long_leg_warn_km, note="seed-sample", now=now
    )
    audit.record(
        session,
        "route.seed_sample",
        route_id=route.id,
        target=published.code.code,
        after={"version": published.version.version, "sample": sample_dir.name},
        actor="cli",
    )
    return published


def _scratch(settings: Settings) -> Path:
    path = settings.data_dir / "tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path
