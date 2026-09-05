"""Regression coverage for browser-to-workflow task-context alignment."""

# Chinese fixture punctuation is intentional.
# ruff: noqa: RUF001

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from gongwen_mcp.artifacts import ArtifactStore
from gongwen_mcp.writing_schemas import AddMaterialRequest, CreateWorkflowRequest
from gongwen_web.v2 import CreateBriefRequest
from gongwen_web.writing_service import YanzhangPlatformService
from yanzhang_core import KnowledgeItem, WritingBrief, WritingStructureSection, YanzhangComposer
from yanzhang_core.packs import RecipeDefinition, RecipeSection, get_recipe
from yanzhang_core.storage import BriefConflictError, ProjectScopeError, WritingStorage


@pytest.fixture
def platform(tmp_path: Path) -> Iterator[YanzhangPlatformService]:
    service = YanzhangPlatformService(
        WritingStorage(tmp_path / "writing.sqlite3"),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
    )
    try:
        yield service
    finally:
        service.close()


async def _project_with_mixed_materials(
    platform: YanzhangPlatformService,
) -> tuple[str, str, str]:
    created = await platform.yanzhang_create_project(
        {"name": "工作流输入贯通", "scenario_pack_id": "gongwen"}
    )
    project_id = cast(str, cast(dict[str, object], created["project"])["id"])
    source = await platform.yanzhang_add_material(
        {
            "project_id": project_id,
            "material_id": "workspace-primary-fixture",
            "title": "主参考材料",
            "content": "截至6月底已完成12项任务，下一步于9月底前完成复盘。",
            "kind": "source",
        }
    )
    style = await platform.yanzhang_add_material(
        {
            "project_id": project_id,
            "material_id": "workspace-style-fixture",
            "title": "写法参考",
            "content": "只学习递进句式；诱饵事实为完成999项任务。",
            "kind": "style_reference",
            "source_url": "https://example.invalid/style",
        }
    )
    source_id = cast(str, cast(dict[str, object], source["material"])["id"])
    style_id = cast(str, cast(dict[str, object], style["material"])["id"])
    return project_id, source_id, style_id


def _brief_payload(project_id: str, material_ids: list[str]) -> dict[str, object]:
    return {
        "project_id": project_id,
        "brief_id": "brief-browser-workbench",
        "topic": "数字化转型阶段复盘",
        "goal": "总结进展并部署下一步任务",
        "audience": "各处室",
        "channel": "document",
        "content_type": "工作总结",
        "scenario_pack_id": "gongwen",
        "recipe_id": "work-summary",
        "constraints": ["所有数字须有来源"],
        "material_ids": material_ids,
        "selected_title": "以实干破难题 以实绩开新局",
        "structure_override": [
            {
                "id": "review",
                "title": "一、在回望中看清来路",
                "purpose": "回顾任务范围和总体进展。",
            },
            {
                "id": "action",
                "title": "二、在攻坚中打开新局",
                "purpose": "部署下一阶段重点任务。",
            },
        ],
    }


@pytest.mark.asyncio
async def test_saved_brief_title_structure_and_sources_reach_workflow_asset(
    platform: YanzhangPlatformService,
) -> None:
    project_id, source_id, style_id = await _project_with_mixed_materials(platform)
    payload = _brief_payload(project_id, [source_id, style_id])

    saved = await platform.create_brief(payload)
    assert saved["brief_id"] == "brief-browser-workbench"

    created = await platform.yanzhang_create_workflow(
        {**payload, "auto_review": True, "requested_exports": []}
    )
    workflow = cast(dict[str, object], created["workflow"])
    assert created["brief_id"] == saved["brief_id"]
    assert workflow["brief_id"] == saved["brief_id"]
    assert cast(dict[str, object], workflow["input"])["brief"] == saved["brief"]

    completed = await platform.yanzhang_run_workflow(
        {"project_id": project_id, "workflow_id": workflow["id"], "mode": "sync"}
    )
    completed_workflow = cast(dict[str, object], completed["workflow"])
    assert completed_workflow["status"] == "succeeded"
    assert completed_workflow["brief_id"] == saved["brief_id"]

    outline_step = next(
        cast(dict[str, object], step)
        for step in cast(list[object], completed_workflow["steps"])
        if cast(dict[str, object], step)["step_id"] == "outline"
    )
    outline = cast(
        list[dict[str, object]],
        cast(dict[str, object], outline_step["output"])["outline"],
    )
    assert [section["title"] for section in outline] == [
        "一、在回望中看清来路",
        "二、在攻坚中打开新局",
    ]

    asset = platform.storage.get_text_asset(
        cast(str, completed_workflow["output_asset_id"]), project_id=project_id
    )
    assert asset.brief_id == saved["brief_id"]
    assert asset.title == "以实干破难题 以实绩开新局"
    assert [block.text for block in asset.blocks if block.kind == "heading"] == [
        "一、在回望中看清来路",
        "二、在攻坚中打开新局",
    ]
    assert "999" not in asset.plain_text()
    paragraphs = tuple(block for block in asset.blocks if block.kind == "paragraph")
    assert all(style_id not in block.knowledge_item_ids for block in paragraphs)
    fact_paragraphs = tuple(block for block in paragraphs if "材料提要" in block.text)
    assert fact_paragraphs
    assert all(source_id in block.knowledge_item_ids for block in fact_paragraphs)
    assert all(not block.knowledge_item_ids for block in paragraphs if block not in fact_paragraphs)
    assert platform.knowledge.list_evidence(source_id, project_id=project_id)
    assert platform.knowledge.list_evidence(style_id, project_id=project_id) == []
    assert [item.id for item in platform.storage.list_briefs(project_id=project_id)] == [
        "brief-browser-workbench"
    ]


@pytest.mark.asyncio
async def test_explicit_material_id_is_an_idempotent_project_scoped_upsert(
    platform: YanzhangPlatformService,
) -> None:
    first_project = await platform.yanzhang_create_project(
        {"name": "材料幂等一", "scenario_pack_id": "gongwen"}
    )
    second_project = await platform.yanzhang_create_project(
        {"name": "材料幂等二", "scenario_pack_id": "gongwen"}
    )
    first_project_id = cast(str, cast(dict[str, object], first_project["project"])["id"])
    second_project_id = cast(str, cast(dict[str, object], second_project["project"])["id"])
    request = {
        "project_id": first_project_id,
        "material_id": "workspace-source-stable",
        "title": "主参考材料",
        "content": "第一版内容。",
        "kind": "source",
    }

    first = await platform.yanzhang_add_material(request)
    second = await platform.yanzhang_add_material({**request, "content": "第二版内容。"})

    assert cast(dict[str, object], first["material"])["id"] == "workspace-source-stable"
    assert cast(dict[str, object], second["material"])["id"] == "workspace-source-stable"
    assert (
        platform.knowledge.get_item("workspace-source-stable", project_id=first_project_id).content
        == "第二版内容。"
    )
    assert len(platform.knowledge.list_items(project_id=first_project_id, limit=20)) == 1
    with pytest.raises(ProjectScopeError, match="does not belong to project"):
        await platform.yanzhang_add_material(
            {**request, "project_id": second_project_id, "content": "跨项目内容。"}
        )


@pytest.mark.asyncio
async def test_saved_brief_id_is_immutable_and_idempotent(
    platform: YanzhangPlatformService,
) -> None:
    project_id, source_id, _ = await _project_with_mixed_materials(platform)
    payload = _brief_payload(project_id, [source_id])

    first = await platform.create_brief(payload)
    replay = await platform.create_brief(payload)

    assert replay == first
    assert len(platform.storage.list_briefs(project_id=project_id)) == 1
    with pytest.raises(BriefConflictError, match="stable brief id is already bound"):
        await platform.create_brief({**payload, "goal": "变更后的目标"})


@pytest.mark.asyncio
async def test_direct_asset_uses_saved_selected_title_and_structure(
    platform: YanzhangPlatformService,
) -> None:
    project_id, source_id, _ = await _project_with_mixed_materials(platform)
    payload = _brief_payload(project_id, [source_id])
    await platform.create_brief(payload)

    created = await platform.create_asset(
        {"project_id": project_id, "brief_id": "brief-browser-workbench"}
    )
    asset = cast(dict[str, object], created["asset"])
    assert asset["title"] == "以实干破难题 以实绩开新局"
    headings = [
        cast(dict[str, object], block)["text"]
        for block in cast(list[object], asset["blocks"])
        if cast(dict[str, object], block)["kind"] == "heading"
    ]
    assert headings == ["一、在回望中看清来路", "二、在攻坚中打开新局"]


@pytest.mark.asyncio
async def test_workflow_rejects_drift_for_an_existing_brief(
    platform: YanzhangPlatformService,
) -> None:
    project_id, source_id, _ = await _project_with_mixed_materials(platform)
    payload = _brief_payload(project_id, [source_id])
    await platform.create_brief(payload)

    with pytest.raises(ValueError, match="已保存简报与当前工作流输入不一致"):
        await platform.yanzhang_create_workflow(
            {**payload, "selected_title": "另一标题", "requested_exports": []}
        )


@pytest.mark.asyncio
async def test_recipe_canonicalizes_conflicting_content_type(
    platform: YanzhangPlatformService,
) -> None:
    created = await platform.yanzhang_create_project(
        {"name": "类型归一", "scenario_pack_id": "academic"}
    )
    project_id = cast(str, cast(dict[str, object], created["project"])["id"])
    saved = await platform.create_brief(
        {
            "project_id": project_id,
            "topic": "基层治理研究",
            "goal": "梳理研究进展",
            "audience": "学术读者",
            "channel": "academic",
            "content_type": "工作总结",
            "scenario_pack_id": "academic",
            "recipe_id": "literature-review",
        }
    )
    brief = cast(dict[str, object], saved["brief"])
    assert brief["content_type"] == "文献综述"


def test_workflow_contract_bounds_and_old_brief_payload_compatibility() -> None:
    project_id = "project-contract"
    payload = _brief_payload(project_id, [])
    request = CreateWorkflowRequest.model_validate(payload)
    assert request.brief_id == "brief-browser-workbench"
    assert request.selected_title == "以实干破难题 以实绩开新局"
    assert [section.id for section in request.structure_override] == ["review", "action"]
    assert (
        AddMaterialRequest.model_validate(
            {
                "project_id": project_id,
                "material_id": "workspace-source-stable",
                "title": "材料",
                "content": "正文",
            }
        ).material_id
        == "workspace-source-stable"
    )
    http_payload = dict(payload)
    http_payload["title"] = http_payload.pop("topic")
    http_brief = CreateBriefRequest.model_validate(http_payload)
    assert http_brief.brief_id == "brief-browser-workbench"
    assert http_brief.selected_title == "以实干破难题 以实绩开新局"

    duplicate = cast(list[dict[str, object]], payload["structure_override"])
    with pytest.raises(ValidationError, match="章节标识不得重复"):
        CreateWorkflowRequest.model_validate(
            {**payload, "structure_override": [duplicate[0], duplicate[0]]}
        )

    legacy = WritingBrief.model_validate_json(
        json.dumps(
            {
                "id": "legacy-brief",
                "title": "旧简报",
                "goal": "验证默认字段",
                "audience": "项目组",
                "content_type": "周报",
                "scenario_pack_id": "workplace",
                "recipe_id": "weekly-report",
            }
        )
    )
    assert legacy.selected_title is None
    assert legacy.structure_override == ()


@pytest.mark.asyncio
async def test_live_prompt_separates_facts_from_style_references() -> None:
    prompts: list[str] = []

    async def callback(_: str, user_prompt: str) -> str:
        prompts.append(user_prompt)
        return json.dumps(
            {
                "title": "已选标题",
                "sections": [{"id": "one", "content": "事实材料显示已完成12项任务。"}],
            },
            ensure_ascii=False,
        )

    brief = WritingBrief(
        title="阶段复盘",
        goal="总结进展",
        audience="项目组",
        content_type="工作总结",
        scenario_pack_id="gongwen",
        recipe_id="work-summary",
        selected_title="已选标题",
        structure_override=(
            WritingStructureSection(id="one", title="一、主要进展", purpose="归纳进展。"),
        ),
    )
    source = KnowledgeItem(
        id="source-one",
        project_id="project-one",
        title="事实材料",
        content="已完成12项任务。",
    )
    style = KnowledgeItem(
        id="style-one",
        project_id="project-one",
        kind="style_reference",
        title="写法参考",
        content="诱饵事实999项。",
        source_url="https://private.example.invalid/style-source?token=secret",
    )
    base_recipe = get_recipe("work-summary", pack_id="gongwen")
    recipe = RecipeDefinition.model_validate(
        {
            **base_recipe.model_dump(mode="python"),
            "sections": [RecipeSection(id="one", title="一、主要进展", purpose="归纳进展。")],
        }
    )
    await YanzhangComposer(callback).compose(
        brief,
        recipe,
        (source, style),
        live=True,
        title=brief.selected_title,
    )

    prompt = json.loads(prompts[0])
    assert [item["id"] for item in prompt["knowledge"]] == ["source-one"]
    assert [item["id"] for item in prompt["style_references"]] == ["style-one"]
    assert set(prompt["style_references"][0]) == {"id", "title", "content"}
    assert "private.example.invalid" not in prompts[0]


def test_browser_prepares_one_final_brief_for_save_workflow_and_asset() -> None:
    script = Path("gongwen_web/static/app.js").read_text(encoding="utf-8")

    assert "async function prepareServerBrief(projectId, operationSerial)" in script
    assert "await ensureWorkflowKnowledge(projectId, operationSerial)" in script
    assert "applyWorkflowManagedMaterialIds(knowledge.ids)" in script
    assert "selected_title: phase2State.selected_title || undefined" in script
    assert "structure_override: serverStructureOverride()" in script
    assert "material_id: await workflowManagedMaterialId" in script
    assert 'globalThis.crypto.subtle.digest("SHA-256", input)' in script
    assert "persistPreparedBrief(projectId, operationSerial, prepared" in script
    assert "brief_id: phase2State.brief.id" in script
    assert "工作流服务没有返回 brief_id" in script
