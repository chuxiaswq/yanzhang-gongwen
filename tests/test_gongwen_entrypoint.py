"""Offline tests for the Gongwen ASGI/CLI entry point."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import uvicorn

from gongwen_web.app import main


def test_importing_app_module_does_not_create_the_default_database(tmp_path: Path) -> None:
    data_dir = tmp_path / "import-side-effect"
    environment = os.environ.copy()
    environment["GONGWEN_DATA_DIR"] = str(data_dir)

    completed = subprocess.run(
        [sys.executable, "-c", "import gongwen_web.app"],
        check=False,
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert not data_dir.exists()


def test_main_starts_uvicorn_with_the_application_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(application: object, **kwargs: object) -> None:
        captured["application"] = application
        captured.update(kwargs)

    monkeypatch.setenv("GONGWEN_ENV", "test")
    monkeypatch.setattr(sys, "argv", ["gongwen-web", "--host", "127.0.0.2", "--port", "9876"])
    monkeypatch.setattr(uvicorn, "run", fake_run)

    main()

    assert captured == {
        "application": "gongwen_web.app:create_app",
        "host": "127.0.0.2",
        "port": 9876,
        "reload": False,
        "workers": 1,
        "access_log": False,
        "proxy_headers": False,
        "server_header": False,
        "factory": True,
    }
