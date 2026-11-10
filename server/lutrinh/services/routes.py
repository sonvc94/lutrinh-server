"""Routes and their drafts (page 03 admin API, page 04 B–D).

* A route is created with an empty draft (revision 1). Every draft write bumps the revision;
  ``PUT draft`` needs ``If-Match: "r<revision>"`` (428 without it, 412 when another tab wrote
  first).
* Status: ``trash`` (deleted_at), ``unpublished`` (unpublished_at), ``shared`` (has a version),
  else ``draft``. ``draftChanged``: the draft differs from what the latest version was built from.
* Road legs: when a draft write adds a road stop without a leg, or moves a leg's end points or
  changes its profile without sending a new line, the stale line is dropped and a
  ``legs.compute`` job is queued (the worker, a later task, writes the line back).
* Trash: ``trash`` / ``restore``; ``purge`` (only from the trash, Mate decision 7A) retires the
  route's codes, deletes its rows and queues ``purge.trash`` for the files.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from lutrinh.core import geo, ids, polyline, rules
from lutrinh.db.models import Code, Draft, Job, Media, Route, RouteVersion, utcnow
from lutrinh.services import codes as code_service
from lutrinh.services import jobs
from lutrinh.services.errors import ServiceError, not_found

STATUSES = ("draft", "shared", "unpublished", "trash")


def empty_draft(title: str) -> dict[str, Any]:
    return {
        "title": title,
        "description": "",
        "days": 1,
        "cover": None,
        "readyMade": None,
        "credits": [],
        "stops": [],
        "legs": [],
    }


def etag(revision: int) -> str:
    return f'"r{revision}"'


def get(session: Session, route_id: str) -> Route:
    route = session.get(Route, route_id)
    if route is None:
        raise not_found("route", route_id)
    return route


def _live(session: Session, route_id: str) -> Route:
    route = get(session, route_id)
    if route.deleted_at is not None:
        raise ServiceError(409, "route_deleted", route_id)
    return route


def get_draft(session: Session, route_id: str) -> Draft:
    get(session, route_id)
    draft = session.get(Draft, route_id)
    if draft is None:
        raise not_found("draft", route_id)
    return draft


def create(session: Session, title: str, body: dict[str, Any] | None = None) -> Route:
    """New route with a draft (empty, or ``body`` from an import). Caller commits."""
    route = Route(id=ids.new_route_id())
    route.draft = Draft(body=body if body is not None else empty_draft(title), revision=1)
    session.add(route)
    session.flush()
    if body is not None:
        queue_legs(session, route.id, missing_legs(body))
    return route


@dataclass(frozen=True)
class Summary:
    route: Route
    title: str
    status: str
    latest_version: int | None
    published_at: datetime | None
    draft_changed: bool
    code: str | None
    stops: int


def status_of(route: Route, latest_version: int | None) -> str:
    if route.deleted_at is not None:
        return "trash"
    if route.unpublished_at is not None:
        return "unpublished"
    return "shared" if latest_version else "draft"


def summarise(session: Session, route: Route) -> Summary:
    latest = session.scalar(
        select(RouteVersion)
        .where(RouteVersion.route_id == route.id)
        .order_by(RouteVersion.version.desc())
        .limit(1)
    )
    body = route.draft.body if route.draft is not None else {}
    revision = route.draft.revision if route.draft is not None else None
    live = code_service.live_code(session, route.id)
    return Summary(
        route=route,
        title=str(body.get("title") or ""),
        status=status_of(route, latest.version if latest else None),
        latest_version=latest.version if latest else None,
        published_at=latest.published_at if latest else None,
        draft_changed=latest is None or route.published_revision != revision,
        code=live.code if live else None,
        stops=len(body.get("stops") or []),
    )


def list_routes(
    session: Session, *, status: str | None = None, q: str | None = None
) -> list[Summary]:
    if status is not None and status not in STATUSES:
        raise ServiceError(422, "invalid_request", f"status must be one of {', '.join(STATUSES)}")
    rows = session.scalars(select(Route).order_by(Route.updated_at.desc())).all()
    needle = (q or "").strip().casefold()
    out = []
    for route in rows:
        s = summarise(session, route)
        if status is not None and s.status != status:
            continue
        if needle and needle not in s.title.casefold() and needle not in route.id:
            code = s.code or ""
            if needle.replace("-", "").upper() not in code:
                continue
        out.append(s)
    return out


def _leg_key(body: dict[str, Any], index: int) -> tuple[Any, ...] | None:
    """What a road leg into stop ``index`` depends on; None = no road leg."""
    stops = body.get("stops") or []
    if index == 0:
        return None
    profile = rules.road_profile(stops[index].get("arrival"))
    if profile is None:
        return None
    a, b = stops[index - 1], stops[index]
    return (a.get("id"), a.get("lat"), a.get("lng"), b.get("lat"), b.get("lng"), profile)


def _keys(body: dict[str, Any]) -> dict[str, tuple[Any, ...]]:
    stops = body.get("stops") or []
    out = {}
    for i, stop in enumerate(stops):
        key = _leg_key(body, i)
        if key is not None:
            out[str(stop.get("id"))] = key
    return out


def leg_inputs(body: dict[str, Any], to_stop: str) -> tuple[Any, ...] | None:
    """What the road leg into ``to_stop`` depends on (``legs.compute``); None = no road leg.

    ``(previous stop id, its lat, lng, this stop's lat, lng, profile)``."""
    for i, stop in enumerate(body.get("stops") or []):
        if stop.get("id") == to_stop:
            return _leg_key(body, i)
    return None


def missing_legs(body: dict[str, Any]) -> list[str]:
    """Road stops that have no leg."""
    have = {leg.get("to") for leg in body.get("legs") or []}
    return [to for to in _keys(body) if to not in have]


def reconcile_legs(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Drop stale lines from ``new`` (in place); returns the stops whose leg must be computed."""
    old_keys, new_keys = _keys(old), _keys(new)
    old_legs = {leg.get("to"): leg for leg in old.get("legs") or []}
    kept, compute = [], []
    for leg in new.get("legs") or []:
        to = leg.get("to")
        stale = (
            to in new_keys
            and to in old_keys
            and old_keys[to] != new_keys[to]
            and old_legs.get(to) == leg  # the client did not send a new line
        )
        if stale:
            compute.append(to)
        else:
            kept.append(leg)
    new["legs"] = kept
    have = {leg.get("to") for leg in kept}
    for to, key in new_keys.items():
        if to not in have and to not in compute and old_keys.get(to) != key:
            compute.append(to)
    return compute


def queue_legs(session: Session, route_id: str, stops: list[str]) -> list[Job]:
    return [
        jobs.enqueue(session, "legs.compute", {"routeId": route_id, "toStop": s}, dedupe=True)
        for s in stops
    ]


def check_if_match(draft: Draft, if_match: str | None) -> None:
    if if_match is None:
        raise ServiceError(428, "precondition_required", "If-Match is required")
    if if_match.strip() != etag(draft.revision):
        raise ServiceError(412, "draft_changed", etag(draft.revision), revision=draft.revision)


@dataclass(frozen=True)
class DraftWrite:
    draft: Draft
    jobs: list[Job]


def put_draft(
    session: Session, route_id: str, body: dict[str, Any], if_match: str | None
) -> DraftWrite:
    _live(session, route_id)
    draft = get_draft(session, route_id)
    check_if_match(draft, if_match)
    new = dict(body)
    compute = reconcile_legs(draft.body, new)
    draft.body = new
    draft.revision += 1
    session.flush()
    return DraftWrite(draft, queue_legs(session, route_id, compute))


def _road_stop(body: dict[str, Any], to_stop: str) -> tuple[int, str]:
    stops = body.get("stops") or []
    for i, stop in enumerate(stops):
        if stop.get("id") == to_stop:
            key = _leg_key(body, i)
            if key is None:
                raise ServiceError(422, "not_a_road_leg", to_stop)
            return i, str(key[-1])
    raise not_found("stop", to_stop)


def compute_leg(session: Session, route_id: str, to_stop: str) -> Job:
    _live(session, route_id)
    draft = get_draft(session, route_id)
    _road_stop(draft.body, to_stop)
    return jobs.enqueue(
        session, "legs.compute", {"routeId": route_id, "toStop": to_stop}, dedupe=True
    )


def put_manual_leg(
    session: Session,
    route_id: str,
    to_stop: str,
    *,
    path: str,
    duration_s: float | None,
    if_match: str | None,
) -> Draft:
    """A line drawn by hand (page 04 C "vẽ tay"); distance from the line."""
    _live(session, route_id)
    draft = get_draft(session, route_id)
    if if_match is not None:
        check_if_match(draft, if_match)
    _, profile = _road_stop(draft.body, to_stop)
    try:
        points = polyline.decode(path)
    except ValueError as exc:
        raise ServiceError(422, "invalid_request", f"path: {exc}") from exc
    if len(points) < 2:
        raise ServiceError(422, "invalid_request", "path needs at least 2 points")
    leg = {
        "to": to_stop,
        "profile": profile,
        "usedProfile": None,
        "source": "manual",
        "status": "ok",
        "distanceM": round(geo.length_m(points)),
        "durationS": round(duration_s or 0),
        "path": polyline.encode(points),
    }
    body = dict(draft.body)
    body["legs"] = [lg for lg in body.get("legs") or [] if lg.get("to") != to_stop] + [leg]
    draft.body = body
    draft.revision += 1
    session.flush()
    return draft


def trash(session: Session, route_id: str, *, now: datetime | None = None) -> Route:
    route = get(session, route_id)
    if route.deleted_at is None:
        route.deleted_at = now or utcnow()
    session.flush()
    return route


def restore(session: Session, route_id: str) -> Route:
    route = get(session, route_id)
    if route.deleted_at is None:
        raise ServiceError(409, "not_in_trash", route_id)
    route.deleted_at = None
    session.flush()
    return route


def purge(session: Session, route_id: str, *, now: datetime | None = None) -> Job:
    """Delete a trashed route for good. Files are left to the ``purge.trash`` job."""
    route = get(session, route_id)
    if route.deleted_at is None:
        raise ServiceError(409, "not_in_trash", "move the route to the trash first")
    media_ids = list(session.scalars(select(Media.id).where(Media.route_id == route_id)))
    code_service.retire_route_codes(session, route_id, now=now)
    session.execute(delete(Code).where(Code.route_id == route_id))
    session.execute(delete(Route).where(Route.id == route_id))
    return jobs.enqueue(session, "purge.trash", {"routeId": route_id, "mediaIds": media_ids})
