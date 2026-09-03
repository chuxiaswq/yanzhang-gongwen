#!/bin/sh
set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ENV_FILE="${GONGWEN_ENV_FILE:-${SCRIPT_DIR}/.env}"
# shellcheck source=deploy/gongwen/common.sh
. "${SCRIPT_DIR}/common.sh"

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 web|mcp" >&2
    exit 2
fi
if [ ! -f "${ENV_FILE}" ]; then
    echo "Run ${SCRIPT_DIR}/start.sh once before viewing an access token." >&2
    exit 1
fi
if [ ! -t 1 ]; then
    echo "Access tokens are shown only in an interactive terminal." >&2
    exit 1
fi

case "$1" in
    web)
        TOKEN_KEY=GONGWEN_ACCESS_TOKEN
        TOKEN_LABEL="Web access token"
        ;;
    mcp)
        TOKEN_KEY=GONGWEN_MCP_ACCESS_TOKEN
        TOKEN_LABEL="MCP access token"
        ;;
    *)
        echo "Usage: $0 web|mcp" >&2
        exit 2
        ;;
esac

TOKEN_VALUE=$(dotenv_read "${TOKEN_KEY}" "${ENV_FILE}" "")
case "${TOKEN_VALUE}" in
    "" | CHANGE_ME_* | CHANGEME_*)
        echo "${TOKEN_LABEL} has not been generated yet." >&2
        exit 1
        ;;
esac

printf '%s: %s\n' "${TOKEN_LABEL}" "${TOKEN_VALUE}"
unset TOKEN_VALUE
