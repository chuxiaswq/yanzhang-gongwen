#!/bin/sh
set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"
ENV_FILE="${GONGWEN_ENV_FILE:-${SCRIPT_DIR}/.env}"
# shellcheck source=deploy/gongwen/common.sh
. "${SCRIPT_DIR}/common.sh"

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required." >&2
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose v2 is required." >&2
    exit 1
fi

ENV_TMP=

start_exit() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ -n "${ENV_TMP}" ]; then
        rm -f "${ENV_TMP}"
    fi
    operation_lock_release
    exit "${status}"
}

operation_lock_acquire
trap start_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [ ! -f "${ENV_FILE}" ]; then
    cp "${SCRIPT_DIR}/env.example" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    echo "Created ${ENV_FILE}"
fi

chmod 600 "${ENV_FILE}"
GONGWEN_ACCESS_TOKEN=$(dotenv_read GONGWEN_ACCESS_TOKEN "${ENV_FILE}" "${GONGWEN_ACCESS_TOKEN:-}")
if grep -q '^GONGWEN_MCP_ACCESS_TOKEN=' "${ENV_FILE}"; then
    MCP_TOKEN_ENTRY_PRESENT=1
else
    MCP_TOKEN_ENTRY_PRESENT=0
fi
GONGWEN_MCP_ACCESS_TOKEN=$(
    dotenv_read GONGWEN_MCP_ACCESS_TOKEN "${ENV_FILE}" "${GONGWEN_MCP_ACCESS_TOKEN:-}"
)
GONGWEN_SITE_ADDRESS=$(dotenv_read GONGWEN_SITE_ADDRESS "${ENV_FILE}" "${GONGWEN_SITE_ADDRESS:-:80}")
raw_bind_address=$(dotenv_read GONGWEN_BIND_ADDRESS "${ENV_FILE}" "${GONGWEN_BIND_ADDRESS:-127.0.0.1}")
GONGWEN_BIND_ADDRESS=$(normalize_bind_address "${raw_bind_address}")
GONGWEN_HTTP_PORT=$(dotenv_read GONGWEN_HTTP_PORT "${ENV_FILE}" "${GONGWEN_HTTP_PORT:-8080}")
GONGWEN_HTTPS_PORT=$(dotenv_read GONGWEN_HTTPS_PORT "${ENV_FILE}" "${GONGWEN_HTTPS_PORT:-8443}")
GONGWEN_ALLOWED_HOSTS=$(
    dotenv_read GONGWEN_ALLOWED_HOSTS "${ENV_FILE}" \
        "${GONGWEN_ALLOWED_HOSTS:-127.0.0.1,localhost,[::1]}"
)

case "${GONGWEN_ACCESS_TOKEN}" in
    "" | CHANGE_ME_*)
    if command -v openssl >/dev/null 2>&1; then
        GONGWEN_ACCESS_TOKEN=$(openssl rand -hex 32)
    else
        GONGWEN_ACCESS_TOKEN=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
    fi
    ENV_TMP="${ENV_FILE}.tmp.$$"
    awk -v value="${GONGWEN_ACCESS_TOKEN}" '
        BEGIN { replaced = 0 }
        /^GONGWEN_ACCESS_TOKEN=/ {
            if (!replaced) {
                print "GONGWEN_ACCESS_TOKEN=" value
                replaced = 1
            }
            next
        }
        { print }
        END {
            if (!replaced) print "GONGWEN_ACCESS_TOKEN=" value
        }
    ' "${ENV_FILE}" >"${ENV_TMP}"
    chmod 600 "${ENV_TMP}"
    mv "${ENV_TMP}" "${ENV_FILE}"
    ENV_TMP=
    chmod 600 "${ENV_FILE}"
    GENERATED_TOKEN=1
    ;;
    *) GENERATED_TOKEN=0 ;;
esac

case "${GONGWEN_MCP_ACCESS_TOKEN}" in
    "" | CHANGE_ME_* | CHANGEME_*)
    if command -v openssl >/dev/null 2>&1; then
        GONGWEN_MCP_ACCESS_TOKEN=$(openssl rand -hex 32)
    else
        GONGWEN_MCP_ACCESS_TOKEN=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
    fi
    GENERATED_MCP_TOKEN=1
    ;;
    *) GENERATED_MCP_TOKEN=0 ;;
esac

MCP_TOKEN_SINGLE_LINE=$(printf '%s' "${GONGWEN_MCP_ACCESS_TOKEN}" | tr -d '\r\n')
if [ "${MCP_TOKEN_SINGLE_LINE}" != "${GONGWEN_MCP_ACCESS_TOKEN}" ]; then
    echo "GONGWEN_MCP_ACCESS_TOKEN must be a single-line value." >&2
    exit 1
fi
unset MCP_TOKEN_SINGLE_LINE
TOKEN_BYTES=$(LC_ALL=C printf '%s' "${GONGWEN_ACCESS_TOKEN}" | wc -c | tr -d ' ')
if [ "${TOKEN_BYTES}" -lt 32 ]; then
    echo "GONGWEN_ACCESS_TOKEN must contain at least 32 bytes." >&2
    exit 1
fi
MCP_TOKEN_BYTES=$(LC_ALL=C printf '%s' "${GONGWEN_MCP_ACCESS_TOKEN}" | wc -c | tr -d ' ')
if [ "${MCP_TOKEN_BYTES}" -lt 32 ]; then
    echo "GONGWEN_MCP_ACCESS_TOKEN must contain at least 32 bytes." >&2
    exit 1
fi
if [ "${GONGWEN_MCP_ACCESS_TOKEN}" = "${GONGWEN_ACCESS_TOKEN}" ]; then
    echo "GONGWEN_MCP_ACCESS_TOKEN must be independent from GONGWEN_ACCESS_TOKEN." >&2
    exit 1
fi

# Persist a generated token, and also append a valid process-supplied token to
# an older deployment file that predates this setting. The lock serializes
# writers and mv publishes the complete 0600 file atomically.
if [ "${GENERATED_MCP_TOKEN}" -eq 1 ] || [ "${MCP_TOKEN_ENTRY_PRESENT}" -eq 0 ]; then
    ENV_TMP="${ENV_FILE}.tmp.$$"
    awk '!/^GONGWEN_MCP_ACCESS_TOKEN=/' "${ENV_FILE}" >"${ENV_TMP}"
    printf 'GONGWEN_MCP_ACCESS_TOKEN=%s\n' "${GONGWEN_MCP_ACCESS_TOKEN}" >>"${ENV_TMP}"
    chmod 600 "${ENV_TMP}"
    mv "${ENV_TMP}" "${ENV_FILE}"
    ENV_TMP=
    chmod 600 "${ENV_FILE}"
fi

export GONGWEN_ACCESS_TOKEN GONGWEN_MCP_ACCESS_TOKEN
export GONGWEN_SITE_ADDRESS GONGWEN_BIND_ADDRESS
export GONGWEN_HTTP_PORT GONGWEN_HTTPS_PORT GONGWEN_ALLOWED_HOSTS

if [ "${GENERATED_TOKEN}" -eq 1 ]; then
    echo "Generated a Web access token and saved it to ${ENV_FILE}."
fi
if [ "${GENERATED_MCP_TOKEN}" -eq 1 ]; then
    echo "Generated an independent MCP access token and saved it to ${ENV_FILE}."
fi

case "${GONGWEN_SITE_ADDRESS}" in
    :80) ;;
    "" | *://* | *:* | */* | *,* | *\** | *[[:space:]]*)
        echo "GONGWEN_SITE_ADDRESS must be :80 or one hostname without a scheme or port." >&2
        exit 1
        ;;
esac

if [ "${GONGWEN_SITE_ADDRESS}" = ":80" ] && \
    ! bind_address_is_loopback "${GONGWEN_BIND_ADDRESS}"; then
    echo "A non-loopback bind requires an HTTPS site address." >&2
    exit 1
fi

case "${GONGWEN_SITE_ADDRESS}" in
    :80) ;;
    *)
        if ! comma_list_contains \
            "${GONGWEN_ALLOWED_HOSTS}" "${GONGWEN_SITE_ADDRESS}"; then
            echo "GONGWEN_ALLOWED_HOSTS must include ${GONGWEN_SITE_ADDRESS}." >&2
            exit 1
        fi
        ;;
esac

for port_value in "${GONGWEN_HTTP_PORT}" "${GONGWEN_HTTPS_PORT}"; do
    case "${port_value}" in
        '' | *[!0-9]*)
            echo "Published HTTP and HTTPS ports must be numeric." >&2
            exit 1
            ;;
    esac
    if [ "${port_value}" -lt 1 ] || [ "${port_value}" -gt 65535 ]; then
        echo "Published HTTP and HTTPS ports must be between 1 and 65535." >&2
        exit 1
    fi
done

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" config --quiet
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" \
    up -d --build --remove-orphans --wait --wait-timeout 120
# A bind-mounted Caddyfile is not part of the Compose service hash. Recreate the
# proxy so running deployments always pick up reviewed proxy configuration.
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" \
    up -d --force-recreate --no-deps --wait --wait-timeout 60 proxy
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" ps

case "${GONGWEN_SITE_ADDRESS}" in
    :80)
        ACCESS_HOST=$(local_access_host "${GONGWEN_BIND_ADDRESS}")
        ACCESS_URL="http://${ACCESS_HOST}:${GONGWEN_HTTP_PORT}"
        ;;
    *)
        if [ "${GONGWEN_HTTPS_PORT}" = "443" ]; then
            ACCESS_URL="https://${GONGWEN_SITE_ADDRESS}"
        else
            ACCESS_URL="https://${GONGWEN_SITE_ADDRESS}:${GONGWEN_HTTPS_PORT}"
        fi
        ;;
esac

echo ""
echo "Yanzhang is starting at ${ACCESS_URL}"
