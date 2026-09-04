"""Offline persistence contracts for project-isolated academic work."""

from __future__ import annotations

from pathlib import Path

import pytest

from yanzhang_academic import (
    ACADEMIC_SCHEMA_VERSION,
    AcademicNotFoundError,
    AcademicRelationError,
    AcademicRepository,
    AcademicSchemaError,
    AcademicStoredDataError,
    Author,
    BibliographicRecord,
    ClaimCitationLink,
    EvidenceSnippet,
    ResearchClaim,
    build_literature_matrix,
)
from yanzhang_core.storage import WRITING_SCHEMA_VERSION, WritingStorage


def _record(*, title: str = "数字平台与基层公共服务") -> BibliographicRecord:
    return BibliographicRecord(
        type="article-journal",
        title=title,
        authors=[Author(literal="王明", sequence="first")],
        issued_year=2025,
        container_title="公共管理研究",
        abstract="研究采用问卷方法分析数字平台对基层公共服务的影响。",
        keywords=["数字平台", "公共服务"],
        doi="10.1234/example.2025.1",
        import_source="manual",
        source_key="wang2025",
    )


@pytest.fixture
def storage(tmp_path: Path) -> WritingStorage:
    value = WritingStorage(tmp_path / "academic.sqlite3")
    value.create_project("项目甲", project_id="project-a", default_pack_id="academic")
    value.create_project("项目乙", project_id="project-b", default_pack_id="academic")
    return value


@pytest.fixture
def repository(storage: WritingStorage) -> AcademicRepository:
    return AcademicRepository(storage)


def test_schema_marker_is_incremental_independent_and_idempotent(storage: WritingStorage) -> None:
    first = AcademicRepository(storage)
    second = AcademicRepository(storage)
    first.check_ready()
    second.check_ready()

    with storage.read_connection() as connection:
        markers = dict(
            connection.execute(
                """
                SELECT key, value FROM schema_metadata
                WHERE key IN ('writing_schema_version', 'academic_schema_version')
                """
            ).fetchall()
        )
        record_tables = connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='academic_records'"
        ).fetchone()
    assert markers["writing_schema_version"] == str(WRITING_SCHEMA_VERSION)
    assert markers["academic_schema_version"] == str(ACADEMIC_SCHEMA_VERSION)
    assert record_tables is not None and record_tables[0] == 1


def test_newer_schema_marker_is_rejected(tmp_path: Path) -> None:
    storage = WritingStorage(tmp_path / "future.sqlite3")
    with storage.write_transaction() as connection:
        connection.execute(
            "INSERT INTO schema_metadata(key, value) VALUES ('academic_schema_version', '99')"
        )
    with pytest.raises(AcademicSchemaError):
        AcademicRepository(storage)


def test_records_are_upserted_searched_and_read_only_inside_project(
    repository: AcademicRepository,
) -> None:
    first = _record()
    second = BibliographicRecord(
        title="组织协同研究",
        abstract="跨部门组织协同是公共治理的重要机制。",
        authors=[Author(literal="李华")],
        issued_year=2024,
        import_source="manual",
        source_key="li2024",
    )
    assert repository.upsert_records("project-a", [first, second]) == [first, second]
    assert repository.upsert_record("project-b", first) == first
    assert repository.get_records("project-a", [second.id, first.id]) == [second, first]
    assert repository.list_records("project-a", query="数字平台") == [first]
    assert repository.list_records("project-a", query="数字平台", offset=1) == []
    assert repository.count_records("project-a") == 2
    assert repository.count_records("project-a", query="数字平台") == 1
    assert len(repository.list_records("project-a", limit=1, offset=1)) == 1
    assert repository.list_records("project-b") == [first]
    assert repository.count_records("project-b") == 1
    with pytest.raises(AcademicNotFoundError):
        repository.get_record("project-b", second.id)
    with pytest.raises(ValueError):
        repository.get_records("project-a", [first.id, first.id])


def test_evidence_claim_and_link_relations_enforce_project_and_source_lineage(
    repository: AcademicRepository,
) -> None:
    record = repository.upsert_record("project-a", _record())
    evidence = EvidenceSnippet(
        record_id=record.id,
        record_source_hash=record.source_hash,
        text="结果表明数字平台显著提升基层公共服务效率。",
        kind="finding",
        page_start=18,
    )
    claim = ResearchClaim(
        text="数字平台显著提升基层公共服务效率。",
        section="研究发现",
        claim_type="result",
    )
    repository.upsert_evidence("project-a", evidence)
    repository.upsert_claim("project-a", claim)
    link = ClaimCitationLink(
        claim_id=claim.id,
        record_id=record.id,
        evidence_id=evidence.id,
        support_score=0.92,
        status="verified",
    )
    repository.upsert_link("project-a", link)

    assert repository.get_evidence("project-a", evidence.id) == evidence
    assert repository.get_claim("project-a", claim.id) == claim
    assert repository.get_link("project-a", link.id) == link
    assert repository.list_evidence("project-a") == [evidence]
    assert repository.list_claims("project-a") == [claim]
    assert repository.list_links("project-a", record_id=record.id) == [link]
    assert repository.count_evidence("project-a") == 1
    assert repository.count_evidence("project-a", record_id=record.id) == 1
    assert repository.count_claims("project-a") == 1
    assert repository.count_links("project-a", evidence_id=evidence.id) == 1
    assert repository.list_evidence("project-b") == []
    assert repository.list_claims("project-b") == []
    assert repository.list_links("project-b") == []
    with pytest.raises(AcademicNotFoundError):
        repository.get_link("project-b", link.id)

    bad_hash = EvidenceSnippet(
        record_id=record.id,
        record_source_hash="0" * 64,
        text="来源版本不一致的证据。",
    )
    with pytest.raises(AcademicRelationError):
        repository.upsert_evidence("project-a", bad_hash)


def test_replace_claim_set_removes_stale_claims_and_keeps_other_project(
    storage: WritingStorage, repository: AcademicRepository
) -> None:
    record = _record()
    evidence = EvidenceSnippet(
        record_id=record.id,
        record_source_hash=record.source_hash,
        text="数字平台提升公共服务效率,也促进跨部门协同。",
    )
    for project_id in ("project-a", "project-b"):
        repository.upsert_record(project_id, record)
        repository.upsert_evidence(project_id, evidence)

    claim_a = ResearchClaim(text="数字平台提升公共服务效率。", section="研究发现")
    claim_b = ResearchClaim(text="数字平台促进跨部门协同。", section="研究发现")
    link_a = ClaimCitationLink(
        claim_id=claim_a.id,
        record_id=record.id,
        evidence_id=evidence.id,
        status="verified",
    )
    link_b = ClaimCitationLink(
        claim_id=claim_b.id,
        record_id=record.id,
        evidence_id=evidence.id,
        status="verified",
    )

    repository.replace_claim_set("project-a", [claim_a, claim_b], [link_a, link_b])
    repository.replace_claim_set("project-b", [claim_a], [link_a])
    repository.replace_claim_set("project-a", [claim_b], [link_b])

    restarted = AcademicRepository(WritingStorage(storage.path))
    assert restarted.list_claims("project-a") == [claim_b]
    assert restarted.list_links("project-a") == [link_b]
    with pytest.raises(AcademicNotFoundError):
        restarted.get_claim("project-a", claim_a.id)
    with pytest.raises(AcademicNotFoundError):
        restarted.get_link("project-a", link_a.id)
    assert restarted.list_claims("project-b") == [claim_a]
    assert restarted.list_links("project-b") == [link_a]


def test_replace_claim_set_rolls_back_when_new_link_breaks_source_lineage(
    repository: AcademicRepository,
) -> None:
    first_record = repository.upsert_record("project-a", _record())
    second_record = repository.upsert_record(
        "project-a",
        BibliographicRecord(
            title="跨部门协同机制研究",
            import_source="manual",
            source_key="second-record",
        ),
    )
    evidence = EvidenceSnippet(
        record_id=first_record.id,
        record_source_hash=first_record.source_hash,
        text="数字平台提升公共服务效率。",
    )
    repository.upsert_evidence("project-a", evidence)
    old_claim = ResearchClaim(text="数字平台提升公共服务效率。")
    old_link = ClaimCitationLink(
        claim_id=old_claim.id,
        record_id=first_record.id,
        evidence_id=evidence.id,
        status="verified",
    )
    repository.replace_claim_set("project-a", [old_claim], [old_link])

    new_claim = ResearchClaim(text="数字平台促进跨部门协同。")
    mismatched_link = ClaimCitationLink(
        claim_id=new_claim.id,
        record_id=second_record.id,
        evidence_id=evidence.id,
    )
    with pytest.raises(AcademicRelationError):
        repository.replace_claim_set("project-a", [new_claim], [mismatched_link])

    assert repository.list_claims("project-a") == [old_claim]
    assert repository.list_links("project-a") == [old_link]


def test_matrix_relations_are_persisted_and_dependent_snapshots_are_removed(
    repository: AcademicRepository,
) -> None:
    record = repository.upsert_record("project-a", _record())
    evidence = EvidenceSnippet(
        record_id=record.id,
        record_source_hash=record.source_hash,
        text="本研究采用问卷方法。结果表明数字平台提升了服务效率。",
        kind="finding",
        page_start=20,
    )
    repository.upsert_evidence("project-a", evidence)
    matrix = build_literature_matrix([record], [evidence], query="服务效率")
    repository.upsert_matrix("project-a", matrix)

    assert repository.get_matrix("project-a", matrix.id) == matrix
    assert repository.list_matrices("project-a") == [matrix]
    assert repository.count_matrices("project-a") == 1
    assert repository.list_matrices("project-b") == []
    assert repository.count_matrices("project-b") == 0
    assert repository.delete_evidence("project-a", evidence.id) is True
    with pytest.raises(AcademicNotFoundError):
        repository.get_matrix("project-a", matrix.id)


def test_record_delete_cascades_project_local_evidence_claim_links_and_fts(
    repository: AcademicRepository,
) -> None:
    record = repository.upsert_record("project-a", _record())
    evidence = EvidenceSnippet(
        record_id=record.id,
        record_source_hash=record.source_hash,
        text="数字平台提升公共服务效率。",
    )
    claim = ResearchClaim(text="数字平台提升公共服务效率。")
    link = ClaimCitationLink(
        claim_id=claim.id,
        record_id=record.id,
        evidence_id=evidence.id,
    )
    repository.upsert_evidence("project-a", evidence)
    repository.upsert_claim("project-a", claim)
    repository.upsert_link("project-a", link)

    assert repository.delete_record("project-a", record.id) is True
    assert repository.list_records("project-a", query="数字平台") == []
    assert repository.list_evidence("project-a") == []
    assert repository.list_links("project-a") == []
    assert repository.get_claim("project-a", claim.id) == claim


def test_strict_json_read_detects_corrupt_or_schema_drifted_payload(
    storage: WritingStorage, repository: AcademicRepository
) -> None:
    record = repository.upsert_record("project-a", _record())
    with storage.write_transaction() as connection:
        connection.execute(
            """
            UPDATE academic_records SET payload_json=?
            WHERE project_id=? AND id=?
            """,
            ('{"id": 42, "id": "duplicate"}', "project-a", record.id),
        )
    with pytest.raises(AcademicStoredDataError):
        repository.get_record("project-a", record.id)


def test_unknown_project_is_rejected_before_any_write(repository: AcademicRepository) -> None:
    with pytest.raises(AcademicNotFoundError):
        repository.upsert_record("missing-project", _record())
    assert repository.list_records("project-a") == []
