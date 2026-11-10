"""spec/canonical-json.json against lutrinh.core.canonical_json."""

from __future__ import annotations

from typing import Any

import pytest

from lutrinh.core import canonical_json
from tests.conftest import load_spec

V = load_spec("canonical-json.json")


@pytest.mark.parametrize("case", V["cases"], ids=lambda c: c["name"])
def test_canonical_vector(case: dict[str, Any]) -> None:
    if "error" in case:
        with pytest.raises(ValueError):
            canonical_json.canonicalise(case["input"])
    else:
        assert canonical_json.canonicalise(case["input"]) == case["canonical"].encode("utf-8")
