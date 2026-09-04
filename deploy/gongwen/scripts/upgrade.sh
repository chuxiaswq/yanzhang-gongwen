#!/bin/sh
set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
COMPOSE_FILE="${DEPLOY_DIR}/compose.yaml"
ENV_FILE="${YANZHANG_ENV_FILE:-${GONGWEN_ENV_FILE:-${DEPLOY_DIR}/.env}}"
BACKUP_DIR=${1:-"${DEPLOY_DIR}/backups"}
# shellcheck source=deploy/gongwen/scripts/config.sh
. "${SCRIPT_DIR}/config.sh"
# shellcheck source=deploy/gongwen/common.sh
. "${DEPLOY_DIR}/common.sh"

if [ "$#" -gt 1 ]; then
    echo "Usage: $0 [backup-directory]" >&2
    exit 2
fi
if [ ! -f "${ENV_FILE}" ]; then
    echo "Run ${SCRIPT_DIR}/start.sh once before upgrading." >&2
    exit 1
fi
require_compose
configure_operation_lock "${DEPLOY_DIR}/.operation.lock"
export_legacy_runtime_config "${ENV_FILE}"

upgrade_exit() {
    status=$?
    trap - EXIT HUP INT TERM
    operation_lock_release
    exit "${status}"
}

operation_lock_acquire
trap upgrade_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Creating a verified pre-upgrade backup..."
"${SCRIPT_DIR}/backup.sh" "${BACKUP_DIR}"

echo "Refreshing pinned base images and rebuilding Yanzhang..."
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" pull proxy
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build --pull gongwen

# start.sh retains the stable named volume, recreates the proxy configuration
# and waits for container health before returning.
"${SCRIPT_DIR}/start.sh"
"${SCRIPT_DIR}/health.sh"

echo "Yanzhang v0.2 upgrade completed with persistent data intact."
