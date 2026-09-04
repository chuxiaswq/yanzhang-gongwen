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
    echo "Run ${SCRIPT_DIR}/start.sh once before restoring data." >&2
    exit 1
fi
configure_operation_lock "${DEPLOY_DIR}/.operation.lock"
export_legacy_runtime_config "${ENV_FILE}"

# The established restore path stops writers, verifies the snapshot and
# restores ownership for the fixed non-root application identity.
exec "${DEPLOY_DIR}/restore.sh" "$@"
