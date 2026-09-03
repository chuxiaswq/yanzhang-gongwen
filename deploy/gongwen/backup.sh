#!/bin/sh
set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"
ENV_FILE="${GONGWEN_ENV_FILE:-${SCRIPT_DIR}/.env}"
# shellcheck source=deploy/gongwen/common.sh
. "${SCRIPT_DIR}/common.sh"
BACKUP_DIR=${1:-"${SCRIPT_DIR}/backups"}

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required." >&2
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose v2 is required." >&2
    exit 1
fi
if [ ! -f "${ENV_FILE}" ]; then
    echo "Run ${SCRIPT_DIR}/start.sh once before creating a backup." >&2
    exit 1
fi
raw_bind_address=$(dotenv_read GONGWEN_BIND_ADDRESS "${ENV_FILE}" "${GONGWEN_BIND_ADDRESS:-127.0.0.1}")
GONGWEN_BIND_ADDRESS=$(normalize_bind_address "${raw_bind_address}")
export GONGWEN_BIND_ADDRESS

mkdir -p "${BACKUP_DIR}"
BACKUP_DIR=$(CDPATH= cd -- "${BACKUP_DIR}" && pwd)
REMOTE_FILE=
PARTIAL_FILE=

compose() {
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

cleanup_backup_artifacts() {
    if [ -n "${REMOTE_FILE}" ]; then
        compose exec -T gongwen rm -f \
            "${REMOTE_FILE}" "${REMOTE_FILE}-wal" "${REMOTE_FILE}-shm" \
            >/dev/null 2>&1 || true
    fi
    if [ -n "${PARTIAL_FILE}" ]; then
        rm -f "${PARTIAL_FILE}" "${PARTIAL_FILE}-wal" "${PARTIAL_FILE}-shm"
    fi
}

backup_exit() {
    status=$?
    trap - EXIT HUP INT TERM
    cleanup_backup_artifacts
    operation_lock_release
    exit "${status}"
}

operation_lock_acquire
trap backup_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
if command -v openssl >/dev/null 2>&1; then
    NONCE=$(openssl rand -hex 6)
else
    NONCE=$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')
fi
RUN_ID="${STAMP}-$$-${NONCE}"
# Keep the transient snapshot on the persistent data volume. The application
# container's /tmp is deliberately capped and may be smaller than the library.
REMOTE_FILE="/var/lib/gongwen/.backup-${RUN_ID}.sqlite3"
LOCAL_FILE="${BACKUP_DIR}/gongwen-${RUN_ID}.sqlite3"
PARTIAL_FILE="${LOCAL_FILE}.partial"
if [ -e "${LOCAL_FILE}" ] || [ -e "${PARTIAL_FILE}" ]; then
    echo "Backup destination already exists: ${LOCAL_FILE}" >&2
    exit 1
fi

# gongwen-admin uses SQLite's online backup API and checks the completed
# snapshot. The second check reads the copied host file before publication.
compose exec -T gongwen gongwen-admin \
    --database /var/lib/gongwen/gongwen.sqlite3 \
    backup --output "${REMOTE_FILE}"
compose exec -T gongwen gongwen-admin --database "${REMOTE_FILE}" check >/dev/null
compose cp "gongwen:${REMOTE_FILE}" "${PARTIAL_FILE}"
chmod 600 "${PARTIAL_FILE}"
HOST_UID=$(id -u)
HOST_GID=$(id -g)
compose run --rm --no-deps --user "${HOST_UID}:${HOST_GID}" \
    --volume "${PARTIAL_FILE}:/verify/gongwen.sqlite3:ro" \
    gongwen gongwen-admin --database /verify/gongwen.sqlite3 check >/dev/null
rm -f "${PARTIAL_FILE}-wal" "${PARTIAL_FILE}-shm"
mv "${PARTIAL_FILE}" "${LOCAL_FILE}"
PARTIAL_FILE=

echo "Backup created: ${LOCAL_FILE}"
if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${LOCAL_FILE}"
elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${LOCAL_FILE}"
fi
