#!/bin/sh
set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "${DEPLOY_DIR}/../.." && pwd)
COMPOSE_FILE="${DEPLOY_DIR}/compose.yaml"
ENV_FILE="${YANZHANG_ENV_FILE:-${GONGWEN_ENV_FILE:-${DEPLOY_DIR}/.env}}"
ENV_TEMPLATE="${YANZHANG_ENV_TEMPLATE:-${PROJECT_ROOT}/.env.example}"
# shellcheck source=deploy/gongwen/scripts/config.sh
. "${SCRIPT_DIR}/config.sh"
# shellcheck source=deploy/gongwen/common.sh
. "${DEPLOY_DIR}/common.sh"

require_compose
configure_operation_lock "${DEPLOY_DIR}/.operation.lock"

start_exit() {
    status=$?
    trap - EXIT HUP INT TERM
    operation_lock_release
    exit "${status}"
}

operation_lock_acquire
trap start_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [ -L "${ENV_FILE}" ]; then
    echo "Environment file must be a regular private file: ${ENV_FILE}" >&2
    exit 1
fi
if [ ! -f "${ENV_FILE}" ]; then
    if [ ! -f "${ENV_TEMPLATE}" ]; then
        echo "Environment template does not exist: ${ENV_TEMPLATE}" >&2
        exit 1
    fi
    cp "${ENV_TEMPLATE}" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    echo "Created ${ENV_FILE}"
fi
chmod 600 "${ENV_FILE}"

YANZHANG_ACCESS_TOKEN=$(config_resolve ACCESS_TOKEN "${ENV_FILE}" "")
case "${YANZHANG_ACCESS_TOKEN}" in
    "" | CHANGE_ME_* | CHANGEME_*)
        YANZHANG_ACCESS_TOKEN=$(generate_token)
        dotenv_write_key YANZHANG_ACCESS_TOKEN "${YANZHANG_ACCESS_TOKEN}" "${ENV_FILE}"
        GENERATED_TOKEN=1
        ;;
    *) GENERATED_TOKEN=0 ;;
esac

YANZHANG_MCP_ACCESS_TOKEN=$(config_resolve MCP_ACCESS_TOKEN "${ENV_FILE}" "")
case "${YANZHANG_MCP_ACCESS_TOKEN}" in
    "" | CHANGE_ME_* | CHANGEME_*)
        YANZHANG_MCP_ACCESS_TOKEN=$(generate_token)
        dotenv_write_key \
            YANZHANG_MCP_ACCESS_TOKEN "${YANZHANG_MCP_ACCESS_TOKEN}" "${ENV_FILE}"
        GENERATED_MCP_TOKEN=1
        ;;
    *) GENERATED_MCP_TOKEN=0 ;;
esac

for token_value in "${YANZHANG_ACCESS_TOKEN}" "${YANZHANG_MCP_ACCESS_TOKEN}"; do
    single_line=$(printf '%s' "${token_value}" | tr -d '\r\n')
    if [ "${single_line}" != "${token_value}" ]; then
        echo "Access tokens must be single-line values." >&2
        exit 1
    fi
    token_bytes=$(LC_ALL=C printf '%s' "${token_value}" | wc -c | tr -d ' ')
    if [ "${token_bytes}" -lt 32 ]; then
        echo "Each access token must contain at least 32 bytes." >&2
        exit 1
    fi
done
unset single_line token_bytes token_value
if [ "${YANZHANG_MCP_ACCESS_TOKEN}" = "${YANZHANG_ACCESS_TOKEN}" ]; then
    echo "YANZHANG_MCP_ACCESS_TOKEN must be independent from YANZHANG_ACCESS_TOKEN." >&2
    exit 1
fi

YANZHANG_SITE_ADDRESS=$(config_resolve SITE_ADDRESS "${ENV_FILE}" ":80")
raw_bind_address=$(config_resolve BIND_ADDRESS "${ENV_FILE}" "127.0.0.1")
YANZHANG_BIND_ADDRESS=$(normalize_bind_address "${raw_bind_address}")
YANZHANG_HTTP_PORT=$(config_resolve HTTP_PORT "${ENV_FILE}" "8080")
YANZHANG_HTTPS_PORT=$(config_resolve HTTPS_PORT "${ENV_FILE}" "8443")
YANZHANG_ALLOWED_HOSTS=$(
    config_resolve ALLOWED_HOSTS "${ENV_FILE}" "127.0.0.1,localhost,[::1]"
)

case "${YANZHANG_SITE_ADDRESS}" in
    :80) ;;
    "" | *://* | *:* | */* | *,* | *\** | *[[:space:]]*)
        echo "YANZHANG_SITE_ADDRESS must be :80 or one hostname without a scheme or port." >&2
        exit 1
        ;;
esac
if [ "${YANZHANG_SITE_ADDRESS}" = ":80" ] && \
    ! bind_address_is_loopback "${YANZHANG_BIND_ADDRESS}"; then
    echo "A non-loopback bind requires an HTTPS site address." >&2
    exit 1
fi
if [ "${YANZHANG_SITE_ADDRESS}" != ":80" ] && \
    ! comma_list_contains "${YANZHANG_ALLOWED_HOSTS}" "${YANZHANG_SITE_ADDRESS}"; then
    echo "YANZHANG_ALLOWED_HOSTS must include ${YANZHANG_SITE_ADDRESS}." >&2
    exit 1
fi
for port_value in "${YANZHANG_HTTP_PORT}" "${YANZHANG_HTTPS_PORT}"; do
    case "${port_value}" in
        "" | *[!0-9]*)
            echo "Published HTTP and HTTPS ports must be numeric." >&2
            exit 1
            ;;
    esac
    if [ "${port_value}" -lt 1 ] || [ "${port_value}" -gt 65535 ]; then
        echo "Published HTTP and HTTPS ports must be between 1 and 65535." >&2
        exit 1
    fi
done
unset port_value raw_bind_address

# Mirror the resolved operational values for existing v0.1 scripts. The new
# names remain authoritative because config_resolve and Compose always select
# YANZHANG_* first. The deployment lock serializes these atomic replacements.
dotenv_write_key YANZHANG_ACCESS_TOKEN "${YANZHANG_ACCESS_TOKEN}" "${ENV_FILE}"
dotenv_write_key GONGWEN_ACCESS_TOKEN "${YANZHANG_ACCESS_TOKEN}" "${ENV_FILE}"
dotenv_write_key YANZHANG_MCP_ACCESS_TOKEN "${YANZHANG_MCP_ACCESS_TOKEN}" "${ENV_FILE}"
dotenv_write_key GONGWEN_MCP_ACCESS_TOKEN "${YANZHANG_MCP_ACCESS_TOKEN}" "${ENV_FILE}"
dotenv_write_key YANZHANG_SITE_ADDRESS "${YANZHANG_SITE_ADDRESS}" "${ENV_FILE}"
dotenv_write_key GONGWEN_SITE_ADDRESS "${YANZHANG_SITE_ADDRESS}" "${ENV_FILE}"
dotenv_write_key YANZHANG_BIND_ADDRESS "${YANZHANG_BIND_ADDRESS}" "${ENV_FILE}"
dotenv_write_key GONGWEN_BIND_ADDRESS "${YANZHANG_BIND_ADDRESS}" "${ENV_FILE}"
dotenv_write_key YANZHANG_HTTP_PORT "${YANZHANG_HTTP_PORT}" "${ENV_FILE}"
dotenv_write_key GONGWEN_HTTP_PORT "${YANZHANG_HTTP_PORT}" "${ENV_FILE}"
dotenv_write_key YANZHANG_HTTPS_PORT "${YANZHANG_HTTPS_PORT}" "${ENV_FILE}"
dotenv_write_key GONGWEN_HTTPS_PORT "${YANZHANG_HTTPS_PORT}" "${ENV_FILE}"
dotenv_write_key YANZHANG_ALLOWED_HOSTS "${YANZHANG_ALLOWED_HOSTS}" "${ENV_FILE}"
dotenv_write_key GONGWEN_ALLOWED_HOSTS "${YANZHANG_ALLOWED_HOSTS}" "${ENV_FILE}"

export YANZHANG_ACCESS_TOKEN YANZHANG_MCP_ACCESS_TOKEN
export YANZHANG_SITE_ADDRESS YANZHANG_BIND_ADDRESS
export YANZHANG_HTTP_PORT YANZHANG_HTTPS_PORT YANZHANG_ALLOWED_HOSTS

if [ "${GENERATED_TOKEN}" -eq 1 ]; then
    echo "Generated a Web access token and saved it to ${ENV_FILE}."
fi
if [ "${GENERATED_MCP_TOKEN}" -eq 1 ]; then
    echo "Generated an independent MCP access token and saved it to ${ENV_FILE}."
fi

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" config --quiet
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" \
    up -d --build --remove-orphans --wait --wait-timeout 120
# The bind-mounted proxy configuration is outside the service hash.
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" \
    up -d --force-recreate --no-deps --wait --wait-timeout 60 proxy
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" ps

case "${YANZHANG_SITE_ADDRESS}" in
    :80)
        access_host=$(local_access_host "${YANZHANG_BIND_ADDRESS}")
        access_url="http://${access_host}:${YANZHANG_HTTP_PORT}"
        ;;
    *)
        if [ "${YANZHANG_HTTPS_PORT}" = "443" ]; then
            access_url="https://${YANZHANG_SITE_ADDRESS}"
        else
            access_url="https://${YANZHANG_SITE_ADDRESS}:${YANZHANG_HTTPS_PORT}"
        fi
        ;;
esac
echo ""
echo "Yanzhang v0.2 is starting at ${access_url}"
