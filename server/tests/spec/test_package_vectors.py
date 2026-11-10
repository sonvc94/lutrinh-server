"""spec/route.schema.json, the sample package and spec/package-vectors.json."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from lutrinh.core import canonical_json, package, polyline
from tests.conftest import SAMPLE_DIR, SPEC_DIR, load_spec

V = load_spec("package-vectors.json")


def test_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(load_spec("route.schema.json"))


def test_sample_matches_schema_and_integrity(sample_bytes: bytes) -> None:
    doc = json.loads(sample_bytes)
    assert list(Draft202012Validator(load_spec("route.schema.json")).iter_errors(doc)) == []
    assert package.check(doc) == []


def test_sample_sha256_and_counts(sample_bytes: bytes, sample_expected: dict[str, Any]) -> None:
    assert hashlib.sha256(sample_bytes).hexdigest() == sample_expected["sha256"]
    assert len(sample_bytes) == sample_expected["bytes"]
    doc = package.read(sample_bytes)
    assert len(doc["stops"]) == sample_expected["stops"] == 9
    assert len(doc["legs"]) == sample_expected["legs"]
    types = [m["type"] for m in doc["media"]]
    assert types.count("photo") == sample_expected["photos"]
    assert types.count("video") == sample_expected["videos"]
    assert doc["size"] == {
        "media": sample_expected["sizeMedia"],
        "files": sample_expected["sizeFiles"],
    }


def test_sample_read_then_write_is_byte_identical(sample_bytes: bytes) -> None:
    assert canonical_json.dumps(json.loads(sample_bytes)) == sample_bytes
    assert not sample_bytes.endswith(b"\n")


def test_sample_leg_paths_are_polyline6_near_their_stops(sample_bytes: bytes) -> None:
    doc = json.loads(sample_bytes)
    stops = {s["id"]: i for i, s in enumerate(doc["stops"])}
    for leg in doc["legs"]:
        pts = polyline.decode(leg["path"])
        end = doc["stops"][stops[leg["to"]]]
        start = doc["stops"][stops[leg["to"]] - 1]
        assert abs(pts[0][0] - start["lat"]) < 1e-4 and abs(pts[0][1] - start["lng"]) < 1e-4
        assert abs(pts[-1][0] - end["lat"]) < 1e-4 and abs(pts[-1][1] - end["lng"]) < 1e-4


def _pointer(doc: Any, path: str) -> tuple[Any, str]:
    parts = [p.replace("~1", "/").replace("~0", "~") for p in path.split("/")[1:]]
    parent = doc
    for p in parts[:-1]:
        parent = parent[int(p)] if isinstance(parent, list) else parent[p]
    return parent, parts[-1]


def apply_ops(doc: Any, ops: list[dict[str, Any]]) -> Any:
    doc = copy.deepcopy(doc)
    for op in ops:
        parent, key = _pointer(doc, op["path"])
        if isinstance(parent, list):
            if op["op"] == "add":
                parent.insert(len(parent) if key == "-" else int(key), op["value"])
            elif op["op"] == "remove":
                del parent[int(key)]
            else:
                parent[int(key)] = op["value"]
        elif op["op"] == "remove":
            del parent[key]
        else:
            parent[key] = op["value"]
    return doc


@pytest.mark.parametrize("case", V["cases"], ids=lambda c: c["name"])
def test_package_vector(case: dict[str, Any]) -> None:
    base = json.loads((SPEC_DIR / V["base"]).read_bytes())
    data = canonical_json.dumps(apply_ops(base, case["ops"]))
    try:
        package.read(data)
        got: set[str] = set()
    except package.PackageError as err:
        got = {p.code for p in err.problems}
    assert got == set(case["expect"])


def test_spec_files_are_listed() -> None:
    # Guard against a vector file being added without a test reading it.
    names = sorted(p.name for p in SPEC_DIR.glob("*.json"))
    assert names == [
        "canonical-json.json",
        "codes.json",
        "package-vectors.json",
        "route.schema.json",
    ]
    assert sorted(p.name for p in SAMPLE_DIR.iterdir()) == ["expected.json", "route.json"]
