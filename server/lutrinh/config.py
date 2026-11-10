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
