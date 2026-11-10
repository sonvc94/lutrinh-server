#!/bin/sh
# First start on a host (page 06 §5): data directory, images, migrations, the admin account,
# then the stack. Safe to run again: an existing admin is kept (`lutrinh admin reset` resets).
#   deploy/bootstrap.sh                    # asks the admin password twice
#   printf '%s\n' "$PW" | deploy/bootstrap.sh --password-stdin
set -eu
. "$(dirname "$0")/lib.sh"

password=""
stdin_flag=""
if [ "${1:-}" = "--password-stdin" ]; then
	# Read it now: the docker commands below would otherwise consume stdin.
	stdin_flag=1
	IFS= read -r password
fi

for d in db media uploads backups tmp; do
	mkdir -p "$DATA_PATH/$d" 2>/dev/null || sudo mkdir -p "$DATA_PATH/$d"
done
own_data "$DATA_PATH"

dc build </dev/null
dc run --rm --no-deps -T app alembic upgrade head </dev/null

# Prints the TOTP URI and backup codes once: scan / write them down now. An existing admin
# makes this step say so and continue.
if [ -n "$stdin_flag" ]; then
	printf '%s\n' "$password" | dc run --rm --no-deps -T app lutrinh admin create --password-stdin || true
else
	dc run --rm --no-deps app lutrinh admin create || true
fi

dc up -d </dev/null
echo "Xong. Kiểm tra: curl -fsS http://localhost:${LUTRINH_HTTP_PORT:-80}/api/v1/meta"
