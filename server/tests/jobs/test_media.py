"""media.image / media.video (page 06 §3; build task 5: no EXIF/GPS, 65 s refused, h264 720p)."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import ExifTags, Image

from lutrinh.services import media as media_service
from tests.jobs.conftest import Env, ffmpeg, ffprobe

GPS = {
    ExifTags.GPS.GPSLatitudeRef: "N",
    ExifTags.GPS.GPSLatitude: (22.0, 49.0, 30.0),
    ExifTags.GPS.GPSLongitudeRef: "E",
    ExifTags.GPS.GPSLongitude: (104.0, 58.0, 48.0),
}


def phone_jpeg(size: tuple[int, int] = (3000, 2000), orientation: int = 6) -> bytes:
    img = Image.new("RGB", size, (200, 30, 30))
    img.paste((30, 30, 200), (0, 0, size[0] // 2, size[1] // 4))  # a mark: top-left quarter
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "PhoneCo"
    exif[ExifTags.Base.Orientation] = orientation
    exif[ExifTags.Base.DateTimeOriginal] = "2026:10:01 08:00:00"
    exif[ExifTags.IFD.GPSInfo] = GPS
    xmp = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><exif:GPSLatitude>22,49.5N</exif:GPSLatitude>'
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90, exif=exif, xmp=xmp + b"</x:xmpmeta>", comment=b"secret")
    return out.getvalue()


def test_stored_photo_has_no_exif_or_gps(env: Env) -> None:
    original = phone_jpeg()
    with Image.open(io.BytesIO(original)) as im:  # the test file really carries GPS
        assert im.getexif().get_ifd(ExifTags.IFD.GPSInfo)
    mid = env.add_upload("IMG_0001.JPG", original)
    assert env.run() == 1
    row = env.media(mid)
    assert row.status == "ready", row.error
    stored = media_service.file_path(env.settings, row.sha256 or "", "photo")
    data = stored.read_bytes()
    assert b"Exif" not in data and b"GPS" not in data and b"xmpmeta" not in data
    assert b"PhoneCo" not in data and b"secret" not in data
    with Image.open(stored) as im:
        assert im.format == "JPEG"
        assert dict(im.getexif()) == {}
        assert "exif" not in im.info and "xmp" not in im.info and "comment" not in im.info
        # Orientation 6 (rotate 90° cw) applied, long side ≤ 2560.
        assert im.size == (1707, 2560) == (row.width, row.height)
        assert im.getpixel((1700, 10))[2] > 150  # the blue mark is now top-right
    assert row.bytes == len(data)
    assert stored.name == f"{row.sha256}.jpg"
    thumb = media_service.thumb_path(env.settings, row.sha256 or "")
    with Image.open(thumb) as im:
        assert im.width == 640 and dict(im.getexif()) == {}
    assert not (env.settings.uploads_dir / mid).exists()  # original removed
    job = env.jobs("media.image")[0]
    assert job.status == "done" and job.result and job.result["sha256"] == row.sha256


def test_small_png_with_alpha_is_flattened_not_enlarged(env: Env) -> None:
    out = io.BytesIO()
    Image.new("RGBA", (300, 200), (0, 0, 0, 0)).save(out, "PNG")
    mid = env.add_upload("logo.png", out.getvalue())
    env.run()
    row = env.media(mid)
    assert row.status == "ready" and (row.width, row.height) == (300, 200)
    with Image.open(media_service.file_path(env.settings, row.sha256 or "", "photo")) as im:
        assert im.mode == "RGB" and im.getpixel((5, 5)) == (255, 255, 255)
    with Image.open(media_service.thumb_path(env.settings, row.sha256 or "")) as im:
        assert im.size == (300, 200)


def test_same_photo_twice_shares_one_file(env: Env) -> None:
    data = phone_jpeg((800, 600), orientation=1)
    a, b = env.add_upload("a.jpg", data), env.add_upload("b.jpg", data)
    assert env.run() == 2
    sha_a, sha_b = env.media(a).sha256, env.media(b).sha256
    assert sha_a == sha_b
    files = list((env.settings.media_dir).rglob("*.jpg"))
    assert len(files) == 2  # one photo + its preview


def test_file_that_is_not_an_image_fails_at_once(env: Env) -> None:
    mid = env.add_upload("fake.jpg", b"not really a jpeg" * 100)
    env.run()
    row = env.media(mid)
    assert row.status == "failed" and (row.error or "").startswith("not_an_image")
    job = env.jobs("media.image")[0]
    assert (job.status, job.attempts) == ("failed", 1)


def make_video(path: Path, seconds: int, size: str, rate: int = 10, audio: bool = True) -> bytes:
    args = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    args += ["-metadata", "location=+22.8250+104.9800/", "-metadata", "title=Chuyến đi"]
    ffmpeg(*args, str(path))
    return path.read_bytes()


def test_video_of_65_s_is_rejected(env: Env, tmp_path: Path) -> None:
    data = make_video(tmp_path / "long.mp4", 65, "160x120", rate=5, audio=False)
    mid = env.add_upload("long.mp4", data)
    env.run()
    row = env.media(mid)
    assert row.status == "failed"
    assert (row.error or "").startswith("video_too_long: 65.0 s > 60 s")
    job = env.jobs("media.video")[0]
    assert (job.status, job.attempts) == ("failed", 1)  # refused, not retried
    assert not list(env.settings.media_dir.rglob("*.mp4"))


def test_accepted_video_is_h264_720p_without_metadata(env: Env, tmp_path: Path) -> None:
    data = make_video(tmp_path / "trip.mp4", 30, "1920x1080")
    mid = env.add_upload("trip.mp4", data)
    env.run()
    row = env.media(mid)
    assert row.status == "ready", row.error
    stored = media_service.file_path(env.settings, row.sha256 or "", "video")
    info = ffprobe(stored)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (video["codec_name"], video["width"], video["height"]) == ("h264", 1280, 720)
    assert audio["codec_name"] == "aac"
    tags = info["format"].get("tags", {})
    assert "location" not in tags and "title" not in tags
    assert (row.width, row.height) == (1280, 720)
    assert row.duration_ms is not None and abs(row.duration_ms - 30_000) < 200
    assert row.bytes == stored.stat().st_size
    assert not list(env.settings.media_dir.rglob("*.jpg"))  # no poster
    data_out = stored.read_bytes()
    assert data_out.index(b"moov") < data_out.index(b"mdat")  # +faststart


def test_portrait_video_keeps_720_on_the_short_side(env: Env, tmp_path: Path) -> None:
    data = make_video(tmp_path / "tall.mp4", 2, "1080x1920", audio=False)
    mid = env.add_upload("tall.mp4", data)
    env.run()
    row = env.media(mid)
    assert row.status == "ready", row.error
    assert (row.width, row.height) == (720, 1280)
