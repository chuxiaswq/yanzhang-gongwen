"""Operational maintenance commands for a deployed 砚章 instance."""

# Chinese punctuation is intentional in operator-facing output.
# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import TypedDict

from gongwen_web.storage import SCHEMA_VERSION, default_database_path

_REQUIRED_SCHEMA: dict[str, frozenset[str]] = {
    "schema_metadata": frozenset({"key", "value"}),
    "documents": frozenset(
        {
            "id",
            "title",
            "document_type",
            "content",
            "metadata_json",
            "current_version",
            "created_at",
            "updated_at",
        }
    ),
    "document_versions": frozenset(
        {
            "id",
            "document_id",
            "version_number",
            "title",
            "document_type",
            "content",
            "metadata_json",
            "note",
            "created_at",
        }
    ),
    "model_usage": frozenset(
        {
            "id",
            "document_id",
            "operation",
            "provider",
            "model",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "latency_ms",
            "success",
            "error_code",
            "metadata_json",
            "created_at",
        }
    ),
    "reference_articles": frozenset(
        {
            "id",
            "title",
            "content",
            "source_id",
            "source_name",
            "url",
            "published_date",
            "summary",
            "style_features_json",
            "content_hash",
            "import_method",
            "created_at",
            "updated_at",
        }
    ),
}


class DatabaseStatus(TypedDict):
    """Serializable database integrity and inventory summary."""

    ok: bool
    integrity: str
    path: str
    size_bytes: int
    schema_version: int | None
    schema_compatible: bool
    schema_errors: list[str]
    documents: int
    document_versions: int
    articles: int
    model_usage: int


def inspect_database(database_path: str | os.PathLike[str]) -> DatabaseStatus:
    """Run an SQLite quick check and return a compact operational inventory."""

    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"数据库文件不存在：{path}")
    with closing(_read_only_connection(path)) as connection:
        row = connection.execute("PRAGMA quick_check").fetchone()
        integrity = str(row[0]) if row is not None else "unknown"
        schema_errors = _schema_errors(connection)
        schema_version = (
            _schema_version(connection)
            if "schema_metadata" not in {error.split(":", 1)[0] for error in schema_errors}
            else None
        )
        if schema_version != SCHEMA_VERSION:
            schema_errors.append(
                f"schema_version: expected {SCHEMA_VERSION}, got {schema_version!r}"
            )
        counts = {
            table: _table_count(connection, table)
            for table in (
                "documents",
                "document_versions",
                "reference_articles",
                "model_usage",
            )
        }
    return DatabaseStatus(
        ok=integrity.casefold() == "ok" and not schema_errors,
        integrity=integrity,
        path=str(path),
        size_bytes=path.stat().st_size,
        schema_version=schema_version,
        schema_compatible=not schema_errors,
        schema_errors=schema_errors,
        documents=counts["documents"],
        document_versions=counts["document_versions"],
        articles=counts["reference_articles"],
        model_usage=counts["model_usage"],
    )


def backup_database(
    source_path: str | os.PathLike[str],
    destination_path: str | os.PathLike[str],
    *,
    overwrite: bool = False,
) -> Path:
    """Create a consistent online SQLite backup and atomically publish it."""

    source = Path(source_path).expanduser().resolve()
    destination = Path(destination_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"数据库文件不存在：{source}")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"备份文件已存在：{destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with closing(sqlite3.connect(source)) as source_connection:
            with closing(sqlite3.connect(temporary)) as destination_connection:
                source_connection.backup(destination_connection)
                destination_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                # Publish a self-contained snapshot.  The live database returns
                # to WAL mode when the application opens it after a restore,
                # while the backup itself remains readable from a read-only
                # file mount without creating ``-wal``/``-shm`` sidecars.
                destination_connection.execute("PRAGMA journal_mode=DELETE")
                row = destination_connection.execute("PRAGMA quick_check").fetchone()
                if row is None or str(row[0]).casefold() != "ok":
                    raise RuntimeError("备份完整性检查未通过")
                destination_connection.commit()
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def restore_database(
    backup_path: str | os.PathLike[str],
    destination_path: str | os.PathLike[str],
    *,
    overwrite: bool = False,
) -> Path:
    """Validate and atomically restore a database while the web service is stopped."""

    backup = Path(backup_path).expanduser().resolve()
    destination = Path(destination_path).expanduser().resolve()
    status = inspect_database(backup)
    if not status["ok"]:
        problems = "; ".join(status["schema_errors"]) or status["integrity"]
        raise RuntimeError(f"备份校验未通过：{problems}")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"目标数据库已存在：{destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.restore")
    try:
        with closing(sqlite3.connect(backup)) as source_connection:
            with closing(sqlite3.connect(temporary)) as destination_connection:
                source_connection.backup(destination_connection)
                row = destination_connection.execute("PRAGMA quick_check").fetchone()
                if row is None or str(row[0]).casefold() != "ok":
                    raise RuntimeError("恢复文件完整性检查未通过")
                destination_connection.commit()
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, destination)
        for suffix in ("-wal", "-shm"):
            Path(f"{destination}{suffix}").unlink(missing_ok=True)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def _read_only_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _schema_version(connection: sqlite3.Connection) -> int | None:
    if not _table_exists(connection, "schema_metadata"):
        return None
    row = connection.execute(
        "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _schema_errors(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    for table, required_columns in _REQUIRED_SCHEMA.items():
        columns = _table_columns(connection, table)
        if not columns:
            errors.append(f"{table}: missing table")
            continue
        missing = sorted(required_columns - columns)
        if missing:
            errors.append(f"{table}: missing columns {','.join(missing)}")
    return errors


def _table_columns(connection: sqlite3.Connection, table: str) -> frozenset[str]:
    if table not in _REQUIRED_SCHEMA:
        raise ValueError(f"不支持的数据表：{table}")
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return frozenset(str(row[1]) for row in rows)


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    if not _table_exists(connection, table):
        return 0
    allowed = {
        "documents",
        "document_versions",
        "reference_articles",
        "model_usage",
    }
    if table not in allowed:
        raise ValueError(f"不支持的数据表：{table}")
    row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0]) if row is not None else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="砚章数据检查、备份与恢复")
    parser.add_argument(
        "--database",
        type=Path,
        default=default_database_path(),
        help="数据库文件路径（默认读取 YANZHANG_DATA_DIR，兼容 GONGWEN_DATA_DIR）",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="检查数据库完整性并显示数据量")
    backup = commands.add_parser("backup", help="创建一致性备份")
    backup.add_argument("--output", type=Path, required=True, help="备份文件路径")
    backup.add_argument("--force", action="store_true", help="覆盖已有备份")
    restore = commands.add_parser("restore", help="恢复备份（先停止 Web 服务）")
    restore.add_argument("--input", type=Path, required=True, help="备份文件路径")
    restore.add_argument("--force", action="store_true", help="覆盖目标数据库")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the maintenance CLI and return a process exit code."""

    args = _parser().parse_args(argv)
    database = Path(args.database)
    try:
        if args.command == "check":
            status = inspect_database(database)
            print(json.dumps(status, ensure_ascii=False, indent=2))
            return 0 if status["ok"] else 2
        if args.command == "backup":
            destination = backup_database(database, Path(args.output), overwrite=bool(args.force))
            print(f"备份已生成：{destination}")
            return 0
        if args.command == "restore":
            destination = restore_database(Path(args.input), database, overwrite=bool(args.force))
            print(f"数据已恢复：{destination}")
            return 0
    except (FileNotFoundError, FileExistsError, RuntimeError, sqlite3.DatabaseError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    raise AssertionError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["DatabaseStatus", "backup_database", "inspect_database", "main", "restore_database"]
