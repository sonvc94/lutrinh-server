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
    # Argon2id cost; tests lower it (the defaults are argon2-cffi's RFC 9106 low-memory profile).
    argon2_time_cost: int = 3
    argon2_memory_kib: int = 65536

    # Uploads (page 03): 8 MB chunks behind a 10 MB proxy body limit; originals ≤ 200 MB (R29).
    upload_chunk_bytes: int = 8 * 1024 * 1024
    media_max_bytes: int = 200 * 1024 * 1024
    import_max_bytes: int = 2 * 1024 * 1024 * 1024

    # Publish warning "long leg within one day" (Mate decision 6A).
    long_leg_warn_km: float = 150

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
