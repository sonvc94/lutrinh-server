"""``media.image`` and ``media.video`` (page 06 §3, page 03 "Kích thước", R11, R29).

Photo: decoded again with Pillow, turned upright, ≤ ``image_max_px`` on the long side, saved as
JPEG ~``image_quality`` without EXIF, GPS, XMP or comments (only the ICC colour profile is
kept), plus a ``thumb_width`` px wide preview ``<sha>.w640.jpg``. Video: ffprobe first; longer
than ``video_max_seconds`` is refused before any encoding; else ffmpeg re-encodes it to H.264
(short side ≤ ``video_short_side``, ≤ ``video_max_fps`` fps) + AAC with ``+faststart`` and no
metadata (phone videos carry their location there). No poster image is made.

The stored file is named by the sha256 of the processed bytes (``media/ab/cd/<sha>.jpg|.mp4``);
an existing file with that name is kept, never rewritten. Then the media row is ``ready`` and
the upload (row and ``uploads/<id>/``) is deleted.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from lutrinh.config import Settings
from lutrinh.db.models import Media, Upload
from lutrinh.jobs import Context, Payload, PermanentError, Result
from lutrinh.services import media as media_service
from lutrinh.services import uploads

THUMB_QUALITY = 80


@dataclass(frozen=True)
class Processed:
    path: Path
    width: int
    height: int
    duration_ms: int | None = None
    thumb: Path | None = None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _store(tmp: Path, dest: Path) -> None:
    """Move ``tmp`` to ``dest`` unless that file exists (same sha256 = same bytes)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        tmp.unlink()
    else:
        os.replace(tmp, dest)


def _rgb(img: Image.Image) -> Image.Image:
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return img.convert("RGB")


def process_image(settings: Settings, src: Path, work: Path) -> Processed:
    try:
        with Image.open(src) as opened:
            icc = opened.info.get("icc_profile")
            upright = ImageOps.exif_transpose(opened)
            img = _rgb(upright)
            img.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as exc:
        raise PermanentError(f"not_an_image: {exc}") from exc
    img.thumbnail((settings.image_max_px, settings.image_max_px), Image.Resampling.LANCZOS)
    img.info = {}  # nothing of the original's metadata (EXIF, GPS, XMP, comments) is written
    extra: dict[str, Any] = {"icc_profile": icc} if icc else {}
    out = work / "photo.jpg"
    img.save(out, "JPEG", quality=settings.image_quality, optimize=True, progressive=True, **extra)
    small = img
    if img.width > settings.thumb_width:
        h = max(1, round(img.height * settings.thumb_width / img.width))
        small = img.resize((settings.thumb_width, h), Image.Resampling.LANCZOS)
    thumb = work / "photo.w640.jpg"
    small.save(thumb, "JPEG", quality=THUMB_QUALITY, optimize=True, **extra)
    return Processed(out, img.width, img.height, thumb=thumb)


def probe(settings: Settings, path: Path) -> dict[str, Any]:
    cmd = [settings.ffprobe, "-v", "error", "-print_format", "json"]
    cmd += ["-show_format", "-show_streams", str(path)]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    if done.returncode != 0:
        raise PermanentError(f"not_a_video: {done.stderr.strip()[:300]}")
    info: dict[str, Any] = json.loads(done.stdout)
    return info


def video_stream(info: dict[str, Any]) -> dict[str, Any] | None:
    for stream in info.get("streams") or []:
        if stream.get("codec_type") == "video" and not (stream.get("disposition") or {}).get(
            "attached_pic"
        ):
            s: dict[str, Any] = stream
            return s
    return None


def duration_s(info: dict[str, Any]) -> float | None:
    values = [(info.get("format") or {}).get("duration")]
    values += [s.get("duration") for s in info.get("streams") or []]
    found = [float(v) for v in values if v not in (None, "N/A")]
    return max(found) if found else None


def _scale(short_side: int) -> str:
    """Short side ≤ ``short_side`` (720p for landscape and portrait), even sizes, no upscaling."""
    s = short_side
    w = f"if(gte(iw,ih),-2,trunc(min({s},iw)/2)*2)"
    h = f"if(gte(iw,ih),trunc(min({s},ih)/2)*2,-2)"
    return f"scale=w='{w}':h='{h}',format=yuv420p"


def ffmpeg_command(settings: Settings, src: Path, out: Path) -> list[str]:
    return [
        settings.ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1", "-map_chapters", "-1",
        "-vf", _scale(settings.video_short_side), "-fpsmax", str(settings.video_max_fps),
        "-c:v", "libx264", "-preset", settings.video_preset, "-crf", str(settings.video_crf),
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-f", "mp4", str(out),
    ]  # fmt: skip


def _nice() -> None:  # runs in the ffmpeg child: low priority, the API stays responsive
    os.nice(10)


def process_video(settings: Settings, src: Path, work: Path) -> Processed:
    info = probe(settings, src)
    if video_stream(info) is None:
        raise PermanentError("not_a_video: no video stream")
    seconds = duration_s(info)
    if seconds is None:
        raise PermanentError("not_a_video: unknown duration")
    if seconds > settings.video_max_seconds:
        raise PermanentError(
            f"video_too_long: {seconds:.1f} s > {settings.video_max_seconds:g} s (R29)"
        )
    out = work / "video.mp4"
    done = subprocess.run(
        ffmpeg_command(settings, src, out),
        capture_output=True,
        text=True,
        timeout=settings.video_timeout_seconds,
        preexec_fn=_nice,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(f"ffmpeg exit {done.returncode}: {done.stderr.strip()[:500]}")
    result = probe(settings, out)
    stream = video_stream(result)
    if stream is None or stream.get("codec_name") != "h264":
        raise RuntimeError("ffmpeg output is not H.264")
    width, height = int(stream["width"]), int(stream["height"])
    if min(width, height) > settings.video_short_side:
        raise RuntimeError(f"ffmpeg output {width}x{height} is larger than 720p")
    length = duration_s(result) or seconds
    return Processed(out, width, height, duration_ms=round(length * 1000))


def _original(settings: Settings, payload: Payload) -> Path:
    src = (settings.data_dir / str(payload["path"])).resolve()
    if not src.is_relative_to(settings.uploads_dir.resolve()):
        raise PermanentError(f"bad_path: {payload['path']}")
    return src


def _handle(ctx: Context, payload: Payload, kind: str) -> Result:
    settings = ctx.settings
    media_id = str(payload["mediaId"])
    with ctx.sessions() as session:
        row = session.get(Media, media_id)
        if row is None:
            return {"skipped": "media_removed"}
        if row.status != "processing":
            return {"skipped": f"media_{row.status}", "sha256": row.sha256}
    src = _original(settings, payload)
    if not src.is_file():
        raise PermanentError(f"original_missing: {payload['path']}")
    work = src.parent / "work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    if kind == "photo":
        made = process_image(settings, src, work)
    else:
        made = process_video(settings, src, work)
    sha = sha256_file(made.path)
    size = made.path.stat().st_size
    _store(made.path, media_service.file_path(settings, sha, kind))
    if made.thumb is not None:
        _store(made.thumb, media_service.thumb_path(settings, sha))
    with ctx.sessions() as session:
        row = session.get(Media, media_id)
        if row is None:  # removed while processing; the file stays for whoever shares its sha
            return {"skipped": "media_removed", "sha256": sha}
        row.sha256, row.bytes = sha, size
        row.width, row.height, row.duration_ms = made.width, made.height, made.duration_ms
        row.status, row.error = "ready", None
        upload = session.get(Upload, media_id)
        if upload is not None:
            session.delete(upload)
        session.commit()
    shutil.rmtree(uploads.directory(settings, media_id), ignore_errors=True)
    out: Result = {"sha256": sha, "bytes": size, "width": made.width, "height": made.height}
    if made.duration_ms is not None:
        out["durationMs"] = made.duration_ms
    return out


def handle_image(ctx: Context, payload: Payload) -> Result:
    return _handle(ctx, payload, "photo")


def handle_video(ctx: Context, payload: Payload) -> Result:
    return _handle(ctx, payload, "video")


def mark_failed(ctx: Context, payload: Payload, message: str) -> None:
    with ctx.sessions() as session:
        row = session.get(Media, str(payload.get("mediaId")))
        if row is not None and row.status == "processing":
            row.status, row.error = "failed", message[:1000]
            session.commit()
