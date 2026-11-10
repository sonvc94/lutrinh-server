"""Valhalla (FOSSGIS ``valhalla1.openstreetmap.de``): every profile, ``motor_scooter`` for
motorbikes because it keeps off expressways (R36). The only module that knows Valhalla's API."""

from __future__ import annotations

from typing import Any

import httpx

from lutrinh.adapters.routing import Answer, LatLng, RouterUnavailable
from lutrinh.core import polyline

COSTING = {"motorbike": "motor_scooter", "car": "auto", "bus": "bus", "walk": "pedestrian"}
# 442/443: no path between the points; 170/171: no road near a point. Both read as no route.
NO_ROUTE_CODES = frozenset({170, 171, 442, 443})


class ValhallaRouter:
    id = "valhalla"

    def __init__(
        self,
        url: str,
        user_agent: str,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = url
        self._client = httpx.Client(
            headers={"User-Agent": user_agent}, timeout=timeout, transport=transport
        )

    def supports(self, profile: str) -> bool:
        return profile in COSTING

    @staticmethod
    def request_body(a: LatLng, b: LatLng, profile: str) -> dict[str, Any]:
        return {
            "locations": [{"lat": a[0], "lon": a[1]}, {"lat": b[0], "lon": b[1]}],
            "costing": COSTING[profile],
            "units": "kilometers",
        }

    def route(self, a: LatLng, b: LatLng, profile: str) -> Answer:
        try:
            r = self._client.post(self.url, json=self.request_body(a, b, profile))
        except httpx.HTTPError as exc:
            raise RouterUnavailable(f"valhalla: {exc}") from exc
        if r.status_code == 400:
            try:
                code = r.json().get("error_code")
            except ValueError:
                code = None
            if code in NO_ROUTE_CODES:
                return Answer("no_route", self.id)
        if r.status_code != 200:
            raise RouterUnavailable(f"valhalla: HTTP {r.status_code} {r.text[:200]}")
        try:
            trip = r.json()["trip"]
            points: list[LatLng] = []
            for leg in trip["legs"]:
                points.extend(polyline.decode(leg["shape"]))
            summary = trip["summary"]
            return Answer(
                "ok",
                self.id,
                points,
                distance_m=float(summary["length"]) * 1000,
                duration_s=float(summary["time"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RouterUnavailable(f"valhalla: unreadable answer ({exc})") from exc
