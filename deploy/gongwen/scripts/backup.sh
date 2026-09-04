#!/bin/sh
set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
ENV_FILE="${YANZHANG_ENV_FILE:-${GONGWEN_ENV_FILE:-${DEPLOY_DIR}/.env}}"
# shellcheck source=deploy/gongwen/scripts/config.sh
. "${SCRIPT_DIR}/config.sh"
# shellcheck source=deploy/gongwen/common.sh
. "${DEPLOY_DIR}/common.sh"

if [ ! -f "${ENV_FILE}" ]; then
    echo "Run ${SCRIPT_DIR}/start.sh once before creating a backup." >&2
    exit 1
fi
configure_operation_lock "${DEPLOY_DIR}/.operation.lock"
export_legacy_runtime_config "${ENV_FILE}"

# The compatibility implementation uses SQLite's online backup API, verifies
# both container and host copies, and keeps large snapshots off the tmpfs.
exec "${DEPLOY_DIR}/backup.sh" "$@"
