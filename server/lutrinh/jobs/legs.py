"""``legs.compute`` (page 06 §3, the app's R36): the road line of one leg, stored in the draft.

The router sees the two stop positions and the profile only. A motorbike leg without a route is
asked again with the car profile and marked ``usedProfile: "car"`` ("tuyến ô tô"); car legs fall
back to OSRM when Valhalla is unavailable (``adapters.routing.Routers``). The off-road guard
keeps a leg ``too_far`` (straight in the app) when a stop is more than ``offroad_max_m`` from the
line's end or the road is more than ``offroad_max_ratio`` × the straight distance. The line is
simplified to ~``leg_simplify_m`` and stored as polyline6 with the road metres and seconds; a
leg that is not ``ok`` has an empty path and 0 m / 0 s.

The draft is written only if the leg's inputs are still the ones the router was asked about (a
moved stop has queued its own job) and with a compare-and-set on ``drafts.revision``, which is
bumped like every draft write (the admin's If-Match).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import update

from lutrinh.adapters.routing import Answer, LatLng, Routers
from lutrinh.config import Settings
from lutrinh.core import geo, polyline
from lutrinh.db.models import Draft, Route, utcnow
from lutrinh.jobs import Context, Payload, Result
from lutrinh.services import routes as route_service


def _leg(to: str, profile: str, used: str | None, answer: Answer, status: str) -> dict[str, Any]:
    return {
        "to": to,
        "profile": profile,
        "usedProfile": used,
        "source": answer.source,
        "status": status,
        "distanceM": 0,
        "durationS": 0,
        "path": "",
    }


def judge(
    settings: Settings, to: str, a: LatLng, b: LatLng, profile: str, used: str | None, ans: Answer
) -> dict[str, Any]:
    """The leg for a router answer, with the off-road guard (R36: 500 m / 5×)."""
    if ans.status != "ok" or len(ans.points) < 2:
        return _leg(to, profile, used, ans, "no_route")
    start, end = ans.points[0], ans.points[-1]
    straight = geo.haversine_m(a, b)
    off_road = max(geo.haversine_m(a, start), geo.haversine_m(b, end)) > settings.offroad_max_m
    detour = straight > 0 and ans.distance_m > settings.offroad_max_ratio * straight
    if off_road or detour:
        return _leg(to, profile, used, ans, "too_far")
    leg = _leg(to, profile, used, ans, "ok")
    leg["distanceM"] = round(ans.distance_m)
    leg["durationS"] = round(ans.duration_s)
    leg["path"] = polyline.encode(geo.simplify(ans.points, settings.leg_simplify_m))
    return leg


def road_leg(
    settings: Settings, routers: Routers, to: str, a: LatLng, b: LatLng, profile: str
) -> dict[str, Any]:
    """Ask the routers (car fallback for motorbike, R36); raises ``RouterUnavailable``."""
    answer = routers.route(a, b, profile)
    if answer.status == "no_route" and profile == "motorbike":
        return judge(settings, to, a, b, profile, "car", routers.route(a, b, "car"))
    return judge(settings, to, a, b, profile, None, answer)


def _put(body: dict[str, Any], leg: dict[str, Any]) -> list[dict[str, Any]]:
    """The draft's legs with ``leg`` replacing the one into the same stop, in stop order."""
    order = {stop.get("id"): i for i, stop in enumerate(body.get("stops") or [])}
    legs = [lg for lg in body.get("legs") or [] if lg.get("to") != leg["to"]] + [leg]
    return sorted(legs, key=lambda lg: order.get(lg.get("to"), len(order)))


def _inputs(ctx: Context, route_id: str, to: str) -> tuple[Any, ...] | str:
    with ctx.sessions() as session:
        route = session.get(Route, route_id)
        draft = session.get(Draft, route_id)
        if route is None or draft is None:
            return "route_removed"
        if route.deleted_at is not None:
            return "route_in_trash"
        key = route_service.leg_inputs(draft.body, to)
        return key if key is not None else "not_a_road_leg"


def handle(ctx: Context, payload: Payload) -> Result:
    route_id, to = str(payload["routeId"]), str(payload["toStop"])
    key = _inputs(ctx, route_id, to)
    if isinstance(key, str):
        return {"skipped": key}
    _, a_lat, a_lng, b_lat, b_lng, profile = key
    leg = road_leg(
        ctx.settings, ctx.routers, to, (float(a_lat), float(a_lng)), (float(b_lat), float(b_lng)),
        str(profile),
    )  # fmt: skip
    for _ in range(10):
        with ctx.sessions() as session:
            draft = session.get(Draft, route_id)
            route = session.get(Route, route_id)
            if draft is None or route is None or route.deleted_at is not None:
                return {"skipped": "route_removed"}
            if route_service.leg_inputs(draft.body, to) != key:
                return {"skipped": "stop_changed"}
            body = dict(draft.body)
            body["legs"] = _put(body, leg)
            written = session.execute(
                update(Draft)
                .where(Draft.route_id == route_id, Draft.revision == draft.revision)
                .values(body=body, revision=draft.revision + 1, updated_at=utcnow())
                .execution_options(synchronize_session=False)
            )
            if getattr(written, "rowcount", 0) == 1:
                session.commit()
                summary = {k: leg[k] for k in ("status", "usedProfile", "distanceM", "durationS")}
                return {"leg": summary, "revision": draft.revision + 1}
            session.rollback()
    raise RuntimeError("the draft kept changing while the leg was written")
