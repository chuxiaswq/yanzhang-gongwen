"""End-to-end regressions for style-only reference fact isolation."""

# Chinese fixture punctuation is intentional.
# ruff: noqa: RUF001

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from gongwen_mcp.artifacts import ArtifactStore
from gongwen_web.fact_audit import audit_document
from gongwen_web.writing_service import YanzhangPlatformService
from yanzhang_core import (
    ContentBlock,
    Evidence,
    KnowledgeItem,
    TextAsset,
    WritingBrief,
    attach_material_evidence,
    evidence_from_material,
    review_asset,
)
from yanzhang_core.storage import WritingStorage


@pytest.mark.asyncio
async def test_live_style_only_number_never_receives_fact_provenance(
    tmp_path: Path,
) -> None:
    prompts: list[dict[str, object]] = []

    async def bait_callback(_: str, user_prompt: str) -> str:
        request = cast(dict[str, object], json.loads(user_prompt))
        prompts.append(request)
        recipe = cast(dict[str, object], request["recipe"])
        sections = cast(list[dict[str, object]], recipe["sections"])
        return json.dumps(
            {
                "title": request["title"],
                "sections": [
                    {
                        "id": section["id"],
                        "content": "沿用递进句式推进工作，目前已完成999项任务。",
                    }
                    for section in sections
                ],
            },
            ensure_ascii=False,
        )

    service = YanzhangPlatformService(
        WritingStorage(tmp_path / "style-isolation.sqlite3"),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        model_callback=bait_callback,
        routing_preset="balanced",
    )
    try:
        created_project = await service.yanzhang_create_project(
            {"name": "写法参考事实隔离", "scenario_pack_id": "gongwen"}
        )
        project_id = cast(str, cast(dict[str, object], created_project["project"])["id"])
        await service.yanzhang_add_material(
            {
                "project_id": project_id,
                "material_id": "fact-source",
                "title": "事实材料",
                "content": "据统计，目前已完成12项任务。",
                "kind": "source",
            }
        )
        await service.yanzhang_add_material(
            {
                "project_id": project_id,
                "material_id": "style-bait",
                "title": "写法参考",
                "content": "学习递进句式；示例表述为目前已完成999项任务。",
                "kind": "style_reference",
            }
        )
        saved = await service.create_brief(
            {
                "project_id": project_id,
                "brief_id": "brief-style-isolation",
                "topic": "阶段任务复盘",
                "goal": "总结进展",
                "audience": "各处室",
                "channel": "document",
                "content_type": "工作总结",
                "scenario_pack_id": "gongwen",
                "recipe_id": "work-summary",
                "material_ids": ["fact-source", "style-bait"],
                "selected_title": "阶段任务复盘",
                "structure_override": [
                    {
                        "id": "progress",
                        "title": "一、主要进展",
                        "purpose": "归纳任务进展。",
                    }
                ],
            }
        )

        created = await service.create_asset(
            {
                "project_id": project_id,
                "brief_id": saved["brief_id"],
                "live": True,
            }
        )
        asset_id = cast(str, cast(dict[str, object], created["asset"])["id"])
        asset = service.storage.get_text_asset(asset_id, project_id=project_id)
        paragraph = next(block for block in asset.blocks if block.kind == "paragraph")

        assert "999项" in paragraph.text
        assert paragraph.knowledge_item_ids == ("fact-source",)
        assert paragraph.evidence_ids == ()
        assert [item["id"] for item in cast(list[dict[str, object]], prompts[0]["knowledge"])] == [
            "fact-source"
        ]
        assert [
            item["id"] for item in cast(list[dict[str, object]], prompts[0]["style_references"])
        ] == ["style-bait"]

        source_evidence = service.knowledge.list_evidence("fact-source", project_id=project_id)
        assert source_evidence
        assert service.knowledge.list_evidence("style-bait", project_id=project_id) == []

        claims = service.knowledge.list_claims(asset.id, project_id=project_id)
        bait_claim = next(claim for claim in claims if "999项" in claim.text)
        assert bait_claim.status == "unsupported"
        assert bait_claim.evidence_ids == ()
        assert service.knowledge.list_citations(asset.id, project_id=project_id) == []

        reviewed = await service.yanzhang_review_asset(
            {
                "project_id": project_id,
                "asset_id": asset.id,
                "checks": ["facts", "citations"],
                "live": False,
            }
        )
        report = cast(dict[str, object], reviewed["review"])
        metrics = cast(dict[str, object], report["metrics"])
        issues = cast(list[dict[str, object]], report["issues"])
        assert metrics["evidence_coverage"] == 0
        assert any(issue["dimension"] == "evidence" for issue in issues)

        audit = audit_document(
            content=paragraph.text,
            materials=["据统计，目前已完成12项任务。"],
            title=asset.title,
        )
        audited_number = next(
            claim
            for sentence in audit.sentences
            for claim in sentence.claims
            if claim.kind == "number" and claim.value == "999项"
        )
        assert audited_number.status != "supported"
        assert audited_number.evidence_fact_ids == []
    finally:
        service.close()


def test_style_reference_is_not_an_evidence_record_even_when_explicitly_linked() -> None:
    source = KnowledgeItem(
        id="fact-source",
        project_id="project-one",
        title="事实材料",
        content="目前已完成12项任务。",
    )
    style = KnowledgeItem(
        id="style-reference",
        project_id="project-one",
        title="写法参考",
        content="目前已完成999项任务。",
        kind="style_reference",
    )
    block = ContentBlock(
        id="paragraph-one",
        kind="paragraph",
        order=0,
        text="目前已完成12项任务。",
        knowledge_item_ids=(source.id, style.id),
    )

    linked, evidence = attach_material_evidence((block,), (source, style))

    assert [item.knowledge_item_id for item in evidence] == [source.id]
    assert linked[0].evidence_ids == (evidence[0].id,)
    with pytest.raises(ValueError, match="写法参考不得转换为事实证据"):
        evidence_from_material(style)


def test_structural_topic_quotes_do_not_block_supported_numeric_facts() -> None:
    source = KnowledgeItem(
        id="fact-source",
        project_id="project-one",
        title="事实材料",
        content="2026年开展基层调研12次，收集意见47条。",
    )
    block = ContentBlock(
        id="paragraph-one",
        kind="paragraph",
        order=0,
        text="围绕“树立和践行正确政绩观”，2026年开展基层调研12次，收集意见47条。",
        knowledge_item_ids=(source.id,),
    )

    linked, evidence = attach_material_evidence(
        (block,),
        (source,),
        structural_topic="树立和践行正确政绩观",
    )

    assert linked[0].evidence_ids == (evidence[0].id,)


@pytest.mark.parametrize(
    ("text", "structural_topic"),
    [
        ("围绕“虚构主题”，2026年开展基层调研12次，收集意见47条。", None),
        (
            "围绕“虚构主题”，2026年开展基层调研12次，收集意见47条。",
            "树立和践行正确政绩观",
        ),
        (
            "材料称“树立和践行正确政绩观”，2026年开展基层调研12次，收集意见47条。",
            "树立和践行正确政绩观",
        ),
    ],
)
def test_structural_quote_exemption_requires_explicit_matching_topic(
    text: str,
    structural_topic: str | None,
) -> None:
    source = KnowledgeItem(
        id="fact-source",
        project_id="project-one",
        title="事实材料",
        content="2026年开展基层调研12次，收集意见47条。",
    )
    block = ContentBlock(
        id="paragraph-one",
        kind="paragraph",
        order=0,
        text=text,
        knowledge_item_ids=(source.id,),
    )

    linked, _ = attach_material_evidence(
        (block,),
        (source,),
        structural_topic=structural_topic,
    )

    assert linked[0].evidence_ids == ()


def test_review_rechecks_stale_citation_content_instead_of_trusting_its_id() -> None:
    evidence = Evidence(
        id="evidence-source",
        knowledge_item_id="fact-source",
        excerpt="目前已完成12项任务。",
    )
    block = ContentBlock(
        id="paragraph-one",
        kind="paragraph",
        order=0,
        text="目前已完成999项任务。",
        evidence_ids=(evidence.id,),
    )
    now = datetime.now(UTC)
    asset = TextAsset(
        id="asset-one",
        brief_id="brief-one",
        title="阶段任务复盘",
        content_type="工作总结",
        channel="document",
        blocks=(block,),
        created_at=now,
        updated_at=now,
    )

    report = review_asset(asset, evidence=(evidence,))

    assert report.metrics.claim_like_count == 1
    assert report.metrics.cited_claim_like_count == 0
    assert report.metrics.evidence_coverage == 0
    assert any(
        issue.dimension == "evidence" and "未覆盖全部事实锚点" in issue.message
        for issue in report.issues
    )


def test_review_exempts_only_the_explicit_brief_topic_quote() -> None:
    evidence = Evidence(
        id="evidence-source",
        knowledge_item_id="fact-source",
        excerpt="2026年开展基层调研12次，收集意见47条。",
    )
    block = ContentBlock(
        id="paragraph-one",
        kind="paragraph",
        order=0,
        text="围绕“树立和践行正确政绩观”，2026年开展基层调研12次，收集意见47条。",
        evidence_ids=(evidence.id,),
    )
    now = datetime.now(UTC)
    asset = TextAsset(
        id="asset-one",
        brief_id="brief-one",
        title="阶段任务复盘",
        content_type="工作总结",
        channel="document",
        blocks=(block,),
        created_at=now,
        updated_at=now,
    )
    brief = WritingBrief(
        id="brief-one",
        title="树立和践行正确政绩观",
        goal="总结进展",
        audience="各处室",
        content_type="工作总结",
        scenario_pack_id="gongwen",
        recipe_id="work-summary",
    )

    matching = review_asset(asset, brief=brief, evidence=(evidence,))
    mismatching = review_asset(
        asset,
        brief=brief.model_copy(update={"title": "另一明确主题"}),
        evidence=(evidence,),
    )

    assert matching.metrics.evidence_coverage == 100
    assert mismatching.metrics.evidence_coverage == 0
    assert any(
        issue.dimension == "evidence" and "未覆盖全部事实锚点" in issue.message
        for issue in mismatching.issues
    )
