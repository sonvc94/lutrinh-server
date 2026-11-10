"""OSRM (FOSSGIS ``routed-car``): car only, the fallback when Valhalla is unavailable (R36).
The only module that knows OSRM's API."""

from __future__ import annotations

import httpx

from lutrinh.adapters.routing import Answer, LatLng, RouterUnavailable
from lutrinh.core import polyline


class OsrmRouter:
    id = "osrm"

    def __init__(
        self,
        url: str,
        user_agent: str,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self._client = httpx.Client(
            headers={"User-Agent": user_agent}, timeout=timeout, transport=transport
        )

    def supports(self, profile: str) -> bool:
        return profile == "car"

    def request_url(self, a: LatLng, b: LatLng) -> str:
        return f"{self.url}/{a[1]},{a[0]};{b[1]},{b[0]}"

    def route(self, a: LatLng, b: LatLng, profile: str) -> Answer:
        if profile != "car":
            raise RouterUnavailable(f"osrm: profile {profile} not served")
        params = {"overview": "full", "geometries": "polyline6", "steps": "false"}
        try:
            r = self._client.get(self.request_url(a, b), params=params)
        except httpx.HTTPError as exc:
            raise RouterUnavailable(f"osrm: {exc}") from exc
        try:
            body = r.json()
        except ValueError as exc:
            raise RouterUnavailable(f"osrm: HTTP {r.status_code}, not JSON") from exc
        if body.get("code") in ("NoRoute", "NoSegment"):
            return Answer("no_route", self.id)
        if r.status_code != 200 or body.get("code") != "Ok":
            raise RouterUnavailable(f"osrm: HTTP {r.status_code} {body.get('code')}")
        try:
            best = body["routes"][0]
            return Answer(
                "ok",
                self.id,
                polyline.decode(best["geometry"]),
                distance_m=float(best["distance"]),
                duration_s=float(best["duration"]),
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RouterUnavailable(f"osrm: unreadable answer ({exc})") from exc
