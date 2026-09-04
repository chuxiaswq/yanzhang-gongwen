"""Contracts for the standalone public preview bundle."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

from gongwen_mcp.writing_server import YANZHANG_TOOL_NAMES

ROOT = Path(__file__).resolve().parents[1]


def test_distribution_metadata_is_standalone_and_pep639() -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = configuration["project"]
    assert project["name"] == "yanzhang-gongwen"
    assert project["version"] == "0.2.0b1"
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE"]
    assert configuration["build-system"]["requires"] == ["hatchling>=1.27"]
    wheel = configuration["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == [
        "gongwen_web",
        "gongwen_mcp",
        "yanzhang",
        "yanzhang_core",
        "yanzhang_academic",
    ]
    assert set(project["scripts"]) == {
        "gongwen-admin",
        "gongwen-demo",
        "gongwen-mcp",
        "gongwen-web",
        "yanzhang-mcp",
        "yanzhang-web",
    }
    direct_names = {
        requirement.split(">", 1)[0].split(";", 1)[0].strip()
        for requirement in project["dependencies"]
    }
    assert direct_names == {
        "cryptography",
        "httpx",
        "mcp",
        "pypdf",
        "pydantic",
        "reportlab",
        "starlette",
        "tzdata",
        "uvicorn",
    }


def test_docker_context_keeps_build_inputs_and_excludes_private_state() -> None:
    patterns = {
        line.strip()
        for line in (ROOT / "deploy/gongwen/Dockerfile.dockerignore")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "docs/" not in patterns
    assert {
        "deploy/gongwen/.env",
        "deploy/gongwen/backups/",
        ".gongwen-data/",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "*.pem",
        "*.key",
        "*.p12",
        "*.pfx",
        "*.sqlite",
        "*.sqlite3",
        "*.sqlite3-*",
        "*.doc",
        "*.docx",
        "*.pdf",
        "*.zip",
        "*.png",
        "*.mp4",
        "*.log",
    } <= patterns


def test_connector_archive_is_deterministic_and_versioned(tmp_path: Path) -> None:
    command = [sys.executable, str(ROOT / "scripts/package_connector.py"), str(tmp_path)]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    archive = tmp_path / "yanzhang-workbuddy-connector-0.2.0-preview.1.zip"
    first = archive.read_bytes()
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    assert archive.read_bytes() == first
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {
            "yanzhang-workbuddy-connector/connector-meta.json",
            "yanzhang-workbuddy-connector/icon.svg",
            "yanzhang-workbuddy-connector/mcp.json",
            "yanzhang-workbuddy-connector/skills/gongwen/SKILL.md",
            "yanzhang-workbuddy-connector/token-schema.json",
        }
    metadata = json.loads(
        (ROOT / "integrations/workbuddy-gongwen/connector-meta.json").read_text(encoding="utf-8")
    )
    assert metadata["version"] == "0.2.0-preview.1"
    skill = (ROOT / "integrations/workbuddy-gongwen/skills/gongwen/SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "version: 0.2.0-preview.1" in skill
    assert "author: Yanzhang" in skill
    allowed_line = next(line for line in skill.splitlines() if line.startswith("allowed-tools:"))
    allowed = [item.strip() for item in allowed_line.partition(":")[2].split(",")]
    assert tuple(item for item in allowed if item.startswith("yanzhang_")) == YANZHANG_TOOL_NAMES
    assert len(allowed) == 71
    assert len(set(allowed)) == len(allowed)


def test_github_workflows_pin_actions_and_audit_every_archive() -> None:
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    for workflow in (ci, release):
        action_lines = [line.strip() for line in workflow.splitlines() if "uses:" in line]
        assert action_lines
        for line in action_lines:
            revision = line.partition("@")[2].partition(" ")[0]
            assert len(revision) == 40
            assert all(character in "0123456789abcdef" for character in revision)
        assert "scripts/release_audit.py --artifacts dist" in workflow
        assert "scripts/package_connector.py dist" in workflow
        assert "scripts/write_checksums.py dist" in workflow
        assert 'PYTHONDONTWRITEBYTECODE: "1"' in workflow
        assert "UV_PROJECT_ENVIRONMENT=%s/yanzhang-venv" in workflow
        assert '"$RUNNER_TEMP" >> "$GITHUB_ENV"' in workflow
        assert "pytest -p no:cacheprovider" in workflow
        assert "-type d -name __pycache__ -prune -exec rm -rf {} +" in workflow
        assert "ruff check --no-cache" in workflow
        assert "ruff format --check --no-cache" in workflow
        assert 'mypy --cache-dir="${RUNNER_TEMP}/mypy-cache"' in workflow
        assert "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9" in workflow
        assert 'version: "0.11.9"' in workflow
    assert "gh release create" in release
    assert "dist/*.zip" in release
    assert "--prerelease" in release
