"""Execute the browser response contracts with Node's dependency-free test runner."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def test_response_validators_in_node() -> None:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the browser contract tests"
    script = Path(__file__).parent / "js" / "response_validators.test.cjs"
    completed = subprocess.run(
        [node, "--test", str(script)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
