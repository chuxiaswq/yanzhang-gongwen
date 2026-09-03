"""Packaging contract tests for the Gongwen MCP distribution assets."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_gongwen_mcp_wheel_includes_server_connector_and_documentation() -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    wheel = configuration["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert "gongwen_mcp" in wheel["packages"]
    assert wheel["force-include"] == {
        "docs": "gongwen_mcp/docs",
        "integrations/workbuddy-gongwen": "gongwen_mcp/integrations/workbuddy-gongwen",
    }

    assert (ROOT / "docs/gongwen-mcp.md").is_file()
    assert (ROOT / "integrations/workbuddy-gongwen/connector-meta.json").is_file()
    assert (ROOT / "integrations/workbuddy-gongwen/mcp.json").is_file()
    assert (ROOT / "integrations/workbuddy-gongwen/token-schema.json").is_file()
