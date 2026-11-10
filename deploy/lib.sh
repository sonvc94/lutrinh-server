# Shared by deploy/*.sh: run from anywhere, read deploy/.env, call compose on this stack.
DEPLOY_DIR=$(cd "$(dirname "$0")" && pwd)
ENV_FILE=${LUTRINH_ENV_FILE:-$DEPLOY_DIR/.env}
if [ ! -f "$ENV_FILE" ]; then
	echo "Thiếu $ENV_FILE: chép deploy/.env.example thành deploy/.env rồi sửa." >&2
	exit 1
fi
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
DATA_PATH=${LUTRINH_DATA_PATH:-/var/lib/lutrinh}
APP_UID=10001

# With COMPOSE_FILE set (e.g. "/opt/lutrinh/deploy/compose.yaml:/opt/lutrinh/deploy/local.yaml"),
# compose reads that list itself, overrides included.
dc() {
	if [ -n "${COMPOSE_FILE:-}" ]; then
		docker compose --env-file "$ENV_FILE" "$@"
	else
		docker compose -f "$DEPLOY_DIR/compose.yaml" --env-file "$ENV_FILE" "$@"
	fi
}

# The containers run as uid 10001 and must own the data directory (and a local restic repo).
own_data() {
	# Docker Desktop (macOS) maps ownership itself; nothing to do there.
	[ "$(uname -s)" = Darwin ] && return 0
	if [ "$(stat -c %u "$1")" != "$APP_UID" ]; then
		chown -R "$APP_UID:$APP_UID" "$1" 2>/dev/null \
			|| sudo chown -R "$APP_UID:$APP_UID" "$1" 2>/dev/null
	fi
}
