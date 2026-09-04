"""Execute dependency-free browser JavaScript checks through pytest and CI."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS_TEST_SCRIPTS = tuple(sorted((ROOT / "tests/js").glob("*.test.cjs")))
JS_BROWSER_SOURCES = (
    ROOT / "gongwen_web/static/app.js",
    ROOT / "gongwen_web/static/workspace_context.js",
    ROOT / "gongwen_web/static/response_validators.js",
)


def _run_node(*arguments: str) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the browser contract tests"
    return subprocess.run(
        [node, *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize("script", JS_TEST_SCRIPTS, ids=lambda path: path.name)
def test_browser_contracts_in_node(script: Path) -> None:
    completed = _run_node("--test", str(script))
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize("source", JS_BROWSER_SOURCES, ids=lambda path: path.name)
def test_browser_source_has_valid_javascript_syntax(source: Path) -> None:
    completed = _run_node("--check", str(source))
    assert completed.returncode == 0, completed.stdout + completed.stderr
