"""The error envelope (page 03 "Bảng lỗi"): ``{"error": {"code", "retryAfterS", …}}``.

Every error the app answers with has this shape, including validation (422
``invalid_request``), unknown paths (404 ``not_found``) and wrong methods (405
``method_not_allowed``).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from lutrinh.core.package import Problem
from lutrinh.services.auth import AuthError
from lutrinh.services.errors import ServiceError
from lutrinh.services.publishing import PublishError

_PUBLISH_STATUS = {
    "route_not_found": 404,
    "version_not_found": 404,
    "route_deleted": 409,
    "no_draft": 409,
    "media_not_ready": 409,
    "not_published": 409,
    "invalid_package": 422,
    "publish_blocked": 422,
}
_HTTP_CODES = {
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "too_large",
}


def problems_json(problems: list[Problem]) -> list[dict[str, str]]:
    return [{"code": p.code, "path": p.path, "message": p.message} for p in problems]


def error_response(
    status: int,
    code: str,
    *,
    detail: str = "",
    retry_after_s: int | None = None,
    **extra: Any,
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "retryAfterS": retry_after_s}
    if detail:
        body["detail"] = detail
    body.update(extra)
    headers = {"Retry-After": str(retry_after_s)} if retry_after_s is not None else None
    return JSONResponse({"error": body}, status_code=status, headers=headers)


async def _service(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ServiceError)
    extra = dict(exc.extra)
    retry = extra.pop("retryAfterS", None)
    return error_response(exc.status, exc.code, detail=exc.detail, retry_after_s=retry, **extra)


async def _publish(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, PublishError)
    return error_response(
        _PUBLISH_STATUS.get(exc.code, 409),
        exc.code,
        detail=str(exc),
        problems=problems_json(exc.problems),
    )


async def _auth(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AuthError)
    if exc.code == "locked":
        return error_response(429, "rate_limited", retry_after_s=exc.retry_after_s)
    return error_response(401, exc.code)


async def _validation(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    problems = [
        {
            "code": str(e.get("type", "invalid")),
            "path": "/" + "/".join(str(p) for p in e.get("loc", ())),
            "message": str(e.get("msg", "")),
        }
        for e in exc.errors()
    ]
    return error_response(422, "invalid_request", problems=problems)


async def _http(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    return error_response(exc.status_code, code)


def install(app: FastAPI) -> None:
    app.add_exception_handler(ServiceError, _service)
    app.add_exception_handler(PublishError, _publish)
    app.add_exception_handler(AuthError, _auth)
    app.add_exception_handler(RequestValidationError, _validation)
    app.add_exception_handler(StarletteHTTPException, _http)
