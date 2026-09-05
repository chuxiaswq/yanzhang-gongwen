"""Scene contracts stay distinct through generation, adaptation and local review."""

# Chinese fixtures intentionally exercise full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import json
from typing import Literal

import pytest

from yanzhang_core.composer import ModelCallbackRequiredError, YanzhangComposer
from yanzhang_core.headlines import (
    CandidateRequest,
    generate_candidates,
    list_headline_formulas,
    score_candidate,
)
from yanzhang_core.models import ContentBlock, KnowledgeItem, TextAsset, WritingBrief
from yanzhang_core.packs import HeadlineKind, get_recipe, list_recipes
from yanzhang_core.reviews import review_asset


def brief_for(recipe_id: str) -> WritingBrief:
    recipe = get_recipe(recipe_id)
    return WritingBrief(
        id="scene-brief",
        title="知识协作平台",
        goal="比较相关路径的适用条件",
        audience="项目参与者",
        content_type=recipe.content_type,
        channel=recipe.channels[0],
        scenario_pack_id=recipe.pack_id,
        recipe_id=recipe.id,
    )


def asset_for(recipe_id: str, text: str) -> TextAsset:
    brief = brief_for(recipe_id)
    return TextAsset(
        id="scene-asset",
        brief_id=brief.id,
        title=brief.title,
        content_type=brief.content_type,
        channel=brief.channel,
        blocks=(ContentBlock(id="body", kind="paragraph", order=0, text=text),),
    )


@pytest.mark.parametrize("recipe_id", [recipe.id for recipe in list_recipes()])
@pytest.mark.asyncio
async def test_every_recipe_has_distinct_section_jobs_and_no_repeated_constraints(
    recipe_id: str,
) -> None:
    brief = brief_for(recipe_id).model_copy(update={"constraints": ("使用已确认资料。",)})
    recipe = get_recipe(recipe_id)
    draft = await YanzhangComposer().compose(brief, recipe)
    paragraphs = [block.text for block in draft.blocks if block.kind == "paragraph"]
    assert len(paragraphs) == len(recipe.sections)
    assert len(set(paragraphs)) == len(paragraphs)
    assert draft.mode == "local"
    all_text = "\n".join(block.text for block in draft.blocks)
    assert all_text.count("使用已确认资料") == 1
    if recipe.pack_id != "gongwen":
        assert "政治站位" not in all_text
        assert "压实责任" not in all_text
        assert "推动落实" not in all_text


@pytest.mark.asyncio
async def test_weekly_report_routes_facts_once_without_turning_plans_into_results() -> None:
    brief = brief_for("weekly-report")
    facts = KnowledgeItem(
        id="weekly-record",
        project_id="test-project",
        kind="source",
        title="工作记录",
        content="已完成登录页验收。当前阻塞为测试环境未就绪。下周计划启动移动端试点。",
    )
    style = KnowledgeItem(
        id="style",
        project_id="test-project",
        kind="style_reference",
        title="表达参考",
        content="累计提升999%。",
    )
    draft = await YanzhangComposer().compose(brief, get_recipe("weekly-report"), (facts, style))
    paragraphs = [block for block in draft.blocks if block.kind == "paragraph"]
    assert "已完成登录页验收" in paragraphs[0].text
    assert "下周计划启动" not in paragraphs[0].text
    assert "下周计划启动" in paragraphs[-1].text
    text = "\n".join(block.text for block in paragraphs)
    assert text.count("已完成登录页验收") == 1
    assert "999" not in text
    assert all("style" not in block.knowledge_item_ids for block in paragraphs)


@pytest.mark.parametrize(
    ("recipe_id", "terms"),
    [
        ("work-email", ("您好", "回复", "请确认")),
        ("weekly-report", ("本周", "阻塞", "下周")),
        ("business-proposal", ("验收标准", "测算", "试点")),
        ("press-release", ("事件主体", "采访引语", "背景")),
        ("literature-review", ("纳入标准", "文献", "研究空白")),
        ("research-abstract", ("方法", "结果", "结论", "原文")),
        ("reviewer-response", ("审稿意见", "修改", "页码")),
    ],
)
@pytest.mark.asyncio
async def test_local_drafts_have_recipe_specific_language(
    recipe_id: str, terms: tuple[str, ...]
) -> None:
    draft = await YanzhangComposer().compose(brief_for(recipe_id), get_recipe(recipe_id))
    text = "\n".join(block.text for block in draft.blocks)
    assert all(term in text for term in terms)


@pytest.mark.parametrize("kind", ["title", "opening", "section_heading", "topic_sentence"])
def test_all_expression_positions_change_with_scenario(kind: HeadlineKind) -> None:
    batches = [
        generate_candidates(CandidateRequest(brief=brief_for(recipe), kind=kind, count=12))
        for recipe in ("work-summary", "weekly-report", "press-release", "literature-review")
    ]
    assert len({tuple(item.text for item in batch.candidates) for batch in batches}) == 4
    academic = " ".join(item.text for item in batches[-1].candidates)
    assert all(term not in academic for term in ("压实责任", "促落实", "行动指南", "成在行动"))
    assert any(term in academic for term in ("证据", "研究", "文献"))


def test_academic_catalog_is_discoverable_and_keeps_stable_formula_ids() -> None:
    academic = list_headline_formulas("title", scenario_pack_id="academic")
    workplace = list_headline_formulas("title", scenario_pack_id="workplace")
    assert [formula.id for formula in academic] == [formula.id for formula in workplace]
    assert {formula.template for formula in academic} != {formula.template for formula in workplace}
    request = CandidateRequest(brief=brief_for("research-outline"))
    assert score_candidate("压实责任，推动知识协作平台开新局", request).channel_fit < 50


@pytest.mark.parametrize("recipe_id", ["weekly-report", "literature-review"])
@pytest.mark.asyncio
async def test_live_prompt_includes_scenario_and_style_constraints(recipe_id: str) -> None:
    calls: list[tuple[str, str]] = []
    recipe = get_recipe(recipe_id)

    async def model(system: str, user: str) -> str:
        calls.append((system, user))
        return json.dumps(
            {
                "title": "知识协作平台",
                "sections": [{"id": s.id, "content": "测试内容。"} for s in recipe.sections],
            },
            ensure_ascii=False,
        )

    brief = brief_for(recipe_id).model_copy(update={"constraints": ("写法参考：证据综合。",)})
    composer = YanzhangComposer(model)
    local = await composer.compose(brief, recipe)
    assert calls == []
    assert local.mode == "local"
    live = await composer.compose(brief, recipe, live=True)
    assert live.mode == "live"
    request = json.loads(calls[0][1])
    assert request["scenario"]["id"] == recipe.pack_id
    assert request["brief"]["constraints"] == ["写法参考：证据综合。"]
    assert "场景写作要求" in calls[0][0]
    if recipe.pack_id == "academic":
        assert "研究" in calls[0][0]


@pytest.mark.asyncio
async def test_live_remains_explicit_without_a_configured_callback() -> None:
    with pytest.raises(ModelCallbackRequiredError):
        await YanzhangComposer().compose(
            brief_for("work-email"), get_recipe("work-email"), live=True
        )


@pytest.mark.parametrize("channel", ["email", "academic", "meeting", "social", "presentation"])
@pytest.mark.asyncio
async def test_channel_variants_keep_facts_without_inventing_commitments(
    channel: Literal["email", "academic", "meeting", "social", "presentation"],
) -> None:
    source = asset_for("literature-review", "现有资料包含关于平台协作的概念讨论。")
    draft = await YanzhangComposer().create_variant(source, target_channel=channel)
    text = "\n".join(block.text for block in draft.blocks)
    assert "平台协作" in text
    assert "结合实际确认后续安排" not in text
    assert "压实责任" not in text
    if channel == "email":
        assert "研究材料" in text and "研究问题" in text
    if channel == "academic":
        assert "尚不据此宣称完成了独立研究" in text


def test_academic_review_is_not_an_official_or_workplace_checklist() -> None:
    brief = brief_for("literature-review")
    report = review_asset(
        asset_for("literature-review", "研究表明该平台具有显著效果。应提高政治站位，压实责任。"),
        brief=brief,
    )
    messages = " ".join(issue.message for issue in report.issues)
    assert "研究发现" in messages
    assert "宣传性套话" in messages
    assert "文献综述" in messages
    assert "目标受众" not in messages
    assert {score.label for score in report.dimensions} >= {"研究证据与引用", "问题与论证"}
    assert report.metrics.claim_like_count == 1
    assert report.metrics.evidence_coverage == 0


def test_research_abstract_and_reviewer_reply_have_distinct_structural_checks() -> None:
    abstract = review_asset(asset_for("research-abstract", "本文讨论平台协作。"))
    reply = review_asset(asset_for("reviewer-response", "感谢审稿人的意见，我们准备补充说明。"))
    assert any("研究摘要" in issue.message for issue in abstract.issues)
    assert any("修改位置" in issue.message for issue in reply.issues)


def test_placeholder_draft_does_not_receive_an_unqualified_rule_pass() -> None:
    report = review_asset(asset_for("research-abstract", "结果：【待补充：真实研究结果】。"))
    assert any("未完成草稿" in issue.message for issue in report.issues)


def test_workplace_and_media_review_use_their_own_delivery_criteria() -> None:
    workplace = review_asset(asset_for("work-email", "分享当前项目进展。"))
    media = review_asset(asset_for("press-release", "全网第一的产品现已发布。"))
    assert any("行动或回复" in issue.message for issue in workplace.issues)
    assert any("极限词" in issue.message for issue in media.issues)
    assert any("新闻事实" in issue.message for issue in media.issues)
    assert {item.label for item in workplace.dimensions} != {
        item.label for item in media.dimensions
    }


def academic_package(*, include_evidence: bool = True) -> str:
    prefix = (
        "示例任务：关注工具使用和知识共享。当前尚未导入研究结果。"
        "请先界定研究范围。作者、年份和引用位置仍待补充。\n\n"
        "【已导入学术材料包】元数据仅用于识别文献，不证明研究结论。\n\n"
        "[文献 ref-fixture] 测试书目标题；年份：2026；DOI：未提供\n\n"
    )
    if not include_evidence:
        return prefix
    return prefix + (
        "[证据 evidence-fixture｜文献 ref-fixture] 这是虚构的界面测试片段，不是研究结论。"
        "测试材料将工具使用与知识共享分开编码，仅用来验证来源定位和正文传递。\n"
        "定位：段 1；字符 0-53"
    )


@pytest.mark.asyncio
async def test_academic_imported_evidence_is_not_crowded_out_by_task_metadata() -> None:
    item = KnowledgeItem(
        id="academic-package",
        project_id="test-project",
        kind="source",
        title="学术原文材料包",
        content=academic_package(),
    )
    draft = await YanzhangComposer().compose(
        brief_for("literature-review"), get_recipe("literature-review"), (item,)
    )
    text = "\n".join(block.text for block in draft.blocks)
    assert "测试材料将工具使用与知识共享分开编码" in text
    assert "这是虚构的界面测试片段，不是研究结论。" in text
    assert "evidence-fixture｜文献 ref-fixture" in text
    assert "定位：段 1" in text
    assert "测试书目标题" not in text
    assert "DOI：未提供" not in text
    assert "示例任务" not in text
    assert text.count("测试材料将工具使用与知识共享分开编码") == 1


@pytest.mark.asyncio
async def test_academic_metadata_alone_is_not_presented_as_research_evidence() -> None:
    item = KnowledgeItem(
        id="metadata-only",
        project_id="test-project",
        kind="source",
        title="仅有书目元数据",
        content=academic_package(include_evidence=False),
    )
    draft = await YanzhangComposer().compose(
        brief_for("literature-review"), get_recipe("literature-review"), (item,)
    )
    assert all("材料提要" not in block.text for block in draft.blocks)
    assert all(not block.knowledge_item_ids for block in draft.blocks)


@pytest.mark.asyncio
async def test_academic_live_prompt_separates_bibliography_from_original_evidence() -> None:
    calls: list[dict[str, object]] = []
    recipe = get_recipe("literature-review")

    async def model(_system: str, user: str) -> str:
        calls.append(json.loads(user))
        return json.dumps(
            {
                "title": "知识协作平台",
                "sections": [
                    {"id": section.id, "content": "测试内容。"} for section in recipe.sections
                ],
            },
            ensure_ascii=False,
        )

    item = KnowledgeItem(
        id="academic-package",
        project_id="test-project",
        kind="source",
        title="学术原文材料包",
        content=academic_package(),
    )
    await YanzhangComposer(model).compose(
        brief_for("literature-review"), recipe, (item,), live=True
    )
    fact_payload = json.dumps(calls[0]["knowledge"], ensure_ascii=False)
    metadata_payload = json.dumps(calls[0]["bibliographic_metadata"], ensure_ascii=False)
    assert "测试材料将工具使用与知识共享分开编码" in fact_payload
    assert "evidence-fixture" in fact_payload
    assert "测试书目标题" not in fact_payload
    assert "测试书目标题" in metadata_payload
    assert "测试材料将工具使用与知识共享分开编码" not in metadata_payload


@pytest.mark.asyncio
async def test_academic_real_evidence_precedes_unmarked_materials_across_items() -> None:
    context = KnowledgeItem(
        id="first-context",
        project_id="test-project",
        kind="source",
        title="背景记录",
        content="背景说明甲。背景说明乙。背景说明丙。背景说明丁。",
    )
    evidence = context.model_copy(update={"id": "last-evidence", "content": academic_package()})
    draft = await YanzhangComposer().compose(
        brief_for("literature-review"), get_recipe("literature-review"), (context, evidence)
    )
    evidence_blocks = [block for block in draft.blocks if "evidence-fixture" in block.text]
    assert evidence_blocks
    assert all("last-evidence" in block.knowledge_item_ids for block in evidence_blocks)


@pytest.mark.asyncio
async def test_long_academic_evidence_keeps_ids_and_tail_locator_and_discloses_truncation() -> None:
    original = "仅供界面测试的长段原文，" * 70 + "原文末尾还有需要结合上下文理解的限定说明。"
    locator = "定位：附录 B，第 88 页；段 9；字符 3000-3900"
    source_header = "[证据 evidence-long-fixture｜文献 ref-long-fixture]"
    item = KnowledgeItem(
        id="long-academic-package",
        project_id="test-project",
        kind="source",
        title="长原文测试材料",
        content=(
            "【已导入学术材料包】元数据不证明结论。\n\n"
            "[文献 ref-long-fixture] 长原文的来源记录；年份：2026\n\n"
            f"{source_header} {original}\n{locator}"
        ),
    )
    draft = await YanzhangComposer().compose(
        brief_for("literature-review"), get_recipe("literature-review"), (item,)
    )
    matching = [block for block in draft.blocks if source_header in block.text]
    assert len(matching) == 1
    paragraph = matching[0].text
    assert source_header in paragraph
    assert locator in paragraph
    assert "原文节选提示" in paragraph
    assert "已截断，不代表完整引文" in paragraph
    assert "请回查原始证据及上下文" in paragraph
    assert original not in paragraph
    assert "…" in paragraph
    assert paragraph.index("原文节选提示") < paragraph.index("仅供界面测试的长段原文")
    assert matching[0].knowledge_item_ids == (item.id,)


@pytest.mark.asyncio
async def test_short_academic_prose_keeps_long_locator_without_false_truncation() -> None:
    original = "这是短原文，只用于检查定位信息是否独立保留。"
    locator = "定位：" + "附录中的完整章节名称及页段说明；" * 40
    source_header = "[证据 evidence-short-fixture｜文献 ref-short-fixture]"
    item = KnowledgeItem(
        id="short-body-long-locator",
        project_id="test-project",
        kind="source",
        title="定位保留测试",
        content=f"【已导入学术材料包】\n\n{source_header} {original}\n{locator}",
    )
    draft = await YanzhangComposer().compose(
        brief_for("literature-review"), get_recipe("literature-review"), (item,)
    )
    text = "\n".join(block.text for block in draft.blocks)
    assert source_header in text
    assert original in text
    assert locator in text
    assert "原文节选提示" not in text
