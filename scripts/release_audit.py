#!/usr/bin/env python3
"""Fail closed when a Yanzhang source tree or release archive leaks local data."""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
import tarfile
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROOTS = frozenset(
    {
        ".dockerignore",
        ".env.example",
        ".github",
        ".gitignore",
        "CHANGELOG.md",
        "LICENSE",
        "PRIVACY.md",
        "README.md",
        "SECURITY.md",
        "deploy",
        "docs",
        "gongwen_mcp",
        "gongwen_web",
        "integrations",
        "pyproject.toml",
        "scripts",
        "tests",
        "uv.lock",
        "yanzhang",
    }
)
IGNORED_ROOTS = frozenset({".git", "dist"})
FORBIDDEN_PARTS = frozenset(
    {
        ".gongwen-data",
        ".mypy_cache",
        ".operation.lock",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "backups",
        "build",
        "htmlcov",
        "node_modules",
        "venv",
    }
)
FORBIDDEN_NAMES = frozenset(
    {
        ".DS_Store",
        ".env",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "auth.json",
        "credentials.json",
        "id_ed25519",
        "id_rsa",
        "secrets.json",
    }
)
FORBIDDEN_SUFFIXES = frozenset(
    {
        ".aac",
        ".avi",
        ".bak",
        ".backup",
        ".cer",
        ".crt",
        ".csv",
        ".db",
        ".doc",
        ".docx",
        ".flac",
        ".gif",
        ".jpeg",
        ".jpg",
        ".key",
        ".log",
        ".m4a",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".ods",
        ".p12",
        ".pem",
        ".pfx",
        ".pdf",
        ".png",
        ".pyc",
        ".sqlite",
        ".sqlite3",
        ".webp",
        ".wav",
        ".xls",
        ".xlsx",
        ".zip",
    }
)
TEXT_SUFFIXES = frozenset(
    {
        "",
        ".css",
        ".dockerignore",
        ".example",
        ".html",
        ".in",
        ".ini",
        ".js",
        ".json",
        ".lock",
        ".md",
        ".py",
        ".sh",
        ".svg",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
)
SECRET_PATTERNS = (
    ("private-key", re.compile(r"BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY")),
    ("github-token", re.compile(r"\bgh[opusr]_[A-Za-z0-9_]{20,}\b")),
    ("github-fine-grained-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("gitlab-token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("npm-token", re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b")),
    ("google-oauth-secret", re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{16,}\b")),
    ("model-key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("live-secret-key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    ("URL credential", re.compile(r"https?://[^\s/:@]+:[^\s/@]+@", re.IGNORECASE)),
)
LITERAL_HOME_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9._-])/" + r"Users/(?!example(?:/|$)|fixture(?:/|$))[^/\s]+/"),
    re.compile(
        r"(?<![A-Za-z0-9._-])/" + r"home/"
        r"(?!example(?:/|$)|runner(?:/|$)|fixture(?:/|$))[^/\s]+/"
    ),
    re.compile(r"[A-Za-z]:[\\/]Users[\\/](?!example(?:[\\/]|$))[^\\/\s]+[\\/]"),
)
TOKEN_ASSIGNMENT = re.compile(
    r"(?m)^[ \t]*(?:export[ \t]+)?"
    r"(?:(?:[A-Z][A-Z0-9_]*_)?(?:API_KEY|ACCESS_TOKEN|TOKEN|SECRET|PASSWORD))"
    r"[ \t]*=[ \t]*"
    r"([^\s#]*)"
)
CONFIG_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?im)(?:^|[,\n{])[ \t]*(?:-[ \t]*)?[\"']?"
    r"(?:[A-Za-z0-9_.-]*[_-])?(?:api[_-]?key|access[_-]?token|token|secret|password)"
    r"[\"']?[ \t]*[:=][ \t]*([^\s#,;}\]]*)"
)
BEARER_VALUE = re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+$/{}-]{12,})")
SAFE_VALUE_PREFIXES = (
    "$",
    "${",
    "CHANGE_ME",
    "CHANGEME",
    "REPLACE_",
    "FIXTURE",
    "TEST_",
    "EXAMPLE_",
)
SDIST_ALLOWED_ROOTS = ALLOWED_ROOTS | {"PKG-INFO"}
WHEEL_ALLOWED_ROOTS = frozenset({"gongwen_mcp", "gongwen_web", "yanzhang"})
CONNECTOR_ARCHIVE_PREFIX = "yanzhang-workbuddy-connector-"
CONNECTOR_ARCHIVE_ROOT = "yanzhang-workbuddy-connector"
CONNECTOR_MEMBERS = frozenset(
    {
        "connector-meta.json",
        "icon.svg",
        "mcp.json",
        "skills/gongwen/SKILL.md",
        "token-schema.json",
    }
)
MAX_FILE_BYTES = 5 * 1024 * 1024
CONFIG_SUFFIXES = frozenset(
    {"", ".example", ".ini", ".json", ".md", ".toml", ".txt", ".yaml", ".yml"}
)


def _expected_connector_archive_name() -> str:
    metadata_path = ROOT / "integrations/workbuddy-gongwen/connector-meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    version = metadata.get("version")
    if not isinstance(version, str) or not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+(?:-preview\.[0-9]+)?", version
    ):
        raise ValueError("connector metadata contains an invalid version")
    return f"{CONNECTOR_ARCHIVE_PREFIX}{version}.zip"


def _path_errors(relative: PurePosixPath) -> list[str]:
    errors: list[str] = []
    if relative.is_absolute() or ".." in relative.parts or "\\" in relative.as_posix():
        errors.append(f"unsafe path: {relative}")
        return errors
    if any(part.casefold() in FORBIDDEN_PARTS for part in relative.parts):
        errors.append(f"private/generated directory: {relative}")
    folded_name = relative.name.casefold()
    if folded_name in FORBIDDEN_NAMES or folded_name.startswith(".env."):
        if folded_name != ".env.example":
            errors.append(f"credential file: {relative}")
    if any(folded_name.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
        errors.append(f"private/generated file type: {relative}")
    return errors


def _safe_credential_value(raw: str) -> bool:
    value = raw.strip().strip("\"'")
    if not value:
        return True
    upper = value.upper()
    if upper.startswith(SAFE_VALUE_PREFIXES):
        return True
    if upper in {"0", "1", "FALSE", "TRUE"}:
        return True
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_-]*_[A-Z0-9_-]+", value))


def _content_errors(label: str, data: bytes) -> list[str]:
    if len(data) > MAX_FILE_BYTES:
        return [f"unexpected file larger than 5 MiB: {label}"]
    if data.startswith(b"SQLite format 3\x00"):
        return [f"SQLite content: {label}"]
    suffix = PurePosixPath(label).suffix.casefold()
    if suffix not in TEXT_SUFFIXES:
        return [f"unreviewed file type: {label}"]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [f"non-UTF-8 text file: {label}"]
    if "\x00" in text:
        return [f"NUL byte in text file: {label}"]
    errors: list[str] = []
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            errors.append(f"{name} signature: {label}")
    for pattern in LITERAL_HOME_PATTERNS:
        if pattern.search(text):
            errors.append(f"local home path: {label}")
            break
    assignment_error = False
    for match in TOKEN_ASSIGNMENT.finditer(text):
        if not _safe_credential_value(match.group(1)):
            errors.append(f"literal credential assignment: {label}")
            assignment_error = True
            break
    if suffix in CONFIG_SUFFIXES and not assignment_error:
        for match in CONFIG_CREDENTIAL_ASSIGNMENT.finditer(text):
            if not _safe_credential_value(match.group(1)):
                errors.append(f"literal credential field: {label}")
                break
    for match in BEARER_VALUE.finditer(text):
        if not _safe_credential_value(match.group(1)):
            errors.append(f"literal Bearer credential: {label}")
            break
    return errors


def audit_source(root: Path) -> list[str]:
    errors: list[str] = []
    actual_roots = {item.name for item in root.iterdir() if item.name not in IGNORED_ROOTS}
    unexpected = sorted(actual_roots - ALLOWED_ROOTS)
    if unexpected:
        errors.append("unexpected top-level entries: " + ", ".join(unexpected))
    missing = {"README.md", "SECURITY.md", "PRIVACY.md", "LICENSE", "pyproject.toml"} - actual_roots
    if missing:
        errors.append("missing required files: " + ", ".join(sorted(missing)))
    for path in sorted(root.rglob("*")):
        try:
            relative = path.relative_to(root)
        except ValueError:
            errors.append(f"path escapes release root: {path}")
            continue
        if relative.parts and relative.parts[0] in IGNORED_ROOTS:
            continue
        pure = PurePosixPath(relative.as_posix())
        if path.is_symlink():
            errors.append(f"symlink is not permitted: {pure}")
            continue
        path_errors = _path_errors(pure)
        errors.extend(path_errors)
        if path.is_file() and not path_errors:
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                errors.append(f"unexpected file larger than 5 MiB: {pure}")
            else:
                errors.extend(_content_errors(str(pure), path.read_bytes()))
    return errors


def _archive_members(path: Path) -> Iterable[tuple[str, bytes, bool, int]]:
    if path.suffix in {".whl", ".zip"}:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                mode = info.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                unsafe_entry = file_type not in {0, stat.S_IFREG}
                data = (
                    archive.read(info)
                    if not unsafe_entry and info.file_size <= MAX_FILE_BYTES
                    else b""
                )
                yield info.filename, data, unsafe_entry, info.file_size
        return
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, mode="r:gz") as archive:
            for info in archive.getmembers():
                if info.isdir():
                    continue
                extracted = archive.extractfile(info) if info.isfile() else None
                unsafe_entry = not info.isfile()
                data = (
                    extracted.read()
                    if extracted is not None and info.size <= MAX_FILE_BYTES
                    else b""
                )
                yield info.name, data, unsafe_entry, info.size
        return
    raise ValueError(f"unsupported release artifact: {path}")


def audit_archive(path: Path) -> list[str]:
    errors: list[str] = []
    member_count = 0
    raw_names: set[str] = set()
    portable_names: set[str] = set()
    sdist_prefix: str | None = None
    connector_members: set[str] = set()
    expected_connector_name = _expected_connector_archive_name() if path.suffix == ".zip" else None
    for name, data, is_link, size in _archive_members(path):
        member_count += 1
        if name in raw_names:
            errors.append(f"duplicate archive member: {path.name}:{name}")
        raw_names.add(name)
        member = PurePosixPath(name)
        portable_name = member.as_posix().casefold()
        if portable_name in portable_names:
            errors.append(f"portable-name collision: {path.name}:{name}")
        portable_names.add(portable_name)
        if is_link:
            errors.append(f"archive link or special entry is not permitted: {path.name}:{name}")
            continue
        if size > MAX_FILE_BYTES:
            errors.append(f"unexpected file larger than 5 MiB: {path.name}:{name}")
            continue
        normalized = member
        if path.name.endswith(".tar.gz"):
            if len(member.parts) < 2:
                errors.append(f"sdist member lacks package prefix: {path.name}:{name}")
                continue
            prefix = member.parts[0]
            if sdist_prefix is None:
                sdist_prefix = prefix
                if not prefix.startswith("yanzhang_gongwen-"):
                    errors.append(f"unexpected sdist prefix: {path.name}:{prefix}")
            elif prefix != sdist_prefix:
                errors.append(f"multiple sdist prefixes: {path.name}:{name}")
            normalized = PurePosixPath(*member.parts[1:])
        elif path.suffix == ".zip":
            if len(member.parts) < 2 or member.parts[0] != CONNECTOR_ARCHIVE_ROOT:
                errors.append(f"unexpected connector root: {path.name}:{name}")
                continue
            normalized = PurePosixPath(*member.parts[1:])
        path_errors = _path_errors(normalized)
        errors.extend(f"{path.name}:{item}" for item in path_errors)
        if not path_errors:
            errors.extend(_content_errors(f"{path.name}:{name}", data))
        if path.suffix == ".whl" and member.parts:
            top = member.parts[0]
            if top not in WHEEL_ALLOWED_ROOTS and not (
                top.startswith("yanzhang_gongwen-") and top.endswith(".dist-info")
            ):
                errors.append(f"unexpected wheel member: {path.name}:{name}")
        elif path.name.endswith(".tar.gz") and normalized.parts:
            if normalized.parts[0] not in SDIST_ALLOWED_ROOTS:
                errors.append(f"unexpected sdist member: {path.name}:{name}")
        elif path.suffix == ".zip":
            connector_members.add(normalized.as_posix())
            if path.name != expected_connector_name:
                errors.append(f"unexpected ZIP artifact: {path.name}")
            if normalized.as_posix() not in CONNECTOR_MEMBERS:
                errors.append(f"unexpected connector member: {path.name}:{name}")
    if member_count == 0:
        errors.append(f"empty archive: {path}")
    if path.suffix == ".zip" and connector_members != CONNECTOR_MEMBERS:
        missing = sorted(CONNECTOR_MEMBERS - connector_members)
        if missing:
            errors.append(f"missing connector members in {path.name}: {', '.join(missing)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifacts", type=Path, help="audit wheel and sdist files in this directory"
    )
    args = parser.parse_args()
    errors = audit_source(ROOT)
    if args.artifacts is not None:
        wheels = sorted(args.artifacts.glob("*.whl"))
        sdists = sorted(args.artifacts.glob("*.tar.gz"))
        connectors = sorted(args.artifacts.glob("*.zip"))
        archives = sorted((*wheels, *sdists, *connectors))
        for label, items in (
            ("wheel", wheels),
            ("sdist", sdists),
            ("connector ZIP", connectors),
        ):
            if len(items) != 1:
                errors.append(
                    f"expected exactly one {label} in {args.artifacts}; found {len(items)}"
                )
        for archive in archives:
            errors.extend(audit_archive(archive))
    if errors:
        for error in sorted(set(errors)):
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        "Release audit passed: allowlist, paths, credentials, source tree and artifacts are clean."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
