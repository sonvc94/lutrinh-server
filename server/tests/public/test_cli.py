"""``lutrinh seed-sample`` and ``lutrinh serve`` (local trying, AGENTS.md)."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lutrinh import cli
from lutrinh.api.app import create_app
from lutrinh.config import get_settings
from lutrinh.core import canonical_json
from lutrinh.db.engine import make_engine
from lutrinh.db.models import Base
from tests.conftest import SAMPLE_DIR

ACCEPT = {"Accept": "application/vnd.lutrinh.route+json;v=1"}


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="seed-sample needs ffmpeg")
def test_seed_sample_publishes_a_downloadable_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LUTRINH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LUTRINH_DATABASE_URL", f"sqlite:///{tmp_path / 'seed.sqlite'}")
    get_settings.cache_clear()
    engine = make_engine(get_settings().db_url)
    Base.metadata.create_all(engine)
    try:
        assert cli.main(["seed-sample"]) == 0
        out = capsys.readouterr().out
        code = next(line for line in out.splitlines() if line.startswith("Mã: ")).split()[1]
        sample = canonical_json.loads((SAMPLE_DIR / "route.json").read_bytes())

        c = TestClient(create_app(get_settings(), engine=engine))
        summary = c.get(f"/api/v1/codes/{code}", headers=ACCEPT).json()
        assert summary["title"] == sample["route"]["title"]
        assert (summary["stops"], summary["photos"], summary["videos"]) == (9, 12, 2)
        token = summary["downloadToken"]
        route = c.get(f"/api/v1/dl/{token}/route", headers=ACCEPT)
        assert route.status_code == 200
        doc: dict[str, Any] = canonical_json.loads(route.content)
        assert [s["title"] for s in doc["stops"]] == [s["title"] for s in sample["stops"]]
        assert doc["legs"] == sample["legs"]
        for item in (doc["media"][0], next(m for m in doc["media"] if m["type"] == "video")):
            r = c.get(f"/api/v1/dl/{token}/media/{item['sha256']}")
            assert r.status_code == 200
            assert len(r.content) == item["bytes"]
            assert hashlib.sha256(r.content).hexdigest() == item["sha256"]
        magic = c.get(summary["cover"]).content[:3]
        assert magic == b"\xff\xd8\xff"  # the 640 px JPEG preview
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_seed_sample_without_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LUTRINH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LUTRINH_DATABASE_URL", f"sqlite:///{tmp_path / 'seed.sqlite'}")
    monkeypatch.setenv("PATH", str(tmp_path))
    get_settings.cache_clear()
    engine = make_engine(get_settings().db_url)
    Base.metadata.create_all(engine)
    try:
        assert cli.main(["seed-sample"]) == 1
        assert "ffmpeg not found" in capsys.readouterr().err
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_serve_runs_uvicorn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUTRINH_DATABASE_URL", f"sqlite:///{tmp_path / 'serve.sqlite'}")
    get_settings.cache_clear()
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.append(kw))
    try:
        assert cli.main(["serve"]) == 0
        assert cli.main(["serve", "--host", "0.0.0.0", "--port", "8123"]) == 0
    finally:
        get_settings.cache_clear()
    assert [(k["host"], k["port"]) for k in calls] == [("127.0.0.1", 8000), ("0.0.0.0", 8123)]
