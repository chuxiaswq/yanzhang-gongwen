"""Offline regression coverage for scene-aware drafts, titles and editing."""

# Chinese fixture punctuation is intentional.
# ruff: noqa: RUF001

from __future__ import annotations

import json

import pytest

from gongwen_mcp.schemas import RewriteTextRequest
from gongwen_web.demo import generate_demo, resolved_style, review_demo, rewrite_demo
from gongwen_web.live import (
    _generation_prompt,
    _generation_system_prompt,
    _review_prompt,
    _review_system_prompt,
    _rewrite_prompt,
    _rewrite_system_prompt,
    _title_prompt,
    _title_system_prompt,
)
from gongwen_web.methodologies import (
    default_content_methodology_id,
    methodology_catalog,
    resolve_content_methodology,
)
from gongwen_web.models import GenerateRequest, ReviewRequest, RewriteRequest
from gongwen_web.title_engine import TitleGenerationRequest, generate_titles_demo, score_title
from yanzhang_core.packs import list_recipes
from yanzhang_core.scenario_profiles import scenario_for_document_type

_NON_OFFICIAL = tuple(recipe for recipe in list_recipes() if recipe.pack_id != "gongwen")
_OFFICIAL_SLOGANS = ("提高站位", "压实责任", "凝心聚力", "实干担当", "守正创新", "贯彻落实")


@pytest.mark.parametrize("document_type", [recipe.content_type for recipe in _NON_OFFICIAL])
def test_every_non_official_recipe_has_applicable_titles_and_real_structure(
    document_type: str,
) -> None:
    catalog = methodology_catalog(document_type)
    recipe = next(recipe for recipe in _NON_OFFICIAL if recipe.content_type == document_type)
    assert catalog.default_content_methodology_id == f"recipe-{recipe.id}"
    assert len(catalog.default_title_formula_ids) == 5
    assert all("material-" not in key for key in catalog.default_title_formula_ids)
    result = generate_demo(GenerateRequest(document_type=document_type, topic="团队知识共享"))
    assert result.meta.mode == "demo"
    assert result.meta.model is None
    assert [item.heading for item in result.outline] == [item.title for item in recipe.sections]
    assert not any(term in result.content for term in _OFFICIAL_SLOGANS)
    assert not any(
        term in candidate.title
        for candidate in result.title_candidates
        for term in _OFFICIAL_SLOGANS
    )
    style = next(card for card in result.source_cards if card.id == "writing-style")
    profile = scenario_for_document_type(document_type)
    assert style.label == profile.recipe_styles[recipe.id]
    assert "权威媒体" not in style.label
    assert result.placeholders
    assert "本节围绕" not in result.content
    assert "按自定义结构" not in result.content


@pytest.mark.parametrize("document_type", ["学术论文", "论文", "期刊论文", "开题报告"])
def test_paper_aliases_resolve_to_research_structure_not_work_summary(document_type: str) -> None:
    method = resolve_content_methodology(document_type)
    assert method.id == "recipe-research-outline"
    assert "资料与方法" in method.headings
    draft = generate_demo(GenerateRequest(document_type=document_type, topic="平台协同"))
    assert "研究问题" in draft.content
    assert "工作总结" not in draft.content


def test_unknown_custom_type_uses_neutral_structure_and_no_publication_fallback() -> None:
    assert default_content_methodology_id("客户交流说明") == "generic-evidence-structure"
    draft = generate_demo(
        GenerateRequest(
            document_type="客户交流说明", topic="服务衔接", reference_style="求是式理论论证"
        )
    )
    assert "背景与目标" in draft.content
    assert not any(term in draft.content for term in _OFFICIAL_SLOGANS)
    assert (
        next(card for card in draft.source_cards if card.id == "writing-style").label == "结论先行"
    )


def test_workplace_draft_preserves_dates_and_does_not_repeat_facts_as_different_results() -> None:
    draft = generate_demo(
        GenerateRequest(
            document_type="周报",
            topic="搜索改版",
            materials="2026年9月3日已完成搜索页交付。下周计划进行验收。接口存在超时风险。",
        )
    )
    assert draft.content.count("2026年9月3日已完成搜索页交付") == 1
    assert draft.facts[0].startswith("2026年9月3日")
    sections = {item.heading: item.content for item in draft.outline}
    assert "完成搜索页交付" in sections["本周完成"]
    assert "下周计划进行验收" in sections["下周计划"]
    assert "超时风险" in sections["风险与协同"]


def test_academic_abstract_leaves_missing_results_unclaimed() -> None:
    draft = generate_demo(
        GenerateRequest(
            document_type="摘要",
            topic="团队知识共享",
            materials="拟采用访谈方法，计划收集资料。",
            reference_style="人民日报式消息评论",
        )
    )
    sections = {item.heading: item.content for item in draft.outline}
    assert "拟采用访谈" in sections["方法"]
    assert "【待补：原文中的实际研究结果" in sections["结果"]
    assert "显著提升" not in draft.content
    assert "研究发现" not in sections["结论"]
    style = next(card for card in draft.source_cards if card.id == "writing-style")
    assert "人民日报" not in style.label


def test_academic_review_scaffold_has_evidence_and_page_locators_not_fake_citations() -> None:
    draft = generate_demo(
        GenerateRequest(
            document_type="文献综述",
            topic="远程协作",
            materials="文献材料A认为同步沟通有助于信息协调。",
        )
    )
    assert "检索式" in draft.content
    assert "页码或段落定位" in draft.content
    assert "研究空白应由" in draft.content
    assert "文献材料A认为" in draft.content
    assert "DOI:" not in draft.content
    assert "参考文献：" not in draft.content


def test_stale_party_media_style_is_not_used_by_academic_or_workplace_requests() -> None:
    for document_type in ("邮件", "文献综述", "摘要"):
        label, description = resolved_style(document_type, "权威媒体综合写法")
        profile = scenario_for_document_type(document_type)
        assert label in {style.label for style in profile.styles}
        assert description
        draft = generate_demo(
            GenerateRequest(
                document_type=document_type,
                topic="信息共享",
                style_references=[{"title": "提高站位，贯彻落实", "source_name": "求是网"}],
            )
        )
        assert not any(card.source_type == "文章来源（仅写法参考）" for card in draft.source_cards)
        assert not any(
            term in candidate.title
            for candidate in draft.title_candidates
            for term in _OFFICIAL_SLOGANS
        )


def test_non_official_titles_do_not_reward_action_slogans_or_require_formal_suffixes() -> None:
    scores = score_title(
        "团队协作：证据与讨论", topic="团队协作", document_type="文献综述", materials=""
    )
    assert scores.document_compliance == 100
    assert scores.action_orientation == 90
    assert scores.rhythm == 90
    email = generate_titles_demo(TitleGenerationRequest(document_type="邮件", topic="排期确认"))
    assert len(email.candidates) == 5
    assert all("关于扎实推进" not in candidate.title for candidate in email.candidates)


def test_rewrite_scene_preserves_personal_voice_and_latin_word_spacing() -> None:
    source = "我们使用 thematic analysis 进行分析。"
    for document_type in ("邮件", "文献综述"):
        result = rewrite_demo(RewriteRequest(text=source, document_type=document_type))
        assert result.text == source
        assert "本单位" not in result.text
        expanded = rewrite_demo(
            RewriteRequest(text=source, document_type=document_type, mode="expand")
        )
        assert "【待补：" in expanded.text
        assert "压实责任" not in expanded.text
    # Existing clients omitting document_type keep their historical default.
    assert "本单位" in rewrite_demo(RewriteRequest(text="我们马上看看。")).text


def test_short_email_and_academic_abstract_do_not_require_official_heading_levels() -> None:
    email = review_demo(
        ReviewRequest(
            title="排期确认", content="请确认下次会议的时间，谢谢。", document_type="邮件"
        )
    )
    assert not any(issue.category in {"结构", "完整性"} for issue in email.issues)
    abstract = review_demo(
        ReviewRequest(title="信息共享", content="研究拟讨论信息共享的影响。", document_type="摘要")
    )
    assert not any(issue.category == "结构" for issue in abstract.issues)
    assert any(issue.category == "证据边界" for issue in abstract.issues)


def test_all_live_prompts_carry_scenario_contract_without_party_media_fallback() -> None:
    draft = GenerateRequest(
        document_type="摘要", topic="远程协作", reference_style="求是式理论论证"
    )
    payload = json.loads(_generation_prompt(draft).split("\n", 1)[1])
    assert payload["scenario_id"] == "academic"
    assert payload["enforce_content_methodology"] is True
    assert payload["content_methodology"]["id"] == "recipe-research-abstract"
    assert "求是" not in payload["reference_style"]
    assert "学术" in _generation_system_prompt("摘要")
    assert "公文写作助手" not in _generation_system_prompt("摘要")
    assert "文献" in _title_system_prompt(5, "文献综述")
    title_payload = json.loads(
        _title_prompt(TitleGenerationRequest(document_type="邮件", topic="排期")).split("\n", 1)[1]
    )
    assert title_payload["scenario_id"] == "workplace"
    rewrite = RewriteRequest(document_type="摘要", text="研究资料待补。")
    assert json.loads(_rewrite_prompt(rewrite).split("\n", 1)[1])["scenario_id"] == "academic"
    assert "公文编辑" not in _rewrite_system_prompt("摘要")
    review = ReviewRequest(document_type="摘要", content="研究资料待补。")
    assert json.loads(_review_prompt(review).split("\n", 1)[1])["scenario_id"] == "academic"
    assert "邮件和短文不强制公文层级标题" in _review_system_prompt("邮件")


def test_mcp_rewrite_accepts_optional_scene_without_breaking_existing_payloads() -> None:
    assert RewriteTextRequest(text="待修改文本").document_type == ""
    assert (
        RewriteTextRequest(text="待修改文本", document_type="邮件").model_dump()["document_type"]
        == "邮件"
    )


@pytest.mark.parametrize("document_type", [recipe.content_type for recipe in _NON_OFFICIAL])
def test_custom_numbered_copy_of_recipe_keeps_the_same_semantic_content(document_type: str) -> None:
    recipe = next(recipe for recipe in _NON_OFFICIAL if recipe.content_type == document_type)
    request = GenerateRequest(
        document_type=document_type,
        topic="团队知识共享",
        materials="2026年9月3日已完成资料整理。文献材料A采用访谈方法。下周计划核对原始记录。",
    )
    standard = generate_demo(request)
    custom = generate_demo(
        GenerateRequest(
            **request.model_dump(exclude={"custom_methodology"}),
            custom_methodology={"steps": [section.title for section in recipe.sections]},
        )
    )
    assert [item.content for item in custom.outline] == [item.content for item in standard.outline]
    assert "本节围绕" not in custom.content
    assert "按自定义结构" not in custom.content
    assert custom.content.count("2026年9月3日已完成资料整理") == 1


@pytest.mark.parametrize(
    "steps",
    [
        ["1. 本周完成", "2. 进行中", "3. 风险与协同", "4. 下周计划"],
        ["（一）本周完成", "（二）进行中", "（三）风险与协同", "（四）下周计划"],
        ["(1) 本周完成", "(2) 进行中", "(3) 风险与协同", "(4) 下周计划"],
    ],
)
def test_custom_heading_numbering_is_preserved_while_facts_match_slots(steps: list[str]) -> None:
    draft = generate_demo(
        GenerateRequest(
            document_type="周报",
            topic="团队协作",
            materials="已完成资料整理。下周计划安排复核。接口存在超时风险。",
            custom_methodology={"steps": steps},
        )
    )
    assert [item.heading for item in draft.outline] == steps
    assert "已完成资料整理" in draft.outline[0].content
    assert "超时风险" in draft.outline[2].content
    assert "下周计划安排复核" in draft.outline[3].content
    assert "本节围绕" not in draft.content


def test_unrecognized_custom_step_stays_explicit_and_keeps_material_instead_of_fake_prose() -> None:
    draft = generate_demo(
        GenerateRequest(
            document_type="邮件",
            topic="排期确认",
            materials="客户希望下周进行评审。",
            custom_methodology={"steps": ["交代排期争议", "比较可用时间"]},
        )
    )
    assert "交代排期争议" in draft.outline[0].content
    assert "比较可用时间" in draft.outline[1].content
    assert draft.content.count("客户希望下周进行评审") == 1
    assert "本节围绕" not in draft.content


def test_custom_step_braces_are_literal_content_not_a_format_expression() -> None:
    draft = generate_demo(
        GenerateRequest(
            document_type="业务方案",
            topic="排期比较",
            custom_methodology={"steps": ["比较{方案A}和{方案B}", "明确{关键条件}"]},
        )
    )
    assert "比较{方案A}和{方案B}" in draft.outline[0].content
    assert "明确{关键条件}" in draft.outline[1].content


@pytest.mark.parametrize(
    ("document_type", "topic", "repeated"),
    [
        ("业务方案", "客户支持知识库改版方案", "方案业务方案"),
        ("业务方案", "客户支持知识库业务方案", "业务方案业务方案"),
        ("周报", "搜索团队周报", "周报周报"),
        ("文献综述", "远程协作文献综述", "综述：文献综述"),
        ("文献综述", "远程协作综述", "综述：文献综述"),
        ("研究提纲", "知识共享研究提纲", "提纲：研究提纲"),
        ("PPT提纲", "客户支持演示提纲", "提纲｜PPT提纲"),
        ("摘要", "知识共享研究摘要", "摘要：研究摘要"),
        ("摘要", "知识共享摘要", "摘要的研究摘要"),
        ("审稿回复", "知识共享审稿回复", "回复：审稿意见回复"),
    ],
)
def test_builtin_title_formulas_do_not_duplicate_an_existing_type_suffix(
    document_type: str,
    topic: str,
    repeated: str,
) -> None:
    result = generate_titles_demo(TitleGenerationRequest(document_type=document_type, topic=topic))
    assert len(result.candidates) == 5
    assert len({candidate.title for candidate in result.candidates}) == 5
    assert any(candidate.title == topic for candidate in result.candidates)
    assert all(repeated not in candidate.title for candidate in result.candidates)
    draft = generate_demo(GenerateRequest(document_type=document_type, topic=topic))
    assert repeated not in draft.title


def test_type_suffix_dedup_preserves_a_type_word_in_the_middle_of_the_topic() -> None:
    topic = "方案比较的研究"
    result = generate_titles_demo(TitleGenerationRequest(document_type="业务方案", topic=topic))
    assert result.recommended_title == "方案比较的研究业务方案"
    assert all(topic in candidate.title for candidate in result.candidates)


def test_selected_titles_and_custom_title_formulas_are_not_silently_rewritten() -> None:
    chosen = "客户支持方案：业务方案"
    draft = generate_demo(
        GenerateRequest(document_type="业务方案", topic="客户支持方案", selected_title=chosen)
    )
    assert draft.title == chosen
    result = generate_titles_demo(
        TitleGenerationRequest(
            document_type="业务方案",
            topic="客户支持方案",
            custom_title_formula="{topic}：{document_type}",
        )
    )
    assert (
        next(candidate for candidate in result.candidates if candidate.formula_id == "custom").title
        == chosen
    )
