#!/bin/sh
set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ENV_FILE="${GONGWEN_ENV_FILE:-${SCRIPT_DIR}/.env}"
# shellcheck source=deploy/gongwen/common.sh
. "${SCRIPT_DIR}/common.sh"

if [ ! -f "${ENV_FILE}" ]; then
    echo "Run ${SCRIPT_DIR}/start.sh once before the smoke check." >&2
    exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required." >&2
    exit 1
fi

GONGWEN_ACCESS_TOKEN=$(dotenv_read GONGWEN_ACCESS_TOKEN "${ENV_FILE}" "${GONGWEN_ACCESS_TOKEN:-}")
GONGWEN_MCP_ACCESS_TOKEN=$(
    dotenv_read GONGWEN_MCP_ACCESS_TOKEN "${ENV_FILE}" "${GONGWEN_MCP_ACCESS_TOKEN:-}"
)
GONGWEN_SITE_ADDRESS=$(dotenv_read GONGWEN_SITE_ADDRESS "${ENV_FILE}" "${GONGWEN_SITE_ADDRESS:-:80}")
raw_bind_address=$(dotenv_read GONGWEN_BIND_ADDRESS "${ENV_FILE}" "${GONGWEN_BIND_ADDRESS:-127.0.0.1}")
GONGWEN_BIND_ADDRESS=$(normalize_bind_address "${raw_bind_address}")
GONGWEN_HTTP_PORT=$(dotenv_read GONGWEN_HTTP_PORT "${ENV_FILE}" "${GONGWEN_HTTP_PORT:-8080}")
GONGWEN_HTTPS_PORT=$(dotenv_read GONGWEN_HTTPS_PORT "${ENV_FILE}" "${GONGWEN_HTTPS_PORT:-8443}")

case "${GONGWEN_SITE_ADDRESS}" in
    :80)
        ACCESS_HOST=$(local_access_host "${GONGWEN_BIND_ADDRESS}")
        BASE_URL="http://${ACCESS_HOST}:${GONGWEN_HTTP_PORT}"
        ;;
    *)
        if [ "${GONGWEN_HTTPS_PORT}" = "443" ]; then
            BASE_URL="https://${GONGWEN_SITE_ADDRESS}"
        else
            BASE_URL="https://${GONGWEN_SITE_ADDRESS}:${GONGWEN_HTTPS_PORT}"
        fi
        ;;
esac

WEB_AUTH_HEADER=
MCP_AUTH_HEADER=
MCP_RESPONSE_HEADERS=
MCP_RESPONSE_BODY=
smoke_exit() {
    status=$?
    trap - EXIT HUP INT TERM
    for private_file in \
        "${WEB_AUTH_HEADER}" "${MCP_AUTH_HEADER}" \
        "${MCP_RESPONSE_HEADERS}" "${MCP_RESPONSE_BODY}"; do
        if [ -n "${private_file}" ]; then
            rm -f "${private_file}"
        fi
    done
    exit "${status}"
}
trap smoke_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# Keep Bearer values out of curl's process arguments, where another local
# process could otherwise observe them. curl reads these 0600 files directly.
WEB_AUTH_HEADER=$(mktemp "${TMPDIR:-/tmp}/gongwen-web-auth.XXXXXX")
MCP_AUTH_HEADER=$(mktemp "${TMPDIR:-/tmp}/gongwen-mcp-auth.XXXXXX")
chmod 600 "${WEB_AUTH_HEADER}" "${MCP_AUTH_HEADER}"
printf 'Authorization: Bearer %s\n' "${GONGWEN_ACCESS_TOKEN}" >"${WEB_AUTH_HEADER}"
printf 'Authorization: Bearer %s\n' "${GONGWEN_MCP_ACCESS_TOKEN}" >"${MCP_AUTH_HEADER}"
unset GONGWEN_ACCESS_TOKEN GONGWEN_MCP_ACCESS_TOKEN

curl --fail --silent --show-error "${BASE_URL}/api/health" >/dev/null
curl --fail --silent --show-error "${BASE_URL}/api/ready" >/dev/null

unauthorized_status=$(
    curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
        "${BASE_URL}/api/documents?limit=1"
)
if [ "${unauthorized_status}" != "401" ]; then
    echo "Expected the protected API to return 401; got ${unauthorized_status}." >&2
    exit 1
fi

curl --fail --silent --show-error \
    --header @"${WEB_AUTH_HEADER}" \
    "${BASE_URL}/api/documents?limit=1" >/dev/null

mcp_unauthorized_status=$(
    curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
        --header 'Accept: application/json, text/event-stream' \
        --header 'Content-Type: application/json' \
        --data-binary \
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"gongwen-deployment-smoke","version":"0.1.0"}}}' \
        "${BASE_URL}/mcp"
)
if [ "${mcp_unauthorized_status}" != "401" ]; then
    echo "Expected MCP without a token to return 401; got ${mcp_unauthorized_status}." >&2
    exit 1
fi

mcp_web_token_status=$(
    curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
        --header @"${WEB_AUTH_HEADER}" \
        --header 'Accept: application/json, text/event-stream' \
        --header 'Content-Type: application/json' \
        --data-binary \
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"gongwen-deployment-smoke","version":"0.1.0"}}}' \
        "${BASE_URL}/mcp"
)
if [ "${mcp_web_token_status}" != "401" ]; then
    echo "Expected the Web token to be rejected by MCP; got ${mcp_web_token_status}." >&2
    exit 1
fi

MCP_RESPONSE_HEADERS=$(mktemp "${TMPDIR:-/tmp}/gongwen-mcp-headers.XXXXXX")
MCP_RESPONSE_BODY=$(mktemp "${TMPDIR:-/tmp}/gongwen-mcp-body.XXXXXX")

mcp_initialize_status=$(
    curl --silent --show-error \
        --dump-header "${MCP_RESPONSE_HEADERS}" \
        --output "${MCP_RESPONSE_BODY}" \
        --write-out '%{http_code}' \
        --header @"${MCP_AUTH_HEADER}" \
        --header 'Accept: application/json, text/event-stream' \
        --header 'Content-Type: application/json' \
        --data-binary \
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"gongwen-deployment-smoke","version":"0.1.0"}}}' \
        "${BASE_URL}/mcp"
)
if [ "${mcp_initialize_status}" != "200" ]; then
    echo "Expected MCP initialize to return 200; got ${mcp_initialize_status}." >&2
    exit 1
fi
if ! grep -Eiq '^content-type:[[:space:]]*(application/json|text/event-stream)' \
    "${MCP_RESPONSE_HEADERS}"; then
    echo "MCP initialize returned an unexpected Content-Type." >&2
    exit 1
fi
if ! grep -Eq '"jsonrpc"[[:space:]]*:[[:space:]]*"2\.0"' "${MCP_RESPONSE_BODY}" || \
    ! grep -Eq '"result"[[:space:]]*:' "${MCP_RESPONSE_BODY}" || \
    ! grep -Eq '"protocolVersion"[[:space:]]*:[[:space:]]*"2025-06-18"' \
        "${MCP_RESPONSE_BODY}"; then
    echo "MCP initialize did not return a valid JSON-RPC result." >&2
    exit 1
fi

echo "Smoke check passed: liveness, storage readiness, Web authentication and MCP initialize."
