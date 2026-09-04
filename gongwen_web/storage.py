"""SQLite persistence for the personal official-document writing app.

The store deliberately exposes plain, JSON-serializable ``TypedDict`` values so
Starlette handlers can pass results directly to ``JSONResponse``.  Each
operation uses its own SQLite connection; writes are serialized in-process and
run in an explicit transaction, while SQLite's WAL and busy timeout cover
concurrent browser requests and multiple worker processes.
"""

# Chinese punctuation is intentional in user-facing validation messages.
# ruff: noqa: RUF001

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

_DATABASE_FILENAME = "gongwen.sqlite3"
SCHEMA_VERSION = 1
_BUSY_TIMEOUT_MS = 5_000
_REQUIRED_CORE_SCHEMA: dict[str, frozenset[str]] = {
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
}


class DocumentRecord(TypedDict):
    """Complete current state of one saved document."""

    id: str
    title: str
    document_type: str
    content: str
    metadata: dict[str, object]
    current_version: int
    created_at: str
    updated_at: str


class DocumentSummary(TypedDict):
    """Compact row returned by the document-list endpoint."""

    id: str
    title: str
    document_type: str
    excerpt: str
    character_count: int
    current_version: int
    created_at: str
    updated_at: str


class DocumentVersion(TypedDict):
    """Immutable document snapshot created by ``save_document``."""

    id: int
    document_id: str
    version: int
    title: str
    document_type: str
    content: str
    metadata: dict[str, object]
    note: str
    created_at: str


class ModelUsageRecord(TypedDict):
    """Token and latency accounting for one model operation."""

    id: int
    document_id: str | None
    operation: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: float | None
    success: bool
    error_code: str | None
    metadata: dict[str, object]
    created_at: str


class ModelUsageSummary(TypedDict):
    """Aggregate model use suitable for a personal usage dashboard."""

    call_count: int
    successful_calls: int
    failed_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: float


class DocumentVersionConflict(RuntimeError):
    """Raised when a stale browser tab attempts an optimistic update."""


def default_data_dir() -> Path:
    """Return the configured local data directory without creating it."""

    configured = os.environ.get("YANZHANG_DATA_DIR", "").strip()
    if not configured:
        configured = os.environ.get("GONGWEN_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return _platform_default_data_dir(
        platform_name=sys.platform,
        environment=os.environ,
        home=Path.home(),
    )


def _platform_default_data_dir(
    *,
    platform_name: str,
    environment: Mapping[str, str],
    home: Path,
) -> Path:
    """Return a platform-native per-user application data directory."""

    if platform_name == "darwin":
        return home / "Library" / "Application Support" / "Yanzhang" / "Gongwen"
    if platform_name.startswith("win"):
        configured_root = environment.get("LOCALAPPDATA", "").strip()
        root = Path(configured_root).expanduser() if configured_root else home / "AppData" / "Local"
        return root / "Yanzhang" / "Gongwen"

    configured_root = environment.get("XDG_DATA_HOME", "").strip()
    root = Path(configured_root).expanduser() if configured_root else home / ".local" / "share"
    return root / "yanzhang" / "gongwen"


def default_database_path() -> Path:
    """Return the default database path used by ``GongwenStorage``."""

    return default_data_dir() / _DATABASE_FILENAME


class GongwenStorage:
    """Thread-safe SQLite repository for drafts, versions, and model usage."""

    def __init__(self, db_path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(db_path).expanduser() if db_path is not None else default_database_path()
        self._write_lock = threading.RLock()
        self.initialize()

    def initialize(self) -> None:
        """Create the data directory and initialize the schema idempotently."""

        with self._write_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.path.parent.chmod(0o700)
            except OSError:
                # Some mounted filesystems do not expose POSIX permission bits.
                pass
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                existing_errors = _core_schema_errors(connection, require_all=False)
                if existing_errors:
                    raise RuntimeError(
                        "database schema is incomplete: " + "; ".join(existing_errors)
                    )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                existing_schema = connection.execute(
                    "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
                ).fetchone()
                if existing_schema is not None and str(existing_schema[0]) != str(SCHEMA_VERSION):
                    raise RuntimeError(
                        "database schema version mismatch: "
                        f"expected {SCHEMA_VERSION}, got {existing_schema[0]!r}"
                    )

                connection.executescript(
                    """

                    CREATE TABLE IF NOT EXISTS documents (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        document_type TEXT NOT NULL DEFAULT '',
                        content TEXT NOT NULL,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        current_version INTEGER NOT NULL CHECK (current_version > 0),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS document_versions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        document_id TEXT NOT NULL,
                        version_number INTEGER NOT NULL CHECK (version_number > 0),
                        title TEXT NOT NULL,
                        document_type TEXT NOT NULL DEFAULT '',
                        content TEXT NOT NULL,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        note TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        UNIQUE (document_id, version_number),
                        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_document_versions_document
                    ON document_versions(document_id, version_number DESC);

                    CREATE TABLE IF NOT EXISTS model_usage (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        document_id TEXT,
                        operation TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        model TEXT NOT NULL,
                        input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
                        output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
                        total_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
                        latency_ms REAL CHECK (latency_ms IS NULL OR latency_ms >= 0),
                        success INTEGER NOT NULL DEFAULT 1 CHECK (success IN (0, 1)),
                        error_code TEXT,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_model_usage_created
                    ON model_usage(created_at DESC);

                    CREATE INDEX IF NOT EXISTS idx_model_usage_document
                    ON model_usage(document_id, created_at DESC);
                    """
                )
                created_errors = _core_schema_errors(connection, require_all=True)
                if created_errors:
                    raise RuntimeError(
                        "database schema is incomplete: " + "; ".join(created_errors)
                    )
                connection.execute(
                    """
                    INSERT INTO schema_metadata(key, value) VALUES ('schema_version', ?)
                    ON CONFLICT(key) DO NOTHING
                    """,
                    (str(SCHEMA_VERSION),),
                )
                connection.commit()

    def check_ready(self) -> None:
        """Run a constant-time database and core-schema readiness probe.

        Full integrity scans belong to ``gongwen-admin check``.  The HTTP probe
        stays lightweight because container and reverse-proxy health checks call
        it frequently, including when the article library has grown large.
        """

        with self._connect() as connection:
            schema_errors = _core_schema_errors(connection, require_all=True)
            if schema_errors:
                raise RuntimeError("database schema is incomplete: " + "; ".join(schema_errors))
            schema = connection.execute(
                "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
            ).fetchone()
            for table in ("documents", "document_versions", "model_usage"):
                connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
        if schema is None or str(schema[0]) != str(SCHEMA_VERSION):
            raise RuntimeError("database schema version mismatch")

    def save_document(
        self,
        *,
        title: str,
        content: str,
        document_type: str = "",
        metadata: Mapping[str, object] | None = None,
        document_id: str | None = None,
        version_note: str = "",
        expected_version: int | None = None,
    ) -> DocumentRecord:
        """Create or update a document and append an immutable version snapshot.

        ``expected_version`` enables optimistic concurrency for multiple browser
        tabs.  Pass ``0`` when the caller expects a new document.
        """

        clean_title = title.strip()
        if not clean_title:
            raise ValueError("文稿标题不能为空")
        if not content.strip():
            raise ValueError("文稿正文不能为空")
        if expected_version is not None and expected_version < 0:
            raise ValueError("expected_version 不能小于 0")

        clean_id = _normalize_document_id(document_id or uuid.uuid4().hex)
        metadata_json = _dump_json_object(metadata)
        now = _utc_now()

        with self._write_transaction() as connection:
            existing = connection.execute(
                "SELECT current_version, created_at FROM documents WHERE id = ?",
                (clean_id,),
            ).fetchone()

            actual_version = int(existing["current_version"]) if existing is not None else 0
            if expected_version is not None and actual_version != expected_version:
                raise DocumentVersionConflict(
                    f"文稿版本已更新：期望 {expected_version}，当前 {actual_version}"
                )

            next_version = actual_version + 1
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO documents(
                        id, title, document_type, content, metadata_json,
                        current_version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_id,
                        clean_title,
                        document_type.strip(),
                        content,
                        metadata_json,
                        next_version,
                        now,
                        now,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE documents
                    SET title = ?, document_type = ?, content = ?, metadata_json = ?,
                        current_version = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        clean_title,
                        document_type.strip(),
                        content,
                        metadata_json,
                        next_version,
                        now,
                        clean_id,
                    ),
                )

            connection.execute(
                """
                INSERT INTO document_versions(
                    document_id, version_number, title, document_type, content,
                    metadata_json, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_id,
                    next_version,
                    clean_title,
                    document_type.strip(),
                    content,
                    metadata_json,
                    version_note.strip(),
                    now,
                ),
            )
            row = connection.execute("SELECT * FROM documents WHERE id = ?", (clean_id,)).fetchone()
            assert row is not None
            return _document_from_row(row)

    def list_documents(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
    ) -> list[DocumentSummary]:
        """List most-recently edited documents, optionally filtering by text."""

        _validate_pagination(limit, offset, maximum=500)
        query = """
            SELECT id, title, document_type, substr(content, 1, 180) AS excerpt,
                   length(content) AS character_count, current_version,
                   created_at, updated_at
            FROM documents
        """
        parameters: list[object] = []
        clean_search = search.strip() if search else ""
        if clean_search:
            pattern = f"%{_escape_like(clean_search)}%"
            query += " WHERE title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\'"
            parameters.extend((pattern, pattern))
        query += " ORDER BY updated_at DESC, id ASC LIMIT ? OFFSET ?"
        parameters.extend((limit, offset))

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_document_summary_from_row(row) for row in rows]

    def get_document(self, document_id: str) -> DocumentRecord | None:
        """Read the current state of a document, or ``None`` when absent."""

        clean_id = _normalize_document_id(document_id)
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM documents WHERE id = ?", (clean_id,)).fetchone()
        return _document_from_row(row) if row is not None else None

    def delete_document(self, document_id: str) -> bool:
        """Delete a document and its versions, preserving anonymized usage totals."""

        clean_id = _normalize_document_id(document_id)
        with self._write_transaction() as connection:
            cursor = connection.execute("DELETE FROM documents WHERE id = ?", (clean_id,))
            return cursor.rowcount > 0

    def list_versions(
        self,
        document_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DocumentVersion]:
        """List immutable snapshots for a document, newest first."""

        clean_id = _normalize_document_id(document_id)
        _validate_pagination(limit, offset, maximum=1_000)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM document_versions
                WHERE document_id = ?
                ORDER BY version_number DESC
                LIMIT ? OFFSET ?
                """,
                (clean_id, limit, offset),
            ).fetchall()
        return [_version_from_row(row) for row in rows]

    def get_version(self, document_id: str, version: int) -> DocumentVersion | None:
        """Read one immutable document version."""

        clean_id = _normalize_document_id(document_id)
        if version < 1:
            raise ValueError("version 必须大于 0")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM document_versions
                WHERE document_id = ? AND version_number = ?
                """,
                (clean_id, version),
            ).fetchone()
        return _version_from_row(row) if row is not None else None

    def record_model_usage(
        self,
        *,
        operation: str,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int | None = None,
        latency_ms: float | None = None,
        success: bool = True,
        error_code: str | None = None,
        document_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> ModelUsageRecord:
        """Persist accounting metadata for one local or remote model operation."""

        clean_operation = operation.strip()
        clean_provider = provider.strip()
        clean_model = model.strip()
        if not clean_operation or not clean_provider or not clean_model:
            raise ValueError("operation、provider 和 model 不能为空")
        for field_name, value in (
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
        ):
            if value < 0:
                raise ValueError(f"{field_name} 不能小于 0")
        clean_total = input_tokens + output_tokens if total_tokens is None else total_tokens
        if clean_total < 0:
            raise ValueError("total_tokens 不能小于 0")
        if latency_ms is not None and latency_ms < 0:
            raise ValueError("latency_ms 不能小于 0")
        clean_document_id = _normalize_document_id(document_id) if document_id else None
        metadata_json = _dump_json_object(metadata)

        with self._write_transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO model_usage(
                    document_id, operation, provider, model, input_tokens,
                    output_tokens, total_tokens, latency_ms, success, error_code,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_document_id,
                    clean_operation,
                    clean_provider,
                    clean_model,
                    input_tokens,
                    output_tokens,
                    clean_total,
                    latency_ms,
                    int(success),
                    error_code.strip() if error_code else None,
                    metadata_json,
                    _utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM model_usage WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            assert row is not None
            return _usage_from_row(row)

    def list_model_usage(
        self,
        *,
        document_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ModelUsageRecord]:
        """List model calls globally or for one document, newest first."""

        _validate_pagination(limit, offset, maximum=1_000)
        parameters: list[object] = []
        query = "SELECT * FROM model_usage"
        if document_id is not None:
            query += " WHERE document_id = ?"
            parameters.append(_normalize_document_id(document_id))
        query += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
        parameters.extend((limit, offset))
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_usage_from_row(row) for row in rows]

    def summarize_model_usage(
        self,
        *,
        document_id: str | None = None,
    ) -> ModelUsageSummary:
        """Return total calls, tokens, and latency for the selected scope."""

        parameters: tuple[object, ...] = ()
        query = """
            SELECT COUNT(*) AS call_count,
                   COALESCE(SUM(success), 0) AS successful_calls,
                   COALESCE(SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END), 0)
                       AS failed_calls,
                   COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(total_tokens), 0) AS total_tokens,
                   COALESCE(SUM(latency_ms), 0.0) AS latency_ms
            FROM model_usage
        """
        if document_id is not None:
            query += " WHERE document_id = ?"
            parameters = (_normalize_document_id(document_id),)
        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        assert row is not None
        return ModelUsageSummary(
            call_count=int(row["call_count"]),
            successful_calls=int(row["successful_calls"]),
            failed_calls=int(row["failed_calls"]),
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            total_tokens=int(row["total_tokens"]),
            latency_ms=float(row["latency_ms"]),
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=_BUSY_TIMEOUT_MS / 1_000,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA synchronous = NORMAL")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()


def _core_schema_errors(
    connection: sqlite3.Connection,
    *,
    require_all: bool,
) -> list[str]:
    """Return bounded structural errors without scanning application rows."""

    errors: list[str] = []
    for table, required_columns in _REQUIRED_CORE_SCHEMA.items():
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if exists is None:
            if require_all:
                errors.append(f"{table}: missing table")
            continue
        columns = frozenset(
            str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        )
        missing = sorted(required_columns - columns)
        if missing:
            errors.append(f"{table}: missing columns {','.join(missing)}")
    return errors


def _document_from_row(row: sqlite3.Row) -> DocumentRecord:
    return DocumentRecord(
        id=str(row["id"]),
        title=str(row["title"]),
        document_type=str(row["document_type"]),
        content=str(row["content"]),
        metadata=_load_json_object(str(row["metadata_json"])),
        current_version=int(row["current_version"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _document_summary_from_row(row: sqlite3.Row) -> DocumentSummary:
    return DocumentSummary(
        id=str(row["id"]),
        title=str(row["title"]),
        document_type=str(row["document_type"]),
        excerpt=str(row["excerpt"]),
        character_count=int(row["character_count"]),
        current_version=int(row["current_version"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _version_from_row(row: sqlite3.Row) -> DocumentVersion:
    return DocumentVersion(
        id=int(row["id"]),
        document_id=str(row["document_id"]),
        version=int(row["version_number"]),
        title=str(row["title"]),
        document_type=str(row["document_type"]),
        content=str(row["content"]),
        metadata=_load_json_object(str(row["metadata_json"])),
        note=str(row["note"]),
        created_at=str(row["created_at"]),
    )


def _usage_from_row(row: sqlite3.Row) -> ModelUsageRecord:
    raw_latency = row["latency_ms"]
    raw_document_id = row["document_id"]
    raw_error_code = row["error_code"]
    return ModelUsageRecord(
        id=int(row["id"]),
        document_id=str(raw_document_id) if raw_document_id is not None else None,
        operation=str(row["operation"]),
        provider=str(row["provider"]),
        model=str(row["model"]),
        input_tokens=int(row["input_tokens"]),
        output_tokens=int(row["output_tokens"]),
        total_tokens=int(row["total_tokens"]),
        latency_ms=float(raw_latency) if raw_latency is not None else None,
        success=bool(row["success"]),
        error_code=str(raw_error_code) if raw_error_code is not None else None,
        metadata=_load_json_object(str(row["metadata_json"])),
        created_at=str(row["created_at"]),
    )


def _normalize_document_id(value: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError("document_id 不能为空")
    if len(clean) > 128:
        raise ValueError("document_id 不能超过 128 个字符")
    if any(character.isspace() or ord(character) < 32 for character in clean):
        raise ValueError("document_id 含有无效字符")
    return clean


def _validate_pagination(limit: int, offset: int, *, maximum: int) -> None:
    if limit < 1 or limit > maximum:
        raise ValueError(f"limit 必须介于 1 和 {maximum} 之间")
    if offset < 0:
        raise ValueError("offset 不能小于 0")


def _dump_json_object(value: Mapping[str, object] | None) -> str:
    candidate: Mapping[str, object] = value or {}
    try:
        return json.dumps(
            dict(candidate), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata 必须是可序列化的 JSON 对象") from exc


def _load_json_object(value: str) -> dict[str, object]:
    decoded = cast(object, json.loads(value))
    if not isinstance(decoded, dict):
        return {}
    return {str(key): item for key, item in decoded.items()}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


__all__ = [
    "DocumentRecord",
    "DocumentSummary",
    "DocumentVersion",
    "DocumentVersionConflict",
    "GongwenStorage",
    "ModelUsageRecord",
    "ModelUsageSummary",
    "default_data_dir",
    "default_database_path",
]
