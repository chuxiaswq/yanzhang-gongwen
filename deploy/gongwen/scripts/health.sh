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
    echo "Run ${SCRIPT_DIR}/start.sh once before the health check." >&2
    exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required." >&2
    exit 1
fi
export_legacy_runtime_config "${ENV_FILE}"

# Retain the established liveness, storage, Web-authentication and MCP checks.
"${DEPLOY_DIR}/smoke.sh"

case "${YANZHANG_SITE_ADDRESS}" in
    :80)
        access_host=$(local_access_host "${YANZHANG_BIND_ADDRESS}")
        base_url="http://${access_host}:${YANZHANG_HTTP_PORT}"
        ;;
    *)
        if [ "${YANZHANG_HTTPS_PORT}" = "443" ]; then
            base_url="https://${YANZHANG_SITE_ADDRESS}"
        else
            base_url="https://${YANZHANG_SITE_ADDRESS}:${YANZHANG_HTTPS_PORT}"
        fi
        ;;
esac

AUTH_HEADER=$(mktemp "${TMPDIR:-/tmp}/yanzhang-v2-auth.XXXXXX")
health_exit() {
    status=$?
    trap - EXIT HUP INT TERM
    rm -f "${AUTH_HEADER}"
    exit "${status}"
}
trap health_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
chmod 600 "${AUTH_HEADER}"
printf 'Authorization: Bearer %s\n' "${YANZHANG_ACCESS_TOKEN}" >"${AUTH_HEADER}"
unset YANZHANG_ACCESS_TOKEN GONGWEN_ACCESS_TOKEN

# These read-only endpoints prove that the v0.2 project store and recoverable
# workflow registry are mounted behind the authenticated API.
curl --fail --silent --show-error \
    --header @"${AUTH_HEADER}" "${base_url}/api/v2/projects?limit=1" >/dev/null
curl --fail --silent --show-error \
    --header @"${AUTH_HEADER}" "${base_url}/api/v2/bootstrap" >/dev/null

echo "Yanzhang v0.2 health check passed."
