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
    assert "`GONGWEN_ALLOW_INSECURE_LOCAL_MODEL=true`" in readme

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


def test_v02_deployment_uses_primary_names_and_local_first_defaults() -> None:
    compose = (_DEPLOY / "compose.yaml").read_text(encoding="utf-8")
    caddy = (_DEPLOY / "Caddyfile").read_text(encoding="utf-8")
    env_example = (_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "YANZHANG_ENV: production" in compose
    assert "YANZHANG_DATA_DIR: /var/lib/gongwen" in compose
    assert "GONGWEN_DATA_DIR: /var/lib/gongwen" in compose
    assert "YANZHANG_ACCESS_TOKEN:" in compose
    assert "GONGWEN_ACCESS_TOKEN:" in compose
    assert "${YANZHANG_ACCESS_TOKEN:-${GONGWEN_ACCESS_TOKEN:-" in compose
    assert "${YANZHANG_BIND_ADDRESS:-${GONGWEN_BIND_ADDRESS:-127.0.0.1}}" in compose
    assert "${YANZHANG_DATA_VOLUME:-${GONGWEN_DATA_VOLUME:-gongwen-web-data}}" in compose
    assert "- gongwen-data:/var/lib/gongwen" in compose
    assert "{$YANZHANG_SITE_ADDRESS}" in caddy
    assert "{$YANZHANG_PROXY_MAX_REQUEST_SIZE:2MB}" in caddy

    assert "YANZHANG_ENV=development" in env_example
    assert "YANZHANG_HOST=127.0.0.1" in env_example
    assert "YANZHANG_BIND_ADDRESS=127.0.0.1" in env_example
    assert "YANZHANG_SITE_ADDRESS=:80" in env_example
    assert "YANZHANG_DATA_VOLUME=gongwen-web-data" in env_example
    assert "YANZHANG_ACCESS_TOKEN=CHANGE_ME_" in env_example
    active_lines = [line for line in env_example.splitlines() if line and not line.startswith("#")]
    assert not any(line.startswith("GONGWEN_") for line in active_lines)


def test_v02_operator_scripts_are_valid_private_and_cover_lifecycle() -> None:
    scripts_dir = _DEPLOY / "scripts"
    script_names = ("start.sh", "backup.sh", "restore.sh", "upgrade.sh", "health.sh")
    for name in (*script_names, "config.sh"):
        path = scripts_dir / name
        subprocess.run(["sh", "-n", str(path)], check=True)
        assert path.is_file()
    for name in script_names:
        assert (scripts_dir / name).stat().st_mode & stat.S_IXUSR

    config = (scripts_dir / "config.sh").read_text(encoding="utf-8")
    start = (scripts_dir / "start.sh").read_text(encoding="utf-8")
    backup = (scripts_dir / "backup.sh").read_text(encoding="utf-8")
    restore = (scripts_dir / "restore.sh").read_text(encoding="utf-8")
    upgrade = (scripts_dir / "upgrade.sh").read_text(encoding="utf-8")
    health = (scripts_dir / "health.sh").read_text(encoding="utf-8")

    assert 'primary_key="YANZHANG_${suffix}"' in config
    assert 'legacy_key="GONGWEN_${suffix}"' in config
    assert '. "${ENV_FILE}"' not in config + start + backup + restore + health
    assert 'chmod 600 "${ENV_FILE}"' in start
    assert "dotenv_write_key YANZHANG_ACCESS_TOKEN" in start
    assert "YANZHANG_MCP_ACCESS_TOKEN must be independent" in start
    assert 'echo "Generated a Web access token: ${YANZHANG_ACCESS_TOKEN}"' not in start
    assert "--remove-orphans --wait --wait-timeout 120" in start
    assert 'exec "${DEPLOY_DIR}/backup.sh"' in backup
    assert 'exec "${DEPLOY_DIR}/restore.sh"' in restore
    assert upgrade.index('"${SCRIPT_DIR}/backup.sh"') < upgrade.index("build --pull gongwen")
    assert '"${SCRIPT_DIR}/health.sh"' in upgrade
    assert "/api/v2/projects?limit=1" in health
    assert "/api/v2/bootstrap" in health
    assert '--header @"${AUTH_HEADER}"' in health
    assert "unset YANZHANG_ACCESS_TOKEN GONGWEN_ACCESS_TOKEN" in health


def test_v02_config_parser_prefers_primary_name_and_treats_values_as_data(
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "executed"
    env_file = tmp_path / ".env"
    literal = f"$(touch {sentinel})"
    env_file.write_text(
        "\n".join(
            (
                "GONGWEN_ACCESS_TOKEN=legacy-value",
                f"YANZHANG_ACCESS_TOKEN={literal}",
                "",
            )
        ),
        encoding="utf-8",
    )
    config = _DEPLOY / "scripts" / "config.sh"
    command = (
        f". {shlex.quote(str(config))}; "
        f"config_resolve ACCESS_TOKEN {shlex.quote(str(env_file))} fallback"
    )
    environment = os.environ.copy()
    environment.pop("YANZHANG_ACCESS_TOKEN", None)
    environment.pop("GONGWEN_ACCESS_TOKEN", None)
    result = subprocess.run(
        ["sh", "-c", command],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == literal
    assert not sentinel.exists()

    env_file.write_text("GONGWEN_ACCESS_TOKEN=legacy-value\n", encoding="utf-8")
    legacy = subprocess.run(
        ["sh", "-c", command],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert legacy.stdout.strip() == "legacy-value"

    env_file.write_text(
        "YANZHANG_ACCESS_TOKEN=first\nYANZHANG_ACCESS_TOKEN=second\n",
        encoding="utf-8",
    )
    duplicate = subprocess.run(
        ["sh", "-c", command],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert duplicate.returncode == 65
    assert "duplicate YANZHANG_ACCESS_TOKEN" in duplicate.stderr


def test_v02_start_generates_primary_tokens_without_printing_them(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_docker.chmod(0o755)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "YANZHANG_ACCESS_TOKEN=CHANGE_ME_WITH_AT_LEAST_32_RANDOM_CHARACTERS",
                "YANZHANG_MCP_ACCESS_TOKEN=CHANGE_ME_WITH_AN_INDEPENDENT_32_BYTE_RANDOM_TOKEN",
                "YANZHANG_SITE_ADDRESS=:80",
                "YANZHANG_BIND_ADDRESS=127.0.0.1",
                "YANZHANG_HTTP_PORT=18080",
                "YANZHANG_HTTPS_PORT=18443",
                "YANZHANG_ALLOWED_HOSTS=127.0.0.1,localhost,[::1]",
                "",
            )
        ),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "YANZHANG_ENV_FILE": str(env_file),
            "YANZHANG_OPERATION_LOCK_DIR": str(tmp_path / ".operation.lock"),
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
        }
    )
    for key in (
        "YANZHANG_ACCESS_TOKEN",
        "YANZHANG_MCP_ACCESS_TOKEN",
        "GONGWEN_ACCESS_TOKEN",
        "GONGWEN_MCP_ACCESS_TOKEN",
    ):
        environment.pop(key, None)

    result = subprocess.run(
        ["sh", str(_DEPLOY / "scripts" / "start.sh")],
        cwd=_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    values = {
        key: value
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if "=" in line
        for key, _, value in (line.partition("="),)
    }
    web_token = values["YANZHANG_ACCESS_TOKEN"]
    mcp_token = values["YANZHANG_MCP_ACCESS_TOKEN"]
    assert len(web_token) >= 64
    assert len(mcp_token) >= 64
    assert web_token != mcp_token
    assert web_token not in result.stdout + result.stderr
    assert mcp_token not in result.stdout + result.stderr
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_v02_compose_primary_values_override_legacy_aliases(tmp_path: Path) -> None:
    docker = shutil.which("docker")
    if docker is None:
        return
    available = subprocess.run(
        [docker, "compose", "version"],
        check=False,
        capture_output=True,
        text=True,
    )
    if available.returncode != 0:
        return
    env_file = tmp_path / ".env"
    primary_token = "FIXTURE_PRIMARY_" + ("p" * 32)
    legacy_token = "FIXTURE_LEGACY_" + ("l" * 32)
    env_file.write_text(
        "\n".join(
            (
                "YANZHANG_BIND_ADDRESS=127.0.0.2",
                "GONGWEN_BIND_ADDRESS=127.0.0.3",
                "YANZHANG_DATA_VOLUME=yanzhang-v2-fixture-data",
                "GONGWEN_DATA_VOLUME=legacy-fixture-data",
                f"YANZHANG_ACCESS_TOKEN={primary_token}",
                f"GONGWEN_ACCESS_TOKEN={legacy_token}",
                "",
            )
        ),
        encoding="utf-8",
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("YANZHANG_", "GONGWEN_"))
    }
    rendered = subprocess.run(
        [
            docker,
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(_DEPLOY / "compose.yaml"),
            "config",
        ],
        cwd=_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "host_ip: 127.0.0.2" in rendered
    assert "name: yanzhang-v2-fixture-data" in rendered
    assert f"YANZHANG_ACCESS_TOKEN: {primary_token}" in rendered
    assert f"GONGWEN_ACCESS_TOKEN: {primary_token}" in rendered
    assert legacy_token not in rendered
