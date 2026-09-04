"""Regression tests for the fail-closed release privacy audit."""

from __future__ import annotations

import importlib.util
import io
import stat
import sys
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_release_audit() -> ModuleType:
    path = ROOT / "scripts/release_audit.py"
    spec = importlib.util.spec_from_file_location("yanzhang_release_audit_tests", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_literal_credential_assignments_fail_while_placeholders_pass() -> None:
    audit = _load_release_audit()
    key_name = "GONGWEN_LLM_API_KEY"
    private_value = "live" + "-credential-material-1234567890"

    assert audit._content_errors(
        ".env.example",
        f"{key_name}={private_value}\n".encode(),
    ) == ["literal credential assignment: .env.example"]
    assert (
        audit._content_errors(
            ".env.example",
            (
                b"GONGWEN_LLM_API_KEY=\n"
                b"GONGWEN_ACCESS_TOKEN=CHANGE_ME_WITH_RANDOM_VALUE\n"
                b"GONGWEN_MCP_ACCESS_TOKEN=${MCP_TOKEN}\n"
            ),
        )
        == []
    )


def test_structured_credential_fields_and_bearer_values_fail() -> None:
    audit = _load_release_audit()
    private_value = "live" + "-credential-material-1234567890"

    assert "literal credential field: settings.json" in audit._content_errors(
        "settings.json",
        f'{{"api_key": "{private_value}"}}'.encode(),
    )
    assert "literal Bearer credential: README.md" in audit._content_errors(
        "README.md",
        ("Authorization: " + "Bearer " + private_value).encode(),
    )
    assert (
        audit._content_errors(
            "settings.toml",
            b'access_token = "${MCP_TOKEN}"\n',
        )
        == []
    )


@pytest.mark.parametrize(
    "value",
    [
        "github_pat_" + "A" * 30,
        "glpat-" + "a" * 24,
        "xoxb-" + "1" * 12 + "-" + "a" * 16,
        "AIza" + "A" * 35,
        "GOCSPX-" + "A" * 24,
        "sk-" + "A" * 24,
        "eyJ" + "A" * 12 + "." + "B" * 12 + "." + "C" * 12,
    ],
)
def test_common_secret_signatures_fail(value: str) -> None:
    audit = _load_release_audit()

    assert audit._content_errors("settings.txt", value.encode())


def test_home_path_boundary_ignores_fixture_paths_but_detects_literal_homes() -> None:
    audit = _load_release_audit()
    private_home = ("/" + "Users/example-person/private.txt").encode()

    assert (
        audit._content_errors(
            "fixture.py",
            b"Path('/fixture/home/private/source.txt')",
        )
        == []
    )
    assert audit._content_errors("fixture.py", private_home) == ["local home path: fixture.py"]


def test_sqlite_magic_is_rejected_even_with_an_innocent_extension() -> None:
    audit = _load_release_audit()

    assert audit._content_errors("notes.bin", b"SQLite format 3\x00private rows") == [
        "SQLite content: notes.bin"
    ]


def test_unknown_file_types_fail_closed() -> None:
    audit = _load_release_audit()

    assert audit._content_errors("opaque.blob", b"private") == ["unreviewed file type: opaque.blob"]


def test_commonjs_test_sources_are_audited_as_text() -> None:
    audit = _load_release_audit()

    assert audit._content_errors("tests/js/contract.test.cjs", b"const fixture = true;\n") == []
    private_value = "sk" + "-" + "A" * 24
    assert audit._content_errors(
        "tests/js/contract.test.cjs",
        f'const token = "{private_value}";\n'.encode(),
    ) == ["model-key signature: tests/js/contract.test.cjs"]


def test_source_audit_rejects_local_virtualenv_and_cache_trees(tmp_path: Path) -> None:
    audit = _load_release_audit()
    for required in ("README.md", "SECURITY.md", "PRIVACY.md", "LICENSE", "pyproject.toml"):
        (tmp_path / required).write_text("fixture", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv/state.txt").write_text("fixture", encoding="utf-8")
    (tmp_path / ".pytest_cache").mkdir()

    errors = audit.audit_source(tmp_path)

    assert any("unexpected top-level entries" in error for error in errors)
    assert any("private/generated directory: .venv" in error for error in errors)
    assert any("private/generated directory: .pytest_cache" in error for error in errors)


def test_sdist_rejects_members_outside_the_release_allowlist(tmp_path: Path) -> None:
    audit = _load_release_audit()
    archive_path = tmp_path / "yanzhang_gongwen-0.1.0b1.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        payload = b"private release note"
        info = tarfile.TarInfo("yanzhang_gongwen-0.1.0b1/private_notes.txt")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    errors = audit.audit_archive(archive_path)

    assert any("unexpected sdist member" in error for error in errors)


def test_wheel_zip_symlinks_are_rejected(tmp_path: Path) -> None:
    audit = _load_release_audit()
    archive_path = tmp_path / "yanzhang_gongwen-0.1.0b1-py3-none-any.whl"
    with zipfile.ZipFile(archive_path, "w") as archive:
        info = zipfile.ZipInfo("gongwen_web/__init__.py")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "elsewhere.py")

    errors = audit.audit_archive(archive_path)

    assert any("link or special entry" in error for error in errors)


def test_large_archive_member_is_rejected_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit = _load_release_audit()
    archive_path = tmp_path / "yanzhang_gongwen-0.1.0b1-py3-none-any.whl"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("gongwen_web/large.py", b"x" * (audit.MAX_FILE_BYTES + 1))

    def unexpected_read(*_: object, **__: object) -> bytes:
        raise AssertionError("oversized archive member was read")

    monkeypatch.setattr(zipfile.ZipFile, "read", unexpected_read)
    errors = audit.audit_archive(archive_path)

    assert any("larger than 5 MiB" in error for error in errors)


def test_connector_archive_uses_one_fixed_root_and_exact_members(tmp_path: Path) -> None:
    audit = _load_release_audit()
    archive_path = tmp_path / audit._expected_connector_archive_name()
    with zipfile.ZipFile(archive_path, "w") as archive:
        for relative in sorted(audit.CONNECTOR_MEMBERS):
            archive.writestr(f"{audit.CONNECTOR_ARCHIVE_ROOT}/{relative}", b"fixture")

    assert audit.audit_archive(archive_path) == []

    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr(f"{audit.CONNECTOR_ARCHIVE_ROOT}/private.txt", b"private")
    assert any(
        "unexpected connector member" in error for error in audit.audit_archive(archive_path)
    )
