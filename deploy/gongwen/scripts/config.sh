#!/bin/sh

# Parse deployment values as data. This file is sourced by the v0.2 operator
# scripts; it deliberately never sources the private environment file.
dotenv_read_key() {
    key=$1
    file=$2

    case "${key}" in
        YANZHANG_* | GONGWEN_* | TZ) ;;
        *)
            echo "Unsupported deployment env key: ${key}" >&2
            return 64
            ;;
    esac

    if [ ! -f "${file}" ]; then
        return 66
    fi
    if parsed_value=$(awk -v wanted="${key}" '
        index($0, wanted "=") == 1 {
            count += 1
            value = substr($0, length(wanted) + 2)
            sub(/\r$/, "", value)
        }
        END {
            if (count == 0) exit 66
            if (count > 1) exit 65
            if (length(value) >= 2) {
                first = substr(value, 1, 1)
                last = substr(value, length(value), 1)
                if ((first == "\"" && last == "\"") ||
                    (first == "\047" && last == "\047")) {
                    value = substr(value, 2, length(value) - 2)
                }
            }
            printf "%s", value
        }
    ' "${file}"); then
        printf '%s\n' "${parsed_value}"
        return 0
    else
        status=$?
    fi
    if [ "${status}" -eq 65 ]; then
        echo "${file} contains duplicate ${key} entries; keep exactly one." >&2
    fi
    return "${status}"
}

# New product-wide names take precedence over their GONGWEN_* compatibility
# aliases. Process environment values keep normal Compose precedence.
config_resolve() {
    suffix=$1
    file=$2
    default_value=${3-}
    case "${suffix}" in
        '' | *[!A-Z0-9_]*)
            echo "Invalid deployment configuration suffix: ${suffix}" >&2
            return 64
            ;;
    esac
    primary_key="YANZHANG_${suffix}"
    legacy_key="GONGWEN_${suffix}"

    if parsed_value=$(printenv "${primary_key}" 2>/dev/null); then
        printf '%s\n' "${parsed_value}"
        return 0
    fi
    if parsed_value=$(dotenv_read_key "${primary_key}" "${file}"); then
        printf '%s\n' "${parsed_value}"
        return 0
    else
        status=$?
        [ "${status}" -eq 66 ] || return "${status}"
    fi
    if parsed_value=$(printenv "${legacy_key}" 2>/dev/null); then
        printf '%s\n' "${parsed_value}"
        return 0
    fi
    if parsed_value=$(dotenv_read_key "${legacy_key}" "${file}"); then
        printf '%s\n' "${parsed_value}"
        return 0
    else
        status=$?
        [ "${status}" -eq 66 ] || return "${status}"
    fi
    printf '%s\n' "${default_value}"
}

dotenv_write_key() {
    key=$1
    value=$2
    file=$3
    case "${key}" in
        YANZHANG_* | GONGWEN_*) ;;
        *) return 64 ;;
    esac
    case "${value}" in
        *"
"*)
            echo "Deployment values must stay on one line." >&2
            return 65
            ;;
    esac
    output="${file}.tmp.$$"
    if ! awk -v wanted="${key}" -v replacement="${value}" '
        BEGIN { replaced = 0 }
        index($0, wanted "=") == 1 {
            if (!replaced) {
                print wanted "=" replacement
                replaced = 1
            }
            next
        }
        { print }
        END {
            if (!replaced) print wanted "=" replacement
        }
    ' "${file}" >"${output}"; then
        rm -f "${output}"
        return 1
    fi
    chmod 600 "${output}"
    mv "${output}" "${file}"
    chmod 600 "${file}"
}

generate_token() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    else
        od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
    fi
}

require_compose() {
    if ! command -v docker >/dev/null 2>&1; then
        echo "Docker is required." >&2
        return 1
    fi
    if ! docker compose version >/dev/null 2>&1; then
        echo "Docker Compose v2 is required." >&2
        return 1
    fi
}

configure_operation_lock() {
    default_lock=$1
    GONGWEN_OPERATION_LOCK_DIR=${YANZHANG_OPERATION_LOCK_DIR:-${GONGWEN_OPERATION_LOCK_DIR:-${default_lock}}}
    export GONGWEN_OPERATION_LOCK_DIR
}

# Bridge new-name values into the host-side v0.1 operator scripts. This keeps
# their hardened backup/restore behavior while Compose and the application use
# YANZHANG_* as the authoritative spelling.
export_legacy_runtime_config() {
    file=$1
    YANZHANG_ACCESS_TOKEN=$(config_resolve ACCESS_TOKEN "${file}" "")
    YANZHANG_MCP_ACCESS_TOKEN=$(config_resolve MCP_ACCESS_TOKEN "${file}" "")
    YANZHANG_SITE_ADDRESS=$(config_resolve SITE_ADDRESS "${file}" ":80")
    raw_bind_address=$(config_resolve BIND_ADDRESS "${file}" "127.0.0.1")
    YANZHANG_BIND_ADDRESS=$(normalize_bind_address "${raw_bind_address}")
    YANZHANG_HTTP_PORT=$(config_resolve HTTP_PORT "${file}" "8080")
    YANZHANG_HTTPS_PORT=$(config_resolve HTTPS_PORT "${file}" "8443")
    YANZHANG_ALLOWED_HOSTS=$(
        config_resolve ALLOWED_HOSTS "${file}" "127.0.0.1,localhost,[::1]"
    )

    GONGWEN_ACCESS_TOKEN=${YANZHANG_ACCESS_TOKEN}
    GONGWEN_MCP_ACCESS_TOKEN=${YANZHANG_MCP_ACCESS_TOKEN}
    GONGWEN_SITE_ADDRESS=${YANZHANG_SITE_ADDRESS}
    GONGWEN_BIND_ADDRESS=${YANZHANG_BIND_ADDRESS}
    GONGWEN_HTTP_PORT=${YANZHANG_HTTP_PORT}
    GONGWEN_HTTPS_PORT=${YANZHANG_HTTPS_PORT}
    GONGWEN_ALLOWED_HOSTS=${YANZHANG_ALLOWED_HOSTS}
    YANZHANG_ENV_FILE=${file}
    GONGWEN_ENV_FILE=${file}

    export YANZHANG_ACCESS_TOKEN YANZHANG_MCP_ACCESS_TOKEN
    export YANZHANG_SITE_ADDRESS YANZHANG_BIND_ADDRESS
    export YANZHANG_HTTP_PORT YANZHANG_HTTPS_PORT YANZHANG_ALLOWED_HOSTS
    export GONGWEN_ACCESS_TOKEN GONGWEN_MCP_ACCESS_TOKEN
    export GONGWEN_SITE_ADDRESS GONGWEN_BIND_ADDRESS
    export GONGWEN_HTTP_PORT GONGWEN_HTTPS_PORT GONGWEN_ALLOWED_HOSTS
    export YANZHANG_ENV_FILE GONGWEN_ENV_FILE
    unset raw_bind_address
}
