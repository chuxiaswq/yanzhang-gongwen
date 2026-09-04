"""Offline contracts for the provider-neutral second-stage writing core."""

# Chinese test fixtures intentionally use full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from yanzhang_core import (
    CandidateRequest,
    Citation,
    Claim,
    ContentBlock,
    Evidence,
    KnowledgeItem,
    ModelProfile,
    ModelRouteRequest,
    ProjectTerm,
    Revision,
    TextAsset,
    WritingBrief,
    WritingProject,
    attach_material_evidence,
    build_provenance_graph,
    evidence_from_material,
    generate_candidates,
    get_recipe,
    get_scenario_pack,
    list_headline_formulas,
    list_recipes,
    list_scenario_packs,
    review_asset,
    route_model,
    routing_presets,
    score_candidate,
)


def _brief() -> WritingBrief:
    return WritingBrief(
        id="brief-1",
        title="项目复盘",
        goal="形成下一阶段行动方案",
        audience="项目管理委员会",
        channel="document",
        content_type="业务复盘",
        scenario_pack_id="workplace",
        recipe_id="weekly-report",
        keywords=("交付质量", "协同机制"),
        knowledge_item_ids=("source-1",),
    )


def _asset(*blocks: ContentBlock, title: str = "项目复盘") -> TextAsset:
    return TextAsset(
        id="asset-1",
        brief_id="brief-1",
        title=title,
        content_type="业务复盘",
        channel="document",
        blocks=blocks,
        current_revision=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_core_models_are_closed_strict_and_keep_traceable_relations() -> None:
    brief = _brief()
    block = ContentBlock(
        id="block-1",
        kind="paragraph",
        order=0,
        text="本周完成3项交付。",
        knowledge_item_ids=("source-1",),
        evidence_ids=("evidence-1",),
    )
    asset = _asset(block)
    revision = Revision(
        id="revision-1",
        asset_id=asset.id,
        version=1,
        blocks=asset.blocks,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    item = KnowledgeItem(
        id="source-1",
        project_id="project-1",
        title="周工作记录",
        content="本周完成3项交付。",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    evidence = Evidence(
        id="evidence-1",
        knowledge_item_id=item.id,
        excerpt=item.content,
        locator="第1段",
    )
    claim = Claim(
        id="claim-1",
        asset_id=asset.id,
        block_id=block.id,
        text=block.text,
        kind="number",
        status="supported",
        evidence_ids=(evidence.id,),
        confidence=100,
    )
    citation = Citation(
        id="citation-1",
        asset_id=asset.id,
        block_id=block.id,
        claim_id=claim.id,
        evidence_id=evidence.id,
        label="周工作记录，第1段",
    )

    assert brief.knowledge_item_ids == (item.id,)
    assert asset.plain_text() == "本周完成3项交付。"
    assert revision.blocks[0].evidence_ids == (citation.evidence_id,)
    assert claim.status == "supported"

    payload = brief.model_dump()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        WritingBrief.model_validate(payload)
    with pytest.raises(ValidationError):
        ContentBlock(kind="heading", order=0, text="缺少层级")
    with pytest.raises(ValidationError):
        Claim(
            asset_id="asset-1",
            block_id="block-1",
            text="缺少证据",
            status="supported",
        )


def test_project_and_term_models_support_local_writing_assets() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    project = WritingProject(
        id="project-1",
        name="年度重点工作",
        default_pack_id="gongwen",
        created_at=timestamp,
        updated_at=timestamp,
    )
    term = ProjectTerm(
        id="term-1",
        project_id=project.id,
        term="人工智能",
        preferred_form="人工智能",
        discouraged_variants=("AI智能",),
    )

    assert project.default_pack_id == "gongwen"
    assert term.discouraged_variants == ("AI智能",)


def test_four_scenario_packs_expose_planned_high_frequency_recipes() -> None:
    packs = list_scenario_packs()

    assert tuple(pack.id for pack in packs) == ("gongwen", "workplace", "media", "academic")
    assert len(list_recipes()) == 17
    assert get_scenario_pack("academic").name == "学术与研究写作"
    assert get_recipe("work-summary", pack_id="gongwen").content_type == "工作总结"
    assert get_recipe("work-email").channels == ("email",)
    assert get_recipe("social-post").default_headline_kind == "opening"
    assert get_recipe("presentation-outline").channels == ("presentation",)
    assert get_recipe("literature-review").sections[-1].id == "gap"
    with pytest.raises(ValueError, match="未知场景包"):
        get_scenario_pack("missing")


@pytest.mark.parametrize("kind", ("title", "opening", "section_heading", "topic_sentence"))
def test_entry_sentence_candidates_are_repeatable_ranked_and_explainable(kind: str) -> None:
    request = CandidateRequest.model_validate(
        {
            "brief": _brief().model_dump(mode="json"),
            "kind": kind,
            "section_topic": "风险治理",
            "count": 6,
            "required_terms": [],
        }
    )

    first = generate_candidates(request)
    second = generate_candidates(request)

    assert first == second
    assert first.kind == kind
    assert len(first.candidates) == 6
    assert first.recommended == first.candidates[0].text
    assert [item.rank for item in first.candidates] == [1, 2, 3, 4, 5, 6]
    assert first.candidates[0].selected is True
    assert all(not item.selected for item in first.candidates[1:])
    assert [item.score for item in first.candidates] == sorted(
        (item.score for item in first.candidates), reverse=True
    )
    assert sum(first.scoring_weights.values()) == 100
    assert all(
        0 <= value <= 100
        for item in first.candidates
        for value in item.scores.model_dump().values()
    )


def test_candidate_scoring_penalizes_unsupported_numbers() -> None:
    request = CandidateRequest(brief=_brief(), kind="title", count=3)

    grounded = score_candidate("项目复盘：形成下一阶段行动方案", request)
    invented = score_candidate("项目复盘实现100%增长", request)

    assert grounded.factual_restraint == 100
    assert invented.factual_restraint < grounded.factual_restraint


def test_candidate_engine_scores_the_full_catalog_before_truncation() -> None:
    batch = generate_candidates(CandidateRequest(brief=_brief(), kind="title", count=5))
    formula_ids = [candidate.formula_id for candidate in batch.candidates]

    # ``action`` is after the first five catalog entries. It reaches the top five
    # only when every eligible formula is scored before the count limit is applied.
    assert "action" in formula_ids
    assert "parallel-triad" in formula_ids
    assert all(candidate.formula_name for candidate in batch.candidates)
    assert all(candidate.techniques for candidate in batch.candidates)


def test_formula_filter_is_strict_deterministic_and_factually_restrained() -> None:
    request = CandidateRequest(
        brief=_brief(),
        kind="title",
        count=12,
        formula_ids=("parallel-quartet", "numbered-quartet"),
    )

    first = generate_candidates(request)
    second = generate_candidates(request.model_validate(request.model_dump(mode="json")))

    assert first == second
    assert {candidate.formula_id for candidate in first.candidates} == {
        "parallel-quartet",
        "numbered-quartet",
    }
    assert all(candidate.scores.factual_restraint == 100 for candidate in first.candidates)
    with pytest.raises(ValidationError, match="formula_ids"):
        CandidateRequest(
            brief=_brief(),
            kind="opening",
            formula_ids=("numbered-quartet",),
        )


@pytest.mark.parametrize("kind", ("title", "opening", "section_heading", "topic_sentence"))
def test_each_expression_kind_exposes_rhetorical_formula_families(kind: str) -> None:
    formulas = list_headline_formulas(kind)  # type: ignore[arg-type]
    techniques = {technique for formula in formulas for technique in formula.techniques}

    assert {"parallel", "antithesis", "progression", "triad", "quartet"} <= techniques
    assert len({formula.id for formula in formulas}) == len(formulas)
    assert all(formula.kind == kind for formula in formulas)


def test_formula_catalog_includes_explainable_main_subtitle_and_segment_patterns() -> None:
    formulas = list_headline_formulas()
    techniques = {technique for formula in formulas for technique in formula.techniques}

    assert "main_subtitle" in techniques
    assert any(formula.segment_count == 3 for formula in formulas)
    assert any(formula.segment_count == 4 for formula in formulas)


def test_model_routing_presets_are_deterministic_and_privacy_aware() -> None:
    assert tuple(preset.id for preset in routing_presets()) == (
        "economy",
        "balanced",
        "quality",
        "local_only",
    )

    economy = route_model(ModelRouteRequest(preset="economy"))
    quality = route_model(
        ModelRouteRequest(preset="quality", required_capabilities=("long_context",))
    )
    local = route_model(ModelRouteRequest(preset="local_only"))
    sensitive = route_model(ModelRouteRequest(preset="quality", contains_sensitive_data=True))

    assert economy.profile.tier == "economy"
    assert quality.profile.tier == "quality"
    assert quality.allows_network is True
    assert local.profile.tier == "local"
    assert local.allows_network is False
    assert sensitive.profile.tier == "local"
    assert sensitive.allows_network is False

    with pytest.raises(ValidationError):
        ModelProfile(
            id="broken",
            name="错误画像",
            provider="configured",
            model="fixture",
            tier="economy",
            capabilities=("drafting",),
            privacy_mode="local",
        )


def test_six_dimension_review_is_offline_traceable_and_actionable() -> None:
    heading = ContentBlock(
        id="heading-1",
        kind="heading",
        order=0,
        text="一、工作情况",
        heading_level=1,
    )
    paragraph = ContentBlock(
        id="paragraph-1",
        kind="paragraph",
        order=1,
        text="哈哈，本周完成3项交付。。但这段使用AI智能表述（还缺少闭合。",
    )
    asset = _asset(heading, paragraph)
    term = ProjectTerm(
        id="term-1",
        project_id="project-1",
        term="人工智能",
        preferred_form="人工智能",
        discouraged_variants=("AI智能",),
    )

    report = review_asset(asset, brief=_brief(), terms=(term,))

    assert tuple(item.dimension for item in report.dimensions) == (
        "evidence",
        "logic",
        "clarity",
        "audience_tone",
        "language",
        "format",
    )
    assert report.metrics.character_count > 0
    assert report.metrics.claim_like_count == 1
    assert report.metrics.evidence_coverage == 0
    assert {issue.dimension for issue in report.issues} >= {
        "evidence",
        "audience_tone",
        "language",
    }
    assert any("人工智能" in issue.suggestion for issue in report.issues)
    assert report.passed is False


def test_review_counts_a_supplied_evidence_link_as_covered() -> None:
    evidence = Evidence(
        id="evidence-1",
        knowledge_item_id="source-1",
        excerpt="本周完成3项交付。",
    )
    block = ContentBlock(
        id="paragraph-1",
        kind="paragraph",
        order=0,
        text="本周完成3项交付。",
        evidence_ids=(evidence.id,),
    )

    report = review_asset(_asset(block), evidence=(evidence,))

    assert report.metrics.evidence_coverage == 100
    assert all(issue.dimension != "evidence" for issue in report.issues)


def test_provenance_graph_links_material_blocks_claims_and_citations() -> None:
    material = KnowledgeItem(
        id="source-1",
        project_id="project-1",
        title="核验材料",
        content="截至2026年9月，项目已完成12项任务。",
        source_url="https://example.test/source",
    )
    block = ContentBlock(
        id="paragraph-1",
        kind="paragraph",
        order=0,
        text="截至2026年9月，项目已完成12项任务。",
        knowledge_item_ids=(material.id,),
    )
    asset = _asset(block)

    first = build_provenance_graph(asset, (material,))
    second = build_provenance_graph(asset, (material,))

    assert first == second
    assert first.asset.blocks[0].evidence_ids == (first.evidence[0].id,)
    assert (
        first.evidence[0].source_hash
        == hashlib.sha256(material.content.encode("utf-8")).hexdigest()
    )
    assert first.claims[0].kind == "date"
    assert first.claims[0].status == "supported"
    assert first.citations[0].claim_id == first.claims[0].id
    assert first.citations[0].evidence_id == first.evidence[0].id
    assert evidence_from_material(material) == first.evidence[0]
    linked_blocks, linked_evidence = attach_material_evidence(asset.blocks, (material,))
    assert linked_blocks == first.asset.blocks
    assert linked_evidence == first.evidence
