"""Admin API under ``/admin/api/v1`` (page 03 "API quản trị", auth page 04 §G).

``POST /session`` is the only route without a session; every other route depends on
``require_admin`` (401 without a live session, 403 on a write without ``X-CSRF-Token``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from lutrinh.api.admin import activity, files, routes, session
from lutrinh.api.deps import require_admin

PREFIX = "/admin/api/v1"


def build_router() -> APIRouter:
    router = APIRouter(prefix=PREFIX)
    router.include_router(session.public, tags=["session"])
    protected = APIRouter(dependencies=[Depends(require_admin)])
    protected.include_router(session.router, tags=["session"])
    protected.include_router(routes.router, tags=["routes"])
    protected.include_router(files.router, tags=["files"])
    protected.include_router(activity.router, tags=["activity"])
    router.include_router(protected)
    return router
