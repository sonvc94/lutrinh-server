#!/bin/sh
# Backups (page 06 §4, §9; D-21 A).
#   deploy/backup.sh               nightly: DB copy → backups/ (keep 7), then restic backs up
#                                  backups/ + media/ off-host, keeps 30 daily + 6 monthly
#   deploy/backup.sh --now         DB copy only (before an update), no restic
#   deploy/backup.sh --restore [SNAPSHOT] [--yes]
#                                  stop the stack, restic restore (default: latest) into the
#                                  data directory, newest backups/db-*.sqlite → db/, start
# The stack's data directory is LUTRINH_DATA_PATH; restic settings come from deploy/.env.
set -eu
. "$(dirname "$0")/lib.sh"

db_copy() {
	# SQLite online backup API: consistent while the API and worker keep writing (WAL).
	dc run --rm --no-deps -T app python - <<'PY'
import datetime, pathlib, sqlite3

data = pathlib.Path("/var/lib/lutrinh")
src = data / "db" / "lutrinh.sqlite"
if not src.is_file():
    raise SystemExit(f"{src} không có: chưa chạy bootstrap?")
out = data / "backups"
out.mkdir(exist_ok=True)
dest = out / f"db-{datetime.datetime.now():%Y-%m-%d-%H%M%S}.sqlite"
part = dest.with_suffix(".part")
for stale in out.glob("db-*.part*"):
    stale.unlink()
a, b = sqlite3.connect(src), sqlite3.connect(part)
try:
    a.backup(b)
    # A self-contained file: no -wal/-shm beside it.
    b.execute("PRAGMA journal_mode=DELETE")
    if b.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("integrity_check thất bại")
finally:
    a.close()
    b.close()
part.rename(dest)
for old in sorted(out.glob("db-*.sqlite"))[:-7]:
    old.unlink()
print(f"DB → {dest}")
PY
}

need_restic() {
	if [ -z "${RESTIC_REPOSITORY:-}" ] || [ -z "${RESTIC_PASSWORD:-}" ] \
		|| [ "${RESTIC_PASSWORD}" = "change-me" ]; then
		echo "Đặt RESTIC_REPOSITORY và RESTIC_PASSWORD trong $ENV_FILE." >&2
		exit 1
	fi
	if [ "${RESTIC_REPOSITORY}" = "/repo-local" ]; then
		# restic runs as uid 10001 (compose.yaml), so it must own the local repository.
		dir=${RESTIC_LOCAL_DIR:?đặt RESTIC_LOCAL_DIR}
		mkdir -p "$dir" 2>/dev/null || sudo mkdir -p "$dir"
		own_data "$dir"
	fi
}

restic_sh() {
	dc --profile backup run --rm --no-deps -T --entrypoint sh "$@"
}

case "${1:-}" in
"")
	need_restic
	db_copy
	restic_sh restic -c '
		set -e
		restic cat config >/dev/null 2>&1 || restic init
		restic backup --host lutrinh --tag nightly /data/backups /data/media
		restic forget --host lutrinh --keep-daily 30 --keep-monthly 6 --prune
	'
	;;
--now)
	db_copy
	;;
--restore)
	need_restic
	snap=${2:-latest}
	[ "$snap" = "--yes" ] && snap=latest
	case " $* " in
	*" --yes "*) ;;
	*)
		printf 'Ghi đè %s bằng bản sao lưu %s? Gõ "yes": ' "$DATA_PATH" "$snap"
		read -r answer
		[ "$answer" = "yes" ] || exit 1
		;;
	esac
	dc stop caddy worker app
	restic_sh restic -c '
		set -e
		restic restore "$0:/data" --target /data
		cd /data
		mkdir -p db uploads tmp
		f=$(ls -1 backups/db-*.sqlite | tail -n 1)
		rm -f db/lutrinh.sqlite-wal db/lutrinh.sqlite-shm
		cp "$f" db/lutrinh.sqlite
		echo "DB ← $f"
	' "$snap"
	dc up -d
	;;
*)
	echo "Dùng: $0 [--now | --restore [SNAPSHOT] [--yes]]" >&2
	exit 2
	;;
esac
