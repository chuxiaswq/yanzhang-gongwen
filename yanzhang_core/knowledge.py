"""Project-scoped knowledge, evidence, claim and citation repositories."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from yanzhang_core.models import Citation, Claim, Evidence, KnowledgeItem
from yanzhang_core.storage import (
    ProjectScopeError,
    RecordNotFoundError,
    WritingStorage,
    WritingStorageError,
)


@dataclass(frozen=True, slots=True)
class KnowledgeSearchResult:
    """One ranked full-text result with a bounded context excerpt."""

    item: KnowledgeItem
    score: float
    excerpt: str


class KnowledgeRepository:
    """Persist and search knowledge while preserving project boundaries."""

    def __init__(self, storage: WritingStorage) -> None:
        self.storage = storage

    def upsert_item(self, item: KnowledgeItem) -> KnowledgeItem:
        """Save an item and update its FTS5 row in the same transaction."""

        now = _utc_now()
        digest = hashlib.sha256(item.content.encode("utf-8")).hexdigest()
        with self.storage.write_transaction() as connection:
            existing = connection.execute(
                "SELECT project_id FROM knowledge_items WHERE id=?", (item.id,)
            ).fetchone()
            if existing is not None and str(existing["project_id"]) != item.project_id:
                raise ProjectScopeError(f"knowledge item does not belong to project: {item.id}")
            connection.execute(
                """
                INSERT INTO knowledge_items(
                    id, project_id, kind, title, content, source_url,
                    published_at, tags_json, content_hash, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    project_id=excluded.project_id,
                    kind=excluded.kind,
                    title=excluded.title,
                    content=excluded.content,
                    source_url=excluded.source_url,
                    published_at=excluded.published_at,
                    tags_json=excluded.tags_json,
                    content_hash=excluded.content_hash,
                    updated_at=excluded.updated_at
                """,
                (
                    item.id,
                    item.project_id,
                    item.kind,
                    item.title,
                    item.content,
                    item.source_url,
                    _optional_datetime_text(item.published_at),
                    json.dumps(item.tags, ensure_ascii=False),
                    digest,
                    _datetime_text(item.created_at),
                    now,
                ),
            )
            connection.execute("DELETE FROM knowledge_items_fts WHERE item_id=?", (item.id,))
            connection.execute(
                "INSERT INTO knowledge_items_fts(item_id, title, content) VALUES (?, ?, ?)",
                (item.id, item.title, item.content),
            )
        return item

    def get_item(self, item_id: str, *, project_id: str | None = None) -> KnowledgeItem:
        where = "id=? AND project_id=?" if project_id is not None else "id=?"
        params: tuple[object, ...] = (item_id, project_id) if project_id is not None else (item_id,)
        with self.storage.read_connection() as connection:
            row = connection.execute(
                f"SELECT * FROM knowledge_items WHERE {where}", params
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"knowledge item not found: {item_id}")
        return _knowledge_item_from_row(row)

    def list_items(
        self,
        *,
        project_id: str | None = None,
        kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KnowledgeItem]:
        _validate_page(limit, offset)
        clauses: list[str] = []
        values: list[object] = []
        if project_id is not None:
            clauses.append("project_id=?")
            values.append(project_id)
        if kind is not None:
            clauses.append("kind=?")
            values.append(kind)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        values.extend((limit, offset))
        with self.storage.read_connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM knowledge_items {where} "
                "ORDER BY updated_at DESC, id ASC LIMIT ? OFFSET ?",
                tuple(values),
            ).fetchall()
        return [_knowledge_item_from_row(row) for row in rows]

    def search(
        self,
        query: str,
        *,
        project_id: str | None = None,
        kind: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[KnowledgeSearchResult]:
        """Run project-filtered FTS5 search with a short-query fallback."""

        normalized = query.strip()
        if not normalized:
            raise ValueError("query must not be empty")
        _validate_page(limit, offset)
        clauses = ["knowledge_items_fts MATCH ?"]
        values: list[object] = [_quoted_fts_query(normalized)]
        if project_id is not None:
            clauses.append("k.project_id=?")
            values.append(project_id)
        if kind is not None:
            clauses.append("k.kind=?")
            values.append(kind)
        values.extend((limit, offset))
        with self.storage.read_connection() as connection:
            try:
                rows = connection.execute(
                    f"""
                    SELECT k.*,
                           bm25(knowledge_items_fts, 0.0, 4.0, 1.0) AS fts_rank,
                           snippet(knowledge_items_fts, 2, '', '', '…', 32) AS excerpt
                    FROM knowledge_items_fts
                    JOIN knowledge_items AS k ON k.id=knowledge_items_fts.item_id
                    WHERE {" AND ".join(clauses)}
                    ORDER BY fts_rank ASC, k.updated_at DESC, k.id ASC
                    LIMIT ? OFFSET ?
                    """,
                    tuple(values),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                raise WritingStorageError(f"knowledge FTS query failed: {exc}") from exc
            if not rows:
                rows = _search_like(
                    connection,
                    normalized,
                    project_id=project_id,
                    kind=kind,
                    limit=limit,
                    offset=offset,
                )
        return [
            KnowledgeSearchResult(
                item=_knowledge_item_from_row(row),
                score=-float(row["fts_rank"]),
                excerpt=str(row["excerpt"])[:1_000],
            )
            for row in rows
        ]

    def delete_item(self, item_id: str, *, project_id: str | None = None) -> bool:
        with self.storage.write_transaction() as connection:
            if project_id is not None:
                _require_knowledge_project(connection, item_id, project_id)
            connection.execute("DELETE FROM knowledge_items_fts WHERE item_id=?", (item_id,))
            cursor = connection.execute("DELETE FROM knowledge_items WHERE id=?", (item_id,))
        return cursor.rowcount > 0

    def add_evidence(
        self,
        evidence: Evidence,
        *,
        project_id: str | None = None,
    ) -> Evidence:
        with self.storage.write_transaction() as connection:
            target_project = _knowledge_project(connection, evidence.knowledge_item_id)
            if project_id is not None:
                _require_expected_project(
                    target_project,
                    project_id,
                    "knowledge item",
                    evidence.knowledge_item_id,
                )
            existing = connection.execute(
                """
                SELECT k.project_id
                FROM evidence_snippets AS e
                JOIN knowledge_items AS k ON k.id=e.knowledge_item_id
                WHERE e.id=?
                """,
                (evidence.id,),
            ).fetchone()
            if existing is not None and str(existing["project_id"]) != target_project:
                raise ProjectScopeError(f"evidence does not belong to project: {evidence.id}")
            connection.execute(
                """
                INSERT INTO evidence_snippets(
                    id, knowledge_item_id, excerpt, locator, source_url,
                    source_hash, published_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    knowledge_item_id=excluded.knowledge_item_id,
                    excerpt=excluded.excerpt,
                    locator=excluded.locator,
                    source_url=excluded.source_url,
                    source_hash=excluded.source_hash,
                    published_at=excluded.published_at
                """,
                (
                    evidence.id,
                    evidence.knowledge_item_id,
                    evidence.excerpt,
                    evidence.locator,
                    evidence.source_url,
                    evidence.source_hash,
                    _optional_datetime_text(evidence.published_at),
                    _utc_now(),
                ),
            )
        return evidence

    def get_evidence(
        self,
        evidence_id: str,
        *,
        project_id: str | None = None,
    ) -> Evidence:
        project_clause = "AND k.project_id=?" if project_id is not None else ""
        params: tuple[object, ...] = (
            (evidence_id, project_id) if project_id is not None else (evidence_id,)
        )
        with self.storage.read_connection() as connection:
            row = connection.execute(
                f"""
                SELECT e.* FROM evidence_snippets AS e
                JOIN knowledge_items AS k ON k.id=e.knowledge_item_id
                WHERE e.id=? {project_clause}
                """,
                params,
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"evidence not found: {evidence_id}")
        return _evidence_from_row(row)

    def list_evidence(
        self,
        knowledge_item_id: str,
        *,
        project_id: str | None = None,
    ) -> list[Evidence]:
        project_clause = "AND k.project_id=?" if project_id is not None else ""
        params: tuple[object, ...] = (
            (knowledge_item_id, project_id) if project_id is not None else (knowledge_item_id,)
        )
        with self.storage.read_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT e.* FROM evidence_snippets AS e
                JOIN knowledge_items AS k ON k.id=e.knowledge_item_id
                WHERE e.knowledge_item_id=? {project_clause}
                ORDER BY e.created_at, e.id
                """,
                params,
            ).fetchall()
        return [_evidence_from_row(row) for row in rows]

    def save_claim(self, claim: Claim, *, project_id: str | None = None) -> Claim:
        now = _utc_now()
        with self.storage.write_transaction() as connection:
            asset_project = _asset_project(connection, claim.asset_id)
            _require_expected_project(asset_project, project_id, "text asset", claim.asset_id)
            existing = connection.execute(
                """
                SELECT a.project_id
                FROM claims AS c JOIN text_assets AS a ON a.id=c.asset_id
                WHERE c.id=?
                """,
                (claim.id,),
            ).fetchone()
            if existing is not None:
                existing_project = (
                    str(existing["project_id"]) if existing["project_id"] is not None else None
                )
                if existing_project != asset_project:
                    raise ProjectScopeError(f"claim does not belong to project: {claim.id}")
            for evidence_id in claim.evidence_ids:
                evidence_project = _evidence_project(connection, evidence_id)
                if evidence_project != asset_project:
                    raise ProjectScopeError(
                        f"claim evidence does not belong to asset project: {evidence_id}"
                    )
            connection.execute(
                """
                INSERT INTO claims(
                    id, asset_id, block_id, text, kind, status,
                    evidence_ids_json, confidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    asset_id=excluded.asset_id,
                    block_id=excluded.block_id,
                    text=excluded.text,
                    kind=excluded.kind,
                    status=excluded.status,
                    evidence_ids_json=excluded.evidence_ids_json,
                    confidence=excluded.confidence,
                    updated_at=excluded.updated_at
                """,
                (
                    claim.id,
                    claim.asset_id,
                    claim.block_id,
                    claim.text,
                    claim.kind,
                    claim.status,
                    json.dumps(claim.evidence_ids, ensure_ascii=False),
                    claim.confidence,
                    now,
                    now,
                ),
            )
        return claim

    def get_claim(self, claim_id: str, *, project_id: str | None = None) -> Claim:
        project_clause = "AND a.project_id=?" if project_id is not None else ""
        params: tuple[object, ...] = (
            (claim_id, project_id) if project_id is not None else (claim_id,)
        )
        with self.storage.read_connection() as connection:
            row = connection.execute(
                f"""
                SELECT c.* FROM claims AS c
                JOIN text_assets AS a ON a.id=c.asset_id
                WHERE c.id=? {project_clause}
                """,
                params,
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"claim not found: {claim_id}")
        return _claim_from_row(row)

    def list_claims(
        self,
        asset_id: str,
        *,
        project_id: str | None = None,
    ) -> list[Claim]:
        project_clause = "AND a.project_id=?" if project_id is not None else ""
        params: tuple[object, ...] = (
            (asset_id, project_id) if project_id is not None else (asset_id,)
        )
        with self.storage.read_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT c.* FROM claims AS c
                JOIN text_assets AS a ON a.id=c.asset_id
                WHERE c.asset_id=? {project_clause}
                ORDER BY c.block_id, c.id
                """,
                params,
            ).fetchall()
        return [_claim_from_row(row) for row in rows]

    def save_citation(self, citation: Citation, *, project_id: str | None = None) -> Citation:
        with self.storage.write_transaction() as connection:
            asset_project = _asset_project(connection, citation.asset_id)
            _require_expected_project(asset_project, project_id, "text asset", citation.asset_id)
            existing = connection.execute(
                """
                SELECT a.project_id
                FROM citations AS c JOIN text_assets AS a ON a.id=c.asset_id
                WHERE c.id=?
                """,
                (citation.id,),
            ).fetchone()
            if existing is not None:
                existing_project = (
                    str(existing["project_id"]) if existing["project_id"] is not None else None
                )
                if existing_project != asset_project:
                    raise ProjectScopeError(f"citation does not belong to project: {citation.id}")
            claim_row = connection.execute(
                "SELECT asset_id, block_id FROM claims WHERE id=?", (citation.claim_id,)
            ).fetchone()
            if claim_row is None:
                raise RecordNotFoundError(f"claim not found: {citation.claim_id}")
            if (
                str(claim_row["asset_id"]) != citation.asset_id
                or str(claim_row["block_id"]) != citation.block_id
            ):
                raise ProjectScopeError(
                    f"citation claim does not belong to the target block: {citation.claim_id}"
                )
            evidence_project = _evidence_project(connection, citation.evidence_id)
            if evidence_project != asset_project:
                raise ProjectScopeError(
                    f"citation evidence does not belong to asset project: {citation.evidence_id}"
                )
            connection.execute(
                """
                INSERT INTO citations(
                    id, asset_id, block_id, claim_id, evidence_id, label, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(claim_id, evidence_id) DO UPDATE SET
                    asset_id=excluded.asset_id,
                    block_id=excluded.block_id,
                    label=excluded.label
                """,
                (
                    citation.id,
                    citation.asset_id,
                    citation.block_id,
                    citation.claim_id,
                    citation.evidence_id,
                    citation.label,
                    _utc_now(),
                ),
            )
        return citation

    def get_citation(
        self,
        citation_id: str,
        *,
        project_id: str | None = None,
    ) -> Citation:
        project_clause = "AND a.project_id=?" if project_id is not None else ""
        params: tuple[object, ...] = (
            (citation_id, project_id) if project_id is not None else (citation_id,)
        )
        with self.storage.read_connection() as connection:
            row = connection.execute(
                f"""
                SELECT c.* FROM citations AS c
                JOIN text_assets AS a ON a.id=c.asset_id
                WHERE c.id=? {project_clause}
                """,
                params,
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"citation not found: {citation_id}")
        return _citation_from_row(row)

    def list_citations(
        self,
        asset_id: str,
        *,
        project_id: str | None = None,
    ) -> list[Citation]:
        project_clause = "AND a.project_id=?" if project_id is not None else ""
        params: tuple[object, ...] = (
            (asset_id, project_id) if project_id is not None else (asset_id,)
        )
        with self.storage.read_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT c.* FROM citations AS c
                JOIN text_assets AS a ON a.id=c.asset_id
                WHERE c.asset_id=? {project_clause}
                ORDER BY c.block_id, c.id
                """,
                params,
            ).fetchall()
        return [_citation_from_row(row) for row in rows]


def _knowledge_project(connection: sqlite3.Connection, item_id: str) -> str:
    row = connection.execute(
        "SELECT project_id FROM knowledge_items WHERE id=?", (item_id,)
    ).fetchone()
    if row is None:
        raise RecordNotFoundError(f"knowledge item not found: {item_id}")
    return str(row["project_id"])


def _require_knowledge_project(
    connection: sqlite3.Connection,
    item_id: str,
    project_id: str,
) -> None:
    _require_expected_project(
        _knowledge_project(connection, item_id),
        project_id,
        "knowledge item",
        item_id,
    )


def _asset_project(connection: sqlite3.Connection, asset_id: str) -> str | None:
    row = connection.execute(
        "SELECT project_id FROM text_assets WHERE id=?", (asset_id,)
    ).fetchone()
    if row is None:
        raise RecordNotFoundError(f"text asset not found: {asset_id}")
    return str(row["project_id"]) if row["project_id"] is not None else None


def _evidence_project(connection: sqlite3.Connection, evidence_id: str) -> str:
    row = connection.execute(
        """
        SELECT k.project_id
        FROM evidence_snippets AS e
        JOIN knowledge_items AS k ON k.id=e.knowledge_item_id
        WHERE e.id=?
        """,
        (evidence_id,),
    ).fetchone()
    if row is None:
        raise RecordNotFoundError(f"evidence not found: {evidence_id}")
    return str(row["project_id"])


def _require_expected_project(
    actual_project_id: str | None,
    expected_project_id: str | None,
    entity_type: str,
    entity_id: str,
) -> None:
    if expected_project_id is not None and actual_project_id != expected_project_id:
        raise ProjectScopeError(f"{entity_type} does not belong to project: {entity_id}")


def _knowledge_item_from_row(row: sqlite3.Row) -> KnowledgeItem:
    published = str(row["published_at"]) if row["published_at"] else None
    tags = json.loads(str(row["tags_json"]))
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise WritingStorageError("stored knowledge tags are invalid")
    return KnowledgeItem(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        kind=cast(Any, str(row["kind"])),
        title=str(row["title"]),
        content=str(row["content"]),
        source_url=str(row["source_url"]),
        published_at=_parse_datetime(published) if published else None,
        tags=tuple(cast(list[str], tags)),
        created_at=_parse_datetime(str(row["created_at"])),
    )


def _evidence_from_row(row: sqlite3.Row) -> Evidence:
    published = str(row["published_at"]) if row["published_at"] else None
    return Evidence(
        id=str(row["id"]),
        knowledge_item_id=str(row["knowledge_item_id"]),
        excerpt=str(row["excerpt"]),
        locator=str(row["locator"]),
        source_url=str(row["source_url"]),
        source_hash=str(row["source_hash"]),
        published_at=_parse_datetime(published) if published else None,
    )


def _claim_from_row(row: sqlite3.Row) -> Claim:
    evidence_ids = json.loads(str(row["evidence_ids_json"]))
    if not isinstance(evidence_ids, list) or any(
        not isinstance(evidence_id, str) for evidence_id in evidence_ids
    ):
        raise WritingStorageError("stored claim evidence ids are invalid")
    return Claim(
        id=str(row["id"]),
        asset_id=str(row["asset_id"]),
        block_id=str(row["block_id"]),
        text=str(row["text"]),
        kind=cast(Any, str(row["kind"])),
        status=cast(Any, str(row["status"])),
        evidence_ids=tuple(cast(list[str], evidence_ids)),
        confidence=int(row["confidence"]),
    )


def _citation_from_row(row: sqlite3.Row) -> Citation:
    return Citation(
        id=str(row["id"]),
        asset_id=str(row["asset_id"]),
        block_id=str(row["block_id"]),
        claim_id=str(row["claim_id"]),
        evidence_id=str(row["evidence_id"]),
        label=str(row["label"]),
    )


def _search_like(
    connection: sqlite3.Connection,
    query: str,
    *,
    project_id: str | None,
    kind: str | None,
    limit: int,
    offset: int,
) -> list[sqlite3.Row]:
    clauses = ["(title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')"]
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    values: list[object] = [f"%{escaped}%", f"%{escaped}%"]
    if project_id is not None:
        clauses.append("project_id=?")
        values.append(project_id)
    if kind is not None:
        clauses.append("kind=?")
        values.append(kind)
    values.extend((limit, offset))
    return connection.execute(
        f"""
        SELECT *, 0.0 AS fts_rank,
               substr(content, 1, 1000) AS excerpt
        FROM knowledge_items
        WHERE {" AND ".join(clauses)}
        ORDER BY updated_at DESC, id ASC LIMIT ? OFFSET ?
        """,
        tuple(values),
    ).fetchall()


def _quoted_fts_query(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _validate_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if offset < 0:
        raise ValueError("offset must be non-negative")


def _optional_datetime_text(value: datetime | None) -> str | None:
    return _datetime_text(value) if value is not None else None


def _datetime_text(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


__all__ = ["KnowledgeRepository", "KnowledgeSearchResult"]
