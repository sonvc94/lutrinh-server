"""Settings from `LUTRINH_*` environment variables (secrets later: /etc/lutrinh/env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# server/lutrinh/config.py → repo root is three levels up.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LUTRINH_")

    # Host layout (page 06 §4): db/, media/, uploads/, backups/ under one directory.
    data_dir: Path = Path("/var/lib/lutrinh")
    # Overrides the SQLite file under data_dir (tests, alembic on a scratch file).
    database_url: str | None = None
    # Shared spec (route.schema.json, vectors). The deploy image must ship it.
    spec_dir: Path = _REPO_ROOT / "spec"
    # Built admin SPA (Vite, base '/admin/'); a placeholder page is served while it is absent.
    admin_dist_dir: Path = _REPO_ROOT / "admin" / "dist"
    # Zone that turns UTC times (GPX) into the route's "day N + HH:mm" (Mate decision 2B).
    local_tz: str = "Asia/Ho_Chi_Minh"

    # Admin login (page 03 D-7, page 04 §G): session 12 h, 2 h idle, 5 failures / 15 min → 15 min.
    session_hours: float = 12
    session_idle_hours: float = 2
    login_max_failures: int = 5
    login_window_minutes: float = 15
    login_lock_minutes: float = 15
    # Test phase: login is username + password only. `LUTRINH_ADMIN_TOTP=on` asks for the TOTP
    # (or a backup code) again; the secret and codes made by `admin create|reset` stay valid.
    admin_totp: bool = False
    # Shortest admin password `lutrinh admin create|reset|set-password` accepts. Raise it (14
    # when TOTP goes back on) before the server holds real data.
    admin_password_min: int = 6
    # Argon2id cost; tests lower it (the defaults are argon2-cffi's RFC 9106 low-memory profile).
    argon2_time_cost: int = 3
    argon2_memory_kib: int = 65536

    # Uploads (page 03): 8 MB chunks behind a 10 MB proxy body limit; originals ≤ 200 MB (R29).
    upload_chunk_bytes: int = 8 * 1024 * 1024
    media_max_bytes: int = 200 * 1024 * 1024
    import_max_bytes: int = 2 * 1024 * 1024 * 1024

    # Publish warning "long leg within one day" (Mate decision 6A).
    long_leg_warn_km: float = 150

    # Public API (page 03, Mate decisions server-public-api 2–9).
    token_hours: float = 2
    lookups_per_hour: int = 30
    bad_lookups_per_hour: int = 10
    # Lock ladder after too many failed lookups; resets after 24 h without a lock.
    lock_ladder_hours: list[float] = [1, 4, 24]
    lock_ladder_reset_hours: float = 24
    # System-wide: this many failed lookups in an hour → mail + tightened per-IP limit for 24 h.
    alarm_bad_lookups_per_hour: int = 500
    alarm_bad_lookups_per_ip: int = 3
    alarm_hours: float = 24
    route_downloads_per_code_hour: int = 10
    media_requests_per_file: int = 3
    bandwidth_month_bytes: int = 100 * 1000**3
    bandwidth_warn_ratio: float = 0.7
    iplog_days: float = 14
    overview_tolerance_m: float = 200
    # Switch for "bảo trì": /api/v1/meta says so, every other public route answers 503.
    maintenance: bool = False
    maintenance_message: str | None = None
    min_app_android: str = "0.0.0"
    min_app_ios: str = "0.0.0"
    # Behind Caddy/Nginx: answer media with X-Accel-Redirect (page 06 §4) instead of the file.
    media_accel: bool = False

    # Worker (page 06 §3, D-20 A): one process runs the `jobs` rows one at a time.
    worker_poll_seconds: float = 2
    # Retry after a failure: base × 2^(attempt-1), at most the cap; `jobs.max_attempts` tries.
    job_backoff_seconds: float = 30
    job_backoff_max_seconds: float = 600
    # A job still `running` after this long belongs to a worker that died; it is claimed again.
    job_stale_minutes: float = 60
    # Nightly jobs (purge.iplog, the 30-day trash sweep) are queued after this local hour.
    nightly_hour: int = 3
    trash_days: float = 30
    # Photos (page 03 "Kích thước", R11): ≤ 2560 px, JPEG ~85 %, no EXIF/GPS; 640 px preview.
    image_max_px: int = 2560
    image_quality: int = 85
    thumb_width: int = 640
    # Videos (R29, page 03): ≤ 60 s, re-encoded to 720p H.264 + AAC, +faststart.
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    video_max_seconds: float = 60
    video_short_side: int = 720
    video_max_fps: int = 30
    video_crf: int = 23
    video_preset: str = "medium"
    video_timeout_seconds: float = 900
    # Routing (R36 via adapters/routing): the router addresses live here and nowhere else.
    valhalla_url: str = "https://valhalla1.openstreetmap.de/route"
    osrm_car_url: str = "https://routing.openstreetmap.de/routed-car/route/v1/driving"
    router_user_agent: str = "LuTrinh-Server/0.1 (route server; httpx)"
    router_timeout_seconds: float = 30
    router_min_interval_seconds: float = 1.0
    # Off-road guard (R36): a stop > 500 m from the road line, or road > 5× straight → too_far.
    offroad_max_m: float = 500
    offroad_max_ratio: float = 5
    leg_simplify_m: float = 10

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'db' / 'lutrinh.sqlite'}"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
