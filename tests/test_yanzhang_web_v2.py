"""Application-service contracts shared by Yanzhang Web v2 and MCP."""

# Chinese fixtures intentionally use full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import asyncio
import base64
import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree

import pytest

from gongwen_mcp.artifacts import ArtifactStore
from gongwen_web.writing_service import YanzhangPlatformService
from yanzhang_academic import AcademicService, BibliographicRecord
from yanzhang_core.models import ContentBlock
from yanzhang_core.storage import RecordNotFoundError, WritingStorage
from yanzhang_core.workflow import WorkflowStateError


class _MetadataFixture:
    name = "crossref"

    async def search(self, query: str, *, limit: int = 10) -> list[BibliographicRecord]:
        return [
            BibliographicRecord(
                title=f"{query}研究",
                issued_year=2026,
                import_source="crossref",
                source_key="fixture-1",
                metadata_verified=True,
            )
        ][:limit]

    async def lookup(self, identifier: str) -> BibliographicRecord | None:
        return BibliographicRecord(
            title=identifier,
            import_source="crossref",
            source_key=identifier,
            metadata_verified=True,
        )


@pytest.fixture
def platform(tmp_path: Path) -> Iterator[YanzhangPlatformService]:
    storage = WritingStorage(tmp_path / "yanzhang.db")
    service = YanzhangPlatformService(
        storage,
        artifact_store=ArtifactStore(tmp_path),
        academic=AcademicService(connectors={"crossref": _MetadataFixture()}),
    )
    try:
        yield service
    finally:
        service.close()


async def _project_and_brief(
    platform: YanzhangPlatformService,
) -> tuple[str, str, str]:
    project = await platform.yanzhang_create_project(
        {"name": "交付项目", "scenario_pack_id": "workplace"}
    )
    project_id = str(project["project"]["id"])  # type: ignore[index]
    material = await platform.yanzhang_add_material(
        {
            "project_id": project_id,
            "title": "周工作记录",
            "content": "本周完成三项交付，并确认下一阶段协同安排。",
            "tags": ["周报"],
        }
    )
    material_id = str(material["material"]["id"])  # type: ignore[index]
    brief = await platform.create_brief(
        {
            "project_id": project_id,
            "topic": "项目周报",
            "goal": "同步进展并明确行动",
            "audience": "项目管理委员会",
            "channel": "document",
            "scenario_pack_id": "workplace",
            "recipe_id": "weekly-report",
            "material_ids": [material_id],
            "keywords": ["交付"],
        }
    )
    brief_id = str(brief["brief"]["id"])  # type: ignore[index]
    return project_id, material_id, brief_id


@pytest.mark.asyncio
async def test_platform_exposes_all_mcp_methods_and_local_full_cycle(
    platform: YanzhangPlatformService,
) -> None:
    method_names = {
        name
        for name in dir(platform)
        if name.startswith("yanzhang_") and callable(getattr(platform, name))
    }
    assert len(method_names) == 45

    status = await platform.yanzhang_get_status({})
    assert status["live_model_available"] is False
    assert status["scenario_pack_count"] == 4
    packs = await platform.yanzhang_list_scene_packs({"channel": "email"})
    assert isinstance(packs["count"], int)
    assert packs["count"] >= 1

    project_id, material_id, brief_id = await _project_and_brief(platform)
    material = await platform.yanzhang_get_material(
        {
            "project_id": project_id,
            "material_id": material_id,
            "chunk_offset": 0,
            "chunk_size": 500,
        }
    )
    assert material["material"]["total_characters"] > 0  # type: ignore[index]
    assert material["material"]["next_offset"] > 0  # type: ignore[index]
    materials = await platform.yanzhang_list_materials(
        {"project_id": project_id, "query": "三项交付", "tags": ["周报"], "limit": 1}
    )
    assert materials["total"] == 1
    no_materials = await platform.yanzhang_list_materials(
        {"project_id": project_id, "query": "不存在的检索词", "limit": 1}
    )
    assert no_materials["total"] == 0
    search = await platform.yanzhang_search(
        {"project_id": project_id, "query": "交付", "scope": "all"}
    )
    assert isinstance(search["total"], int)
    assert search["total"] >= 1

    titles = await platform.yanzhang_generate_titles(
        {
            "project_id": project_id,
            "topic": "项目周报",
            "goal": "同步进展并明确行动",
            "audience": "项目管理委员会",
            "channel": "document",
            "content_type": "周报",
            "scenario_pack_id": "workplace",
            "recipe_id": "weekly-report",
            "material_ids": [material_id],
            "count": 12,
        }
    )
    assert len(titles["candidate_batch"]["candidates"]) == 12  # type: ignore[index]
    filtered_titles = await platform.yanzhang_generate_titles(
        {
            "project_id": project_id,
            "topic": "项目周报",
            "goal": "同步进展并明确行动",
            "audience": "项目管理委员会",
            "channel": "document",
            "content_type": "周报",
            "scenario_pack_id": "workplace",
            "recipe_id": "weekly-report",
            "material_ids": [material_id],
            "headline_kind": "title",
            "formula_ids": ["parallel-quartet"],
            "count": 8,
        }
    )
    filtered_candidates = filtered_titles["candidate_batch"]["candidates"]  # type: ignore[index]
    assert len(filtered_candidates) == 1
    assert filtered_candidates[0]["formula_id"] == "parallel-quartet"

    created = await platform.create_asset(
        {"project_id": project_id, "brief_id": brief_id, "live": False}
    )
    asset = created["asset"]
    asset_id = str(asset["id"])  # type: ignore[index]
    assert created["generation_mode"] == "local"
    assert asset["current_revision"] == 1  # type: ignore[index]

    revision = await platform.create_revision(
        {
            "project_id": project_id,
            "asset_id": asset_id,
            "blocks": asset["blocks"],  # type: ignore[index]
            "expected_revision": 1,
            "note": "确认版本",
        }
    )
    assert revision["revision"]["version"] == 2  # type: ignore[index]
    raw_blocks = asset["blocks"]  # type: ignore[index]
    assert isinstance(raw_blocks, list)
    formula_blocks = [dict(block) for block in raw_blocks]
    formula_blocks[0]["text"] = "=2+2"
    await platform.create_revision(
        {
            "project_id": project_id,
            "asset_id": asset_id,
            "blocks": formula_blocks,
            "expected_revision": 2,
            "note": "表格安全测试",
        }
    )
    revisions = await platform.yanzhang_list_revisions(
        {"project_id": project_id, "asset_id": asset_id}
    )
    assert revisions["total"] == 3

    report = await platform.yanzhang_review_asset(
        {"project_id": project_id, "asset_id": asset_id, "checks": ["facts"]}
    )
    assert report["review_dimensions"] == ["evidence"]
    assert len(report["review"]["dimensions"]) == 1  # type: ignore[index]
    assert report["effective_mode"] == "local"
    assert report["resolved_route"]["profile"]["id"] == "local-deterministic"  # type: ignore[index]
    variant = await platform.yanzhang_create_variant(
        {
            "project_id": project_id,
            "asset_id": asset_id,
            "target_channel": "email",
            "instruction": "结论前置",
        }
    )
    assert variant["asset"]["parent_asset_id"] == asset_id  # type: ignore[index]
    assert variant["asset"]["channel"] == "email"  # type: ignore[index]

    artifact_ids: set[str] = set()
    for export_format in ("docx", "pdf", "markdown", "text", "html", "latex", "csv"):
        exported = await platform.yanzhang_export_asset(
            {"project_id": project_id, "asset_id": asset_id, "format": export_format}
        )
        artifact = exported["artifact"]
        artifact_id = str(artifact["artifact_id"])  # type: ignore[index]
        artifact_ids.add(artifact_id)
        assert str(artifact["resource_uri"]).startswith(  # type: ignore[index]
            f"yanzhang://projects/{project_id}/exports/"
        )
        assert artifact["project_id"] == project_id  # type: ignore[index]
        assert artifact["asset_id"] == asset_id  # type: ignore[index]
        assert artifact["revision_id"]  # type: ignore[index]
        assert artifact["creator"] == "yanzhang_export_asset"  # type: ignore[index]
        if export_format == "csv":
            assert isinstance(platform.artifact_store, ArtifactStore)
            assert b"'=2+2" in platform.artifact_store.read_bytes(
                artifact_id,
                project_id=project_id,
            )
    assert len(artifact_ids) == 7


@pytest.mark.asyncio
async def test_document_import_and_project_isolation(
    platform: YanzhangPlatformService,
) -> None:
    project_id, material_id, brief_id = await _project_and_brief(platform)
    other = await platform.yanzhang_create_project(
        {"name": "其他项目", "scenario_pack_id": "workplace"}
    )
    other_id = str(other["project"]["id"])  # type: ignore[index]
    imported = await platform.import_document(
        {
            "project_id": project_id,
            "filename": "notes.md",
            "media_type": "text/markdown",
            "data_base64": base64.b64encode("# 记录\n\n离线导入内容".encode()).decode(),
            "tags": ["导入"],
        }
    )
    assert imported["document"]["content_type"] == "text/markdown"  # type: ignore[index]
    assert imported["material"]["project_id"] == project_id  # type: ignore[index]

    asset = await platform.create_asset({"project_id": project_id, "brief_id": brief_id})
    asset_id = str(asset["asset"]["id"])  # type: ignore[index]
    with pytest.raises(RecordNotFoundError):
        await platform.yanzhang_get_material({"project_id": other_id, "material_id": material_id})
    with pytest.raises(RecordNotFoundError):
        await platform.yanzhang_get_asset({"project_id": other_id, "asset_id": asset_id})


@pytest.mark.asyncio
async def test_workflow_operations_enforce_project_scope(
    platform: YanzhangPlatformService,
) -> None:
    project_id, material_id, _ = await _project_and_brief(platform)
    other = await platform.yanzhang_create_project(
        {"name": "隔离工作流项目", "scenario_pack_id": "workplace"}
    )
    other_id = str(other["project"]["id"])  # type: ignore[index]
    created = await platform.yanzhang_create_workflow(
        {
            "project_id": project_id,
            "topic": "作用域检查",
            "goal": "验证项目隔离",
            "audience": "项目组",
            "channel": "document",
            "content_type": "周报",
            "scenario_pack_id": "workplace",
            "recipe_id": "weekly-report",
            "material_ids": [material_id],
        }
    )
    workflow_id = str(created["workflow"]["id"])  # type: ignore[index]

    for action in (
        lambda: platform.yanzhang_get_workflow(
            {"project_id": other_id, "workflow_id": workflow_id}
        ),
        lambda: platform.yanzhang_run_workflow(
            {"project_id": other_id, "workflow_id": workflow_id, "mode": "sync"}
        ),
        lambda: platform.yanzhang_cancel_workflow(
            {"project_id": other_id, "workflow_id": workflow_id}
        ),
        lambda: platform.resume_workflow(
            {
                "project_id": other_id,
                "workflow_id": workflow_id,
                "resume_from": "research",
            }
        ),
    ):
        with pytest.raises(RecordNotFoundError):
            await action()

    fetched = await platform.yanzhang_get_workflow(
        {"project_id": project_id, "workflow_id": workflow_id}
    )
    assert fetched["workflow"]["project_id"] == project_id  # type: ignore[index]


@pytest.mark.asyncio
async def test_review_checks_filter_dimensions_and_explicit_live_uses_routed_model(
    tmp_path: Path,
) -> None:
    storage = WritingStorage(tmp_path / "review-live.db")
    calls: list[dict[str, object]] = []

    async def callback(system_prompt: str, user_prompt: str) -> str:
        assert "JSON" in system_prompt
        payload = json.loads(user_prompt)
        assert isinstance(payload, dict)
        calls.append(payload)
        blocks = payload["asset"]["blocks"]
        return json.dumps(
            {
                "issues": [
                    {
                        "dimension": "evidence",
                        "severity": "info",
                        "block_id": blocks[0]["id"],
                        "message": "建议再次核对材料中的时间口径。",
                        "suggestion": "回到证据原文确认统计周期。",
                    }
                ]
            },
            ensure_ascii=False,
        )

    service = YanzhangPlatformService(
        storage,
        artifact_store=ArtifactStore(tmp_path),
        model_callback=callback,
        routing_preset="balanced",
    )
    try:
        project_id, _, brief_id = await _project_and_brief(service)
        created = await service.create_asset(
            {"project_id": project_id, "brief_id": brief_id, "live": False}
        )
        asset_id = str(created["asset"]["id"])  # type: ignore[index]

        local = await service.yanzhang_review_asset(
            {
                "project_id": project_id,
                "asset_id": asset_id,
                "checks": ["structure"],
                "model_profile_id": "configured-quality",
                "live": False,
            }
        )
        assert local["effective_mode"] == "local"
        assert local["review_dimensions"] == ["logic", "format"]
        assert local["resolved_route"]["profile"]["id"] == "local-deterministic"  # type: ignore[index]
        assert calls == []

        enhanced = await service.yanzhang_review_asset(
            {
                "project_id": project_id,
                "asset_id": asset_id,
                "checks": ["facts"],
                "model_profile_id": "configured-quality",
                "live": True,
            }
        )
        assert enhanced["effective_mode"] == "live"
        assert enhanced["review_dimensions"] == ["evidence"]
        assert enhanced["resolved_route"]["profile"]["id"] == "configured-quality"  # type: ignore[index]
        assert enhanced["model_issue_count"] == 1
        issues = enhanced["review"]["issues"]  # type: ignore[index]
        assert any(issue["id"] == "model-issue-001" for issue in issues)
        assert len(calls) == 1
    finally:
        service.close()


@pytest.mark.asyncio
async def test_docx_export_preserves_block_heading_levels_and_deduplicates_title(
    platform: YanzhangPlatformService,
) -> None:
    project_id, _, brief_id = await _project_and_brief(platform)
    brief = platform.storage.get_brief(brief_id, project_id=project_id)
    title = "项目推进情况"
    asset = platform.storage.create_text_asset(
        brief,
        (
            ContentBlock(id="title", kind="title", order=0, text=title),
            ContentBlock(
                id="heading-one",
                kind="heading",
                order=1,
                text="总体情况",
                heading_level=1,
            ),
            ContentBlock(id="body", kind="paragraph", order=2, text="正文内容。"),
            ContentBlock(
                id="heading-three",
                kind="heading",
                order=3,
                text="具体安排",
                heading_level=3,
            ),
        ),
        title=title,
        project_id=project_id,
    )
    exported = await platform.yanzhang_export_asset(
        {"project_id": project_id, "asset_id": asset.id, "format": "docx"}
    )
    assert exported["template_id"] == "standard"
    artifact = exported["artifact"]
    assert isinstance(platform.artifact_store, ArtifactStore)
    payload = platform.artifact_store.read_bytes(
        str(artifact["artifact_id"]),  # type: ignore[index]
        project_id=project_id,
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(document_xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: dict[str, tuple[str | None, str | None]] = {}
    all_text: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace))
        if not text:
            continue
        all_text.append(text)
        style = paragraph.find("./w:pPr/w:pStyle", namespace)
        outline = paragraph.find("./w:pPr/w:outlineLvl", namespace)
        attribute = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val"
        paragraphs[text] = (
            style.get(attribute) if style is not None else None,
            outline.get(attribute) if outline is not None else None,
        )

    assert all_text.count(title) == 1
    assert paragraphs[title] == ("Title", None)
    assert paragraphs["总体情况"] == ("Heading1", "0")
    assert paragraphs["具体安排"] == ("Heading3", "2")

    brief_export = await platform.yanzhang_export_asset(
        {
            "project_id": project_id,
            "asset_id": asset.id,
            "format": "docx",
            "template_id": "brief",
        }
    )
    assert brief_export["template_id"] == "brief"
    brief_artifact = brief_export["artifact"]
    brief_payload = platform.artifact_store.read_bytes(
        str(brief_artifact["artifact_id"]),  # type: ignore[index]
        project_id=project_id,
    )
    with zipfile.ZipFile(io.BytesIO(brief_payload)) as archive:
        brief_document_xml = archive.read("word/document.xml")
    assert brief_document_xml != document_xml
    assert b'w:top="1440"' in brief_document_xml
    assert b'w:top="2098"' in document_xml


@pytest.mark.asyncio
async def test_persistent_six_step_workflow(platform: YanzhangPlatformService) -> None:
    project_id, material_id, _ = await _project_and_brief(platform)
    request = {
        "project_id": project_id,
        "topic": "自动周报",
        "goal": "形成可交付文稿",
        "audience": "项目组",
        "channel": "document",
        "content_type": "周报",
        "scenario_pack_id": "workplace",
        "recipe_id": "weekly-report",
        "material_ids": [material_id],
        "requested_exports": ["markdown"],
    }
    created = await platform.yanzhang_create_workflow(request)
    workflow = created["workflow"]
    assert [step["step_id"] for step in workflow["steps"]] == [  # type: ignore[index]
        "research",
        "titles",
        "outline",
        "draft",
        "review",
        "export",
    ]
    run = await platform.yanzhang_run_workflow(
        {"project_id": project_id, "workflow_id": workflow["id"], "mode": "sync"}  # type: ignore[index]
    )
    assert run["workflow"]["status"] == "succeeded"  # type: ignore[index]
    assert run["workflow"]["output_asset_id"]  # type: ignore[index]
    assert run["workflow"]["state"]["exports"]  # type: ignore[index]

    queued = await platform.yanzhang_create_workflow(request)
    cancelled = await platform.yanzhang_cancel_workflow(
        {"project_id": project_id, "workflow_id": queued["workflow"]["id"]}  # type: ignore[index]
    )
    assert cancelled["workflow"]["cancel_requested"] is True  # type: ignore[index]


@pytest.mark.asyncio
async def test_workflow_resume_guard_state_matrix_and_background_mode(
    platform: YanzhangPlatformService,
) -> None:
    project_id, material_id, _ = await _project_and_brief(platform)
    request = {
        "project_id": project_id,
        "topic": "可恢复周报",
        "goal": "验证工作流恢复边界",
        "audience": "项目组",
        "channel": "document",
        "content_type": "周报",
        "scenario_pack_id": "workplace",
        "recipe_id": "weekly-report",
        "material_ids": [material_id],
    }

    async def create_run() -> str:
        created = await platform.yanzhang_create_workflow(request)
        return str(created["workflow"]["id"])  # type: ignore[index]

    queued_id = await create_run()
    with pytest.raises(WorkflowStateError, match="resume step mismatch"):
        await platform.yanzhang_run_workflow(
            {
                "project_id": project_id,
                "workflow_id": queued_id,
                "mode": "sync",
                "resume_from": "draft",
            }
        )
    accepted = await platform.yanzhang_run_workflow(
        {
            "project_id": project_id,
            "workflow_id": queued_id,
            "mode": "background",
            "resume_from": "research",
        }
    )
    assert accepted["accepted"] is True
    for _ in range(200):
        current = await platform.yanzhang_get_workflow(
            {"project_id": project_id, "workflow_id": queued_id}
        )
        if current["workflow"]["status"] == "succeeded":  # type: ignore[index]
            break
        await asyncio.sleep(0.01)
    assert current["workflow"]["status"] == "succeeded"  # type: ignore[index]

    failed_id = await create_run()
    with platform.storage.write_transaction() as connection:
        connection.execute(
            "UPDATE workflow_runs SET status='failed', current_step_id='titles' WHERE id=?",
            (failed_id,),
        )
        connection.execute(
            "UPDATE step_runs SET status='succeeded' WHERE run_id=? AND step_id='research'",
            (failed_id,),
        )
        connection.execute(
            "UPDATE step_runs SET status='failed' WHERE run_id=? AND step_id='titles'",
            (failed_id,),
        )
    with pytest.raises(WorkflowStateError, match="explicit resume_from"):
        await platform.yanzhang_run_workflow(
            {"project_id": project_id, "workflow_id": failed_id, "mode": "sync"}
        )
    with pytest.raises(WorkflowStateError, match="resume step mismatch"):
        await platform.yanzhang_run_workflow(
            {
                "project_id": project_id,
                "workflow_id": failed_id,
                "mode": "sync",
                "resume_from": "outline",
            }
        )
    resumed = await platform.yanzhang_run_workflow(
        {
            "project_id": project_id,
            "workflow_id": failed_id,
            "mode": "sync",
            "resume_from": "titles",
        }
    )
    assert resumed["workflow"]["status"] == "succeeded"  # type: ignore[index]

    waiting_id = await create_run()
    with platform.storage.write_transaction() as connection:
        connection.execute(
            "UPDATE workflow_runs SET status='waiting_review', current_step_id='outline' "
            "WHERE id=?",
            (waiting_id,),
        )
        connection.execute(
            "UPDATE step_runs SET status='succeeded' "
            "WHERE run_id=? AND step_id IN ('research', 'titles')",
            (waiting_id,),
        )
    with pytest.raises(WorkflowStateError, match="explicit resume_from"):
        await platform.yanzhang_run_workflow(
            {"project_id": project_id, "workflow_id": waiting_id, "mode": "sync"}
        )
    assert (
        platform.workflow_engine.validate_resume_from(
            waiting_id,
            "outline",
            project_id=project_id,
        )
        == "outline"
    )

    for terminal_status in ("succeeded", "cancelled"):
        terminal_id = await create_run()
        with platform.storage.write_transaction() as connection:
            connection.execute(
                "UPDATE workflow_runs SET status=?, current_step_id=NULL WHERE id=?",
                (terminal_status, terminal_id),
            )
        terminal = await platform.yanzhang_run_workflow(
            {"project_id": project_id, "workflow_id": terminal_id, "mode": "background"}
        )
        assert terminal["accepted"] is False
        assert terminal["workflow"]["status"] == terminal_status  # type: ignore[index]
        with pytest.raises(WorkflowStateError, match="terminal"):
            await platform.yanzhang_run_workflow(
                {
                    "project_id": project_id,
                    "workflow_id": terminal_id,
                    "mode": "background",
                    "resume_from": "research",
                }
            )


@pytest.mark.asyncio
async def test_live_callback_runs_between_storage_transactions(tmp_path: Path) -> None:
    storage = WritingStorage(tmp_path / "live.db")
    calls: list[tuple[str, str]] = []

    async def callback(system_prompt: str, user_prompt: str) -> str:
        calls.append((system_prompt, user_prompt))
        storage.append_audit_event(
            action="callback",
            entity_type="test",
            entity_id="live",
            summary="模型调用期间数据库可独立写入",
        )
        request = json.loads(user_prompt)
        return json.dumps(
            {
                "title": request["title"],
                "sections": [
                    {"id": section["id"], "content": f"{section['title']}的实时内容。"}
                    for section in request["recipe"]["sections"]
                ],
            },
            ensure_ascii=False,
        )

    platform = YanzhangPlatformService(
        storage,
        artifact_store=ArtifactStore(tmp_path),
        model_callback=callback,
        routing_preset="balanced",
    )
    try:
        project_id, _, brief_id = await _project_and_brief(platform)
        result = await platform.create_asset(
            {"project_id": project_id, "brief_id": brief_id, "live": True}
        )
        assert result["generation_mode"] == "live"
        assert result["resolved_route"]["allows_network"] is True  # type: ignore[index]
        assert len(calls) == 1
        assert storage.list_audit_events()[0]["action"] == "callback"
    finally:
        platform.close()


@pytest.mark.asyncio
async def test_academic_operations_are_project_persistent(
    platform: YanzhangPlatformService,
) -> None:
    project_id, _, _ = await _project_and_brief(platform)
    imported = await platform.yanzhang_import_literature(
        {
            "project_id": project_id,
            "content": "@article{tagged, title={Tagged record}, keywords={existing; shared}}",
            "format": "bibtex",
            "tags": ["shared", "project-tag"],
        }
    )
    imported_record = imported["items"][0]  # type: ignore[index]
    assert imported_record["keywords"] == ["existing", "shared", "project-tag"]
    persisted_import = await platform.yanzhang_get_literature(
        {"project_id": project_id, "record_id": imported_record["id"]}
    )
    assert persisted_import["record"]["keywords"] == [  # type: ignore[index]
        "existing",
        "shared",
        "project-tag",
    ]

    searched = await platform.yanzhang_search_literature(
        {"project_id": project_id, "query": "数字治理", "provider": "crossref"}
    )
    record_id = str(searched["items"][0]["id"])  # type: ignore[index]
    fetched = await platform.yanzhang_get_literature(
        {"project_id": project_id, "record_id": record_id}
    )
    assert fetched["record"]["metadata_verified"] is True  # type: ignore[index]
    records_page = await platform.yanzhang_list_literature(
        {
            "project_id": project_id,
            "query": "数字治理",
            "include_abstract": False,
            "limit": 1,
            "offset": 0,
        }
    )
    assert records_page["total"] == 1
    assert records_page["count"] == 1
    assert records_page["items"][0]["abstract"] == ""  # type: ignore[index]

    extracted = await platform.yanzhang_extract_evidence(
        {
            "project_id": project_id,
            "record_id": record_id,
            "text": "数字治理研究表明协同机制能够改善信息共享质量。",
            "query": "协同机制",
        }
    )
    evidence_id = str(extracted["items"][0]["id"])  # type: ignore[index]
    evidence_page = await platform.yanzhang_list_evidence(
        {"project_id": project_id, "record_id": record_id}
    )
    assert evidence_page["total"] == 1
    evidence_item = await platform.yanzhang_get_evidence(
        {"project_id": project_id, "evidence_id": evidence_id}
    )
    assert evidence_item["evidence"]["record_id"] == record_id  # type: ignore[index]
    matrix = await platform.yanzhang_build_literature_matrix(
        {
            "project_id": project_id,
            "record_ids": [record_id],
            "evidence_ids": [evidence_id],
            "query": "协同机制",
        }
    )
    assert matrix["matrix"]["record_ids"] == [record_id]  # type: ignore[index]
    matrix_id = str(matrix["matrix"]["id"])  # type: ignore[index]
    matrix_page = await platform.yanzhang_list_literature_matrices({"project_id": project_id})
    assert matrix_page["total"] == 1
    matrix_item = await platform.yanzhang_get_literature_matrix(
        {"project_id": project_id, "matrix_id": matrix_id}
    )
    assert matrix_item["matrix"]["id"] == matrix_id  # type: ignore[index]

    claim = {
        "text": "协同机制能够改善信息共享质量",
        "section": "研究发现",
        "requires_citation": True,
    }
    from yanzhang_academic import ResearchClaim

    claim_id = ResearchClaim.model_validate(claim).id
    link = {
        "claim_id": claim_id,
        "record_id": record_id,
        "evidence_id": evidence_id,
        "relation": "supports",
    }
    audit = await platform.yanzhang_verify_citations(
        {
            "project_id": project_id,
            "record_ids": [record_id],
            "evidence_ids": [evidence_id],
            "claims": [claim],
            "links": [link],
        }
    )
    assert audit["citation_audit"]["coverage"] == 1.0  # type: ignore[index]
    verified_link = audit["citation_audit"]["links"][0]  # type: ignore[index]
    claims_page = await platform.yanzhang_list_research_claims({"project_id": project_id})
    assert claims_page["total"] == 1
    claim_item = await platform.yanzhang_get_research_claim(
        {"project_id": project_id, "claim_id": claim_id}
    )
    assert claim_item["claim"]["id"] == claim_id  # type: ignore[index]
    links_page = await platform.yanzhang_list_citation_links(
        {"project_id": project_id, "record_id": record_id}
    )
    assert links_page["total"] == 1
    link_item = await platform.yanzhang_get_citation_link(
        {"project_id": project_id, "link_id": verified_link["id"]}
    )
    assert link_item["link"]["evidence_id"] == evidence_id  # type: ignore[index]

    academic_brief = {
        "project_id": project_id,
        "title": "数字治理研究",
        "research_question": "协同机制如何影响信息共享？",
        "record_ids": [record_id],
    }
    titles = await platform.yanzhang_suggest_academic_titles({**academic_brief, "count": 3})
    outline = await platform.yanzhang_create_academic_outline(
        {**academic_brief, "evidence_ids": [evidence_id]}
    )
    abstract = await platform.yanzhang_draft_abstract(
        {**academic_brief, "claims": [claim], "links": [link], "max_characters": 800}
    )
    integrity = await platform.yanzhang_review_academic_integrity(
        {
            "project_id": project_id,
            "manuscript": "协同机制能够改善信息共享质量。",
            "record_ids": [record_id],
            "evidence_ids": [evidence_id],
            "claims": [claim],
            "links": [link],
        }
    )
    rebuttal = await platform.yanzhang_prepare_rebuttal(
        {
            "project_id": project_id,
            "comments": [{"category": "style", "message": "请进一步说明研究边界。"}],
            "changes": {},
        }
    )
    assert titles["count"] == 3
    assert outline["outline"]["sections"]  # type: ignore[index]
    assert abstract["abstract"]["text"]  # type: ignore[index]
    assert "passed" in integrity["integrity_review"]  # type: ignore[operator]
    assert rebuttal["count"] == 1
