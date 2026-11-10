from __future__ import annotations

import pytest

from lutrinh.core import polyline


def test_round_trip() -> None:
    pts = [(22.8233, 104.9836), (23.064, 104.993), (-33.86882, 151.209296), (0.0, -0.000001)]
    assert polyline.decode(polyline.encode(pts)) == pts


def test_known_value() -> None:
    # Google's documented example at precision 5 is "_p~iF~ps|U_ulLnnqC_mqNvxq`@";
    # at precision 6 the same points encode as below (OSRM/Valhalla polyline6).
    pts = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
    assert polyline.encode(pts) == "_izlhA~rlgdF_{geC~ywl@_kwzCn`{nI"


@pytest.mark.parametrize("bad", ["_", "a b", "_p~iF"])
def test_malformed(bad: str) -> None:
    with pytest.raises(ValueError):
        polyline.decode(bad)
