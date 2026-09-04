"""Regression coverage for current academic claim snapshots."""

from __future__ import annotations

from pathlib import Path

import pytest

from gongwen_mcp.artifacts import ArtifactStore
from gongwen_web.writing_service import YanzhangPlatformService
from yanzhang_academic import (
    AcademicNotFoundError,
    BibliographicRecord,
    ClaimCitationLink,
    EvidenceSnippet,
    ResearchClaim,
)
from yanzhang_core.storage import WritingStorage


@pytest.mark.asyncio
async def test_verification_replaces_current_claim_snapshot_across_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "claims.sqlite3"
    storage = WritingStorage(database_path)
    storage.create_project("项目甲", project_id="project-a", default_pack_id="academic")
    storage.create_project("项目乙", project_id="project-b", default_pack_id="academic")
    platform = YanzhangPlatformService(storage, artifact_store=ArtifactStore(tmp_path))

    record = BibliographicRecord(
        title="数字平台与协同治理",
        abstract="数字平台提升公共服务效率并促进跨部门协同。",
        import_source="manual",
        source_key="claim-set-fixture",
    )
    evidence = EvidenceSnippet(
        record_id=record.id,
        record_source_hash=record.source_hash,
        text="研究表明数字平台提升公共服务效率,并促进跨部门协同。",
    )
    claim_a = ResearchClaim(text="数字平台提升公共服务效率。", section="研究发现")
    claim_b = ResearchClaim(text="数字平台促进跨部门协同。", section="研究发现")
    link_a = ClaimCitationLink(
        claim_id=claim_a.id,
        record_id=record.id,
        evidence_id=evidence.id,
    )
    link_b = ClaimCitationLink(
        claim_id=claim_b.id,
        record_id=record.id,
        evidence_id=evidence.id,
    )

    try:
        for project_id in ("project-a", "project-b"):
            platform.academic_repository.upsert_record(project_id, record)
            platform.academic_repository.upsert_evidence(project_id, evidence)

        await platform.yanzhang_verify_citations(
            {
                "project_id": "project-a",
                "record_ids": [record.id],
                "evidence_ids": [evidence.id],
                "claims": [claim_a.model_dump(), claim_b.model_dump()],
                "links": [link_a.model_dump(), link_b.model_dump()],
            }
        )
        await platform.yanzhang_verify_citations(
            {
                "project_id": "project-b",
                "record_ids": [record.id],
                "evidence_ids": [evidence.id],
                "claims": [claim_a.model_dump()],
                "links": [link_a.model_dump()],
            }
        )
        await platform.yanzhang_verify_citations(
            {
                "project_id": "project-a",
                "record_ids": [record.id],
                "evidence_ids": [evidence.id],
                "claims": [claim_b.model_dump()],
                "links": [link_b.model_dump()],
            }
        )
    finally:
        platform.close()

    restarted = YanzhangPlatformService(
        WritingStorage(database_path), artifact_store=ArtifactStore(tmp_path)
    )
    try:
        claims_a = await restarted.yanzhang_list_research_claims({"project_id": "project-a"})
        links_a = await restarted.yanzhang_list_citation_links({"project_id": "project-a"})
        claims_a_items = claims_a["items"]
        links_a_items = links_a["items"]
        assert isinstance(claims_a_items, list)
        assert isinstance(links_a_items, list)
        assert [item["id"] for item in claims_a_items] == [claim_b.id]
        assert [item["id"] for item in links_a_items] == [link_b.id]
        with pytest.raises(AcademicNotFoundError):
            await restarted.yanzhang_get_research_claim(
                {"project_id": "project-a", "claim_id": claim_a.id}
            )
        with pytest.raises(AcademicNotFoundError):
            await restarted.yanzhang_get_citation_link(
                {"project_id": "project-a", "link_id": link_a.id}
            )

        claims_b = await restarted.yanzhang_list_research_claims({"project_id": "project-b"})
        links_b = await restarted.yanzhang_list_citation_links({"project_id": "project-b"})
        claims_b_items = claims_b["items"]
        links_b_items = links_b["items"]
        assert isinstance(claims_b_items, list)
        assert isinstance(links_b_items, list)
        assert [item["id"] for item in claims_b_items] == [claim_a.id]
        assert [item["id"] for item in links_b_items] == [link_a.id]
    finally:
        restarted.close()
