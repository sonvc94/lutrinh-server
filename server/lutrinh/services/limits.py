"""Rate limits and counters of the public API (page 03 "Giới hạn tốc độ", D-14 A).

Everything lives in SQLite (page 06 §2: one Uvicorn process, counters survive a restart):

* Code lookups per IP: 30 an hour (sliding hour) → 429 + Retry-After until the oldest one is an
  hour old. Failed lookups (400 ``bad_format``/``bad_check`` and 404; a 410 is a real code and
  counts only as a lookup) per IP: the 10th in an hour locks the IP for 1 h, the next lock 4 h,
  then 24 h; the ladder starts again after 24 h without a lock. A locked IP gets 429 on every
  lookup.
* System-wide: 500 failed lookups in an hour → a mail to the admin and a per-IP failure limit
  of 3 an hour for the next 24 h.
* route.json per code per IP: 10 an hour → 429. Media requests per token: files × 3 → 429
  (``DownloadToken.media_limit``).
* Bandwidth: bytes handed out per UTC month; a mail at 70 % of the cap, 503 ``quota`` at it.
* Daily counts per route (``daily_counts``: lookup / bad_lookup / download).
* IP rows older than 14 days are deleted by the API itself while it writes (no worker yet).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from lutrinh.adapters.mail import Mailer
from lutrinh.config import Settings
from lutrinh.db.models import Alarm, DailyCount, DownloadToken, IpEvent, IpLock, MonthlyBytes
from lutrinh.services.errors import ServiceError

HOUR = timedelta(hours=1)
BAD_LOOKUPS_ALARM = "bad_lookups"


def retry_after(until: datetime, now: datetime) -> int:
    return max(1, math.ceil((until - now).total_seconds()))


def rate_limited(until: datetime, now: datetime) -> ServiceError:
    return ServiceError(429, "rate_limited", retryAfterS=retry_after(until, now))


def purge_old(session: Session, settings: Settings, now: datetime) -> None:
    """Forget IPs after ``iplog_days`` (D-14 A) and tokens a day after they expired."""
    cutoff = now - timedelta(days=settings.iplog_days)
    session.execute(delete(IpEvent).where(IpEvent.at < cutoff))
    session.execute(delete(IpLock).where(IpLock.locked_until < cutoff))
    session.execute(delete(DownloadToken).where(DownloadToken.expires_at < now - timedelta(days=1)))


def count_day(session: Session, kind: str, route_id: str | None, now: datetime) -> None:
    stmt = insert(DailyCount).values(
        day=now.date().isoformat(), route_id=route_id or "", kind=kind, count=1
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["day", "route_id", "kind"],
            set_={"count": DailyCount.count + 1},
        )
    )


def _events(
    session: Session, kind: str, now: datetime, *, ip: str | None = None, key: str | None = None
) -> tuple[int, datetime | None]:
    stmt = select(func.count(), func.min(IpEvent.at)).where(
        IpEvent.kind == kind, IpEvent.at > now - HOUR
    )
    if ip is not None:
        stmt = stmt.where(IpEvent.ip == ip)
    if key is not None:
        stmt = stmt.where(IpEvent.key == key)
    n, oldest = session.execute(stmt).one()
    if isinstance(oldest, str):  # func.min() loses the column type on SQLite
        oldest = datetime.fromisoformat(oldest)
    if oldest is not None and oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=now.tzinfo)
    return int(n), oldest


def _alarm_active(session: Session, now: datetime) -> bool:
    alarm = session.get(Alarm, BAD_LOOKUPS_ALARM)
    return alarm is not None and alarm.until > now


def check_lookup(session: Session, settings: Settings, ip: str, now: datetime) -> None:
    """Raise 429 when this IP is locked or has used its lookups for the hour."""
    lock = session.get(IpLock, ip)
    if lock is not None and lock.locked_until > now:
        raise rate_limited(lock.locked_until, now)
    n, oldest = _events(session, "lookup", now, ip=ip)
    if n >= settings.lookups_per_hour and oldest is not None:
        raise rate_limited(oldest + HOUR, now)


def _lock(session: Session, settings: Settings, ip: str, now: datetime) -> None:
    ladder = settings.lock_ladder_hours
    lock = session.get(IpLock, ip)
    reset = timedelta(hours=settings.lock_ladder_reset_hours)
    if lock is not None and lock.locked_until + reset > now:
        level = min(lock.level + 1, len(ladder))
    else:
        level = 1
    until = now + timedelta(hours=ladder[level - 1])
    if lock is None:
        session.add(IpLock(ip=ip, level=level, locked_at=now, locked_until=until))
    else:
        lock.level, lock.locked_at, lock.locked_until = level, now, until


def record_lookup(
    session: Session,
    settings: Settings,
    mailer: Mailer,
    ip: str,
    now: datetime,
    *,
    failed: bool,
    route_id: str | None,
) -> None:
    """Count one lookup (and a failure); lock the IP or raise the system alarm when due."""
    purge_old(session, settings, now)
    session.add(IpEvent(at=now, ip=ip, kind="lookup"))
    count_day(session, "bad_lookup" if failed else "lookup", route_id, now)
    if not failed:
        session.flush()
        return
    session.add(IpEvent(at=now, ip=ip, kind="bad_lookup"))
    session.flush()
    alarm = _alarm_active(session, now)
    limit = settings.alarm_bad_lookups_per_ip if alarm else settings.bad_lookups_per_hour
    failures, _ = _events(session, "bad_lookup", now, ip=ip)
    if failures >= limit:
        _lock(session, settings, ip, now)
    if not alarm:
        total, _ = _events(session, "bad_lookup", now)
        if total >= settings.alarm_bad_lookups_per_hour:
            until = now + timedelta(hours=settings.alarm_hours)
            row = session.get(Alarm, BAD_LOOKUPS_ALARM)
            if row is None:
                session.add(Alarm(name=BAD_LOOKUPS_ALARM, raised_at=now, until=until))
            else:
                row.raised_at, row.until = now, until
            mailer.send(
                "Lữ Trình: nhiều lần tra mã sai",
                f"{total} lần tra mã sai trong một giờ qua. Giới hạn mỗi IP đã siết còn "
                f"{settings.alarm_bad_lookups_per_ip} lần sai/giờ trong "
                f"{settings.alarm_hours:g} giờ.",
            )
    session.flush()


def record_route_download(
    session: Session, settings: Settings, ip: str, code: str, now: datetime
) -> None:
    """route.json per code per IP: raise 429 past the hourly limit, else count it."""
    n, oldest = _events(session, "route", now, ip=ip, key=code)
    if n >= settings.route_downloads_per_code_hour and oldest is not None:
        raise rate_limited(oldest + HOUR, now)
    session.add(IpEvent(at=now, ip=ip, kind="route", key=code))
    session.flush()


def _month(now: datetime) -> str:
    return now.strftime("%Y-%m")


def check_quota(session: Session, settings: Settings, now: datetime) -> None:
    row = session.get(MonthlyBytes, _month(now))
    if row is not None and row.bytes >= settings.bandwidth_month_bytes:
        raise ServiceError(503, "quota", "monthly bandwidth cap reached")


def add_bytes(session: Session, settings: Settings, mailer: Mailer, n: int, now: datetime) -> None:
    month = _month(now)
    session.execute(
        insert(MonthlyBytes)
        .values(month=month, bytes=n)
        .on_conflict_do_update(index_elements=["month"], set_={"bytes": MonthlyBytes.bytes + n})
    )
    row = session.get(MonthlyBytes, month, populate_existing=True)
    cap = settings.bandwidth_month_bytes
    if (
        row is not None
        and row.warned_at is None
        and row.bytes >= cap * settings.bandwidth_warn_ratio
    ):
        row.warned_at = now
        mailer.send(
            "Lữ Trình: băng thông tháng",
            f"Tháng {month} đã phát {row.bytes} byte, "
            f"{row.bytes * 100 // cap} % của trần {cap} byte.",
        )
    session.flush()
