"""Offline tests for traceable fact extraction and sentence-level auditing."""

# Chinese official-document test data intentionally uses full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

from gongwen_web.fact_audit import audit_document, audit_facts, extract_material_facts

_MATERIALS = [
    "市数据资源管理局于2026年8月31日完成6个平台整合，平均办理时长缩短31%。",
    "市财政局负责预算审核，计划于9月15日前完成复核。",
]


def test_extract_material_facts_has_stable_ids_and_exact_source_locations() -> None:
    padded_materials = [f"  {_MATERIALS[0]}", _MATERIALS[1]]
    first = extract_material_facts(padded_materials)
    second = extract_material_facts(padded_materials)

    assert [fact.model_dump() for fact in first] == [fact.model_dump() for fact in second]
    assert len({fact.fact_id for fact in first}) == len(first)
    assert {fact.kind for fact in first} == {"number", "date", "organization", "task"}

    for fact in first:
        source = padded_materials[fact.source_index - 1]
        assert source[fact.start : fact.end] == fact.value
        assert fact.source_label == f"材料{fact.source_index}"
        assert fact.line >= 1
        assert fact.column >= 1

    values = {(fact.kind, fact.value) for fact in first}
    assert ("organization", "市数据资源管理局") in values
    assert ("date", "2026年8月31日") in values
    assert ("number", "6个") in values
    assert ("number", "31%") in values
    assert ("organization", "平均办") not in values


def test_supported_document_maps_every_claim_to_material_evidence() -> None:
    content = _MATERIALS[0]
    result = audit_document(title="数字化转型工作总结", content=content, materials=_MATERIALS)

    assert len(result.sentences) == 1
    sentence = result.sentences[0]
    assert sentence.status == "supported"
    assert sentence.has_claim is True
    assert all(claim.status == "supported" for claim in sentence.claims)
    assert all(claim.evidence_fact_ids for claim in sentence.claims)
    assert {link.fact_id for link in sentence.evidence} <= {fact.fact_id for fact in result.facts}
    assert result.issues == []
    assert result.metrics.evidence_coverage_percent == 100
    assert result.metrics.supported_sentence_count == 1
    assert result.metrics.referenced_fact_count > 0


def test_changed_numbers_and_date_are_reported_as_contradicted() -> None:
    content = "市数据资源管理局于2026年9月30日完成8个平台整合，平均办理时长缩短45%。"
    result = audit_facts(_MATERIALS, content, title="数字化转型工作总结")

    sentence = result.sentences[0]
    assert sentence.status == "contradicted"
    contradicted_values = {
        claim.value for claim in sentence.claims if claim.status == "contradicted"
    }
    assert contradicted_values == {"2026年9月30日", "8个", "45%"}
    assert all(
        link.relationship == "contradicts"
        for link in sentence.evidence
        if link.fact_id
        in {
            fact_id
            for claim in sentence.claims
            if claim.status == "contradicted"
            for fact_id in claim.evidence_fact_ids
        }
    )
    assert result.metrics.contradicted_claim_count == 3
    assert result.metrics.contradicted_sentence_count == 1
    assert any(issue.level == "error" and issue.category == "事实冲突" for issue in result.issues)


def test_mixed_sentence_is_partial_and_flags_unknown_organization_and_task() -> None:
    content = "市数据资源管理局完成6个平台整合。\n市审计局同步开展专项核验。\n一、下一步安排"
    result = audit_document(content=content, materials=_MATERIALS)

    assert [sentence.status for sentence in result.sentences] == [
        "supported",
        "unverified",
        "supported",
    ]
    unknown = result.sentences[1]
    assert {claim.kind for claim in unknown.claims} == {"organization", "task"}
    assert all(claim.status == "unverified" for claim in unknown.claims)
    assert any(
        issue.category == "主体依据" and issue.mentions == ["市审计局"] for issue in result.issues
    )
    assert any(issue.category == "任务依据" for issue in result.issues)
    # Structural headings are mapped but do not dilute claim-level coverage.
    assert result.sentences[2].has_claim is False
    assert result.metrics.sentence_count == 3
    assert result.metrics.claim_sentence_count == 2
    assert result.metrics.unverified_sentence_count == 1
    assert 0 < result.metrics.evidence_coverage_percent < 100


def test_nearby_task_or_organization_wording_can_be_partial() -> None:
    materials = "市数字化发展中心负责政务平台整合与验收。"
    content = "数字化发展中心推进政务平台整合。"
    result = audit_document(content=content, materials=materials)

    assert result.sentences[0].status in {"supported", "partial"}
    assert any(
        claim.kind in {"organization", "task"} and claim.status in {"supported", "partial"}
        for claim in result.sentences[0].claims
    )
    assert result.model_dump(mode="json") == audit_document(
        content=content, materials=materials
    ).model_dump(mode="json")


def test_claims_without_material_are_unverified_but_plain_headings_are_not_issues() -> None:
    result = audit_document(
        title="工作安排",
        content="一、总体要求\n市综合治理中心于10月20日前完成12项检查。",
        materials="",
    )

    assert result.sentences[0].has_claim is False
    assert result.sentences[0].status == "supported"
    assert result.sentences[1].status == "unverified"
    assert result.metrics.extracted_fact_count == 0
    assert result.metrics.evidence_coverage_percent == 0
    assert {issue.category for issue in result.issues} >= {
        "数字依据",
        "日期依据",
        "主体依据",
        "任务依据",
    }
