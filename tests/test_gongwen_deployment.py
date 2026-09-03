"""Static contracts for the personal production deployment bundle."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import stat
import subprocess
from pathlib import Path

_ROOT = Path(__file__).parents[1]
_DEPLOY = _ROOT / "deploy" / "gongwen"
_PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^ ;\\]+)")


def _pins(value: str) -> dict[str, str]:
    return {
        re.sub(r"[-_.]+", "-", match.group(1)).casefold(): match.group(2)
        for line in value.splitlines()
        if (match := _PIN.match(line)) is not None
    }


def test_deployment_requirements_match_the_checked_in_uv_lock(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        return
    exported = tmp_path / "requirements.lock"
    environment = os.environ.copy()
    environment["UV_CACHE_DIR"] = str(tmp_path / "uv-cache")
    subprocess.run(
        [
            uv,
            "export",
            "--format",
            "requirements.txt",
            "--no-dev",
            "--no-emit-project",
            "--locked",
            "--output-file",
            str(exported),
        ],
        cwd=_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    checked_in = (_DEPLOY / "requirements.lock").read_text(encoding="utf-8").splitlines()
    regenerated = exported.read_text(encoding="utf-8").splitlines()
    assert checked_in[2:] == regenerated[2:]


def test_build_lock_matches_its_inputs_and_has_no_runtime_version_conflicts() -> None:
    runtime_text = (_DEPLOY / "requirements.lock").read_text(encoding="utf-8")
    build_input_text = (_DEPLOY / "requirements-build.in").read_text(encoding="utf-8")
    build_lock_text = (_DEPLOY / "requirements-build.lock").read_text(encoding="utf-8")
    runtime_pins = _pins(runtime_text)
    build_input_pins = _pins(build_input_text)
    build_lock_pins = _pins(build_lock_text)

    assert build_input_pins == build_lock_pins
    assert "hatchling" in build_lock_pins
    shared = runtime_pins.keys() & build_lock_pins.keys()
    assert {name: (runtime_pins[name], build_lock_pins[name]) for name in shared} == {
        name: (runtime_pins[name], runtime_pins[name]) for name in shared
    }


def test_deployment_scripts_are_valid_and_keep_large_backups_off_tmpfs() -> None:
    scripts = [
        "common.sh",
        "start.sh",
        "show-token.sh",
        "smoke.sh",
        "backup.sh",
        "restore.sh",
    ]
    for name in scripts:
        subprocess.run(["sh", "-n", str(_DEPLOY / name)], check=True)

    backup = (_DEPLOY / "backup.sh").read_text(encoding="utf-8")
    restore = (_DEPLOY / "restore.sh").read_text(encoding="utf-8")
    assert 'REMOTE_FILE="/var/lib/gongwen/' in backup
    assert 'REMOTE_FILE="/tmp/' not in backup
    assert 'PARTIAL_FILE="${LOCAL_FILE}.partial"' in backup
    assert '--volume "${PARTIAL_FILE}:/verify/gongwen.sqlite3:ro"' in backup
    assert 'mv "${PARTIAL_FILE}" "${LOCAL_FILE}"' in backup
    assert '"${REMOTE_FILE}-wal" "${REMOTE_FILE}-shm"' in backup
    assert "operation_lock_acquire\ntrap backup_exit EXIT" in backup
    assert "operation_lock_acquire\ntrap restart_after_failure EXIT" in restore
    assert "trap backup_exit EXIT" in backup
    assert "operation_lock_acquire" in backup


def test_deployment_uses_one_protected_non_root_worker_and_atomic_token_update() -> None:
    compose = (_DEPLOY / "compose.yaml").read_text(encoding="utf-8")
    dockerfile = (_DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    start = (_DEPLOY / "start.sh").read_text(encoding="utf-8")
    caddy = (_DEPLOY / "Caddyfile").read_text(encoding="utf-8")
    common = (_DEPLOY / "common.sh").read_text(encoding="utf-8")

    assert "GONGWEN_ENV: production" in compose
    assert "GONGWEN_WORKERS: 1" in compose
    assert "GONGWEN_ACCESS_LOG: ${GONGWEN_ACCESS_LOG:-false}" in compose
    assert "GONGWEN_ACCESS_TOKEN:" in compose
    assert "GONGWEN_MCP_ACCESS_TOKEN:" in compose
    assert "GONGWEN_CLIENT_LLM_BASE_URL_ALLOWLIST:" in compose
    assert "GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH:" in compose
    assert "GONGWEN_ALLOW_UNAUTHENTICATED:" not in compose
    assert "read_only: true" in compose
    assert "cap_drop:" in compose and "- ALL" in compose
    assert "USER 10001:10001" in dockerfile
    assert "COPY deploy/gongwen/requirements.lock" in dockerfile
    assert "COPY deploy/gongwen/requirements-build.lock" in dockerfile
    assert "-r /tmp/gongwen-requirements-build.lock" in dockerfile
    assert "-r /tmp/gongwen-requirements.lock" in dockerfile
    assert "pip install --no-deps --no-build-isolation ." in dockerfile
    assert "pip install --upgrade pip" not in dockerfile
    assert "PIP_DEFAULT_TIMEOUT=60" in dockerfile
    assert "PIP_RETRIES=10" in dockerfile
    assert dockerfile.index("COPY deploy/gongwen/requirements.lock") < dockerfile.index("COPY . .")
    assert dockerfile.index("--require-hashes") < dockerfile.index(
        "pip install --no-deps --no-build-isolation ."
    )
    assert "APP_UID" not in dockerfile and "APP_GID" not in dockerfile
    assert "GONGWEN_APP_UID" not in compose and "GONGWEN_APP_GID" not in compose
    assert "GONGWEN_ACCESS_TOKEN=%s" not in start
    assert 'mv "${ENV_TMP}" "${ENV_FILE}"' in start
    assert "contains duplicate ${key}" in common
    assert "A non-loopback bind requires an HTTPS site address" in start
    assert "one hostname without a scheme or port" in start
    assert "up -d --build --remove-orphans --wait --wait-timeout 120" in start
    assert "up -d --force-recreate --no-deps --wait --wait-timeout 60 proxy" in start
    assert "GONGWEN_ALLOWED_HOSTS must include" in start
    assert 'echo "Generated access token: ${GONGWEN_ACCESS_TOKEN}"' not in start
    assert "Generated a Web access token and saved it" in start
    assert '. "${ENV_FILE}"' not in start
    assert "dotenv_read GONGWEN_ACCESS_TOKEN" in start
    assert "dotenv_read GONGWEN_MCP_ACCESS_TOKEN" in start
    assert "GONGWEN_MCP_ACCESS_TOKEN must be independent" in start
    assert 'echo "Generated MCP access token: ${GONGWEN_MCP_ACCESS_TOKEN}"' not in start
    assert "Generated an independent MCP access token" in start
    smoke = (_DEPLOY / "smoke.sh").read_text(encoding="utf-8")
    assert '. "${ENV_FILE}"' not in smoke
    assert "dotenv_read GONGWEN_ACCESS_TOKEN" in smoke
    assert "dotenv_read GONGWEN_MCP_ACCESS_TOKEN" in smoke
    assert smoke.count('"${BASE_URL}/mcp"') == 3
    assert '--header @"${WEB_AUTH_HEADER}"' in smoke
    assert '--header @"${MCP_AUTH_HEADER}"' in smoke
    assert '--header "Authorization: Bearer ${GONGWEN_ACCESS_TOKEN}"' not in smoke
    assert '--header "Authorization: Bearer ${GONGWEN_MCP_ACCESS_TOKEN}"' not in smoke
    assert "unset GONGWEN_ACCESS_TOKEN GONGWEN_MCP_ACCESS_TOKEN" in smoke
    assert "Accept: application/json, text/event-stream" in smoke
    assert "Content-Type: application/json" in smoke
    assert '"method":"initialize"' in smoke
    assert '"protocolVersion":"2025-06-18"' in smoke
    assert 'mkdir "${GONGWEN_OPERATION_LOCK_DIR}"' in common
    assert "operation_lock_owner_is_alive" in common
    assert "Recovered stale deployment lock" in common
    assert "{$GONGWEN_PROXY_MAX_REQUEST_SIZE:2MB}" in caddy
    assert "Strict-Transport-Security" not in caddy
    assert "http://127.0.0.1:2019" in caddy
    assert "header_up Host 127.0.0.1" in caddy
    assert "http://127.0.0.1:2019/api/ready" in compose
    assert "NO_PROXY: gongwen,localhost,127.0.0.1,::1" in compose
    assert "no_proxy: gongwen,localhost,127.0.0.1,::1" in compose
    assert '- -Y\n        - "off"\n        - -q' in compose
    assert '["CMD", "caddy", "validate"' not in compose

    env_example = (_DEPLOY / "env.example").read_text(encoding="utf-8")
    readme = (_DEPLOY / "README.md").read_text(encoding="utf-8")
    assert "GONGWEN_MCP_ACCESS_TOKEN=" in env_example
    assert "GONGWEN_ACCESS_LOG=false" in env_example
    assert "https://DOMAIN/mcp" in readme
    assert "GONGWEN_MCP_ACCESS_TOKEN" in readme
    assert "GONGWEN_CLIENT_LLM_BASE_URL_ALLOWLIST=" in env_example
    assert "GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH=false" in env_example
    assert "GONGWEN_CLIENT_LLM_BASE_URL_ALLOWLIST" in readme
    assert "不限制由运维人员设置的 `GONGWEN_LLM_BASE_URL`" in readme

    requirements = (_DEPLOY / "requirements.lock").read_text(encoding="utf-8")
    assert "uv export --format requirements.txt --no-dev --no-emit-project --locked" in requirements
    assert "--hash=sha256:" in requirements
    for package in ("httpx", "pydantic", "starlette", "uvicorn"):
        assert f"{package}==" in requirements
    build_requirements = (_DEPLOY / "requirements-build.lock").read_text(encoding="utf-8")
    assert "hatchling==1.31.0" in build_requirements
    assert "--hash=sha256:" in build_requirements
    assert "--constraints deploy/gongwen/requirements.lock" in build_requirements


def test_dotenv_parser_treats_values_as_data_and_rejects_duplicates(tmp_path: Path) -> None:
    sentinel = tmp_path / "executed"
    env_file = tmp_path / ".env"
    literal = f"$(touch {sentinel})"
    env_file.write_text(f"GONGWEN_ACCESS_TOKEN={literal}\n", encoding="utf-8")
    common = _DEPLOY / "common.sh"
    command = (
        f". {shlex.quote(str(common))}; "
        f"dotenv_read GONGWEN_ACCESS_TOKEN {shlex.quote(str(env_file))}"
    )

    result = subprocess.run(
        ["sh", "-c", command],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == literal
    assert not sentinel.exists()

    env_file.write_text(
        "GONGWEN_ACCESS_TOKEN=first\nGONGWEN_ACCESS_TOKEN=second\n",
        encoding="utf-8",
    )
    duplicate = subprocess.run(
        ["sh", "-c", command],
        check=False,
        capture_output=True,
        text=True,
    )
    assert duplicate.returncode == 65
    assert "duplicate GONGWEN_ACCESS_TOKEN" in duplicate.stderr

    mcp_command = (
        f". {shlex.quote(str(common))}; "
        f"dotenv_read GONGWEN_MCP_ACCESS_TOKEN {shlex.quote(str(env_file))}"
    )
    env_file.write_text(f"GONGWEN_MCP_ACCESS_TOKEN={literal}\n", encoding="utf-8")
    mcp_result = subprocess.run(
        ["sh", "-c", mcp_command],
        check=True,
        capture_output=True,
        text=True,
    )
    assert mcp_result.stdout.strip() == literal
    assert not sentinel.exists()


def test_start_generates_independent_tokens_without_printing_them(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_docker.chmod(0o755)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "GONGWEN_ACCESS_TOKEN=CHANGE_ME_WITH_AT_LEAST_32_RANDOM_CHARACTERS",
                "GONGWEN_SITE_ADDRESS=:80",
                "GONGWEN_BIND_ADDRESS=127.0.0.1",
                "GONGWEN_HTTP_PORT=18080",
                "GONGWEN_HTTPS_PORT=18443",
                "GONGWEN_ALLOWED_HOSTS=127.0.0.1,localhost,[::1]",
                "",
            )
        ),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "GONGWEN_ENV_FILE": str(env_file),
            "GONGWEN_OPERATION_LOCK_DIR": str(tmp_path / ".operation.lock"),
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
        }
    )

    first = subprocess.run(
        ["sh", str(_DEPLOY / "start.sh")],
        cwd=_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    web_token_lines = [
        line
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if line.startswith("GONGWEN_ACCESS_TOKEN=")
    ]
    mcp_token_lines = [
        line
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if line.startswith("GONGWEN_MCP_ACCESS_TOKEN=")
    ]
    assert len(web_token_lines) == 1
    assert len(mcp_token_lines) == 1
    web_token = web_token_lines[0].partition("=")[2]
    mcp_token = mcp_token_lines[0].partition("=")[2]
    assert len(web_token.encode("utf-8")) >= 32
    assert len(mcp_token.encode("utf-8")) >= 32
    assert mcp_token != web_token
    assert web_token not in first.stdout
    assert web_token not in first.stderr
    assert mcp_token not in first.stdout
    assert mcp_token not in first.stderr
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600

    second = subprocess.run(
        ["sh", str(_DEPLOY / "start.sh")],
        cwd=_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert f"GONGWEN_MCP_ACCESS_TOKEN={mcp_token}" in env_file.read_text(encoding="utf-8")
    assert mcp_token not in second.stdout
    assert mcp_token not in second.stderr


def test_show_token_rejects_noninteractive_output_without_disclosing_secret(
    tmp_path: Path,
) -> None:
    secret = "web-token-" + ("s" * 32)
    env_file = tmp_path / ".env"
    env_file.write_text(f"GONGWEN_ACCESS_TOKEN={secret}\n", encoding="utf-8")
    environment = os.environ.copy()
    environment["GONGWEN_ENV_FILE"] = str(env_file)

    result = subprocess.run(
        ["sh", str(_DEPLOY / "show-token.sh"), "web"],
        cwd=_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert "interactive terminal" in result.stderr


def test_operation_lock_recovers_a_dead_owner_pid(tmp_path: Path) -> None:
    lock_dir = tmp_path / ".operation.lock"
    lock_dir.mkdir()
    (lock_dir / "pid").write_text("99999999\n", encoding="utf-8")
    common = _DEPLOY / "common.sh"
    command = "; ".join(
        (
            "set -eu",
            f"SCRIPT_DIR={shlex.quote(str(tmp_path))}",
            f". {shlex.quote(str(common))}",
            "operation_lock_acquire",
            'test "$(cat "${GONGWEN_OPERATION_LOCK_DIR}/pid")" = "$$"',
            "operation_lock_release",
            'test ! -e "${GONGWEN_OPERATION_LOCK_DIR}"',
        )
    )

    result = subprocess.run(
        ["sh", "-c", command],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Recovered stale deployment lock" in result.stderr

    lock_dir.mkdir()
    (lock_dir / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    busy = subprocess.run(
        [
            "sh",
            "-c",
            "; ".join(
                (
                    f"SCRIPT_DIR={shlex.quote(str(tmp_path))}",
                    f". {shlex.quote(str(common))}",
                    "operation_lock_acquire",
                )
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert busy.returncode == 73
    assert "is active" in busy.stderr


def test_bind_address_helpers_normalize_ipv4_ipv6_and_localhost() -> None:
    common = _DEPLOY / "common.sh"
    command = "; ".join(
        (
            f". {shlex.quote(str(common))}",
            'test "$(normalize_bind_address localhost)" = "127.0.0.1"',
            'test "$(normalize_bind_address ::1)" = "[::1]"',
            'test "$(normalize_bind_address 2001:db8::8)" = "[2001:db8::8]"',
            'test "$(local_access_host ::1)" = "[::1]"',
            "bind_address_is_loopback 127.0.0.2",
            "! bind_address_is_loopback 0.0.0.0",
            "comma_list_contains '127.0.0.1, gongwen.example.com' gongwen.example.com",
            "! comma_list_contains '127.0.0.1, localhost' gongwen.example.com",
        )
    )
    subprocess.run(["sh", "-c", command], check=True)
