"""Run the due jobs once, like ``lutrinh worker --once``, but offline: the routers answer
"unavailable" (no FOSSGIS calls from the e2e), so leg jobs just wait for a retry while media jobs
(Pillow/ffmpeg) run for real. Used by publish-flow.spec.ts; run from server/ with ``uv run``."""

from __future__ import annotations

from lutrinh.adapters.routing import Answer, Routers, RouterUnavailable, Throttle
from lutrinh.config import get_settings
from lutrinh.db.engine import make_engine, make_sessionmaker
from lutrinh.jobs import Context, worker


class Offline:
    id = "valhalla"

    def supports(self, profile: str) -> bool:
        return True

    def route(self, a: object, b: object, profile: str) -> Answer:
        raise RouterUnavailable("e2e: no network routers")


settings = get_settings()
ctx = Context(
    settings,
    make_sessionmaker(make_engine(settings.db_url)),
    Routers(Offline(), None, Throttle(0)),
)
print("jobs run:", worker.run(ctx, once=True, nightly=False))
