"""``lutrinh`` command line (page 06 §8: no password reset by mail, only on the host).

* ``lutrinh admin create``: the one admin account; prints the TOTP URI (scan it in any
  Authenticator app) and 10 single-use backup codes, once.
* ``lutrinh admin reset``: new password, TOTP secret and backup codes; ends every session.

The password is asked twice on the terminal, or read from stdin with ``--password-stdin``.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from lutrinh.config import get_settings
from lutrinh.db.engine import make_engine, make_sessionmaker
from lutrinh.services import audit, auth


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
    try:
        with make_sessionmaker(engine)() as session:
            try:
                enrolment = auth.enrol(session, settings, password, reset=args.action == "reset")
            except auth.AuthError as exc:
                messages = {
                    "admin_exists": "Đã có tài khoản quản trị; dùng `lutrinh admin reset`.",
                    "no_admin": "Chưa có tài khoản quản trị; dùng `lutrinh admin create`.",
                    "weak_password": f"Mật khẩu cần ít nhất {auth.PASSWORD_MIN} ký tự.",
                }
                print(messages.get(exc.code, exc.code), file=sys.stderr)
                return 1
            audit.record(session, f"admin.{args.action}", actor="cli")
            session.commit()
    finally:
        engine.dispose()
    print("TOTP (quét bằng app Authenticator):")
    print(enrolment.totp_uri)
    print(f"Khóa nhập tay: {enrolment.totp_secret}")
    print("Mã dự phòng (mỗi mã dùng một lần; in ra giấy, không lưu ở đây):")
    for code in enrolment.backup_codes:
        print(f"  {code}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lutrinh")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("admin", help="the admin account")
    admin.add_argument("action", choices=["create", "reset"])
    admin.add_argument("--password-stdin", action="store_true")
    admin.set_defaults(run=_admin)
    args = parser.parse_args(argv)
    code: int = args.run(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
