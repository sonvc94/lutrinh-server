"""What the public API answers (page 03 "Công khai /api/v1"; Mate decisions server-public-api).

* ``issue_token``: random ``tk_…`` token, stored in ``download_tokens``, valid 2 hours, tied to
  one code + one version (the version previewed, even if a newer one is published meanwhile).
* ``open_token``: unknown or expired token → 401 ``token_expired``; the code or route stopped
  being shared since → the lookup's 410 (``code_revoked`` / ``code_expired`` /
  ``route_unpublished``).
* ``summary``: the preview of page 03 (counts, size, region, overview polyline6, cover URL).
* ``check_updates``: per downloaded link ``current`` | ``newer`` (+ changes) | ``unpublished`` |
  ``revoked`` | ``expired``; an unknown code or a route id that does not match → ``unpublished``.
* ``accepted_format``: the ``v=N`` of ``Accept: application/vnd.lutrinh.route+json;v=N``; a
  package newer than N → 406 ``format_unsupported``. No such Accept → no limit.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from lutrinh.config import Settings
from lutrinh.core import canonical_json, codes, geo, package, polyline
from lutrinh.db.models import DownloadToken, RouteVersion
from lutrinh.services import codes as code_service
from lutrinh.services.errors import ServiceError

ROUTE_MEDIA_TYPE = "application/vnd.lutrinh.route+json"
FORMAT_VERSIONS = [package.FORMAT_VERSION]
MAX_UPDATE_LINKS = 50


def accepted_format(accept: str | None) -> int | None:
    """Highest ``v`` the client accepts for the route media type; None = no limit."""
    best: int | None = None
    for part in (accept or "").split(","):
        fields = [f.strip() for f in part.split(";")]
        if fields[0].lower() != ROUTE_MEDIA_TYPE:
            continue
        for param in fields[1:]:
            name, _, value = param.partition("=")
            if name.strip().lower() == "v" and value.strip().isdigit():
                v = int(value.strip())
                best = v if best is None else max(best, v)
    return best


def check_format(document: dict[str, Any], accepted: int | None) -> None:
    if accepted is not None and int(document["formatVersion"]) > accepted:
        raise ServiceError(406, "format_unsupported", f"formatVersion {document['formatVersion']}")


def issue_token(
    session: Session,
    settings: Settings,
    found: code_service.Lookup,
    now: datetime,
) -> DownloadToken:
    version = found.version
    row = DownloadToken(
        token="tk_" + secrets.token_urlsafe(32),
        code=found.code.code,
        route_id=version.route_id,
        version=version.version,
        created_at=now,
        expires_at=now + timedelta(hours=settings.token_hours),
        media_limit=version.media_files * settings.media_requests_per_file,
        media_used=0,
    )
    session.add(row)
    session.flush()
    return row


@dataclass(frozen=True)
class Opened:
    token: DownloadToken
    version: RouteVersion


def open_token(session: Session, token: str, now: datetime) -> Opened:
    row = session.get(DownloadToken, token)
    if row is None or row.expires_at <= now:
        raise ServiceError(401, "token_expired")
    code_service.lookup(session, row.code, now=now)  # raises the 410s
    version = session.get(RouteVersion, (row.route_id, row.version))
    if version is None:
        raise ServiceError(410, "route_unpublished", codes.display(row.code))
    return Opened(row, version)


def _overview(doc: dict[str, Any], tolerance_m: float) -> str:
    """The whole route as one simplified polyline6: ok leg paths, else straight to the stop."""
    legs = {leg["to"]: leg for leg in doc["legs"]}
    points: list[tuple[float, float]] = []
    for stop in doc["stops"]:
        leg = legs.get(stop["id"])
        if points and leg is not None and leg["status"] == "ok" and leg["path"]:
            points.extend(polyline.decode(leg["path"]))
        points.append((stop["lat"], stop["lng"]))
    return polyline.encode(geo.simplify(points, tolerance_m))


def media_url(token: str, sha256: str, *, width: int | None = None) -> str:
    url = f"/api/v1/dl/{token}/media/{sha256}"
    return f"{url}?w={width}" if width else url


def summary(found: code_service.Lookup, token: DownloadToken, settings: Settings) -> dict[str, Any]:
    doc = canonical_json.loads(found.version.route_json)
    route = doc["route"]
    media = {m["id"]: m for m in doc["media"]}
    cover = media.get(route["cover"]) if route.get("cover") else None
    distance = sum(leg["distanceM"] or 0 for leg in doc["legs"])
    return {
        "code": codes.display(found.code.code),
        "routeId": route["id"],
        "version": route["version"],
        "formatVersion": doc["formatVersion"],
        "title": route["title"],
        "description": route["description"],
        "days": route["days"],
        "stops": len(doc["stops"]),
        "distanceM": round(distance),
        "photos": sum(1 for m in doc["media"] if m["type"] == "photo"),
        "videos": sum(1 for m in doc["media"] if m["type"] == "video"),
        "bytes": doc["size"]["media"],
        "files": doc["size"]["files"],
        "region": route["region"],
        "overview": _overview(doc, settings.overview_tolerance_m),
        "cover": media_url(token.token, cover["sha256"], width=640) if cover else None,
        "downloadToken": token.token,
        "tokenExpiresAt": package.format_timestamp(token.expires_at),
    }


def changes(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """What the app would download: stops added/removed/edited, media files added + bytes."""
    old_stops = {s["id"]: s for s in old["stops"]} if old else {}
    old_legs = {leg["to"]: leg for leg in old["legs"]} if old else {}
    new_legs = {leg["to"]: leg for leg in new["legs"]}
    new_ids = [s["id"] for s in new["stops"]]
    edited = sum(
        1
        for s in new["stops"]
        if s["id"] in old_stops
        and (s != old_stops[s["id"]] or new_legs.get(s["id"]) != old_legs.get(s["id"]))
    )
    have = {m["sha256"] for m in old["media"]} if old else set()
    added: dict[str, int] = {}
    for m in new["media"]:
        if m["sha256"] not in have:
            added[m["sha256"]] = m["bytes"]
    return {
        "stopsAdded": [i for i in new_ids if i not in old_stops],
        "stopsRemoved": [i for i in old_stops if i not in set(new_ids)],
        "stopsEdited": edited,
        "mediaAdded": len(added),
        "bytes": sum(added.values()),
    }


_STATUS = {
    "code_revoked": "revoked",
    "code_expired": "expired",
}


def check_update(
    session: Session, code: str, route_id: str, version: int, now: datetime
) -> dict[str, Any]:
    out: dict[str, Any] = {"code": code, "routeId": route_id}
    try:
        found = code_service.lookup(session, code, now=now)
    except ServiceError as exc:
        return out | {"status": _STATUS.get(exc.code, "unpublished")}
    latest = found.version
    if latest.route_id != route_id:
        return out | {"status": "unpublished"}
    if latest.version <= version:
        return out | {"status": "current", "version": latest.version}
    mine = session.get(RouteVersion, (route_id, version))
    old = canonical_json.loads(mine.route_json) if mine is not None else None
    return out | {
        "status": "newer",
        "version": latest.version,
        "publishedAt": package.format_timestamp(latest.published_at),
        "note": latest.note,
        "changes": changes(old, canonical_json.loads(latest.route_json)),
    }
