"""End to end through the API: GPX import → draft → publish → code → v2 → revoke/reissue."""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from lutrinh.api.admin import PREFIX
from lutrinh.core import codes
from lutrinh.db.engine import make_sessionmaker
from lutrinh.db.models import RouteVersion
from lutrinh.services import codes as code_service
from lutrinh.services.errors import ServiceError
from tests.admin.conftest import Admin
from tests.admin.helpers import gpx_three_stops, import_file


def _lookup(admin: Admin, code: str) -> int:
    """What the public API (a later task) will answer for a typed code: the version, or raise."""
    with make_sessionmaker(admin.app.state.engine)() as db:
        return code_service.lookup(db, code).version.version


def _lookup_error(admin: Admin, code: str) -> tuple[int, str]:
    with pytest.raises(ServiceError) as err:
        _lookup(admin, code)
    return err.value.status, err.value.code


def test_gpx_import_publish_code_v2_revoke_reissue(admin: Admin, client: TestClient) -> None:
    # Draft from a 3-stop GPX (the import creates the route and its draft).
    imp = import_file(client, "gpx", "ha-giang.gpx", gpx_three_stops())
    assert imp["status"] == "ready", imp
    assert imp["preview"]["stops"] == 3
    assert imp["preview"]["legsFromTrack"] == 2
    r = client.post(f"{PREFIX}/imports/{imp['id']}/apply", json={})
    assert r.status_code == 201, r.text
    route_id = r.json()["routeId"]
    assert client.post(f"{PREFIX}/imports/{imp['id']}/apply", json={}).status_code == 409

    draft = client.get(f"{PREFIX}/routes/{route_id}/draft")
    body = draft.json()["body"]
    assert [s["time"] for s in body["stops"]] == ["08:00", "10:00", "13:00"]
    assert [leg["source"] for leg in body["legs"]] == ["gpx", "gpx"]
    assert client.get(f"{PREFIX}/routes/{route_id}").json()["status"] == "draft"

    # Publish v1: a code is issued.
    pre = client.get(f"{PREFIX}/routes/{route_id}/publish").json()
    assert pre["canPublish"] is True and pre["nextVersion"] == 1, pre
    r = client.post(f"{PREFIX}/routes/{route_id}/publish", json={"note": "Bản đầu"})
    assert r.status_code == 201, r.text
    v1 = r.json()
    assert v1["version"]["version"] == 1
    assert v1["codeIssued"] is True
    code = v1["code"]["code"]
    assert codes.parse(code) == code.replace("-", "")
    assert _lookup(admin, code) == 1
    listed = client.get(f"{PREFIX}/routes/{route_id}").json()
    assert listed["status"] == "shared" and listed["code"] == code
    assert listed["draftChanged"] is False

    # Edit the draft (If-Match), publish v2: same code, v1 keeps its sha256.
    etag = draft.headers["ETag"]
    body["title"] = "Hà Giang 1 ngày (sửa)"
    no_match = client.put(f"{PREFIX}/routes/{route_id}/draft", json=body)
    assert no_match.status_code == 428
    r = client.put(f"{PREFIX}/routes/{route_id}/draft", json=body, headers={"If-Match": etag})
    assert r.status_code == 200, r.text
    stale = client.put(f"{PREFIX}/routes/{route_id}/draft", json=body, headers={"If-Match": etag})
    assert stale.status_code == 412
    assert stale.json()["error"]["code"] == "draft_changed"
    assert client.get(f"{PREFIX}/routes/{route_id}").json()["draftChanged"] is True

    r = client.post(f"{PREFIX}/routes/{route_id}/publish", json={"note": "Sửa tên"})
    assert r.status_code == 201, r.text
    v2 = r.json()
    assert v2["version"]["version"] == 2
    assert v2["codeIssued"] is False and v2["code"]["code"] == code
    assert v2["version"]["sha256"] != v1["version"]["sha256"]
    versions = {v["version"]: v for v in client.get(f"{PREFIX}/routes/{route_id}/versions").json()}
    assert versions[1]["sha256"] == v1["version"]["sha256"]
    with make_sessionmaker(admin.app.state.engine)() as db:
        row = db.get(RouteVersion, (route_id, 1))
        assert row is not None
        assert hashlib.sha256(row.route_json).hexdigest() == v1["version"]["sha256"]
    assert _lookup(admin, code) == 2

    # Revoke + reissue: a different code; the old one answers 410.
    r = client.post(f"{PREFIX}/codes/{code}/revoke", json={"reason": "lộ mã", "reissue": True})
    assert r.status_code == 200, r.text
    new_code = r.json()["newCode"]["code"]
    assert new_code != code
    assert r.json()["revoked"]["live"] is False
    assert _lookup_error(admin, code) == (410, "code_revoked")
    assert _lookup(admin, new_code) == 2
    assert client.post(f"{PREFIX}/codes/{code}/revoke", json={}).status_code == 409
    listed_codes = client.get(f"{PREFIX}/routes/{route_id}/codes").json()
    assert [c["live"] for c in listed_codes] == [True, False]

    # Unpublish: lookups answer 410; republishing v1 makes v3 and the code works again.
    r = client.post(f"{PREFIX}/routes/{route_id}/unpublish")
    assert r.status_code == 200 and r.json()["status"] == "unpublished"
    assert _lookup_error(admin, new_code) == (410, "route_unpublished")
    r = client.post(f"{PREFIX}/routes/{route_id}/versions/1/republish", json={"note": "Quay lại"})
    assert r.status_code == 201, r.text
    v3 = r.json()["version"]
    assert v3["version"] == 3 and v3["sourceVersion"] == 1
    assert v3["sha256"] != v1["version"]["sha256"]  # version and publishedAt differ
    assert _lookup(admin, new_code) == 3
    assert client.get(f"{PREFIX}/routes/{route_id}").json()["status"] == "shared"

    actions = [e["action"] for e in client.get(f"{PREFIX}/audit").json()]
    for action in (
        "import.apply",
        "draft.update",
        "route.publish",
        "code.revoke",
        "code.issue",
        "route.unpublish",
        "route.republish",
    ):
        assert action in actions
