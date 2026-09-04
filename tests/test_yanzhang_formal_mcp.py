"""End-to-end coverage for Yanzhang tools on the formal shared MCP server."""

# Chinese fixture prose intentionally uses full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from gongwen_mcp.server import create_server
from gongwen_mcp.tools import build_context
from gongwen_web.runtime import RuntimeSettings
from gongwen_web.writing_service import YanzhangPlatformService
from yanzhang_academic import ResearchClaim


def _result(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


@pytest.mark.asyncio
async def test_formal_server_runs_persistent_project_to_export_workflow(tmp_path: Path) -> None:
    settings = RuntimeSettings(environment="test")
    context = build_context(settings=settings, data_dir=tmp_path)
    try:
        platform = context.yanzhang_platform
        assert isinstance(platform, YanzhangPlatformService)
        assert platform.storage.path == context.storage.path
        assert platform.artifact_store is context.artifact_store
        assert platform.runtime is settings

        server = create_server(context)
        tools = await server.list_tools()
        assert len(tools) == 71

        _, created_value = await server.call_tool(
            "yanzhang_create_project",
            {
                "name": "服务质效写作项目",
                "description": "正式 MCP 本地闭环",
                "scenario_pack_id": "gongwen",
            },
        )
        created = _result(created_value)
        project_id = cast(str, _result(created["project"])["id"])

        _, material_value = await server.call_tool(
            "yanzhang_add_material",
            {
                "project_id": project_id,
                "title": "核定事实材料",
                "content": "截至2026年8月，完成12项任务，服务群众300人次。",
                "kind": "source",
                "tags": ["已核定"],
            },
        )
        material = _result(material_value)
        material_id = cast(str, _result(material["material"])["id"])

        _, workflow_value = await server.call_tool(
            "yanzhang_create_workflow",
            {
                "project_id": project_id,
                "topic": "提升服务质效",
                "goal": "形成可核验的工作总结",
                "audience": "机关干部",
                "content_type": "工作总结",
                "scenario_pack_id": "gongwen",
                "recipe_id": "work-summary",
                "material_ids": [material_id],
                "requested_exports": ["markdown"],
            },
        )
        workflow = _result(_result(workflow_value)["workflow"])
        workflow_id = cast(str, workflow["id"])

        _, completed_value = await server.call_tool(
            "yanzhang_run_workflow",
            {"project_id": project_id, "workflow_id": workflow_id, "mode": "sync"},
        )
        completed = _result(_result(completed_value)["workflow"])
        assert completed["status"] == "succeeded"
        assert [step["status"] for step in completed["steps"]] == ["succeeded"] * 6
        asset_id = cast(str, completed["output_asset_id"])

        _, asset_value = await server.call_tool(
            "yanzhang_get_asset",
            {"project_id": project_id, "asset_id": asset_id},
        )
        asset = _result(_result(asset_value)["asset"])
        assert "完成12项任务" in cast(str, asset["content"])

        _, export_value = await server.call_tool(
            "yanzhang_export_asset",
            {"project_id": project_id, "asset_id": asset_id, "format": "markdown"},
        )
        exported = _result(export_value)
        assert exported["mime"] == "text/markdown; charset=utf-8"
        assert exported["project_id"] == project_id
        assert exported["asset_id"] == asset_id
        assert exported["revision_id"]
        assert exported["creator"] == "yanzhang_export_asset"
        assert cast(str, exported["resource_uri"]).startswith(
            f"yanzhang://projects/{project_id}/exports/"
        )
        resource_contents = list(await server.read_resource(cast(str, exported["resource_uri"])))
        exported_bytes = cast(bytes, resource_contents[0].content)
        assert exported_bytes.startswith(b"# ")
        assert "完成12项任务" in exported_bytes.decode("utf-8")
        with pytest.raises(ValueError):
            await server.read_resource(f"gongwen://exports/{cast(str, exported['artifact_id'])}")
    finally:
        context.close()

    reopened = build_context(settings=settings, data_dir=tmp_path)
    try:
        server = create_server(reopened)
        _, projects_value = await server.call_tool("yanzhang_list_projects", {})
        projects = _result(projects_value)
        assert [item["id"] for item in projects["items"]] == [project_id]

        _, assets_value = await server.call_tool("yanzhang_list_assets", {"project_id": project_id})
        assets = _result(assets_value)
        assert [item["id"] for item in assets["items"]] == [asset_id]
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_formal_mcp_headlines_apply_adopted_title_and_structure(tmp_path: Path) -> None:
    context = build_context(settings=RuntimeSettings(environment="test"), data_dir=tmp_path)
    try:
        server = create_server(context)
        _, project_value = await server.call_tool(
            "yanzhang_create_project",
            {"name": "标题上下文测试", "scenario_pack_id": "gongwen"},
        )
        project_id = cast(str, _result(_result(project_value)["project"])["id"])
        common: dict[str, object] = {
            "project_id": project_id,
            "topic": "年度工作复盘",
            "goal": "形成面向干部的总结",
            "audience": "机关干部",
            "content_type": "工作总结",
            "scenario_pack_id": "gongwen",
            "recipe_id": "work-summary",
            "selected_title": "以实干实绩答好年度复盘之问",
            "structure_override": [
                {
                    "id": "progress",
                    "title": "一、主要进展",
                    "purpose": "概括已经核定的进展。",
                }
            ],
            "count": 1,
            "formula_ids": ["direct"],
        }

        _, opening_value = await server.call_tool(
            "yanzhang_generate_titles",
            {**common, "headline_kind": "opening"},
        )
        opening = _result(_result(opening_value)["candidate_batch"])
        _, heading_value = await server.call_tool(
            "yanzhang_generate_titles",
            {**common, "headline_kind": "section_heading"},
        )
        heading = _result(_result(heading_value)["candidate_batch"])

        assert cast(str, opening["recommended"]).startswith("围绕以实干实绩答好年度复盘之问")
        assert heading["recommended"] == "一、主要进展"
    finally:
        context.close()


@pytest.mark.asyncio
async def test_formal_yanzhang_errors_do_not_reflect_unknown_fields(tmp_path: Path) -> None:
    context = build_context(
        settings=RuntimeSettings(environment="test"),
        data_dir=tmp_path,
    )
    try:
        server = create_server(context)
        secret = "SECRET-MATERIAL-token-private-fixture"
        with pytest.raises(ToolError) as captured:
            await server.call_tool(
                "yanzhang_create_project",
                {"name": "校验测试", "unexpected": secret},
            )
        assert "invalid_request" in str(captured.value)
        assert secret not in str(captured.value)
        platform = context.yanzhang_platform
        assert isinstance(platform, YanzhangPlatformService)
        assert platform.storage.list_projects() == []
    finally:
        context.close()


@pytest.mark.asyncio
async def test_formal_mcp_passes_journal_profile_into_integrity_review(tmp_path: Path) -> None:
    context = build_context(
        settings=RuntimeSettings(environment="test"),
        data_dir=tmp_path,
    )
    try:
        server = create_server(context)
        _, created_value = await server.call_tool(
            "yanzhang_create_project",
            {"name": "期刊完整性审校", "scenario_pack_id": "academic"},
        )
        project_id = cast(str, _result(_result(created_value)["project"])["id"])

        _, review_value = await server.call_tool(
            "yanzhang_review_academic_integrity",
            {
                "project_id": project_id,
                "manuscript": (
                    "# 一个超过上限的研究题名\n\n## 摘要\n简短摘要。\n\n## 结论\n结论正文。"
                ),
                "journal": {
                    "name": "示例期刊",
                    "required_sections": ["摘要", "研究方法", "结论"],
                    "title_max_characters": 5,
                    "custom_rules": ["逐项核对匿名要求"],
                },
            },
        )
        payload = _result(review_value)
        review = _result(payload["integrity_review"])
        comments = cast(list[dict[str, object]], review["comments"])
        messages = [cast(str, item["message"]) for item in comments]

        assert any("题名共" in message and "上限 5" in message for message in messages)
        assert any("研究方法" in message and "缺少" in message for message in messages)
        assert "期刊自定义要求需人工逐项核对：逐项核对匿名要求" in messages
        assert cast(int, payload["manuscript_words"]) > 0
        assert cast(str, payload["journal_profile_id"]).startswith("journal_")
    finally:
        context.close()


@pytest.mark.asyncio
async def test_formal_mcp_recovers_project_academic_objects_and_resources(
    tmp_path: Path,
) -> None:
    context = build_context(
        settings=RuntimeSettings(environment="test"),
        data_dir=tmp_path,
    )
    try:
        server = create_server(context)
        _, created_value = await server.call_tool(
            "yanzhang_create_project",
            {"name": "学术恢复项目", "scenario_pack_id": "academic"},
        )
        project_id = cast(str, _result(_result(created_value)["project"])["id"])
        _, other_value = await server.call_tool(
            "yanzhang_create_project",
            {"name": "学术隔离项目", "scenario_pack_id": "academic"},
        )
        other_project_id = cast(str, _result(_result(other_value)["project"])["id"])

        _, imported_value = await server.call_tool(
            "yanzhang_import_literature",
            {
                "project_id": project_id,
                "format": "bibtex",
                "content": (
                    "@article{fixture,title={Digital collaboration},"
                    "author={Li, Ming},year={2025},abstract={Collaboration improves sharing}}"
                ),
            },
        )
        record = cast(list[dict[str, Any]], _result(imported_value)["items"])[0]
        record_id = cast(str, record["id"])

        _, evidence_value = await server.call_tool(
            "yanzhang_extract_evidence",
            {
                "project_id": project_id,
                "record_id": record_id,
                "text": "Collaboration improves sharing across departments.",
                "query": "Collaboration",
            },
        )
        evidence = cast(list[dict[str, Any]], _result(evidence_value)["items"])[0]
        evidence_id = cast(str, evidence["id"])

        _, matrix_value = await server.call_tool(
            "yanzhang_build_literature_matrix",
            {
                "project_id": project_id,
                "record_ids": [record_id],
                "evidence_ids": [evidence_id],
            },
        )
        matrix_id = cast(str, _result(_result(matrix_value)["matrix"])["id"])

        claim = {"text": "Collaboration improves sharing across departments."}
        claim_id = ResearchClaim.model_validate(claim).id
        _, audit_value = await server.call_tool(
            "yanzhang_verify_citations",
            {
                "project_id": project_id,
                "record_ids": [record_id],
                "evidence_ids": [evidence_id],
                "claims": [claim],
                "links": [
                    {
                        "claim_id": claim_id,
                        "record_id": record_id,
                        "evidence_id": evidence_id,
                    }
                ],
            },
        )
        audit = _result(_result(audit_value)["citation_audit"])
        link_id = cast(str, cast(list[dict[str, Any]], audit["links"])[0]["id"])

        tool_cases = {
            "yanzhang_list_literature": ({}, record_id),
            "yanzhang_list_evidence": ({}, evidence_id),
            "yanzhang_list_literature_matrices": ({}, matrix_id),
            "yanzhang_list_research_claims": ({}, claim_id),
            "yanzhang_list_citation_links": ({}, link_id),
        }
        for name, (arguments, expected_id) in tool_cases.items():
            _, value = await server.call_tool(name, {"project_id": project_id, **arguments})
            page = _result(value)
            assert page["total"] == 1
            assert cast(list[dict[str, Any]], page["items"])[0]["id"] == expected_id

        get_cases = {
            "yanzhang_get_literature": ({"record_id": record_id}, "record"),
            "yanzhang_get_evidence": ({"evidence_id": evidence_id}, "evidence"),
            "yanzhang_get_literature_matrix": ({"matrix_id": matrix_id}, "matrix"),
            "yanzhang_get_research_claim": ({"claim_id": claim_id}, "claim"),
            "yanzhang_get_citation_link": ({"link_id": link_id}, "link"),
        }
        for name, (arguments, response_key) in get_cases.items():
            _, value = await server.call_tool(name, {"project_id": project_id, **arguments})
            assert _result(_result(value)[response_key])["id"]

        _, isolated_page_value = await server.call_tool(
            "yanzhang_list_literature",
            {"project_id": other_project_id},
        )
        assert _result(isolated_page_value)["items"] == []
        with pytest.raises(ToolError, match="not_found"):
            await server.call_tool(
                "yanzhang_get_literature",
                {"project_id": other_project_id, "record_id": record_id},
            )

        resource_uris = [
            f"yanzhang://projects/{project_id}/academic/literature",
            f"yanzhang://projects/{project_id}/academic/literature/{record_id}",
            f"yanzhang://projects/{project_id}/academic/evidence",
            f"yanzhang://projects/{project_id}/academic/evidence/{evidence_id}",
            f"yanzhang://projects/{project_id}/academic/matrices",
            f"yanzhang://projects/{project_id}/academic/matrices/{matrix_id}",
            f"yanzhang://projects/{project_id}/academic/claims",
            f"yanzhang://projects/{project_id}/academic/claims/{claim_id}",
            f"yanzhang://projects/{project_id}/academic/citation-links",
            f"yanzhang://projects/{project_id}/academic/citation-links/{link_id}",
        ]
        for uri in resource_uris:
            contents = list(await server.read_resource(uri))
            payload = json.loads(cast(str, contents[0].content))
            assert isinstance(payload, dict) and payload
        with pytest.raises(ValueError):
            await server.read_resource(
                f"yanzhang://projects/{other_project_id}/academic/literature/{record_id}"
            )
    finally:
        context.close()
