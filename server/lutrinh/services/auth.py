"""Admin login (D-7 A, page 03 "Đăng nhập quản trị", page 04 §G).

* One account: username + password (Argon2id, at least ``settings.admin_password_min``
  characters). While ``settings.admin_totp`` is on (off during the test phase) a TOTP (6 digits,
  30 s, ±1 step for clock drift) or one of 10 single-use backup codes (10 characters) is needed
  too. Everything is checked in one call and the answer never says which part was wrong.
* An accepted TOTP step is never accepted again (replay within its 30 s window).
* 5 failures within 15 minutes lock the login for 15 minutes and send a mail.
* Sessions live in the database (logout deletes the row): 12 h absolute, 2 h idle. The cookie
  holds a random token; the table holds its sha256. A CSRF token is bound to each session.
* No password reset by mail: ``lutrinh admin reset`` on the host (page 06 §8).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from lutrinh.adapters.mail import Mailer
from lutrinh.config import Settings
from lutrinh.core.codes import ALPHABET
from lutrinh.db.models import AdminBackupCode, AdminSession, AdminUser, utcnow

BACKUP_CODES = 10
BACKUP_CODE_LENGTH = 10
TOTP_ISSUER = "Lữ Trình"
USERNAME = "admin"  # default; ``set_password`` may rename the one account


class AuthError(Exception):
    """``code``: bad_credentials, locked (``retry_after_s``), admin_exists, no_admin,
    weak_password."""

    def __init__(self, code: str, retry_after_s: int | None = None, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.retry_after_s = retry_after_s
        self.detail = detail


def hasher(settings: Settings) -> PasswordHasher:
    return PasswordHasher(
        time_cost=settings.argon2_time_cost, memory_cost=settings.argon2_memory_kib
    )


def _verify(ph: PasswordHasher, hashed: str, secret: str) -> bool:
    try:
        return ph.verify(hashed, secret)
    except (VerificationError, InvalidHashError):
        return False


def _normalise_backup(raw: str) -> str:
    return "".join(ch for ch in raw.upper() if ch not in " -\t")


@dataclass(frozen=True)
class Enrolment:
    """What ``lutrinh admin create/reset`` prints once: never stored in clear."""

    totp_secret: str
    totp_uri: str
    backup_codes: list[str]


def enrol(session: Session, settings: Settings, password: str, *, reset: bool = False) -> Enrolment:
    """Create the admin (or, with ``reset``, replace password, TOTP and backup codes and end
    every session). Caller commits."""
    _check_password(settings, password)
    admin = _the_admin(session)
    if admin is not None and not reset:
        raise AuthError("admin_exists")
    if admin is None and reset:
        raise AuthError("no_admin")
    ph = hasher(settings)
    if admin is None:
        admin = AdminUser(username=USERNAME, password_hash="", totp_secret="")
        session.add(admin)
    enrolment = _new_second_factor(ph, admin)
    _store_password(ph, admin, password)
    session.flush()
    return enrolment


def set_password(
    session: Session, settings: Settings, password: str, *, username: str = USERNAME
) -> bool:
    """Set the username and password of the one admin without touching its TOTP secret or
    backup codes (a new account gets fresh ones it never shows: ``reset`` prints them when TOTP
    goes back on). Ends every session. Returns True when the account was created. Caller
    commits."""
    _check_password(settings, password)
    if not 1 <= len(username) <= 40:
        raise AuthError("bad_username", detail="1 to 40 characters")
    admin = _the_admin(session)
    created = admin is None
    ph = hasher(settings)
    if admin is None:
        admin = AdminUser(username=username, password_hash="", totp_secret="")
        session.add(admin)
        _new_second_factor(ph, admin)
    admin.username = username
    _store_password(ph, admin, password)
    session.flush()
    return created


def _check_password(settings: Settings, password: str) -> None:
    if len(password) < settings.admin_password_min:
        raise AuthError(
            "weak_password", detail=f"at least {settings.admin_password_min} characters"
        )


def _the_admin(session: Session) -> AdminUser | None:
    return session.scalar(select(AdminUser).order_by(AdminUser.id).limit(1))


def _new_second_factor(ph: PasswordHasher, admin: AdminUser) -> Enrolment:
    secret = pyotp.random_base32()
    codes = [
        "".join(secrets.choice(ALPHABET) for _ in range(BACKUP_CODE_LENGTH))
        for _ in range(BACKUP_CODES)
    ]
    admin.totp_secret = secret
    admin.last_totp_step = None
    admin.backup_codes = [AdminBackupCode(code_hash=ph.hash(c)) for c in codes]
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=admin.username or USERNAME, issuer_name=TOTP_ISSUER
    )
    return Enrolment(secret, uri, [f"{c[:5]}-{c[5:]}" for c in codes])


def _store_password(ph: PasswordHasher, admin: AdminUser, password: str) -> None:
    admin.password_hash = ph.hash(password)
    admin.failed_count = 0
    admin.first_failed_at = None
    admin.locked_until = None
    admin.sessions = []


def _totp_step(admin: AdminUser, code: str, now: datetime) -> int | None:
    """The matching TOTP time step (±1), or None. Steps already used are refused."""
    if len(code) != 6 or not code.isdigit():
        return None
    totp = pyotp.TOTP(admin.totp_secret)
    current = totp.timecode(now)
    for step in (current - 1, current, current + 1):
        if admin.last_totp_step is not None and step <= admin.last_totp_step:
            continue
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def _backup_code(ph: PasswordHasher, admin: AdminUser, code: str) -> AdminBackupCode | None:
    normal = _normalise_backup(code)
    if len(normal) != BACKUP_CODE_LENGTH:
        return None
    for row in admin.backup_codes:
        if row.used_at is None and _verify(ph, row.code_hash, normal):
            return row
    return None


@dataclass(frozen=True)
class NewSession:
    token: str  # cookie value, shown once
    row: AdminSession


def login(
    session: Session,
    settings: Settings,
    mailer: Mailer,
    username: str,
    password: str,
    code: str = "",
    *,
    now: datetime | None = None,
) -> NewSession:
    """Check username + password (+ TOTP or a backup code while ``settings.admin_totp`` is on)
    and open a session. Commits on failure too, so the failure counter survives; the caller
    commits on success."""
    now = now or utcnow()
    admin = session.scalar(select(AdminUser).where(AdminUser.username == username))
    if admin is None:
        raise AuthError("bad_credentials")
    if admin.locked_until is not None and admin.locked_until > now:
        raise AuthError("locked", retry_after_s=_seconds(admin.locked_until - now))

    ph = hasher(settings)
    password_ok = _verify(ph, admin.password_hash, password)
    step = backup = None
    second_ok = True
    if settings.admin_totp:
        step = _totp_step(admin, code.strip(), now)
        backup = None if step is not None else _backup_code(ph, admin, code)
        second_ok = step is not None or backup is not None
    if not password_ok or not second_ok:
        _fail(session, settings, mailer, admin, now)
        raise AuthError("bad_credentials")

    admin.failed_count = 0
    admin.first_failed_at = None
    admin.locked_until = None
    if step is not None:
        admin.last_totp_step = step
    if backup is not None:
        backup.used_at = now
    if ph.check_needs_rehash(admin.password_hash):
        admin.password_hash = ph.hash(password)
    token = secrets.token_urlsafe(32)
    row = AdminSession(
        id=_token_id(token),
        admin_id=admin.id,
        csrf_token=secrets.token_urlsafe(32),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_hours),
    )
    session.add(row)
    session.flush()
    return NewSession(token, row)


def _fail(
    session: Session, settings: Settings, mailer: Mailer, admin: AdminUser, now: datetime
) -> None:
    window = timedelta(minutes=settings.login_window_minutes)
    if admin.first_failed_at is None or now - admin.first_failed_at > window:
        admin.first_failed_at = now
        admin.failed_count = 1
    else:
        admin.failed_count += 1
    if admin.failed_count >= settings.login_max_failures:
        admin.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
        admin.failed_count = 0
        admin.first_failed_at = None
        mailer.send(
            "Lữ Trình: đăng nhập quản trị bị khóa",
            f"{settings.login_max_failures} lần đăng nhập sai; khóa đến "
            f"{admin.locked_until.isoformat()} (UTC).",
        )
    session.commit()


def _seconds(delta: timedelta) -> int:
    return max(1, int(delta.total_seconds() + 0.999))


def _token_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current(
    session: Session, settings: Settings, token: str | None, *, now: datetime | None = None
) -> AdminSession | None:
    """The live session for a cookie value (touching its idle timer), or None."""
    if not token:
        return None
    now = now or utcnow()
    row = session.get(AdminSession, _token_id(token))
    if row is None:
        return None
    idle = timedelta(hours=settings.session_idle_hours)
    if row.expires_at <= now or row.last_seen_at + idle <= now:
        session.delete(row)
        session.commit()
        return None
    row.last_seen_at = now
    session.commit()
    return row


def idle_expires_at(settings: Settings, row: AdminSession) -> datetime:
    return min(row.expires_at, row.last_seen_at + timedelta(hours=settings.session_idle_hours))


def logout(session: Session, row: AdminSession) -> None:
    session.delete(row)
