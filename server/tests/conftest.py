from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

SPEC_DIR = Path(__file__).resolve().parents[2] / "spec"
SAMPLE_DIR = SPEC_DIR / "samples" / "ha-giang-4n"


def load_spec(name: str) -> Any:
    return json.loads((SPEC_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def sample_bytes() -> bytes:
    return (SAMPLE_DIR / "route.json").read_bytes()


@pytest.fixture
def sample_expected() -> dict[str, Any]:
    return json.loads((SAMPLE_DIR / "expected.json").read_text(encoding="utf-8"))
