#!/bin/sh

# Only these deployment keys are read by host-side scripts. Values are parsed
# as data rather than sourced as shell code; Compose reads all other settings.
dotenv_read() {
    key=$1
    file=$2
    default_value=${3-}

    case "${key}" in
        GONGWEN_ACCESS_TOKEN | GONGWEN_MCP_ACCESS_TOKEN | \
            GONGWEN_SITE_ADDRESS | GONGWEN_BIND_ADDRESS | \
            GONGWEN_HTTP_PORT | GONGWEN_HTTPS_PORT | GONGWEN_ALLOWED_HOSTS) ;;
        *)
            echo "Unsupported deployment env key: ${key}" >&2
            return 64
            ;;
    esac

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
    case "${status}" in
        66)
            printf '%s\n' "${default_value}"
            return 0
            ;;
        65)
            echo "${file} contains duplicate ${key} entries; keep exactly one." >&2
            return 65
            ;;
        *)
            echo "Failed to read ${key} from ${file}." >&2
            return "${status}"
            ;;
    esac
}

normalize_bind_address() {
    case "$1" in
        [Ll][Oo][Cc][Aa][Ll][Hh][Oo][Ss][Tt]) printf '%s\n' '127.0.0.1' ;;
        ::1 | \[::1\]) printf '%s\n' '[::1]' ;;
        :: | \[::\]) printf '%s\n' '[::]' ;;
        \[*\]) printf '%s\n' "$1" ;;
        *:*) printf '[%s]\n' "$1" ;;
        *) printf '%s\n' "$1" ;;
    esac
}

bind_address_is_loopback() {
    case "$(normalize_bind_address "$1")" in
        127.* | \[::1\]) return 0 ;;
        *) return 1 ;;
    esac
}

local_access_host() {
    case "$(normalize_bind_address "$1")" in
        \[::1\]) printf '%s\n' '[::1]' ;;
        127.*) normalize_bind_address "$1" ;;
        *) printf '%s\n' '127.0.0.1' ;;
    esac
}

comma_list_contains() {
    printf '%s\n' "$1" | awk -F, -v expected="$2" '
        {
            for (field_index = 1; field_index <= NF; field_index += 1) {
                value = $field_index
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
                if (value == expected) found = 1
            }
        }
        END { exit(found ? 0 : 1) }
    '
}

operation_lock_owner_is_alive() {
    owner_pid=$1
    case "${owner_pid}" in
        '' | *[!0-9]*) return 1 ;;
    esac
    [ "${owner_pid}" -gt 1 ] 2>/dev/null || return 1
    kill -0 "${owner_pid}" 2>/dev/null
}

# start, backup and restore all change deployment state, so only one of them may
# run at a time. mkdir/mv provide atomic acquisition and stale-lock claiming.
operation_lock_acquire() {
    GONGWEN_OPERATION_LOCK_DIR=${GONGWEN_OPERATION_LOCK_DIR:-"${SCRIPT_DIR}/.operation.lock"}
    GONGWEN_OPERATION_LOCK_ACQUIRED=0
    if [ "${GONGWEN_OPERATION_LOCK_HELD:-0}" = "1" ]; then
        return 0
    fi

    missing_pid_rechecked=0
    recovery_attempt=0
    while [ "${recovery_attempt}" -lt 5 ]; do
        if mkdir "${GONGWEN_OPERATION_LOCK_DIR}" 2>/dev/null; then
            if ! printf '%s\n' "$$" >"${GONGWEN_OPERATION_LOCK_DIR}/pid"; then
                rm -f "${GONGWEN_OPERATION_LOCK_DIR}/pid"
                rmdir "${GONGWEN_OPERATION_LOCK_DIR}" 2>/dev/null || true
                return 73
            fi
            GONGWEN_OPERATION_LOCK_ACQUIRED=1
            GONGWEN_OPERATION_LOCK_HELD=1
            export GONGWEN_OPERATION_LOCK_HELD
            return 0
        fi

        if [ ! -d "${GONGWEN_OPERATION_LOCK_DIR}" ] || \
            [ -L "${GONGWEN_OPERATION_LOCK_DIR}" ]; then
            echo "Deployment lock path is not a directory: ${GONGWEN_OPERATION_LOCK_DIR}" >&2
            return 73
        fi

        owner_pid=$(cat "${GONGWEN_OPERATION_LOCK_DIR}/pid" 2>/dev/null || true)
        if operation_lock_owner_is_alive "${owner_pid}"; then
            echo "Another gongwen deployment operation is active (PID ${owner_pid})." >&2
            return 73
        fi

        # A process may have created the directory but not written its PID yet.
        # Give that narrow acquisition window one recheck before stale recovery.
        if [ -z "${owner_pid}" ] && [ "${missing_pid_rechecked}" -eq 0 ]; then
            missing_pid_rechecked=1
            sleep 1
            continue
        fi

        recovery_attempt=$((recovery_attempt + 1))
        stale_lock="${GONGWEN_OPERATION_LOCK_DIR}.stale.$$.$recovery_attempt"
        if [ -e "${stale_lock}" ] || [ -L "${stale_lock}" ]; then
            continue
        fi
        if mv "${GONGWEN_OPERATION_LOCK_DIR}" "${stale_lock}" 2>/dev/null; then
            rm -f "${stale_lock}/pid"
            if ! rmdir "${stale_lock}" 2>/dev/null; then
                echo "Recovered the lock; inspect leftover directory ${stale_lock}." >&2
            else
                echo "Recovered stale deployment lock owned by PID ${owner_pid:-unknown}." >&2
            fi
            missing_pid_rechecked=0
        fi
    done

    echo "Deployment lock remained busy: ${GONGWEN_OPERATION_LOCK_DIR}" >&2
    return 73
}

operation_lock_release() {
    if [ "${GONGWEN_OPERATION_LOCK_ACQUIRED:-0}" = "1" ]; then
        owner_pid=$(cat "${GONGWEN_OPERATION_LOCK_DIR}/pid" 2>/dev/null || true)
        if [ "${owner_pid}" = "$$" ]; then
            rm -f "${GONGWEN_OPERATION_LOCK_DIR}/pid"
            rmdir "${GONGWEN_OPERATION_LOCK_DIR}" 2>/dev/null || true
        else
            echo "Deployment lock ownership changed; leaving it in place." >&2
        fi
        GONGWEN_OPERATION_LOCK_ACQUIRED=0
        GONGWEN_OPERATION_LOCK_HELD=0
        export GONGWEN_OPERATION_LOCK_HELD
    fi
}
