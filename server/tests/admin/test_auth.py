"""Auth (page 04 §G): session required everywhere, CSRF on writes, password + TOTP login."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from datetime import timedelta
from typing import Any

import pyotp
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from lutrinh.api.admin import PREFIX
from lutrinh.db.engine import make_sessionmaker
from lutrinh.db.models import AdminSession, utcnow
from lutrinh.services import auth
from tests.admin.conftest import PASSWORD, Admin

PARAMS = {
    "route_id": "rt_00000000",
    "to_stop": "s_00000000",
    "job_id": "1",
    "version": "1",
    "code": "HG4N-7KQE",
    "media_id": "m_000000000000",
    "import_id": "imp_000000000000",
    "n": "0",
}
LOGIN = ("POST", f"{PREFIX}/session")


def _walk(routes: Iterable[Any]) -> Iterator[tuple[str, set[str]]]:
    """(path, methods) of every endpoint in ``app.routes``. FastAPI ≥ 0.16x keeps an included
    router as one entry whose ``effective_route_contexts()`` yields its routes with the full
    path; older versions flatten them into ``APIRoute`` entries."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route.path, set(route.methods)
        elif hasattr(route, "effective_route_contexts"):
            for ctx in route.effective_route_contexts():
                if isinstance(ctx.original_route, APIRoute):
                    yield ctx.path, set(ctx.original_route.methods)


def _admin_endpoints(admin: Admin) -> list[tuple[str, str]]:
    out = []
    for path, methods in _walk(admin.app.routes):
        if path.startswith(PREFIX):
            filled = re.sub(r"\{(\w+)\}", lambda m: PARAMS[m.group(1)], path)
            out.extend((method, filled) for method in sorted(methods))
    return out


def _login(c: TestClient, code: str, password: str = PASSWORD) -> int:
    return c.post(f"{PREFIX}/session", json={"password": password, "code": code}).status_code


def test_every_admin_route_answers_401_without_a_session(admin: Admin, anon: TestClient) -> None:
    endpoints = [e for e in _admin_endpoints(admin) if e != LOGIN]
    assert len(endpoints) >= 30
    for method, path in endpoints:
        r = anon.request(method, path, json={})
        assert r.status_code == 401, (method, path, r.status_code, r.text)
        assert r.json() == {
            "error": {"code": "unauthenticated", "retryAfterS": None, "detail": "log in first"}
        }


def test_every_write_without_csrf_token_answers_403(admin: Admin, client: TestClient) -> None:
    token = client.headers.pop("X-CSRF-Token")
    writes = [(m, p) for m, p in _admin_endpoints(admin) if m != "GET" and (m, p) != LOGIN]
    assert len(writes) >= 20
    for method, path in writes:
        r = client.request(method, path, json={})
        assert r.status_code == 403, (method, path, r.status_code, r.text)
        assert r.json()["error"]["code"] == "csrf_failed"
    r = client.post(f"{PREFIX}/routes", json={}, headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403
    r = client.post(f"{PREFIX}/routes", json={}, headers={"X-CSRF-Token": token})
    assert r.status_code == 201


def test_login_with_password_and_totp_sets_a_host_cookie(admin: Admin, anon: TestClient) -> None:
    assert anon.get(f"{PREFIX}/session").status_code == 401
    r = anon.post(f"{PREFIX}/session", json={"password": PASSWORD, "code": admin.totp.now()})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("__Host-lt_session=")
    for flag in ("HttpOnly", "Path=/", "SameSite=strict", "Secure", "Max-Age=43200"):
        assert flag in cookie
    assert "Domain" not in cookie
    session = anon.get(f"{PREFIX}/session")
    assert session.status_code == 200
    assert session.json()["csrfToken"] == r.json()["csrfToken"]


def test_login_with_a_wrong_totp_fails(admin: Admin, anon: TestClient) -> None:
    wrong = f"{(int(admin.totp.now()) + 1) % 1_000_000:06d}"
    r = anon.post(f"{PREFIX}/session", json={"password": PASSWORD, "code": wrong})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "bad_credentials"
    assert "set-cookie" not in r.headers
    assert anon.get(f"{PREFIX}/session").status_code == 401


def test_login_with_a_wrong_password_and_a_valid_totp_fails(admin: Admin, anon: TestClient) -> None:
    assert _login(anon, admin.totp.now(), password="sai-mat-khau-roi-nhe") == 401


def test_a_totp_code_is_accepted_once(admin: Admin, anon: TestClient) -> None:
    code = admin.totp.now()
    assert _login(anon, code) == 200
    assert _login(anon, code) == 401


def test_a_backup_code_replaces_the_totp_once(admin: Admin, anon: TestClient) -> None:
    code = admin.backup_codes[0]
    assert _login(anon, code.lower().replace("-", " ")) == 200
    assert _login(anon, code) == 401
    assert _login(anon, admin.backup_codes[1]) == 200


def test_five_failures_lock_the_login_and_send_a_mail(admin: Admin, anon: TestClient) -> None:
    for _ in range(5):
        assert _login(anon, "000000", password="sai-mat-khau-roi-nhe") == 401
    r = anon.post(f"{PREFIX}/session", json={"password": PASSWORD, "code": admin.totp.now()})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert 0 < int(r.headers["Retry-After"]) <= 15 * 60
    assert len(admin.mailer.sent) == 1


def test_logout_ends_the_session(admin: Admin, client: TestClient) -> None:
    assert client.delete(f"{PREFIX}/session").status_code == 204
    assert client.get(f"{PREFIX}/session").status_code == 401


def test_idle_and_absolute_expiry(admin: Admin) -> None:
    factory = make_sessionmaker(admin.app.state.engine)
    with factory() as db:
        now = utcnow()
        new = auth.login(db, admin.settings, admin.mailer, PASSWORD, admin.totp.now(), now=now)
        db.commit()
        later = now + timedelta(hours=1, minutes=59)
        assert auth.current(db, admin.settings, new.token, now=later) is not None
        idle = later + timedelta(hours=2)
        assert auth.current(db, admin.settings, new.token, now=idle) is None
        assert db.get(AdminSession, new.row.id) is None

        step = admin.totp.timecode(now) + 2
        new = auth.login(
            db,
            admin.settings,
            admin.mailer,
            PASSWORD,
            admin.totp.generate_otp(step),
            now=now + timedelta(seconds=60),
        )
        db.commit()
        t = now
        for _ in range(7):  # active every 1 h 50 min: the 12 h limit still ends it
            t += timedelta(hours=1, minutes=50)
            alive = auth.current(db, admin.settings, new.token, now=t)
        assert alive is None


def test_admin_reset_replaces_totp_and_ends_sessions(admin: Admin, client: TestClient) -> None:
    factory = make_sessionmaker(admin.app.state.engine)
    with factory() as db:
        enrolment = auth.enrol(db, admin.settings, PASSWORD + "-moi", reset=True)
        db.commit()
    assert client.get(f"{PREFIX}/session").status_code == 401
    assert _login(client, admin.totp.now()) == 401
    new = pyotp.TOTP(enrolment.totp_secret)
    assert _login(client, new.now(), password=PASSWORD + "-moi") == 200
