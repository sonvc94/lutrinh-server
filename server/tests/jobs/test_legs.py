"""legs.compute (R36 via adapters/routing): ≥ 1 s between router calls, car fallback, guard."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from typing import Any

import httpx
import pytest

from lutrinh.adapters.routing import Answer, LatLng, Routers, RouterUnavailable, Throttle
from lutrinh.adapters.routing.osrm import OsrmRouter
from lutrinh.adapters.routing.valhalla import ValhallaRouter
from lutrinh.config import Settings
from lutrinh.core import geo, polyline
from lutrinh.db.models import Draft
from lutrinh.jobs import worker
from lutrinh.services import routes
from tests.jobs.conftest import Env, line, ok_answer, unavailable

HA_GIANG, QUAN_BA, YEN_MINH, DONG_VAN = (
    (22.8233, 104.9784), (23.0679, 104.9906), (23.1170, 105.1435), (23.2785, 105.3632),
)  # fmt: skip


def stop(sid: str, lat_lng: LatLng, arrival: str | None = "motorbike", day: int = 1) -> Any:
    return {
        "id": sid, "day": day, "time": None, "title": sid, "note": "",
        "lat": lat_lng[0], "lng": lat_lng[1], "arrival": arrival, "media": [],
    }  # fmt: skip


def new_route(env: Env, stops: list[Any]) -> str:
    with env.session() as s:
        body = routes.empty_draft("Hà Giang")
        body["stops"] = stops
        route = routes.create(s, "Hà Giang", body)  # queues legs.compute for every road stop
        s.commit()
        return route.id


def draft(env: Env, route_id: str) -> Draft:
    with env.session() as s:
        d = s.get(Draft, route_id)
        assert d is not None
        return d


def legs(env: Env, route_id: str) -> dict[str, Any]:
    return {lg["to"]: lg for lg in draft(env, route_id).body["legs"]}


def test_router_calls_are_at_least_one_second_apart(env: Env) -> None:
    interval = Settings().router_min_interval_seconds
    assert interval == 1.0  # the shipped default (FOSSGIS, R36)
    env.ctx.routers.throttle = Throttle(interval)
    rid = new_route(
        env, [stop("s1", HA_GIANG), stop("s2", QUAN_BA), stop("s3", YEN_MINH), stop("s4", DONG_VAN)]
    )
    assert env.run() == 3
    times = [c.at for c in env.valhalla.calls]
    assert len(times) == 3
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert all(g >= 1.0 for g in gaps), gaps
    assert [lg["status"] for lg in legs(env, rid).values()] == ["ok", "ok", "ok"]


def test_legs_get_geometry_distance_and_duration(env: Env) -> None:
    rid = new_route(env, [stop("s1", HA_GIANG), stop("s2", QUAN_BA), stop("s3", YEN_MINH)])
    before = draft(env, rid).revision
    env.run()
    got = legs(env, rid)
    assert list(got) == ["s2", "s3"]  # stop order
    leg = got["s2"]
    straight = geo.haversine_m(HA_GIANG, QUAN_BA)
    assert leg["status"] == "ok" and leg["source"] == "valhalla" and leg["usedProfile"] is None
    assert leg["profile"] == "motorbike"
    assert leg["distanceM"] == round(straight * 1.3) and leg["durationS"] == 600
    points = polyline.decode(leg["path"])
    assert 2 < len(points) <= 21 and points[0] == pytest.approx(HA_GIANG, abs=1e-6)
    assert draft(env, rid).revision == before + 2  # one bump per written leg (If-Match)
    assert [c.profile for c in env.valhalla.calls] == ["motorbike", "motorbike"]
    assert {j.status for j in env.jobs("legs.compute")} == {"done"}


def test_motorbike_without_route_is_asked_again_as_car(env: Env) -> None:
    def answer(a: LatLng, b: LatLng, profile: str) -> Answer:
        return (
            Answer("no_route", "valhalla")
            if profile == "motorbike"
            else ok_answer("valhalla", a, b)
        )

    env.valhalla.answer = answer
    rid = new_route(env, [stop("s1", HA_GIANG), stop("s2", QUAN_BA, arrival=None)])  # not set
    env.run()
    leg = legs(env, rid)["s2"]
    assert (leg["status"], leg["profile"], leg["usedProfile"]) == ("ok", "motorbike", "car")
    assert [c.profile for c in env.valhalla.calls] == ["motorbike", "car"]


def test_both_profiles_without_route_stay_straight(env: Env) -> None:
    env.valhalla.answer = lambda a, b, p: Answer("no_route", "valhalla")
    rid = new_route(env, [stop("s1", HA_GIANG), stop("s2", QUAN_BA)])
    env.run()
    leg = legs(env, rid)["s2"]
    assert (leg["status"], leg["usedProfile"], leg["path"], leg["distanceM"]) == (
        "no_route", "car", "", 0,
    )  # fmt: skip


def test_car_leg_falls_back_to_osrm_when_valhalla_is_down(env: Env) -> None:
    env.valhalla.answer = unavailable
    rid = new_route(env, [stop("s1", HA_GIANG), stop("s2", QUAN_BA, arrival="car")])
    env.run()
    leg = legs(env, rid)["s2"]
    assert (leg["status"], leg["source"], leg["profile"]) == ("ok", "osrm", "car")
    assert [c.profile for c in env.osrm.calls] == ["car"]


def test_motorbike_leg_is_retried_with_backoff_when_valhalla_is_down(env: Env) -> None:
    env.valhalla.answer = unavailable
    rid = new_route(env, [stop("s1", HA_GIANG), stop("s2", QUAN_BA)])
    env.run()
    (job,) = env.jobs("legs.compute")
    assert (job.status, job.attempts) == ("queued", 1)
    assert job.run_at == env.clock() + timedelta(seconds=30)
    assert "HTTP 503" in (job.error or "")
    assert env.osrm.calls == []  # OSRM is car only
    env.clock.advance(seconds=30)
    env.run()
    env.clock.advance(seconds=60)
    env.run()
    (job,) = env.jobs("legs.compute")
    assert (job.status, job.attempts) == ("failed", 3)
    assert "legs" not in draft(env, rid).body or legs(env, rid) == {}


def test_off_road_stop_and_long_detour_are_too_far(env: Env) -> None:
    far = (HA_GIANG[0] + 0.01, HA_GIANG[1])  # the road starts ~1.1 km from the stop

    def answer(a: LatLng, b: LatLng, profile: str) -> Answer:
        if a == HA_GIANG:
            return Answer("ok", "valhalla", line(far, b), 30_000, 2000)
        return ok_answer("valhalla", a, b, factor=6)  # 6× the straight line

    env.valhalla.answer = answer
    rid = new_route(env, [stop("s1", HA_GIANG), stop("s2", QUAN_BA), stop("s3", YEN_MINH)])
    env.run()
    got = legs(env, rid)
    assert [got[s]["status"] for s in ("s2", "s3")] == ["too_far", "too_far"]
    assert got["s2"]["path"] == "" and got["s2"]["durationS"] == 0


def test_moved_stop_drops_the_stale_answer(env: Env) -> None:
    rid = new_route(env, [stop("s1", HA_GIANG), stop("s2", QUAN_BA)])

    def answer(a: LatLng, b: LatLng, profile: str) -> Answer:
        with env.session() as s:  # the admin moves s2 while the router is asked
            d = s.get(Draft, rid)
            assert d is not None
            body = json.loads(json.dumps(d.body))
            body["stops"][1]["lat"] = 23.1
            d.body, d.revision = body, d.revision + 1
            s.commit()
        return ok_answer("valhalla", a, b)

    env.valhalla.answer = answer
    with env.session() as s:
        job = worker.claim(s, env.settings, env.clock())
    assert job is not None
    worker.execute(env.ctx, job)
    (done,) = env.jobs("legs.compute")
    assert done.status == "done" and done.result == {"skipped": "stop_changed"}
    assert "legs" not in draft(env, rid).body or legs(env, rid) == {}


def test_throttle_waits_out_the_interval() -> None:
    now = [100.0]
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    t = Throttle(1.0, clock=lambda: now[0], sleep=sleep)
    t.wait()
    now[0] += 0.25
    t.wait()
    now[0] += 3
    t.wait()
    assert slept == [0.75]


# --- adapters: httpx MockTransport, no network ---


def test_valhalla_request_and_answer() -> None:
    seen: list[httpx.Request] = []
    shape = polyline.encode([HA_GIANG, QUAN_BA])

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = {"trip": {"legs": [{"shape": shape}], "summary": {"length": 27.257, "time": 2869}}}
        return httpx.Response(200, json=body)

    v = ValhallaRouter("https://v.test/route", "UA/1", 5, transport=httpx.MockTransport(handler))
    ans = v.route(HA_GIANG, QUAN_BA, "motorbike")
    assert ans == Answer("ok", "valhalla", [HA_GIANG, QUAN_BA], 27257.0, 2869.0)
    sent = json.loads(seen[0].content)
    assert sent == {
        "locations": [{"lat": 22.8233, "lon": 104.9784}, {"lat": 23.0679, "lon": 104.9906}],
        "costing": "motor_scooter",
        "units": "kilometers",
    }  # only the two stops and the costing (R36)
    assert seen[0].headers["User-Agent"] == "UA/1"


def test_valhalla_no_route_and_unavailable() -> None:
    answers = iter([
        httpx.Response(400, json={"error_code": 442, "error": "No path could be found"}),
        httpx.Response(503, text="busy"),
        httpx.Response(200, json={"oops": 1}),
    ])  # fmt: skip
    v = ValhallaRouter(
        "https://v.test/route", "UA", 5, httpx.MockTransport(lambda r: next(answers))
    )
    assert v.route(HA_GIANG, QUAN_BA, "car").status == "no_route"
    for _ in range(2):
        with pytest.raises(RouterUnavailable):
            v.route(HA_GIANG, QUAN_BA, "car")


def test_osrm_is_car_only_and_converted() -> None:
    urls: list[str] = []
    geometry = polyline.encode([HA_GIANG, QUAN_BA])

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if "105.0" in str(request.url):
            return httpx.Response(400, json={"code": "NoRoute"})
        route = {"geometry": geometry, "distance": 27000.5, "duration": 2400.0}
        return httpx.Response(200, json={"code": "Ok", "routes": [route]})

    o = OsrmRouter("https://o.test/route/v1/driving/", "UA", 5, httpx.MockTransport(handler))
    assert not o.supports("motorbike") and o.supports("car")
    ans = o.route(HA_GIANG, QUAN_BA, "car")
    assert ans == Answer("ok", "osrm", [HA_GIANG, QUAN_BA], 27000.5, 2400.0)
    assert urls[0].startswith("https://o.test/route/v1/driving/104.9784,22.8233;104.9906,23.0679?")
    assert o.route(HA_GIANG, (23.0, 105.0), "car").status == "no_route"
    with pytest.raises(RouterUnavailable):
        o.route(HA_GIANG, QUAN_BA, "motorbike")


def test_routers_send_car_to_osrm_only_when_valhalla_is_unavailable() -> None:
    from tests.jobs.conftest import FakeRouter

    v, o = FakeRouter(answer=unavailable), FakeRouter(id="osrm", profiles=("car",))
    r = Routers(v, o, Throttle(0))
    assert r.route(HA_GIANG, QUAN_BA, "car").source == "osrm"
    with pytest.raises(RouterUnavailable):
        r.route(HA_GIANG, QUAN_BA, "walk")


@pytest.mark.skipif(not os.environ.get("LUTRINH_LIVE_ROUTER"), reason="LUTRINH_LIVE_ROUTER=1")
def test_live_valhalla_and_osrm_smoke() -> None:
    """Optional: one real request to each FOSSGIS router (Hà Giang → Quản Bạ)."""
    from lutrinh.adapters import routing

    s = Settings()
    r = routing.from_settings(s)
    moto = r.ask(r.primary, HA_GIANG, QUAN_BA, "motorbike")
    assert moto.status == "ok" and 20_000 < moto.distance_m < 60_000, moto.distance_m
    assert r.car_fallback is not None
    car = r.ask(r.car_fallback, HA_GIANG, QUAN_BA, "car")
    assert car.status == "ok" and 20_000 < car.distance_m < 60_000, car.distance_m
