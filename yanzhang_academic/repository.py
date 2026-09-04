"""Project-isolated SQLite persistence for the academic writing pack.

The repository shares :class:`yanzhang_core.storage.WritingStorage` connections
and transactions.  It contains no connector or model calls, so every transaction
is short-lived and limited to local persistence work.
"""

# Chinese user-facing persistence messages intentionally use full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import NoReturn, cast

from pydantic import BaseModel, ValidationError

from yanzhang_academic.models import (
    BibliographicRecord,
    ClaimCitationLink,
    EvidenceSnippet,
    LiteratureMatrix,
    ResearchClaim,
)
from yanzhang_core.storage import WritingStorage

ACADEMIC_SCHEMA_VERSION = 1
_MAX_BATCH_ITEMS = 1_000
_SHA256 = re.compile(r"[0-9a-f]{64}")
_WHITESPACE = re.compile(r"\s+")


class AcademicRepositoryError(RuntimeError):
    """Stable base exception for academic persistence failures."""


class AcademicSchemaError(AcademicRepositoryError):
    """Raised when the academic schema marker or objects are inconsistent."""


class AcademicNotFoundError(AcademicRepositoryError, LookupError):
    """Raised when an object is absent from the requested project."""


class AcademicRelationError(AcademicRepositoryError, ValueError):
    """Raised when a cross-object relation violates project or source lineage."""


class AcademicStoredDataError(AcademicRepositoryError, ValueError):
    """Raised when persisted JSON does not satisfy its closed model contract."""


class AcademicRepository:
    """Persist literature, evidence, claims, links, and matrices by project."""

    def __init__(self, storage: WritingStorage) -> None:
        if not isinstance(storage, WritingStorage):
            raise TypeError("storage 应为 WritingStorage")
        self.storage = storage
        self.initialize()

    def initialize(self) -> None:
        """Apply every missing academic migration in one local transaction."""

        with self.storage.write_transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            row = connection.execute(
                "SELECT value FROM schema_metadata WHERE key='academic_schema_version'"
            ).fetchone()
            current = _schema_version(row)
            if current > ACADEMIC_SCHEMA_VERSION:
                raise AcademicSchemaError(
                    "academic schema version is newer than this application: "
                    f"{current} > {ACADEMIC_SCHEMA_VERSION}"
                )
            for version in range(current + 1, ACADEMIC_SCHEMA_VERSION + 1):
                statements = _MIGRATIONS.get(version)
                if statements is None:
                    raise AcademicSchemaError(f"academic schema migration is missing: {version}")
                for statement in statements:
                    connection.execute(statement)
            connection.execute(
                """
                INSERT INTO schema_metadata(key, value)
                VALUES ('academic_schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (str(ACADEMIC_SCHEMA_VERSION),),
            )
            _check_schema_objects(connection)

    def check_ready(self) -> None:
        """Verify the schema marker and required academic tables."""

        with self.storage.read_connection() as connection:
            row = connection.execute(
                "SELECT value FROM schema_metadata WHERE key='academic_schema_version'"
            ).fetchone()
            if _schema_version(row) != ACADEMIC_SCHEMA_VERSION:
                raise AcademicSchemaError("academic schema version is missing or incompatible")
            _check_schema_objects(connection)

    def upsert_record(self, project_id: str, record: BibliographicRecord) -> BibliographicRecord:
        """Insert or refresh one bibliographic record inside a project."""

        return self.upsert_records(project_id, [record])[0]

    def upsert_records(
        self, project_id: str, records: Sequence[BibliographicRecord]
    ) -> list[BibliographicRecord]:
        """Atomically insert or refresh a bounded record collection."""

        project_key = _project_key(project_id)
        values = _model_batch(records, BibliographicRecord, "records")
        with self.storage.write_transaction() as connection:
            _require_project(connection, project_key)
            for record in values:
                _upsert_record(connection, project_key, record)
        return values

    def get_record(self, project_id: str, record_id: str) -> BibliographicRecord:
        """Read one record only from the named project."""

        project_key = _project_key(project_id)
        record_key = _entity_key(record_id, "record_id")
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            return _get_record(connection, project_key, record_key)

    def get_records(self, project_id: str, record_ids: Sequence[str]) -> list[BibliographicRecord]:
        """Read records in caller order, rejecting missing or duplicate IDs."""

        project_key = _project_key(project_id)
        ids = _entity_ids(record_ids, "record_ids")
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            return [_get_record(connection, project_key, record_id) for record_id in ids]

    def list_records(
        self,
        project_id: str,
        *,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BibliographicRecord]:
        """List or search bibliographic records within one project."""

        project_key = _project_key(project_id)
        _validate_page(limit, offset)
        normalized_query = query.strip() if query is not None else ""
        if query is not None and not normalized_query:
            raise ValueError("query 应包含检索文本")
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            if normalized_query:
                rows = _search_record_rows(
                    connection,
                    project_key,
                    normalized_query,
                    limit=limit,
                    offset=offset,
                )
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM academic_records
                    WHERE project_id=?
                    ORDER BY imported_at DESC, id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (project_key, limit, offset),
                ).fetchall()
            return [_record_from_row(row) for row in rows]

    def count_records(self, project_id: str, *, query: str | None = None) -> int:
        """Count bibliographic records using the same project-local search semantics."""

        project_key = _project_key(project_id)
        normalized_query = query.strip() if query is not None else ""
        if query is not None and not normalized_query:
            raise ValueError("query 应包含检索文本")
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            if normalized_query:
                fts_row = connection.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM academic_records_fts
                    WHERE academic_records_fts MATCH ? AND project_id=?
                    """,
                    (_fts_query(normalized_query), project_key),
                ).fetchone()
                fts_total = int(fts_row["total"]) if fts_row is not None else 0
                if fts_total:
                    return fts_total
                escaped = _like_pattern(normalized_query)
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS total FROM academic_records
                    WHERE project_id=? AND (
                        title LIKE ? ESCAPE '\\' OR abstract LIKE ? ESCAPE '\\'
                        OR authors_text LIKE ? ESCAPE '\\'
                        OR keywords_text LIKE ? ESCAPE '\\'
                        OR COALESCE(doi, '') LIKE ? ESCAPE '\\'
                        OR source_key LIKE ? ESCAPE '\\'
                    )
                    """,
                    (project_key, escaped, escaped, escaped, escaped, escaped, escaped),
                ).fetchone()
                return int(row["total"]) if row is not None else 0
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM academic_records WHERE project_id=?",
                (project_key,),
            ).fetchone()
            return int(row["total"]) if row is not None else 0

    def delete_record(self, project_id: str, record_id: str) -> bool:
        """Delete a record and every project-local dependent object."""

        project_key = _project_key(project_id)
        record_key = _entity_key(record_id, "record_id")
        with self.storage.write_transaction() as connection:
            _require_project(connection, project_key)
            _delete_matrices_for_records(connection, project_key, [record_key])
            cursor = connection.execute(
                "DELETE FROM academic_records WHERE project_id=? AND id=?",
                (project_key, record_key),
            )
        return cursor.rowcount > 0

    def upsert_evidence(self, project_id: str, evidence: EvidenceSnippet) -> EvidenceSnippet:
        """Insert or refresh one exact, source-bound evidence excerpt."""

        return self.upsert_evidence_batch(project_id, [evidence])[0]

    def upsert_evidence_batch(
        self, project_id: str, evidence: Sequence[EvidenceSnippet]
    ) -> list[EvidenceSnippet]:
        """Atomically persist a bounded evidence collection."""

        project_key = _project_key(project_id)
        values = _model_batch(evidence, EvidenceSnippet, "evidence")
        with self.storage.write_transaction() as connection:
            _require_project(connection, project_key)
            for snippet in values:
                _upsert_evidence(connection, project_key, snippet)
        return values

    def get_evidence(self, project_id: str, evidence_id: str) -> EvidenceSnippet:
        """Read one evidence excerpt and re-check its current source lineage."""

        project_key = _project_key(project_id)
        evidence_key = _entity_key(evidence_id, "evidence_id")
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            return _get_evidence(connection, project_key, evidence_key)

    def get_evidence_batch(
        self, project_id: str, evidence_ids: Sequence[str]
    ) -> list[EvidenceSnippet]:
        """Read evidence in caller order, rejecting missing or duplicate IDs."""

        project_key = _project_key(project_id)
        ids = _entity_ids(evidence_ids, "evidence_ids")
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            return [_get_evidence(connection, project_key, evidence_id) for evidence_id in ids]

    def list_evidence(
        self,
        project_id: str,
        *,
        record_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EvidenceSnippet]:
        """List project evidence, optionally narrowed to one record."""

        project_key = _project_key(project_id)
        record_key = _entity_key(record_id, "record_id") if record_id is not None else None
        _validate_page(limit, offset)
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            if record_key is None:
                rows = connection.execute(
                    """
                    SELECT * FROM academic_evidence WHERE project_id=?
                    ORDER BY created_at, id LIMIT ? OFFSET ?
                    """,
                    (project_key, limit, offset),
                ).fetchall()
            else:
                _get_record(connection, project_key, record_key)
                rows = connection.execute(
                    """
                    SELECT * FROM academic_evidence
                    WHERE project_id=? AND record_id=?
                    ORDER BY created_at, id LIMIT ? OFFSET ?
                    """,
                    (project_key, record_key, limit, offset),
                ).fetchall()
            return [_evidence_from_row(connection, project_key, row) for row in rows]

    def count_evidence(self, project_id: str, *, record_id: str | None = None) -> int:
        """Count project evidence, optionally narrowed to one existing record."""

        project_key = _project_key(project_id)
        record_key = _entity_key(record_id, "record_id") if record_id is not None else None
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            if record_key is None:
                row = connection.execute(
                    "SELECT COUNT(*) AS total FROM academic_evidence WHERE project_id=?",
                    (project_key,),
                ).fetchone()
            else:
                _get_record(connection, project_key, record_key)
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS total FROM academic_evidence
                    WHERE project_id=? AND record_id=?
                    """,
                    (project_key, record_key),
                ).fetchone()
            return int(row["total"]) if row is not None else 0

    def delete_evidence(self, project_id: str, evidence_id: str) -> bool:
        """Delete evidence, its citation links, and matrices that used it."""

        project_key = _project_key(project_id)
        evidence_key = _entity_key(evidence_id, "evidence_id")
        with self.storage.write_transaction() as connection:
            _require_project(connection, project_key)
            _delete_matrices_for_evidence(connection, project_key, [evidence_key])
            cursor = connection.execute(
                "DELETE FROM academic_evidence WHERE project_id=? AND id=?",
                (project_key, evidence_key),
            )
        return cursor.rowcount > 0

    def upsert_claim(self, project_id: str, claim: ResearchClaim) -> ResearchClaim:
        """Insert or refresh one manuscript claim."""

        return self.upsert_claims(project_id, [claim])[0]

    def upsert_claims(
        self, project_id: str, claims: Sequence[ResearchClaim]
    ) -> list[ResearchClaim]:
        """Atomically persist a bounded claim collection."""

        project_key = _project_key(project_id)
        values = _model_batch(claims, ResearchClaim, "claims")
        with self.storage.write_transaction() as connection:
            _require_project(connection, project_key)
            for claim in values:
                _upsert_claim(connection, project_key, claim)
        return values

    def replace_claim_set(
        self,
        project_id: str,
        claims: Sequence[ResearchClaim],
        links: Sequence[ClaimCitationLink],
    ) -> tuple[list[ResearchClaim], list[ClaimCitationLink]]:
        """Atomically replace the current manuscript claim and citation-link set.

        Citation verification describes one snapshot of the current manuscript.  A
        replacement therefore removes claims (and their cascading links) that are
        absent from the new snapshot instead of leaving them available after a
        process restart.  Bibliographic records and evidence remain reusable.
        """

        project_key = _project_key(project_id)
        claim_values = _model_batch(claims, ResearchClaim, "claims")
        link_values = _model_batch(links, ClaimCitationLink, "links")
        claim_ids = {claim.id for claim in claim_values}
        unknown_claim_ids = sorted({link.claim_id for link in link_values} - claim_ids)
        if unknown_claim_ids:
            raise AcademicRelationError(
                "引文链接引用了本次论断集合以外的论断：" + "、".join(unknown_claim_ids)
            )

        with self.storage.write_transaction() as connection:
            _require_project(connection, project_key)
            # Validate every reusable source relation before replacing the current
            # snapshot.  The surrounding transaction also preserves the old set if
            # a later uniqueness or stored-data check fails.
            for link in link_values:
                _get_record(connection, project_key, link.record_id)
                evidence = _get_evidence(connection, project_key, link.evidence_id)
                if evidence.record_id != link.record_id:
                    raise AcademicRelationError("引文链接中的题录与证据来源不一致")

            connection.execute(
                "DELETE FROM academic_claim_links WHERE project_id=?", (project_key,)
            )
            connection.execute("DELETE FROM academic_claims WHERE project_id=?", (project_key,))
            for claim in claim_values:
                _upsert_claim(connection, project_key, claim)
            for link in link_values:
                _upsert_link(connection, project_key, link)
        return claim_values, link_values

    def get_claim(self, project_id: str, claim_id: str) -> ResearchClaim:
        """Read one claim only from the named project."""

        project_key = _project_key(project_id)
        claim_key = _entity_key(claim_id, "claim_id")
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            return _get_claim(connection, project_key, claim_key)

    def get_claims(self, project_id: str, claim_ids: Sequence[str]) -> list[ResearchClaim]:
        """Read claims in caller order, rejecting missing or duplicate IDs."""

        project_key = _project_key(project_id)
        ids = _entity_ids(claim_ids, "claim_ids")
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            return [_get_claim(connection, project_key, claim_id) for claim_id in ids]

    def list_claims(
        self, project_id: str, *, limit: int = 100, offset: int = 0
    ) -> list[ResearchClaim]:
        """List manuscript claims inside one project."""

        project_key = _project_key(project_id)
        _validate_page(limit, offset)
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            rows = connection.execute(
                """
                SELECT * FROM academic_claims WHERE project_id=?
                ORDER BY created_at, id LIMIT ? OFFSET ?
                """,
                (project_key, limit, offset),
            ).fetchall()
            return [_claim_from_row(row) for row in rows]

    def count_claims(self, project_id: str) -> int:
        """Count manuscript claims inside one project."""

        project_key = _project_key(project_id)
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM academic_claims WHERE project_id=?",
                (project_key,),
            ).fetchone()
            return int(row["total"]) if row is not None else 0

    def delete_claim(self, project_id: str, claim_id: str) -> bool:
        """Delete a claim and its project-local citation links."""

        project_key = _project_key(project_id)
        claim_key = _entity_key(claim_id, "claim_id")
        with self.storage.write_transaction() as connection:
            _require_project(connection, project_key)
            cursor = connection.execute(
                "DELETE FROM academic_claims WHERE project_id=? AND id=?",
                (project_key, claim_key),
            )
        return cursor.rowcount > 0

    def upsert_link(self, project_id: str, link: ClaimCitationLink) -> ClaimCitationLink:
        """Insert or refresh one validated claim-to-evidence relation."""

        return self.upsert_links(project_id, [link])[0]

    def upsert_links(
        self, project_id: str, links: Sequence[ClaimCitationLink]
    ) -> list[ClaimCitationLink]:
        """Atomically persist citation links after checking every relation."""

        project_key = _project_key(project_id)
        values = _model_batch(links, ClaimCitationLink, "links")
        with self.storage.write_transaction() as connection:
            _require_project(connection, project_key)
            for link in values:
                _upsert_link(connection, project_key, link)
        return values

    def get_link(self, project_id: str, link_id: str) -> ClaimCitationLink:
        """Read one citation link and verify its full project-local lineage."""

        project_key = _project_key(project_id)
        link_key = _entity_key(link_id, "link_id")
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            return _get_link(connection, project_key, link_key)

    def get_links(self, project_id: str, link_ids: Sequence[str]) -> list[ClaimCitationLink]:
        """Read citation links in caller order."""

        project_key = _project_key(project_id)
        ids = _entity_ids(link_ids, "link_ids")
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            return [_get_link(connection, project_key, link_id) for link_id in ids]

    def list_links(
        self,
        project_id: str,
        *,
        claim_id: str | None = None,
        record_id: str | None = None,
        evidence_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[ClaimCitationLink]:
        """List citation links using only project-scoped filters."""

        project_key = _project_key(project_id)
        _validate_page(limit, offset)
        clauses = ["project_id=?"]
        values: list[object] = [project_key]
        for column, raw_value in (
            ("claim_id", claim_id),
            ("record_id", record_id),
            ("evidence_id", evidence_id),
        ):
            if raw_value is not None:
                clauses.append(f"{column}=?")
                values.append(_entity_key(raw_value, column))
        values.extend((limit, offset))
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            rows = connection.execute(
                f"""
                SELECT * FROM academic_claim_links
                WHERE {" AND ".join(clauses)}
                ORDER BY created_at, id LIMIT ? OFFSET ?
                """,
                tuple(values),
            ).fetchall()
            return [_link_from_row(connection, project_key, row) for row in rows]

    def count_links(
        self,
        project_id: str,
        *,
        claim_id: str | None = None,
        record_id: str | None = None,
        evidence_id: str | None = None,
    ) -> int:
        """Count project-scoped citation links using optional lineage filters."""

        project_key = _project_key(project_id)
        clauses = ["project_id=?"]
        values: list[object] = [project_key]
        for column, raw_value in (
            ("claim_id", claim_id),
            ("record_id", record_id),
            ("evidence_id", evidence_id),
        ):
            if raw_value is not None:
                clauses.append(f"{column}=?")
                values.append(_entity_key(raw_value, column))
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS total FROM academic_claim_links
                WHERE {" AND ".join(clauses)}
                """,
                tuple(values),
            ).fetchone()
            return int(row["total"]) if row is not None else 0

    def delete_link(self, project_id: str, link_id: str) -> bool:
        """Delete one citation link from the named project."""

        project_key = _project_key(project_id)
        link_key = _entity_key(link_id, "link_id")
        with self.storage.write_transaction() as connection:
            _require_project(connection, project_key)
            cursor = connection.execute(
                "DELETE FROM academic_claim_links WHERE project_id=? AND id=?",
                (project_key, link_key),
            )
        return cursor.rowcount > 0

    def upsert_matrix(self, project_id: str, matrix: LiteratureMatrix) -> LiteratureMatrix:
        """Persist a literature matrix only after checking all source relations."""

        if not isinstance(matrix, LiteratureMatrix):
            raise TypeError("matrix 应为 LiteratureMatrix")
        project_key = _project_key(project_id)
        with self.storage.write_transaction() as connection:
            _require_project(connection, project_key)
            _upsert_matrix(connection, project_key, matrix)
        return matrix

    def get_matrix(self, project_id: str, matrix_id: str) -> LiteratureMatrix:
        """Read one matrix and verify all project-local source references."""

        project_key = _project_key(project_id)
        matrix_key = _entity_key(matrix_id, "matrix_id")
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            return _get_matrix(connection, project_key, matrix_key)

    def list_matrices(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[LiteratureMatrix]:
        """List validated matrices inside one project."""

        project_key = _project_key(project_id)
        _validate_page(limit, offset)
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            rows = connection.execute(
                """
                SELECT * FROM academic_matrices WHERE project_id=?
                ORDER BY updated_at DESC, id ASC LIMIT ? OFFSET ?
                """,
                (project_key, limit, offset),
            ).fetchall()
            return [_matrix_from_row(connection, project_key, row) for row in rows]

    def count_matrices(self, project_id: str) -> int:
        """Count validated literature matrices inside one project."""

        project_key = _project_key(project_id)
        with self.storage.read_connection() as connection:
            _require_project(connection, project_key)
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM academic_matrices WHERE project_id=?",
                (project_key,),
            ).fetchone()
            return int(row["total"]) if row is not None else 0

    def delete_matrix(self, project_id: str, matrix_id: str) -> bool:
        """Delete one literature matrix from the named project."""

        project_key = _project_key(project_id)
        matrix_key = _entity_key(matrix_id, "matrix_id")
        with self.storage.write_transaction() as connection:
            _require_project(connection, project_key)
            cursor = connection.execute(
                "DELETE FROM academic_matrices WHERE project_id=? AND id=?",
                (project_key, matrix_key),
            )
        return cursor.rowcount > 0


def _upsert_record(
    connection: sqlite3.Connection, project_id: str, record: BibliographicRecord
) -> None:
    _require_sha256(record.source_hash, "record.source_hash")
    previous = connection.execute(
        "SELECT source_hash FROM academic_records WHERE project_id=? AND id=?",
        (project_id, record.id),
    ).fetchone()
    if previous is not None and str(previous["source_hash"]) != record.source_hash:
        dependent_evidence = connection.execute(
            """
            SELECT 1 FROM academic_evidence
            WHERE project_id=? AND record_id=? LIMIT 1
            """,
            (project_id, record.id),
        ).fetchone()
        dependent_matrix = connection.execute(
            """
            SELECT 1 FROM academic_matrix_records
            WHERE project_id=? AND record_id=? LIMIT 1
            """,
            (project_id, record.id),
        ).fetchone()
        if dependent_evidence is not None or dependent_matrix is not None:
            raise AcademicRelationError("题录来源哈希已变化，请先移除依赖该版本的证据和矩阵")
    authors = " ".join(author.display_name() for author in record.authors)
    now = _utc_now()
    connection.execute(
        """
        INSERT INTO academic_records(
            project_id, id, title, abstract, authors_text, keywords_text,
            doi, source_key, source_hash, import_source, imported_at,
            payload_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id, id) DO UPDATE SET
            title=excluded.title,
            abstract=excluded.abstract,
            authors_text=excluded.authors_text,
            keywords_text=excluded.keywords_text,
            doi=excluded.doi,
            source_key=excluded.source_key,
            source_hash=excluded.source_hash,
            import_source=excluded.import_source,
            imported_at=excluded.imported_at,
            payload_json=excluded.payload_json,
            updated_at=excluded.updated_at
        """,
        (
            project_id,
            record.id,
            record.title,
            record.abstract,
            authors,
            " ".join(record.keywords),
            record.doi,
            record.source_key,
            record.source_hash,
            record.import_source,
            record.imported_at.isoformat(),
            _dump_model(record),
            now,
            now,
        ),
    )


def _get_record(
    connection: sqlite3.Connection, project_id: str, record_id: str
) -> BibliographicRecord:
    row = connection.execute(
        "SELECT * FROM academic_records WHERE project_id=? AND id=?",
        (project_id, record_id),
    ).fetchone()
    if row is None:
        raise AcademicNotFoundError(f"academic record not found in project: {record_id}")
    return _record_from_row(row)


def _record_from_row(row: sqlite3.Row) -> BibliographicRecord:
    record = _load_model(row["payload_json"], BibliographicRecord, "bibliographic record")
    if (
        record.id != str(row["id"])
        or record.source_hash != str(row["source_hash"])
        or record.title != str(row["title"])
    ):
        raise AcademicStoredDataError("bibliographic record columns do not match stored JSON")
    _require_sha256(record.source_hash, "record.source_hash", stored=True)
    return record


def _search_record_rows(
    connection: sqlite3.Connection,
    project_id: str,
    query: str,
    *,
    limit: int,
    offset: int,
) -> list[sqlite3.Row]:
    rows = connection.execute(
        """
        SELECT r.*
        FROM academic_records_fts
        JOIN academic_records AS r
          ON r.project_id=academic_records_fts.project_id
         AND r.id=academic_records_fts.record_id
        WHERE academic_records_fts MATCH ?
          AND academic_records_fts.project_id=?
        ORDER BY bm25(academic_records_fts), r.imported_at DESC, r.id ASC
        LIMIT ? OFFSET ?
        """,
        (_fts_query(query), project_id, limit, offset),
    ).fetchall()
    if rows:
        return cast(list[sqlite3.Row], rows)
    has_fts_match = connection.execute(
        """
        SELECT 1 FROM academic_records_fts
        WHERE academic_records_fts MATCH ? AND project_id=? LIMIT 1
        """,
        (_fts_query(query), project_id),
    ).fetchone()
    if has_fts_match is not None:
        return []
    escaped = _like_pattern(query)
    return cast(
        list[sqlite3.Row],
        connection.execute(
            """
            SELECT * FROM academic_records
            WHERE project_id=? AND (
                title LIKE ? ESCAPE '\\' OR abstract LIKE ? ESCAPE '\\'
                OR authors_text LIKE ? ESCAPE '\\' OR keywords_text LIKE ? ESCAPE '\\'
                OR COALESCE(doi, '') LIKE ? ESCAPE '\\' OR source_key LIKE ? ESCAPE '\\'
            )
            ORDER BY imported_at DESC, id ASC LIMIT ? OFFSET ?
            """,
            (project_id, escaped, escaped, escaped, escaped, escaped, escaped, limit, offset),
        ).fetchall(),
    )


def _upsert_evidence(
    connection: sqlite3.Connection, project_id: str, evidence: EvidenceSnippet
) -> None:
    _require_sha256(evidence.record_source_hash, "evidence.record_source_hash")
    _require_sha256(evidence.content_hash, "evidence.content_hash")
    record = _get_record(connection, project_id, evidence.record_id)
    if evidence.record_source_hash != record.source_hash:
        raise AcademicRelationError("证据来源哈希与项目内题录版本不一致")
    previous = connection.execute(
        """
        SELECT record_id, content_hash FROM academic_evidence
        WHERE project_id=? AND id=?
        """,
        (project_id, evidence.id),
    ).fetchone()
    if previous is not None and (
        str(previous["record_id"]) != evidence.record_id
        or str(previous["content_hash"]) != evidence.content_hash
    ):
        raise AcademicRelationError("同一证据标识不得改绑来源或正文")
    now = _utc_now()
    connection.execute(
        """
        INSERT INTO academic_evidence(
            project_id, id, record_id, record_source_hash, content_hash,
            payload_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id, id) DO UPDATE SET
            record_source_hash=excluded.record_source_hash,
            payload_json=excluded.payload_json,
            updated_at=excluded.updated_at
        """,
        (
            project_id,
            evidence.id,
            evidence.record_id,
            evidence.record_source_hash,
            evidence.content_hash,
            _dump_model(evidence),
            now,
            now,
        ),
    )


def _get_evidence(
    connection: sqlite3.Connection, project_id: str, evidence_id: str
) -> EvidenceSnippet:
    row = connection.execute(
        "SELECT * FROM academic_evidence WHERE project_id=? AND id=?",
        (project_id, evidence_id),
    ).fetchone()
    if row is None:
        raise AcademicNotFoundError(f"academic evidence not found in project: {evidence_id}")
    return _evidence_from_row(connection, project_id, row)


def _evidence_from_row(
    connection: sqlite3.Connection, project_id: str, row: sqlite3.Row
) -> EvidenceSnippet:
    evidence = _load_model(row["payload_json"], EvidenceSnippet, "evidence snippet")
    if (
        evidence.id != str(row["id"])
        or evidence.record_id != str(row["record_id"])
        or evidence.record_source_hash != str(row["record_source_hash"])
        or evidence.content_hash != str(row["content_hash"])
    ):
        raise AcademicStoredDataError("evidence columns do not match stored JSON")
    record = _get_record(connection, project_id, evidence.record_id)
    if evidence.record_source_hash != record.source_hash:
        raise AcademicStoredDataError("evidence source lineage no longer matches its record")
    return evidence


def _upsert_claim(connection: sqlite3.Connection, project_id: str, claim: ResearchClaim) -> None:
    previous = connection.execute(
        "SELECT text FROM academic_claims WHERE project_id=? AND id=?",
        (project_id, claim.id),
    ).fetchone()
    if previous is not None and str(previous["text"]) != claim.text:
        linked = connection.execute(
            """
            SELECT 1 FROM academic_claim_links
            WHERE project_id=? AND claim_id=? LIMIT 1
            """,
            (project_id, claim.id),
        ).fetchone()
        if linked is not None:
            raise AcademicRelationError("已关联证据的论断正文不得原位替换")
    now = _utc_now()
    connection.execute(
        """
        INSERT INTO academic_claims(
            project_id, id, text, section, payload_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id, id) DO UPDATE SET
            text=excluded.text,
            section=excluded.section,
            payload_json=excluded.payload_json,
            updated_at=excluded.updated_at
        """,
        (project_id, claim.id, claim.text, claim.section, _dump_model(claim), now, now),
    )


def _get_claim(connection: sqlite3.Connection, project_id: str, claim_id: str) -> ResearchClaim:
    row = connection.execute(
        "SELECT * FROM academic_claims WHERE project_id=? AND id=?",
        (project_id, claim_id),
    ).fetchone()
    if row is None:
        raise AcademicNotFoundError(f"academic claim not found in project: {claim_id}")
    return _claim_from_row(row)


def _claim_from_row(row: sqlite3.Row) -> ResearchClaim:
    claim = _load_model(row["payload_json"], ResearchClaim, "research claim")
    if claim.id != str(row["id"]) or claim.text != str(row["text"]):
        raise AcademicStoredDataError("claim columns do not match stored JSON")
    return claim


def _upsert_link(connection: sqlite3.Connection, project_id: str, link: ClaimCitationLink) -> None:
    _get_claim(connection, project_id, link.claim_id)
    _get_record(connection, project_id, link.record_id)
    evidence = _get_evidence(connection, project_id, link.evidence_id)
    if evidence.record_id != link.record_id:
        raise AcademicRelationError("引文链接中的题录与证据来源不一致")
    previous = connection.execute(
        """
        SELECT claim_id, record_id, evidence_id FROM academic_claim_links
        WHERE project_id=? AND id=?
        """,
        (project_id, link.id),
    ).fetchone()
    if previous is not None and (
        str(previous["claim_id"]) != link.claim_id
        or str(previous["record_id"]) != link.record_id
        or str(previous["evidence_id"]) != link.evidence_id
    ):
        raise AcademicRelationError("同一引文链接标识不得改绑论断或证据")
    same_relation = connection.execute(
        """
        SELECT id FROM academic_claim_links
        WHERE project_id=? AND claim_id=? AND evidence_id=?
        """,
        (project_id, link.claim_id, link.evidence_id),
    ).fetchone()
    if same_relation is not None and str(same_relation["id"]) != link.id:
        raise AcademicRelationError("同一论断与证据关系已使用另一个引文链接标识")
    now = _utc_now()
    connection.execute(
        """
        INSERT INTO academic_claim_links(
            project_id, id, claim_id, record_id, evidence_id,
            payload_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id, id) DO UPDATE SET
            payload_json=excluded.payload_json,
            updated_at=excluded.updated_at
        """,
        (
            project_id,
            link.id,
            link.claim_id,
            link.record_id,
            link.evidence_id,
            _dump_model(link),
            now,
            now,
        ),
    )


def _get_link(connection: sqlite3.Connection, project_id: str, link_id: str) -> ClaimCitationLink:
    row = connection.execute(
        "SELECT * FROM academic_claim_links WHERE project_id=? AND id=?",
        (project_id, link_id),
    ).fetchone()
    if row is None:
        raise AcademicNotFoundError(f"academic citation link not found in project: {link_id}")
    return _link_from_row(connection, project_id, row)


def _link_from_row(
    connection: sqlite3.Connection, project_id: str, row: sqlite3.Row
) -> ClaimCitationLink:
    link = _load_model(row["payload_json"], ClaimCitationLink, "claim citation link")
    if (
        link.id != str(row["id"])
        or link.claim_id != str(row["claim_id"])
        or link.record_id != str(row["record_id"])
        or link.evidence_id != str(row["evidence_id"])
    ):
        raise AcademicStoredDataError("citation-link columns do not match stored JSON")
    _get_claim(connection, project_id, link.claim_id)
    _get_record(connection, project_id, link.record_id)
    evidence = _get_evidence(connection, project_id, link.evidence_id)
    if evidence.record_id != link.record_id:
        raise AcademicStoredDataError("citation link points to evidence from another record")
    return link


def _upsert_matrix(
    connection: sqlite3.Connection, project_id: str, matrix: LiteratureMatrix
) -> None:
    record_ids, evidence_relations = _validate_matrix_relations(connection, project_id, matrix)
    now = _utc_now()
    connection.execute(
        """
        INSERT INTO academic_matrices(
            project_id, id, query, payload_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id, id) DO UPDATE SET
            query=excluded.query,
            payload_json=excluded.payload_json,
            updated_at=excluded.updated_at
        """,
        (project_id, matrix.id, matrix.query, _dump_model(matrix), now, now),
    )
    connection.execute(
        "DELETE FROM academic_matrix_records WHERE project_id=? AND matrix_id=?",
        (project_id, matrix.id),
    )
    connection.execute(
        "DELETE FROM academic_matrix_evidence WHERE project_id=? AND matrix_id=?",
        (project_id, matrix.id),
    )
    connection.executemany(
        """
        INSERT INTO academic_matrix_records(project_id, matrix_id, record_id, position)
        VALUES (?, ?, ?, ?)
        """,
        [
            (project_id, matrix.id, record_id, position)
            for position, record_id in enumerate(record_ids)
        ],
    )
    connection.executemany(
        """
        INSERT INTO academic_matrix_evidence(project_id, matrix_id, record_id, evidence_id)
        VALUES (?, ?, ?, ?)
        """,
        [
            (project_id, matrix.id, record_id, evidence_id)
            for record_id, evidence_id in evidence_relations
        ],
    )


def _get_matrix(
    connection: sqlite3.Connection, project_id: str, matrix_id: str
) -> LiteratureMatrix:
    row = connection.execute(
        "SELECT * FROM academic_matrices WHERE project_id=? AND id=?",
        (project_id, matrix_id),
    ).fetchone()
    if row is None:
        raise AcademicNotFoundError(f"academic matrix not found in project: {matrix_id}")
    return _matrix_from_row(connection, project_id, row)


def _matrix_from_row(
    connection: sqlite3.Connection, project_id: str, row: sqlite3.Row
) -> LiteratureMatrix:
    matrix = _load_model(row["payload_json"], LiteratureMatrix, "literature matrix")
    if matrix.id != str(row["id"]) or matrix.query != str(row["query"]):
        raise AcademicStoredDataError("matrix columns do not match stored JSON")
    record_ids, evidence_relations = _validate_matrix_relations(connection, project_id, matrix)
    stored_records = tuple(
        str(item["record_id"])
        for item in connection.execute(
            """
            SELECT record_id FROM academic_matrix_records
            WHERE project_id=? AND matrix_id=? ORDER BY position
            """,
            (project_id, matrix.id),
        ).fetchall()
    )
    stored_evidence = {
        (str(item["record_id"]), str(item["evidence_id"]))
        for item in connection.execute(
            """
            SELECT record_id, evidence_id FROM academic_matrix_evidence
            WHERE project_id=? AND matrix_id=?
            """,
            (project_id, matrix.id),
        ).fetchall()
    }
    if stored_records != record_ids or stored_evidence != set(evidence_relations):
        raise AcademicStoredDataError("matrix relation rows do not match stored JSON")
    return matrix


def _validate_matrix_relations(
    connection: sqlite3.Connection, project_id: str, matrix: LiteratureMatrix
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    if not matrix.record_ids:
        raise AcademicRelationError("文献矩阵至少需要一条项目内题录")
    record_ids = tuple(matrix.record_ids)
    if len(record_ids) != len(set(record_ids)):
        raise AcademicRelationError("文献矩阵 record_ids 不得重复")
    row_record_ids = tuple(row.record_id for row in matrix.rows)
    if row_record_ids != record_ids:
        raise AcademicRelationError("文献矩阵行顺序必须与 record_ids 完全一致")
    for record_id in record_ids:
        _get_record(connection, project_id, record_id)
    relations: list[tuple[str, str]] = []
    seen_evidence: set[str] = set()
    for row in matrix.rows:
        if len(row.evidence_ids) != len(set(row.evidence_ids)):
            raise AcademicRelationError("文献矩阵行内 evidence_ids 不得重复")
        for evidence_id in row.evidence_ids:
            if evidence_id in seen_evidence:
                raise AcademicRelationError("同一证据不得重复出现在多个矩阵行")
            evidence = _get_evidence(connection, project_id, evidence_id)
            if evidence.record_id != row.record_id:
                raise AcademicRelationError("文献矩阵证据与所在题录行不一致")
            seen_evidence.add(evidence_id)
            relations.append((row.record_id, evidence_id))
    return record_ids, tuple(relations)


def _delete_matrices_for_records(
    connection: sqlite3.Connection, project_id: str, record_ids: Sequence[str]
) -> None:
    for record_id in record_ids:
        connection.execute(
            """
            DELETE FROM academic_matrices
            WHERE project_id=? AND id IN (
                SELECT matrix_id FROM academic_matrix_records
                WHERE project_id=? AND record_id=?
            )
            """,
            (project_id, project_id, record_id),
        )


def _delete_matrices_for_evidence(
    connection: sqlite3.Connection, project_id: str, evidence_ids: Sequence[str]
) -> None:
    for evidence_id in evidence_ids:
        connection.execute(
            """
            DELETE FROM academic_matrices
            WHERE project_id=? AND id IN (
                SELECT matrix_id FROM academic_matrix_evidence
                WHERE project_id=? AND evidence_id=?
            )
            """,
            (project_id, project_id, evidence_id),
        )


def _require_project(connection: sqlite3.Connection, project_id: str) -> None:
    row = connection.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone()
    if row is None:
        raise AcademicNotFoundError(f"writing project not found: {project_id}")


def _project_key(value: str) -> str:
    return _bounded_key(value, "project_id", 128)


def _entity_key(value: str, name: str) -> str:
    return _bounded_key(value, name, 200)


def _bounded_key(value: str, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} 应为 str")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{name} 长度应为 1 到 {maximum}")
    return normalized


def _entity_ids(values: Sequence[str], name: str) -> list[str]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} 应为字符串序列")
    if len(values) > _MAX_BATCH_ITEMS:
        raise ValueError(f"{name} 最多包含 {_MAX_BATCH_ITEMS} 项")
    normalized = [_entity_key(value, name) for value in values]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{name} 不得重复")
    return normalized


def _model_batch[ModelT: BaseModel](
    values: Sequence[ModelT], model: type[ModelT], name: str
) -> list[ModelT]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} 应为模型序列")
    if len(values) > _MAX_BATCH_ITEMS:
        raise ValueError(f"{name} 最多包含 {_MAX_BATCH_ITEMS} 项")
    normalized = list(values)
    if any(not isinstance(value, model) for value in normalized):
        raise TypeError(f"{name} 包含错误的模型类型")
    ids: list[str] = []
    for value in normalized:
        raw_id: object = getattr(value, "id", None)
        if not isinstance(raw_id, str) or not raw_id:
            raise ValueError(f"{name} 模型缺少有效 id")
        ids.append(raw_id)
    if len(ids) != len(set(ids)):
        raise ValueError(f"{name} id 不得重复")
    return normalized


def _validate_page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 1_000:
        raise ValueError("limit 应为 1 到 1000 的整数")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset 应为非负整数")


def _require_sha256(value: str, name: str, *, stored: bool = False) -> None:
    if _SHA256.fullmatch(value) is None:
        if stored:
            raise AcademicStoredDataError(f"stored {name} is not a canonical sha256")
        raise AcademicRelationError(f"{name} 应为 64 位小写 SHA-256")


def _dump_model(model: BaseModel) -> str:
    return model.model_dump_json(exclude_none=False)


def _load_model[ModelT: BaseModel](value: object, model: type[ModelT], label: str) -> ModelT:
    if not isinstance(value, str):
        raise AcademicStoredDataError(f"stored {label} JSON is not text")
    try:
        parsed = json.loads(
            value,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(parsed, Mapping):
            raise ValueError("top-level JSON is not an object")
        return model.model_validate_json(value, strict=True)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        raise AcademicStoredDataError(f"stored {label} JSON is invalid") from exc


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> NoReturn:
    raise ValueError(f"invalid JSON constant: {value}")


def _fts_query(value: str) -> str:
    terms = [term for term in _WHITESPACE.split(value.strip()) if term]
    return " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _schema_version(row: sqlite3.Row | None) -> int:
    if row is None:
        return 0
    try:
        version = int(row["value"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AcademicSchemaError("academic schema version is malformed") from exc
    if version < 0:
        raise AcademicSchemaError("academic schema version is negative")
    return version


def _check_schema_objects(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
    ).fetchall()
    available = {str(row["name"]) for row in rows}
    missing = [name for name in _REQUIRED_TABLES if name not in available]
    if missing:
        raise AcademicSchemaError("academic schema objects are missing: " + ", ".join(missing))
    trigger_rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'"
    ).fetchall()
    available_triggers = {str(row["name"]) for row in trigger_rows}
    missing_triggers = [name for name in _REQUIRED_TRIGGERS if name not in available_triggers]
    if missing_triggers:
        raise AcademicSchemaError(
            "academic schema triggers are missing: " + ", ".join(missing_triggers)
        )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


_REQUIRED_TABLES = (
    "academic_records",
    "academic_records_fts",
    "academic_evidence",
    "academic_claims",
    "academic_claim_links",
    "academic_matrices",
    "academic_matrix_records",
    "academic_matrix_evidence",
)

_REQUIRED_TRIGGERS = (
    "academic_records_fts_insert",
    "academic_records_fts_update_delete",
    "academic_records_fts_update_insert",
    "academic_records_fts_delete",
)

_MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        """
        CREATE TABLE IF NOT EXISTS academic_records (
            project_id TEXT NOT NULL,
            id TEXT NOT NULL,
            title TEXT NOT NULL,
            abstract TEXT NOT NULL DEFAULT '',
            authors_text TEXT NOT NULL DEFAULT '',
            keywords_text TEXT NOT NULL DEFAULT '',
            doi TEXT,
            source_key TEXT NOT NULL DEFAULT '',
            source_hash TEXT NOT NULL,
            import_source TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(project_id, id),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_academic_records_project_date
        ON academic_records(project_id, imported_at DESC, id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_academic_records_project_doi
        ON academic_records(project_id, doi)
        """,
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS academic_records_fts USING fts5(
            project_id UNINDEXED,
            record_id UNINDEXED,
            title,
            abstract,
            authors,
            keywords,
            tokenize='unicode61'
        )
        """,
        """
        CREATE TRIGGER IF NOT EXISTS academic_records_fts_insert
        AFTER INSERT ON academic_records BEGIN
            INSERT INTO academic_records_fts(
                project_id, record_id, title, abstract, authors, keywords
            ) VALUES (
                NEW.project_id, NEW.id, NEW.title, NEW.abstract,
                NEW.authors_text, NEW.keywords_text
            );
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS academic_records_fts_update_delete
        AFTER UPDATE ON academic_records BEGIN
            DELETE FROM academic_records_fts
            WHERE project_id=OLD.project_id AND record_id=OLD.id;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS academic_records_fts_update_insert
        AFTER UPDATE ON academic_records BEGIN
            INSERT INTO academic_records_fts(
                project_id, record_id, title, abstract, authors, keywords
            ) VALUES (
                NEW.project_id, NEW.id, NEW.title, NEW.abstract,
                NEW.authors_text, NEW.keywords_text
            );
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS academic_records_fts_delete
        AFTER DELETE ON academic_records BEGIN
            DELETE FROM academic_records_fts
            WHERE project_id=OLD.project_id AND record_id=OLD.id;
        END
        """,
        """
        CREATE TABLE IF NOT EXISTS academic_evidence (
            project_id TEXT NOT NULL,
            id TEXT NOT NULL,
            record_id TEXT NOT NULL,
            record_source_hash TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(project_id, id),
            UNIQUE(project_id, id, record_id),
            FOREIGN KEY(project_id, record_id)
                REFERENCES academic_records(project_id, id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_academic_evidence_record
        ON academic_evidence(project_id, record_id, created_at, id)
        """,
        """
        CREATE TABLE IF NOT EXISTS academic_claims (
            project_id TEXT NOT NULL,
            id TEXT NOT NULL,
            text TEXT NOT NULL,
            section TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(project_id, id),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_academic_claims_project
        ON academic_claims(project_id, created_at, id)
        """,
        """
        CREATE TABLE IF NOT EXISTS academic_claim_links (
            project_id TEXT NOT NULL,
            id TEXT NOT NULL,
            claim_id TEXT NOT NULL,
            record_id TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(project_id, id),
            UNIQUE(project_id, claim_id, evidence_id),
            FOREIGN KEY(project_id, claim_id)
                REFERENCES academic_claims(project_id, id) ON DELETE CASCADE,
            FOREIGN KEY(project_id, record_id)
                REFERENCES academic_records(project_id, id) ON DELETE CASCADE,
            FOREIGN KEY(project_id, evidence_id, record_id)
                REFERENCES academic_evidence(project_id, id, record_id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_academic_links_claim
        ON academic_claim_links(project_id, claim_id, created_at, id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_academic_links_record
        ON academic_claim_links(project_id, record_id, evidence_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS academic_matrices (
            project_id TEXT NOT NULL,
            id TEXT NOT NULL,
            query TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(project_id, id),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_academic_matrices_project
        ON academic_matrices(project_id, updated_at DESC, id)
        """,
        """
        CREATE TABLE IF NOT EXISTS academic_matrix_records (
            project_id TEXT NOT NULL,
            matrix_id TEXT NOT NULL,
            record_id TEXT NOT NULL,
            position INTEGER NOT NULL CHECK(position >= 0),
            PRIMARY KEY(project_id, matrix_id, record_id),
            UNIQUE(project_id, matrix_id, position),
            FOREIGN KEY(project_id, matrix_id)
                REFERENCES academic_matrices(project_id, id) ON DELETE CASCADE,
            FOREIGN KEY(project_id, record_id)
                REFERENCES academic_records(project_id, id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_academic_matrix_records_record
        ON academic_matrix_records(project_id, record_id, matrix_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS academic_matrix_evidence (
            project_id TEXT NOT NULL,
            matrix_id TEXT NOT NULL,
            record_id TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            PRIMARY KEY(project_id, matrix_id, evidence_id),
            FOREIGN KEY(project_id, matrix_id)
                REFERENCES academic_matrices(project_id, id) ON DELETE CASCADE,
            FOREIGN KEY(project_id, record_id)
                REFERENCES academic_records(project_id, id) ON DELETE CASCADE,
            FOREIGN KEY(project_id, evidence_id, record_id)
                REFERENCES academic_evidence(project_id, id, record_id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_academic_matrix_evidence_source
        ON academic_matrix_evidence(project_id, evidence_id, matrix_id)
        """,
    )
}


__all__ = [
    "ACADEMIC_SCHEMA_VERSION",
    "AcademicNotFoundError",
    "AcademicRelationError",
    "AcademicRepository",
    "AcademicRepositoryError",
    "AcademicSchemaError",
    "AcademicStoredDataError",
]
