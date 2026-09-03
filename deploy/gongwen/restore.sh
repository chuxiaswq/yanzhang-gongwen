#!/bin/sh
set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"
ENV_FILE="${GONGWEN_ENV_FILE:-${SCRIPT_DIR}/.env}"
# shellcheck source=deploy/gongwen/common.sh
. "${SCRIPT_DIR}/common.sh"

if [ "$#" -ne 2 ] || [ "$2" != "--yes" ]; then
    echo "Usage: $0 /absolute/or/relative/backup.sqlite3 --yes" >&2
    exit 2
fi

BACKUP_DIR=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
BACKUP_FILE="${BACKUP_DIR}/$(basename -- "$1")"
if [ ! -f "${BACKUP_FILE}" ]; then
    echo "Backup file does not exist: ${BACKUP_FILE}" >&2
    exit 1
fi
if [ ! -f "${ENV_FILE}" ]; then
    echo "Run ${SCRIPT_DIR}/start.sh once before restoring data." >&2
    exit 1
fi
raw_bind_address=$(dotenv_read GONGWEN_BIND_ADDRESS "${ENV_FILE}" "${GONGWEN_BIND_ADDRESS:-127.0.0.1}")
GONGWEN_BIND_ADDRESS=$(normalize_bind_address "${raw_bind_address}")
export GONGWEN_BIND_ADDRESS
if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required." >&2
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose v2 is required." >&2
    exit 1
fi

compose() {
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

SERVICES_STOPPED=0
restart_after_failure() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ "${SERVICES_STOPPED}" -eq 1 ]; then
        echo "Restore did not complete; restarting the existing services." >&2
        compose up -d gongwen proxy >/dev/null 2>&1 || true
    fi
    operation_lock_release
    exit "${status}"
}

operation_lock_acquire
trap restart_after_failure EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Stopping the web service before restore..."
SERVICES_STOPPED=1
compose stop proxy gongwen

# The short-lived maintenance process runs as root only so it can read a
# host-owned 0600 backup and restore ownership to the non-root application UID.
compose run --rm --no-deps --user 0:0 \
    --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
    --volume "${BACKUP_FILE}:/restore/gongwen.sqlite3:ro" \
    gongwen sh -ec '
        gongwen-admin --database /var/lib/gongwen/gongwen.sqlite3 \
            restore --input /restore/gongwen.sqlite3 --force
        app_uid=$(id -u gongwen)
        app_gid=$(id -g gongwen)
        chown "${app_uid}:${app_gid}" /var/lib/gongwen/gongwen.sqlite3
        chmod 600 /var/lib/gongwen/gongwen.sqlite3
        gongwen-admin --database /var/lib/gongwen/gongwen.sqlite3 check
    '

echo "Restore passed integrity checks. Starting services..."
"${SCRIPT_DIR}/start.sh"
SERVICES_STOPPED=0
