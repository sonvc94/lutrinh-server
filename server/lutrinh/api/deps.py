"""Request dependencies: settings, a database session, the admin session and its CSRF check.

Auth (page 04 §G): the cookie ``__Host-lt_session`` (Secure, HttpOnly, SameSite=Strict,
Path=/) carries a random token; every ``/admin/api/v1`` route except ``POST /session`` needs a
live session (401 ``unauthenticated``), and every write (any method but GET/HEAD/OPTIONS) also
needs the session's token in ``X-CSRF-Token`` (403 ``csrf_failed``).
"""

from __future__ import annotations

import hmac
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from lutrinh.adapters.mail import Mailer
from lutrinh.config import Settings
from lutrinh.db.models import AdminSession
from lutrinh.services import auth
from lutrinh.services.errors import ServiceError

COOKIE = "__Host-lt_session"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_mailer(request: Request) -> Mailer:
    mailer: Mailer = request.app.state.mailer
    return mailer


def get_db(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.app.state.sessionmaker
    with factory() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]
MailerDep = Annotated[Mailer, Depends(get_mailer)]


def require_admin(request: Request, db: DbDep, settings: SettingsDep) -> AdminSession:
    row = auth.current(db, settings, request.cookies.get(COOKIE))
    if row is None:
        raise ServiceError(401, "unauthenticated", "log in first")
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not hmac.compare_digest(sent.encode(), row.csrf_token.encode()):
            raise ServiceError(403, "csrf_failed", f"{CSRF_HEADER} missing or wrong")
    return row


AdminDep = Annotated[AdminSession, Depends(require_admin)]
