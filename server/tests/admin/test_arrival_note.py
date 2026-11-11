"""Stop ``arrivalNote`` (note on the travel into a stop): draft → legs → publish → download."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from lutrinh.adapters.routing import Routers, Throttle
from lutrinh.api.admin import PREFIX
from lutrinh.db.engine import make_sessionmaker
from lutrinh.jobs import Context, worker
from tests.admin.conftest import Admin
from tests.jobs.conftest import FakeRouter

ACCEPT = {"Accept": "application/vnd.lutrinh.route+json;v=1"}
NOTE = "Đường dốc khó đi. Gửi xe phía đối diện, 30k"


def _stop(sid: str, time: str, lat: float, lng: float, **kw: Any) -> dict[str, Any]:
    return {"id": sid, "day": 1, "time": time, "title": sid, "note": "", "lat": lat, "lng": lng,
            "arrival": kw.pop("arrival", None), "media": [], **kw}  # fmt: skip


def _draft(c: TestClient, rid: str) -> tuple[dict[str, Any], str]:
    r = c.get(f"{PREFIX}/routes/{rid}/draft")
    return r.json()["body"], r.headers["ETag"]


def _put(c: TestClient, rid: str, body: dict[str, Any]) -> Any:
    _, etag = _draft(c, rid)
    r = c.put(f"{PREFIX}/routes/{rid}/draft", json=body, headers={"If-Match": etag})
    assert r.status_code == 200, r.text
    return r.json()["body"]


def _run_worker(admin: Admin) -> int:
    ctx = Context(
        admin.settings,
        make_sessionmaker(admin.app.state.engine),
        Routers(FakeRouter(), None, Throttle(0)),
    )
    return worker.run(ctx, once=True, nightly=False)


def test_arrival_note_is_trimmed_and_absent_when_empty(client: TestClient) -> None:
    rid = client.post(f"{PREFIX}/routes", json={"title": "Ninh Bình"}).json()["id"]
    body, _ = _draft(client, rid)
    body["stops"] = [
        _stop("s_a", "08:00", 20.25, 105.89),
        _stop("s_b", "10:00", 20.22, 105.93, arrival="plane", arrivalNote=f"  {NOTE}\n"),
        _stop("s_c", "12:00", 20.21, 105.95, arrival="boat", arrivalNote="   "),
        _stop("s_d", "13:00", 20.20, 105.96, arrival="boat", arrivalNote=None),
    ]
    stored = _put(client, rid, body)["stops"]
    assert stored[1]["arrivalNote"] == NOTE
    assert ["arrivalNote" in s for s in stored] == [False, True, False, False]
    # old drafts (no key anywhere) keep their shape
    assert "arrivalNote" not in _put(client, rid, {**body, "stops": body["stops"][:1]})["stops"][0]


def test_arrival_note_survives_legs_and_reaches_the_package(
    admin: Admin, client: TestClient
) -> None:
    rid = client.post(f"{PREFIX}/routes", json={"title": "Ninh Bình"}).json()["id"]
    body, _ = _draft(client, rid)
    body["stops"] = [
        _stop("s_a", "08:00", 20.25, 105.89),
        _stop("s_b", "10:00", 20.22, 105.93, arrival="motorbike", arrivalNote=NOTE),
        _stop("s_c", "12:00", 20.21, 105.95, arrival="motorbike"),
    ]
    _put(client, rid, body)
    assert _run_worker(admin) == 2  # legs into s_b and s_c
    body, _ = _draft(client, rid)
    assert {leg["to"] for leg in body["legs"]} == {"s_b", "s_c"}
    assert body["stops"][1]["arrivalNote"] == NOTE

    # move s_b: both legs touching it are stale and recomputed; the note stays on the stop
    body["stops"][1]["lat"] = 20.23
    body = _put(client, rid, body)
    assert body["legs"] == []
    assert _run_worker(admin) == 2
    body, _ = _draft(client, rid)
    assert {leg["to"] for leg in body["legs"]} == {"s_b", "s_c"}
    assert body["stops"][1]["arrivalNote"] == NOTE

    r = client.post(f"{PREFIX}/routes/{rid}/publish", json={})
    assert r.status_code == 201, r.text
    code = r.json()["code"]["code"]
    token = client.get(f"/api/v1/codes/{code}", headers=ACCEPT).json()["downloadToken"]
    route = client.get(f"/api/v1/dl/{token}/route", headers=ACCEPT)
    assert route.status_code == 200, route.text
    stops = json.loads(route.content)["stops"]
    assert [s.get("arrivalNote") for s in stops] == [None, NOTE, None]
    assert "arrivalNote" not in stops[0] and "arrivalNote" not in stops[2]


def test_arrival_note_on_the_first_stop_blocks_publishing(client: TestClient) -> None:
    rid = client.post(f"{PREFIX}/routes", json={"title": "Ninh Bình"}).json()["id"]
    body, _ = _draft(client, rid)
    body["stops"] = [
        _stop("s_b", "08:00", 20.22, 105.93, arrival="train", arrivalNote=NOTE),  # moved to top
        _stop("s_a", "10:00", 20.25, 105.89, arrival="train"),
    ]
    _put(client, rid, body)
    pre = client.get(f"{PREFIX}/routes/{rid}/publish").json()
    assert pre["canPublish"] is False
    assert [(b["code"], b["path"]) for b in pre["blockers"]] == [
        ("arrival_note_first_stop", "/stops/0/arrivalNote")
    ]
    body["stops"][1]["arrivalNote"] = body["stops"][0].pop("arrivalNote")
    _put(client, rid, body)
    assert client.get(f"{PREFIX}/routes/{rid}/publish").json()["canPublish"] is True


def test_arrival_note_over_1000_fails_the_preflight(client: TestClient) -> None:
    rid = client.post(f"{PREFIX}/routes", json={"title": "Ninh Bình"}).json()["id"]
    body, _ = _draft(client, rid)
    body["stops"] = [
        _stop("s_a", "08:00", 20.25, 105.89),
        _stop("s_b", "10:00", 20.22, 105.93, arrival="train", arrivalNote="đ" * 1001),
    ]
    _put(client, rid, body)
    pre = client.get(f"{PREFIX}/routes/{rid}/publish").json()
    assert pre["canPublish"] is False
    assert [b["path"] for b in pre["blockers"]] == ["/stops/1/arrivalNote"]
