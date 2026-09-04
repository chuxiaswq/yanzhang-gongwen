"""SQLite persistence for the provider-neutral Yanzhang writing core.

The core schema deliberately lives beside the preview application's legacy
tables.  It owns an independent ``writing_schema_version`` metadata key and
never mutates the legacy ``schema_version`` value or any legacy row.  Remote
model and connector calls belong outside this module; each public write opens
and closes a short transaction around persistence only.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

from pydantic import BaseModel

from yanzhang_core.models import (
    Channel,
    ContentBlock,
    ProjectTerm,
    Revision,
    TextAsset,
    WritingBrief,
    WritingProject,
)

WRITING_SCHEMA_VERSION = 3
_BUSY_TIMEOUT_MS = 5_000


class WritingStorageError(RuntimeError):
    """Base class for writing-core persistence failures."""


class RecordNotFoundError(WritingStorageError, LookupError):
    """Raised when a requested writing-core record does not exist."""


class RevisionConflictError(WritingStorageError):
    """Raised when an asset revision changed since the caller read it."""


class ProjectScopeError(WritingStorageError):
    """Raised when linked records belong to different projects."""


class WorkflowRunRecord(TypedDict):
    """JSON-safe persisted state for one workflow run."""

    id: str
    workflow_id: str
    workflow_version: str
    project_id: str | None
    status: str
    current_step_id: str | None
    cancel_requested: bool
    input: dict[str, object]
    state: dict[str, object]
    definition: dict[str, object]
    output_asset_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: str
    started_at: str | None
    updated_at: str
    finished_at: str | None


class StepRunRecord(TypedDict):
    """JSON-safe checkpoint for one workflow step."""

    id: str
    run_id: str
    step_id: str
    position: int
    handler: str
    status: str
    attempt_count: int
    input: dict[str, object]
    output: dict[str, object]
    checkpoint: dict[str, object]
    error_code: str | None
    error_message: str | None
    started_at: str | None
    updated_at: str
    finished_at: str | None


class AuditEventRecord(TypedDict):
    """Append-only audit event without source document bodies."""

    id: str
    project_id: str | None
    actor: str
    action: str
    entity_type: str
    entity_id: str
    summary: str
    metadata: dict[str, object]
    created_at: str


class LegacyMigrationReport(TypedDict):
    """Idempotent legacy migration counts."""

    legacy_available: bool
    assets_created: int
    assets_existing: int
    revisions_created: int
    revisions_existing: int


class WritingStorage:
    """Thread-safe repositories for projects, briefs, assets and workflow state."""

    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path).expanduser()
        self._write_lock = threading.RLock()
        self.initialize()

    def initialize(self) -> None:
        """Create or validate the independent writing-core schema."""

        with self._write_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                version_row = connection.execute(
                    "SELECT value FROM schema_metadata WHERE key='writing_schema_version'"
                ).fetchone()
                current_version = int(version_row[0]) if version_row is not None else 0
                if current_version not in {0, 1, 2, WRITING_SCHEMA_VERSION}:
                    raise WritingStorageError(
                        "writing schema version mismatch: "
                        f"expected {WRITING_SCHEMA_VERSION}, got {version_row[0]!r}"
                    )
                connection.executescript(_SCHEMA_SQL)
                if current_version == 1 and not _column_exists(connection, "projects", "tags_json"):
                    connection.execute(
                        "ALTER TABLE projects ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'"
                    )
                if current_version in {1, 2} and not _column_exists(
                    connection, "evidence_snippets", "source_hash"
                ):
                    connection.execute(
                        "ALTER TABLE evidence_snippets "
                        "ADD COLUMN source_hash TEXT NOT NULL DEFAULT ''"
                    )
                _create_knowledge_fts(connection)
                connection.execute(
                    """
                    INSERT INTO schema_metadata(key, value)
                    VALUES ('writing_schema_version', ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                    """,
                    (str(WRITING_SCHEMA_VERSION),),
                )
                connection.commit()

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a short-lived read connection."""

        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def write_transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield one serialized transaction for persistence-only work."""

        with self._write_lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

    def check_ready(self) -> None:
        """Verify the schema marker and all required writing tables."""

        with self.read_connection() as connection:
            marker = connection.execute(
                "SELECT value FROM schema_metadata WHERE key='writing_schema_version'"
            ).fetchone()
            if marker is None or int(marker[0]) != WRITING_SCHEMA_VERSION:
                raise WritingStorageError("writing schema version is missing or incompatible")
            for table in _REQUIRED_TABLES:
                if not _table_exists(connection, table):
                    raise WritingStorageError(f"writing table is missing: {table}")

    def save_project(self, project: WritingProject) -> WritingProject:
        """Insert or update a project."""

        with self.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO projects(
                    id, name, description, tags_json, default_pack_id,
                    default_model_profile_id, archived, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    tags_json=excluded.tags_json,
                    default_pack_id=excluded.default_pack_id,
                    default_model_profile_id=excluded.default_model_profile_id,
                    archived=excluded.archived,
                    updated_at=excluded.updated_at
                """,
                (
                    project.id,
                    project.name,
                    project.description,
                    _dump_json(project.tags),
                    project.default_pack_id,
                    project.default_model_profile_id,
                    int(project.archived),
                    _datetime_text(project.created_at),
                    _datetime_text(project.updated_at),
                ),
            )
        return project

    def create_project(
        self,
        name: str,
        *,
        description: str = "",
        tags: Sequence[str] = (),
        default_pack_id: str = "workplace",
        default_model_profile_id: str | None = None,
        project_id: str | None = None,
    ) -> WritingProject:
        """Create a project using domain-model defaults."""

        return self.save_project(
            WritingProject(
                id=project_id or uuid.uuid4().hex,
                name=name,
                description=description,
                tags=tuple(tags),
                default_pack_id=default_pack_id,
                default_model_profile_id=default_model_profile_id,
            )
        )

    def get_project(self, project_id: str) -> WritingProject:
        with self.read_connection() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise RecordNotFoundError(f"project not found: {project_id}")
        return _project_from_row(row)

    def list_projects(self, *, limit: int = 50, offset: int = 0) -> list[WritingProject]:
        _validate_page(limit, offset)
        with self.read_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC, id ASC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_project_from_row(row) for row in rows]

    def save_brief(self, brief: WritingBrief, *, project_id: str | None = None) -> WritingBrief:
        """Persist a complete immutable brief payload under its stable id."""

        now = _utc_now()
        with self.write_transaction() as connection:
            _validate_brief_project(connection, brief.id, project_id)
            connection.execute(
                """
                INSERT INTO writing_briefs(id, project_id, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    project_id=COALESCE(excluded.project_id, writing_briefs.project_id),
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (brief.id, project_id, _dump_model(brief), now, now),
            )
        return brief

    def get_brief(self, brief_id: str, *, project_id: str | None = None) -> WritingBrief:
        where = "id=? AND project_id=?" if project_id is not None else "id=?"
        params: tuple[object, ...] = (
            (brief_id, project_id) if project_id is not None else (brief_id,)
        )
        with self.read_connection() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM writing_briefs WHERE {where}", params
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"brief not found: {brief_id}")
        return WritingBrief.model_validate_json(str(row[0]))

    def list_briefs(
        self,
        *,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WritingBrief]:
        _validate_page(limit, offset)
        where = "WHERE project_id=?" if project_id is not None else ""
        params: tuple[object, ...] = (project_id, limit, offset) if project_id else (limit, offset)
        with self.read_connection() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM writing_briefs {where} "
                "ORDER BY updated_at DESC, id ASC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [WritingBrief.model_validate_json(str(row[0])) for row in rows]

    def create_text_asset(
        self,
        brief: WritingBrief,
        blocks: Sequence[ContentBlock],
        *,
        title: str | None = None,
        status: str = "draft",
        channel: Channel | None = None,
        project_id: str | None = None,
        parent_asset_id: str | None = None,
        asset_id: str | None = None,
        note: str = "创建文稿",
        model_profile_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> TextAsset:
        """Create an asset and its first immutable revision atomically."""

        normalized_blocks = tuple(blocks)
        asset = TextAsset(
            id=asset_id or uuid.uuid4().hex,
            brief_id=brief.id,
            parent_asset_id=parent_asset_id,
            title=title or brief.title,
            content_type=brief.content_type,
            channel=channel or brief.channel,
            status=cast(Any, status),
            blocks=normalized_blocks,
            current_revision=1,
        )
        revision = Revision(
            asset_id=asset.id,
            version=1,
            note=note,
            blocks=normalized_blocks,
            model_profile_id=model_profile_id or brief.model_profile_id,
            created_at=asset.created_at,
        )
        with self.write_transaction() as connection:
            _validate_brief_project(connection, brief.id, project_id)
            if project_id is not None and parent_asset_id is not None:
                _validate_asset_project(connection, parent_asset_id, project_id)
            _upsert_brief(connection, brief, project_id=project_id)
            connection.execute(
                """
                INSERT INTO text_assets(
                    id, project_id, brief_id, parent_asset_id, title, content_type,
                    channel, status, current_revision, brief_json, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset.id,
                    project_id,
                    asset.brief_id,
                    asset.parent_asset_id,
                    asset.title,
                    asset.content_type,
                    asset.channel,
                    asset.status,
                    asset.current_revision,
                    _dump_model(brief),
                    _dump_json(metadata or {}),
                    _datetime_text(asset.created_at),
                    _datetime_text(asset.updated_at),
                ),
            )
            _insert_revision(connection, revision, title=asset.title)
        return asset

    def get_text_asset(self, asset_id: str, *, project_id: str | None = None) -> TextAsset:
        project_clause = "AND a.project_id=?" if project_id is not None else ""
        params: tuple[object, ...] = (
            (asset_id, project_id) if project_id is not None else (asset_id,)
        )
        with self.read_connection() as connection:
            row = connection.execute(
                f"""
                SELECT a.*, r.blocks_json
                FROM text_assets AS a
                JOIN revisions AS r
                  ON r.asset_id=a.id AND r.version=a.current_revision
                WHERE a.id=? {project_clause}
                """,
                params,
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"text asset not found: {asset_id}")
        return _asset_from_row(row)

    def list_text_assets(
        self,
        *,
        project_id: str | None = None,
        content_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TextAsset]:
        _validate_page(limit, offset)
        clauses: list[str] = []
        values: list[object] = []
        for field, value in (
            ("a.project_id", project_id),
            ("a.content_type", content_type),
            ("a.status", status),
        ):
            if value is not None:
                clauses.append(f"{field}=?")
                values.append(value)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        values.extend((limit, offset))
        with self.read_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT a.*, r.blocks_json
                FROM text_assets AS a
                JOIN revisions AS r
                  ON r.asset_id=a.id AND r.version=a.current_revision
                {where}
                ORDER BY a.updated_at DESC, a.id ASC LIMIT ? OFFSET ?
                """,
                tuple(values),
            ).fetchall()
        return [_asset_from_row(row) for row in rows]

    def save_revision(
        self,
        asset_id: str,
        blocks: Sequence[ContentBlock],
        *,
        note: str = "",
        model_profile_id: str | None = None,
        expected_revision: int | None = None,
        title: str | None = None,
        status: str | None = None,
        workflow_run_id: str | None = None,
        project_id: str | None = None,
    ) -> Revision:
        """Append a revision with optimistic concurrency protection."""

        normalized_blocks = tuple(blocks)
        now = datetime.now(UTC)
        with self.write_transaction() as connection:
            where = "id=? AND project_id=?" if project_id is not None else "id=?"
            params: tuple[object, ...] = (
                (asset_id, project_id) if project_id is not None else (asset_id,)
            )
            asset = connection.execute(
                f"SELECT title, current_revision FROM text_assets WHERE {where}", params
            ).fetchone()
            if asset is None:
                raise RecordNotFoundError(f"text asset not found: {asset_id}")
            current = int(asset["current_revision"])
            if expected_revision is not None and current != expected_revision:
                raise RevisionConflictError(
                    f"revision conflict: expected {expected_revision}, current {current}"
                )
            revision = Revision(
                asset_id=asset_id,
                version=current + 1,
                note=note,
                blocks=normalized_blocks,
                created_at=now,
                model_profile_id=model_profile_id,
            )
            _insert_revision(
                connection,
                revision,
                title=title or str(asset["title"]),
                workflow_run_id=workflow_run_id,
            )
            updates = ["current_revision=?", "updated_at=?"]
            values: list[object] = [revision.version, _datetime_text(now)]
            if title is not None:
                updates.append("title=?")
                values.append(title)
            if status is not None:
                updates.append("status=?")
                values.append(status)
            values.append(asset_id)
            connection.execute(
                f"UPDATE text_assets SET {', '.join(updates)} WHERE id=?",
                tuple(values),
            )
        return revision

    def get_revision(
        self,
        asset_id: str,
        version: int,
        *,
        project_id: str | None = None,
    ) -> Revision:
        project_clause = "AND a.project_id=?" if project_id is not None else ""
        params: tuple[object, ...] = (
            (asset_id, version, project_id) if project_id is not None else (asset_id, version)
        )
        with self.read_connection() as connection:
            row = connection.execute(
                f"""
                SELECT r.* FROM revisions AS r
                JOIN text_assets AS a ON a.id=r.asset_id
                WHERE r.asset_id=? AND r.version=? {project_clause}
                """,
                params,
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"revision not found: {asset_id}@{version}")
        return _revision_from_row(row)

    def list_revisions(
        self,
        asset_id: str,
        *,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Revision]:
        _validate_page(limit, offset)
        project_clause = "AND a.project_id=?" if project_id is not None else ""
        params: tuple[object, ...] = (
            (asset_id, project_id, limit, offset)
            if project_id is not None
            else (asset_id, limit, offset)
        )
        with self.read_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT r.* FROM revisions AS r
                JOIN text_assets AS a ON a.id=r.asset_id
                WHERE r.asset_id=? {project_clause}
                ORDER BY version DESC LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [_revision_from_row(row) for row in rows]

    def save_project_term(self, term: ProjectTerm) -> ProjectTerm:
        """Upsert a project terminology rule."""

        now = _utc_now()
        with self.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO project_terms(
                    id, project_id, term, preferred_form, description,
                    discouraged_variants_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, term) DO UPDATE SET
                    id=excluded.id,
                    preferred_form=excluded.preferred_form,
                    description=excluded.description,
                    discouraged_variants_json=excluded.discouraged_variants_json,
                    updated_at=excluded.updated_at
                """,
                (
                    term.id,
                    term.project_id,
                    term.term,
                    term.preferred_form,
                    term.description,
                    _dump_json(term.discouraged_variants),
                    now,
                    now,
                ),
            )
        return term

    def list_project_terms(self, project_id: str) -> list[ProjectTerm]:
        with self.read_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM project_terms WHERE project_id=? ORDER BY term, id",
                (project_id,),
            ).fetchall()
        return [
            ProjectTerm(
                id=str(row["id"]),
                project_id=str(row["project_id"]),
                term=str(row["term"]),
                preferred_form=str(row["preferred_form"]),
                description=str(row["description"]),
                discouraged_variants=tuple(_load_list(str(row["discouraged_variants_json"]))),
            )
            for row in rows
        ]

    def delete_project_term(self, term_id: str, *, project_id: str) -> bool:
        """Delete one terminology rule inside its owning project."""

        with self.write_transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM project_terms WHERE id=? AND project_id=?",
                (term_id, project_id),
            )
        return cursor.rowcount > 0

    def append_audit_event(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        project_id: str | None = None,
        actor: str = "local-user",
        summary: str = "",
        metadata: Mapping[str, object] | None = None,
        event_id: str | None = None,
    ) -> AuditEventRecord:
        """Append a compact event; source bodies stay in their owning records."""

        record: AuditEventRecord = {
            "id": event_id or uuid.uuid4().hex,
            "project_id": project_id,
            "actor": actor,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "summary": summary,
            "metadata": dict(metadata or {}),
            "created_at": _utc_now(),
        }
        with self.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO audit_events(
                    id, project_id, actor, action, entity_type, entity_id,
                    summary, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["project_id"],
                    record["actor"],
                    record["action"],
                    record["entity_type"],
                    record["entity_id"],
                    record["summary"],
                    _dump_json(record["metadata"]),
                    record["created_at"],
                ),
            )
        return record

    def list_audit_events(
        self,
        *,
        project_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEventRecord]:
        _validate_page(limit, offset, maximum=500)
        where = "WHERE project_id=?" if project_id is not None else ""
        params: tuple[object, ...] = (project_id, limit, offset) if project_id else (limit, offset)
        with self.read_connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM audit_events {where} "
                "ORDER BY created_at DESC, id ASC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [_audit_event_from_row(row) for row in rows]

    def migrate_legacy_gongwen(self) -> LegacyMigrationReport:
        """Copy valid legacy documents into the new model without altering legacy tables.

        IDs, revision numbers and timestamps are retained.  Deterministic new
        revision IDs plus ``legacy_version_id`` metadata make repeated calls
        idempotent and preserve the original integer row identifier.
        """

        report: LegacyMigrationReport = {
            "legacy_available": False,
            "assets_created": 0,
            "assets_existing": 0,
            "revisions_created": 0,
            "revisions_existing": 0,
        }
        with self.write_transaction() as connection:
            if not (
                _table_exists(connection, "documents")
                and _table_exists(connection, "document_versions")
            ):
                return report
            report["legacy_available"] = True
            documents = connection.execute("SELECT * FROM documents ORDER BY id").fetchall()
            versions = connection.execute(
                "SELECT * FROM document_versions ORDER BY document_id, version_number"
            ).fetchall()
            versions_by_document: dict[str, list[sqlite3.Row]] = {}
            for version in versions:
                versions_by_document.setdefault(str(version["document_id"]), []).append(version)

            # Validate the complete source snapshot before the first insert.
            for document in documents:
                document_id = str(document["id"])
                available = versions_by_document.get(document_id, [])
                numbers = [int(row["version_number"]) for row in available]
                current = int(document["current_version"])
                if current < 1 or numbers != list(range(1, current + 1)):
                    raise WritingStorageError(
                        f"legacy document has an incomplete version sequence: {document_id}"
                    )

            for document in documents:
                document_id = str(document["id"])
                existing_asset = connection.execute(
                    "SELECT metadata_json FROM text_assets WHERE id=?", (document_id,)
                ).fetchone()
                if existing_asset is None:
                    _insert_legacy_asset(connection, document)
                    report["assets_created"] += 1
                else:
                    existing_metadata = _load_object(str(existing_asset["metadata_json"]))
                    if existing_metadata.get("legacy_source") != "gongwen":
                        raise WritingStorageError(
                            f"legacy document id conflicts with a writing asset: {document_id}"
                        )
                    report["assets_existing"] += 1

                for legacy_version in versions_by_document.get(document_id, []):
                    revision_id = f"legacy-gongwen-{legacy_version['id']}"
                    existing_revision = connection.execute(
                        "SELECT asset_id, version FROM revisions WHERE id=?", (revision_id,)
                    ).fetchone()
                    if existing_revision is not None:
                        if str(existing_revision["asset_id"]) != document_id or int(
                            existing_revision["version"]
                        ) != int(legacy_version["version_number"]):
                            raise WritingStorageError(
                                f"legacy revision id conflicts with another revision: {revision_id}"
                            )
                        report["revisions_existing"] += 1
                        continue
                    _insert_legacy_revision(connection, legacy_version, revision_id)
                    report["revisions_created"] += 1
        return report

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=_BUSY_TIMEOUT_MS / 1_000,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection


YanzhangStorage = WritingStorage


def _validate_brief_project(
    connection: sqlite3.Connection,
    brief_id: str,
    project_id: str | None,
) -> None:
    if project_id is None:
        return
    row = connection.execute(
        "SELECT project_id FROM writing_briefs WHERE id=?", (brief_id,)
    ).fetchone()
    if row is None:
        return
    current_project = str(row["project_id"]) if row["project_id"] is not None else None
    if current_project == project_id:
        return
    if current_project is None:
        attached = connection.execute(
            "SELECT 1 FROM text_assets WHERE brief_id=? LIMIT 1", (brief_id,)
        ).fetchone()
        if attached is None:
            return
    raise ProjectScopeError(f"brief does not belong to project: {brief_id}")


def _validate_asset_project(
    connection: sqlite3.Connection,
    asset_id: str,
    project_id: str,
) -> None:
    row = connection.execute(
        "SELECT project_id FROM text_assets WHERE id=?", (asset_id,)
    ).fetchone()
    if row is None:
        raise RecordNotFoundError(f"text asset not found: {asset_id}")
    current_project = str(row["project_id"]) if row["project_id"] is not None else None
    if current_project != project_id:
        raise ProjectScopeError(f"text asset does not belong to project: {asset_id}")


def _upsert_brief(
    connection: sqlite3.Connection,
    brief: WritingBrief,
    *,
    project_id: str | None,
) -> None:
    now = _utc_now()
    connection.execute(
        """
        INSERT INTO writing_briefs(id, project_id, payload_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            project_id=COALESCE(excluded.project_id, writing_briefs.project_id),
            payload_json=excluded.payload_json,
            updated_at=excluded.updated_at
        """,
        (brief.id, project_id, _dump_model(brief), now, now),
    )


def _insert_revision(
    connection: sqlite3.Connection,
    revision: Revision,
    *,
    title: str,
    workflow_run_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO revisions(
            id, asset_id, version, title, note, blocks_json, model_profile_id,
            workflow_run_id, model_lineage_json, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', ?)
        """,
        (
            revision.id,
            revision.asset_id,
            revision.version,
            title,
            revision.note,
            _dump_json(revision.blocks),
            revision.model_profile_id,
            workflow_run_id,
            _datetime_text(revision.created_at),
        ),
    )


def _project_from_row(row: sqlite3.Row) -> WritingProject:
    return WritingProject(
        id=str(row["id"]),
        name=str(row["name"]),
        description=str(row["description"]),
        tags=tuple(_load_list(str(row["tags_json"]))),
        default_pack_id=str(row["default_pack_id"]),
        default_model_profile_id=(
            str(row["default_model_profile_id"])
            if row["default_model_profile_id"] is not None
            else None
        ),
        archived=bool(row["archived"]),
        created_at=_parse_datetime(str(row["created_at"])),
        updated_at=_parse_datetime(str(row["updated_at"])),
    )


def _asset_from_row(row: sqlite3.Row) -> TextAsset:
    blocks = _blocks_from_json(str(row["blocks_json"]))
    return TextAsset(
        id=str(row["id"]),
        brief_id=str(row["brief_id"]),
        parent_asset_id=str(row["parent_asset_id"]) if row["parent_asset_id"] else None,
        title=str(row["title"]),
        content_type=str(row["content_type"]),
        channel=cast(Any, str(row["channel"])),
        status=cast(Any, str(row["status"])),
        blocks=blocks,
        current_revision=int(row["current_revision"]),
        created_at=_parse_datetime(str(row["created_at"])),
        updated_at=_parse_datetime(str(row["updated_at"])),
    )


def _revision_from_row(row: sqlite3.Row) -> Revision:
    return Revision(
        id=str(row["id"]),
        asset_id=str(row["asset_id"]),
        version=int(row["version"]),
        note=str(row["note"]),
        blocks=_blocks_from_json(str(row["blocks_json"])),
        created_at=_parse_datetime(str(row["created_at"])),
        model_profile_id=str(row["model_profile_id"]) if row["model_profile_id"] else None,
    )


def _audit_event_from_row(row: sqlite3.Row) -> AuditEventRecord:
    return {
        "id": str(row["id"]),
        "project_id": str(row["project_id"]) if row["project_id"] else None,
        "actor": str(row["actor"]),
        "action": str(row["action"]),
        "entity_type": str(row["entity_type"]),
        "entity_id": str(row["entity_id"]),
        "summary": str(row["summary"]),
        "metadata": _load_object(str(row["metadata_json"])),
        "created_at": str(row["created_at"]),
    }


def _insert_legacy_asset(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    document_id = str(row["id"])
    content_type = str(row["document_type"]) or "official_document"
    brief_id = f"legacy-gongwen-{document_id}"
    brief_payload: dict[str, object] = {
        "id": brief_id,
        "title": str(row["title"]),
        "goal": "保留并继续编辑旧版砚章公文文稿",
        "audience": "原文读者",
        "channel": "document",
        "content_type": content_type,
        "scenario_pack_id": "gongwen",
        "recipe_id": "legacy-import",
        "tone": "准确、清晰、得体",
        "length": "legacy",
        "target_language": "zh-CN",
        "constraints": [],
        "keywords": [],
        "knowledge_item_ids": [],
        "model_profile_id": None,
    }
    connection.execute(
        """
        INSERT OR IGNORE INTO writing_briefs(
            id, project_id, payload_json, created_at, updated_at
        ) VALUES (?, NULL, ?, ?, ?)
        """,
        (
            brief_id,
            _dump_json(brief_payload),
            str(row["created_at"]),
            str(row["updated_at"]),
        ),
    )
    connection.execute(
        """
        INSERT INTO text_assets(
            id, project_id, brief_id, parent_asset_id, title, content_type,
            channel, status, current_revision, brief_json, metadata_json,
            created_at, updated_at
        ) VALUES (?, NULL, ?, NULL, ?, ?, 'document', 'draft', ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            brief_id,
            str(row["title"]),
            content_type,
            int(row["current_version"]),
            _dump_json(brief_payload),
            _dump_json(
                {
                    "legacy_source": "gongwen",
                    "legacy_metadata": _load_object(str(row["metadata_json"])),
                }
            ),
            str(row["created_at"]),
            str(row["updated_at"]),
        ),
    )


def _insert_legacy_revision(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    revision_id: str,
) -> None:
    content = str(row["content"])
    chunks = tuple(
        content[offset : offset + 200_000] for offset in range(0, max(1, len(content)), 200_000)
    )
    blocks = tuple(
        ContentBlock(
            id=f"legacy-block-{row['document_id']}-{row['version_number']}-{order}",
            kind="paragraph",
            order=order,
            text=chunk,
        )
        for order, chunk in enumerate(chunks)
    )
    connection.execute(
        """
        INSERT INTO revisions(
            id, asset_id, version, title, note, blocks_json, model_profile_id,
            workflow_run_id, model_lineage_json, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)
        """,
        (
            revision_id,
            str(row["document_id"]),
            int(row["version_number"]),
            str(row["title"]),
            str(row["note"]),
            _dump_json(blocks),
            _dump_json({"legacy_source": "gongwen", "legacy_version_id": int(row["id"])}),
            _dump_json({"legacy_metadata": _load_object(str(row["metadata_json"]))}),
            str(row["created_at"]),
        ),
    )


def _create_knowledge_fts(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "knowledge_items_fts"):
        try:
            connection.execute(
                """
                CREATE VIRTUAL TABLE knowledge_items_fts
                USING fts5(item_id UNINDEXED, title, content, tokenize='trigram')
                """
            )
        except sqlite3.OperationalError:
            connection.execute(
                """
                CREATE VIRTUAL TABLE knowledge_items_fts
                USING fts5(item_id UNINDEXED, title, content, tokenize='unicode61')
                """
            )
    connection.execute(
        """
        INSERT INTO knowledge_items_fts(item_id, title, content)
        SELECT k.id, k.title, k.content
        FROM knowledge_items AS k
        WHERE NOT EXISTS (
            SELECT 1 FROM knowledge_items_fts AS f WHERE f.item_id=k.id
        )
        """
    )


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", (name,)
        ).fetchone()
        is not None
    )


def _column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    return any(
        str(row["name"]) == column for row in connection.execute(f"PRAGMA table_info({table})")
    )


def _dump_model(model: BaseModel) -> str:
    return model.model_dump_json()


def _dump_json(value: object) -> str:
    def default(item: object) -> object:
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        if isinstance(item, datetime):
            return _datetime_text(item)
        raise TypeError(f"unsupported JSON value: {type(item).__name__}")

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=default)


def _load_object(value: str) -> dict[str, object]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise WritingStorageError("stored JSON value is not an object")
    return cast(dict[str, object], loaded)


def _load_list(value: str) -> list[str]:
    loaded = json.loads(value)
    if not isinstance(loaded, list) or any(not isinstance(item, str) for item in loaded):
        raise WritingStorageError("stored JSON value is not a string list")
    return cast(list[str], loaded)


def _blocks_from_json(value: str) -> tuple[ContentBlock, ...]:
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        raise WritingStorageError("stored blocks are not a list")
    return tuple(ContentBlock.model_validate(item) for item in loaded)


def _datetime_text(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _validate_page(limit: int, offset: int, *, maximum: int = 100) -> None:
    if not 1 <= limit <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")
    if offset < 0:
        raise ValueError("offset must be non-negative")


_REQUIRED_TABLES = (
    "projects",
    "writing_briefs",
    "text_assets",
    "revisions",
    "knowledge_items",
    "knowledge_items_fts",
    "evidence_snippets",
    "claims",
    "citations",
    "workflow_runs",
    "step_runs",
    "audit_events",
    "project_terms",
)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    default_pack_id TEXT NOT NULL DEFAULT 'workplace',
    default_model_profile_id TEXT,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS writing_briefs (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_writing_briefs_project
ON writing_briefs(project_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS text_assets (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    brief_id TEXT NOT NULL,
    parent_asset_id TEXT,
    title TEXT NOT NULL,
    content_type TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'document',
    status TEXT NOT NULL DEFAULT 'draft',
    current_revision INTEGER NOT NULL CHECK (current_revision >= 0),
    brief_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (brief_id) REFERENCES writing_briefs(id) ON DELETE RESTRICT,
    FOREIGN KEY (parent_asset_id) REFERENCES text_assets(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_text_assets_project
ON text_assets(project_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_text_assets_kind
ON text_assets(content_type, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS revisions (
    id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    title TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    blocks_json TEXT NOT NULL,
    model_profile_id TEXT,
    workflow_run_id TEXT,
    model_lineage_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(asset_id, version),
    FOREIGN KEY (asset_id) REFERENCES text_assets(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_revisions_asset
ON revisions(asset_id, version DESC);

CREATE TABLE IF NOT EXISTS knowledge_items (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    content_hash TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_knowledge_project_kind
ON knowledge_items(project_id, kind, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_hash
ON knowledge_items(project_id, content_hash);

CREATE TABLE IF NOT EXISTS evidence_snippets (
    id TEXT PRIMARY KEY,
    knowledge_item_id TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    locator TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    source_hash TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (knowledge_item_id) REFERENCES knowledge_items(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_evidence_knowledge
ON evidence_snippets(knowledge_item_id, id);

CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    block_id TEXT NOT NULL,
    text TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    confidence INTEGER NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 100),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES text_assets(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_claims_asset ON claims(asset_id, block_id, id);

CREATE TABLE IF NOT EXISTS citations (
    id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    block_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(claim_id, evidence_id),
    FOREIGN KEY (asset_id) REFERENCES text_assets(id) ON DELETE CASCADE,
    FOREIGN KEY (claim_id) REFERENCES claims(id) ON DELETE CASCADE,
    FOREIGN KEY (evidence_id) REFERENCES evidence_snippets(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_citations_asset ON citations(asset_id, block_id, id);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    workflow_version TEXT NOT NULL,
    project_id TEXT,
    status TEXT NOT NULL,
    current_step_id TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    input_json TEXT NOT NULL,
    state_json TEXT NOT NULL DEFAULT '{}',
    definition_json TEXT NOT NULL,
    output_asset_id TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL,
    FOREIGN KEY (output_asset_id) REFERENCES text_assets(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_status
ON workflow_runs(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_project
ON workflow_runs(project_id, updated_at DESC, id);

CREATE TABLE IF NOT EXISTS step_runs (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    handler TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    input_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT NOT NULL DEFAULT '{}',
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    error_message TEXT,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(run_id, step_id),
    FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_step_runs_run
ON step_runs(run_id, position);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_events_project
ON audit_events(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_entity
ON audit_events(entity_type, entity_id, created_at DESC);

CREATE TABLE IF NOT EXISTS project_terms (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    term TEXT NOT NULL,
    preferred_form TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    discouraged_variants_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, term),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_project_terms_project
ON project_terms(project_id, term);
"""


__all__ = [
    "AuditEventRecord",
    "LegacyMigrationReport",
    "ProjectScopeError",
    "RecordNotFoundError",
    "RevisionConflictError",
    "StepRunRecord",
    "WorkflowRunRecord",
    "WritingStorage",
    "WritingStorageError",
    "YanzhangStorage",
]
