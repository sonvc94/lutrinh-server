from __future__ import annotations

import math
import random
import struct

import pytest

from lutrinh.core import canonical_json


def test_random_doubles_round_trip_exactly() -> None:
    rng = random.Random(3)
    for _ in range(5000):
        x = struct.unpack("<d", rng.getrandbits(64).to_bytes(8, "little"))[0]
        if math.isnan(x) or math.isinf(x):
            continue
        text = canonical_json.dumps(x).decode()
        assert float(text) == x
        assert canonical_json.canonicalise(text) == text.encode()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1e21, "1e+21"),
        (1e-7, "1e-7"),
        (-1e-6, "-0.000001"),
        (1.5e300, "1.5e+300"),
        (123456789012345680000.0, "123456789012345680000"),
        (0.5, "0.5"),
        (-0.0, "0"),
    ],
)
def test_number_forms(value: float, expected: str) -> None:
    assert canonical_json.dumps(value) == expected.encode()


def test_rejects_non_json() -> None:
    for bad in (float("nan"), float("inf"), {1: 2}, object(), 2**53):
        with pytest.raises((ValueError, TypeError)):
            canonical_json.dumps(bad)
    with pytest.raises(ValueError):
        canonical_json.dumps("\ud800")
