"""One error type for the admin services; the API turns it into the error envelope."""

from __future__ import annotations

from typing import Any


class ServiceError(Exception):
    """``status`` is the HTTP status the API answers with; ``code`` the stable error code."""

    def __init__(self, status: int, code: str, detail: str = "", **extra: Any) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.status = status
        self.code = code
        self.detail = detail
        self.extra = extra


def not_found(what: str, ident: object) -> ServiceError:
    return ServiceError(404, f"{what}_not_found", str(ident))
