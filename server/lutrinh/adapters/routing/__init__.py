"""Routing adapters (page 06 §1 ``adapters/routing/``, the app's R36 ``RoutingProvider``).

A ``Router`` answers one leg: two (lat, lng) positions and a profile (``motorbike``, ``car``,
``bus``, ``walk``), nothing else is sent. ``Routers`` is the registry the worker uses: Valhalla
FOSSGIS first, OSRM ``routed-car`` as the car-only fallback when Valhalla is unavailable. The
addresses come from ``Settings`` (one place); every call passes one ``Throttle`` so requests are
at least ``router_min_interval_seconds`` apart.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from lutrinh.config import Settings

LatLng = tuple[float, float]
Status = Literal["ok", "no_route"]


@dataclass(frozen=True)
class Answer:
    """A router's answer. ``points`` (lat, lng) and the numbers are only meaningful when ok."""

    status: Status
    source: str
    points: list[LatLng] = field(default_factory=list)
    distance_m: float = 0
    duration_s: float = 0


class RouterUnavailable(Exception):
    """Network error, timeout, 5xx, 429 or an answer that cannot be read: try again later."""


class Router(Protocol):
    id: str

    def supports(self, profile: str) -> bool: ...

    def route(self, a: LatLng, b: LatLng, profile: str) -> Answer: ...


class Throttle:
    """At most one call per ``interval`` seconds (FOSSGIS usage policy, R36)."""

    def __init__(
        self,
        interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            left = self._last + self.interval - self._clock()
            if left > 0:
                self._sleep(left)
        self._last = self._clock()


@dataclass
class Routers:
    primary: Router
    car_fallback: Router | None
    throttle: Throttle

    def ask(self, router: Router, a: LatLng, b: LatLng, profile: str) -> Answer:
        self.throttle.wait()
        return router.route(a, b, profile)

    def route(self, a: LatLng, b: LatLng, profile: str) -> Answer:
        """Primary router; for ``car`` the fallback when the primary is unavailable (R36)."""
        try:
            return self.ask(self.primary, a, b, profile)
        except RouterUnavailable:
            fallback = self.car_fallback
            if profile != "car" or fallback is None or not fallback.supports("car"):
                raise
            return self.ask(fallback, a, b, "car")


def from_settings(settings: Settings) -> Routers:
    from lutrinh.adapters.routing.osrm import OsrmRouter
    from lutrinh.adapters.routing.valhalla import ValhallaRouter

    return Routers(
        primary=ValhallaRouter(
            settings.valhalla_url, settings.router_user_agent, settings.router_timeout_seconds
        ),
        car_fallback=OsrmRouter(
            settings.osrm_car_url, settings.router_user_agent, settings.router_timeout_seconds
        ),
        throttle=Throttle(settings.router_min_interval_seconds),
    )
