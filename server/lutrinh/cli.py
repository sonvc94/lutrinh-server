"""``lutrinh`` command line (page 06 §8: no password reset by mail, only on the host).

* ``lutrinh admin create``: the one admin account; prints the TOTP URI (scan it in any
  Authenticator app) and 10 single-use backup codes, once.
* ``lutrinh admin reset``: new password, TOTP secret and backup codes; ends every session.
* ``lutrinh admin set-password [--username admin]``: only the username and password of the
  one admin (created when missing); the TOTP secret and codes stay; ends every session. Test
  phase: ``echo 123456 | lutrinh admin set-password --username admin --password-stdin``.
  Login asks for the TOTP only while ``LUTRINH_ADMIN_TOTP=on``.

The password is asked twice on the terminal, or read from stdin with ``--password-stdin``.

For trying the server on one machine (AGENTS.md "Chạy thử trên máy"):

* ``lutrinh serve [--host 127.0.0.1] [--port 8000]``: the API with Uvicorn, one process (the
  rate-limit counters are in SQLite, page 06 §2). ``--host 0.0.0.0`` for the LAN / the Android
  emulator (``http://10.0.2.2:8000``).
* ``lutrinh worker [--once]``: the job worker (``lutrinh.jobs.worker``), a second process next
  to ``serve`` on the same data directory: photos, videos, road legs, nightly purges.
* ``lutrinh seed-sample``: publishes ``spec/samples/ha-giang-4n`` as a route and prints its code
  (needs ffmpeg for the placeholder media, ``services.seed``).
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from lutrinh.config import get_settings
from lutrinh.core import codes
from lutrinh.db.engine import make_engine, make_sessionmaker
from lutrinh.services import audit, auth, seed


def _password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Mật khẩu (≥ 14 ký tự): ")
    if getpass.getpass("Nhập lại: ") != first:
        raise SystemExit("Hai lần nhập không khớp.")
    return first


def _admin(args: argparse.Namespace) -> int:
    settings = get_settings()
    password = _password(args.password_stdin)
    engine = make_engine(settings.db_url)
    enrolment = None
    created = False
    try:
        with make_sessionmaker(engine)() as session:
            try:
                if args.action == "set-password":
                    created = auth.set_password(session, settings, password, username=args.username)
                else:
                    enrolment = auth.enrol(
                        session, settings, password, reset=args.action == "reset"
                    )
            except auth.AuthError as exc:
                messages = {
                    "admin_exists": "Đã có tài khoản quản trị; dùng `lutrinh admin reset`.",
                    "no_admin": "Chưa có tài khoản quản trị; dùng `lutrinh admin create`.",
                    "weak_password": f"Mật khẩu cần ít nhất {settings.admin_password_min} ký tự.",
                    "bad_username": "Tên đăng nhập dài 1–40 ký tự.",
                }
                print(messages.get(exc.code, exc.code), file=sys.stderr)
                return 1
            audit.record(session, f"admin.{args.action}", actor="cli")
            session.commit()
    finally:
        engine.dispose()
    if enrolment is None:
        verb = "Đã tạo" if created else "Đã cập nhật"
        print(f"{verb} tài khoản quản trị «{args.username}»; mọi phiên đăng nhập đã bị đóng.")
        print("Đăng nhập chỉ cần tên đăng nhập + mật khẩu khi LUTRINH_ADMIN_TOTP=off (mặc định).")
        return 0
    print("TOTP (quét bằng app Authenticator):")
    print(enrolment.totp_uri)
    print(f"Khóa nhập tay: {enrolment.totp_secret}")
    print("Mã dự phòng (mỗi mã dùng một lần; in ra giấy, không lưu ở đây):")
    for code in enrolment.backup_codes:
        print(f"  {code}")
    return 0


def _seed(args: argparse.Namespace) -> int:
    settings = get_settings()
    sample = args.sample or settings.spec_dir / "samples" / "ha-giang-4n"
    engine = make_engine(settings.db_url)
    try:
        with make_sessionmaker(engine)() as session:
            try:
                published = seed.seed_sample(session, settings, sample)
            except seed.SeedError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            session.commit()
    finally:
        engine.dispose()
    v = published.version
    print(f"Lộ trình {v.route_id} v{v.version}: {v.media_files} tệp, {v.media_bytes} byte")
    print(f"Mã: {codes.display(published.code.code)}")
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from lutrinh.api.app import create_app

    # One process only: two would keep two sets of counters (page 06 §2).
    uvicorn.run(create_app(), host=args.host, port=args.port, proxy_headers=True)
    return 0


def _worker(args: argparse.Namespace) -> int:
    from lutrinh.jobs import worker

    return worker.main(["--once"] if args.once else [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lutrinh")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("admin", help="the admin account")
    admin.add_argument("action", choices=["create", "reset", "set-password"])
    admin.add_argument("--password-stdin", action="store_true")
    admin.add_argument("--username", default=auth.USERNAME, help="set-password only")
    admin.set_defaults(run=_admin)
    seed_cmd = sub.add_parser("seed-sample", help="publish the spec sample route, print its code")
    seed_cmd.add_argument("--sample", type=Path, default=None, help="sample directory")
    seed_cmd.set_defaults(run=_seed)
    serve = sub.add_parser("serve", help="run the API with Uvicorn")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(run=_serve)
    work = sub.add_parser("worker", help="run the background jobs (media, legs, purges)")
    work.add_argument("--once", action="store_true", help="run the due jobs, then exit")
    work.set_defaults(run=_worker)
    args = parser.parse_args(argv)
    code: int = args.run(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
