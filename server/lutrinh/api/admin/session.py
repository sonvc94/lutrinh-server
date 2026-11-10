"""``/session``: log in (password + TOTP in one call), read, log out (page 04 §G)."""

from __future__ import annotations

from fastapi import APIRouter, Response

from lutrinh.api.admin import schemas as s
from lutrinh.api.deps import COOKIE, AdminDep, DbDep, MailerDep, SettingsDep
from lutrinh.db.models import AdminSession
from lutrinh.services import audit, auth

public = APIRouter()
router = APIRouter()


def _out(settings: SettingsDep, row: AdminSession) -> s.SessionOut:
    return s.SessionOut(
        csrf_token=row.csrf_token,
        expires_at=row.expires_at,
        idle_expires_at=auth.idle_expires_at(settings, row),
    )


@public.post("/session", response_model=s.SessionOut, summary="Log in")
def login(
    body: s.LoginIn, response: Response, db: DbDep, settings: SettingsDep, mailer: MailerDep
) -> s.SessionOut:
    new = auth.login(db, settings, mailer, body.password, body.code)
    audit.record(db, "session.login")
    db.commit()
    response.set_cookie(
        COOKIE,
        new.token,
        max_age=int(settings.session_hours * 3600),
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return _out(settings, new.row)


@router.get("/session", response_model=s.SessionOut, summary="Current session")
def read(admin: AdminDep, settings: SettingsDep) -> s.SessionOut:
    return _out(settings, admin)


@router.delete("/session", status_code=204, summary="Log out")
def logout(admin: AdminDep, db: DbDep) -> Response:
    row = db.get(AdminSession, admin.id)
    if row is not None:
        auth.logout(db, row)
    audit.record(db, "session.logout")
    db.commit()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return response
