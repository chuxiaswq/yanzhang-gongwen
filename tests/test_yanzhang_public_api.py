from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yanzhang_core
from yanzhang_core import exporters, knowledge, parsers, plugins, storage, workflow

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_MODULES = (storage, knowledge, workflow, plugins, parsers, exporters)


def test_public_api_reexports_every_extension_and_runtime_contract() -> None:
    exported = yanzhang_core.__all__
    assert len(exported) == len(set(exported))

    expected = {name for module in PUBLIC_MODULES for name in module.__all__}
    assert expected <= set(exported)
    for module in PUBLIC_MODULES:
        for name in module.__all__:
            assert getattr(yanzhang_core, name) is getattr(module, name)


def test_public_module_exports_do_not_collide() -> None:
    origins: dict[str, str] = {}
    for module in PUBLIC_MODULES:
        for name in module.__all__:
            assert name not in origins, (
                f"{name} exported by {origins.get(name)} and {module.__name__}"
            )
            origins[name] = module.__name__


def test_import_does_not_discover_plugins_or_write_user_data(tmp_path: Path) -> None:
    script = """
import importlib.metadata

def forbidden_discovery():
    raise AssertionError("entry point discovery ran during import")

importlib.metadata.entry_points = forbidden_discovery
import yanzhang_core

assert yanzhang_core.WritingStorage.__module__ == "yanzhang_core.storage"
assert yanzhang_core.create_extension_registry.__module__ == "yanzhang_core.plugins"
"""
    environment = {
        **os.environ,
        "HOME": str(tmp_path),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(ROOT),
    }
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert list(tmp_path.iterdir()) == []
