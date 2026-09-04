"""Offline contract tests for the universal Yanzhang MCP tool group."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import cast

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from gongwen_mcp.writing_schemas import (
    AddMaterialRequest,
    BuildLiteratureMatrixRequest,
    CancelWorkflowRequest,
    CreateProjectRequest,
    CreateVariantRequest,
    CreateWorkflowRequest,
    DeleteProjectTermRequest,
    ExportAssetRequest,
    GenerateTitlesRequest,
    GetCitationLinkRequest,
    GetEvidenceRequest,
    GetLiteratureMatrixRequest,
    GetResearchClaimRequest,
    ImportLiteratureRequest,
    ListCitationLinksRequest,
    ListEvidenceRequest,
    ListLiteratureMatricesRequest,
    ListLiteratureRequest,
    ListProjectTermsRequest,
    ListResearchClaimsRequest,
    ListScenePacksRequest,
    ReviewAssetRequest,
    SearchLiteratureRequest,
    StatusRequest,
    UnifiedSearchRequest,
    UpsertProjectTermRequest,
    VerifyCitationsRequest,
    WritingRequest,
)
from gongwen_mcp.writing_server import (
    YANZHANG_TOOL_NAMES,
    create_writing_server,
    register_writing_tools,
)
from gongwen_mcp.writing_tools import PlatformResult, YanzhangPlatform


class FakePlatform:
    """Record typed requests without using storage, credentials or a network."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, WritingRequest]] = []
        self.fail_operation: str | None = None

    def __getattr__(self, name: str) -> Callable[[WritingRequest], Awaitable[Mapping[str, object]]]:
        if not name.startswith("yanzhang_"):
            raise AttributeError(name)

        async def call(request: WritingRequest) -> PlatformResult:
            self.calls.append((name, request))
            if name == self.fail_operation:
                raise RuntimeError("SECRET-MATERIAL-sk-private-value")
            return {
                "ok": True,
                "operation": name,
                "request_type": type(request).__name__,
            }

        return call


def _server(platform: FakePlatform) -> FastMCP:
    return create_writing_server(cast(YanzhangPlatform, platform))


@pytest.mark.asyncio
async def test_registers_complete_tool_group_with_closed_bounded_schemas() -> None:
    server = _server(FakePlatform())
    tools = await server.list_tools()

    assert tuple(tool.name for tool in tools) == YANZHANG_TOOL_NAMES
    assert len(YANZHANG_TOOL_NAMES) == 45
    assert len(YANZHANG_TOOL_NAMES) == len(set(YANZHANG_TOOL_NAMES))
    assert all(tool.name.startswith("yanzhang_") and tool.name.isascii() for tool in tools)
    assert all(tool.inputSchema["additionalProperties"] is False for tool in tools)

    schemas = {tool.name: tool.inputSchema for tool in tools}
    title_defs = cast(dict[str, dict[str, object]], schemas["yanzhang_generate_titles"]["$defs"])
    assert title_defs["CandidateCount"]["minimum"] == 1
    assert title_defs["CandidateCount"]["maximum"] == 12
    academic_title_defs = cast(
        dict[str, dict[str, object]],
        schemas["yanzhang_suggest_academic_titles"]["$defs"],
    )
    assert academic_title_defs["AcademicCandidateCount"]["maximum"] == 10

    material_defs = cast(dict[str, dict[str, object]], schemas["yanzhang_get_material"]["$defs"])
    assert material_defs["ChunkSize"]["minimum"] == 500
    assert material_defs["ChunkSize"]["maximum"] == 20_000

    import_defs = cast(dict[str, dict[str, object]], schemas["yanzhang_import_literature"]["$defs"])
    assert import_defs["ImportContent"]["maxLength"] == 2_000_000
    verify_defs = cast(dict[str, dict[str, object]], schemas["yanzhang_verify_citations"]["$defs"])
    assert verify_defs["Claims"]["maxItems"] == 500
    assert verify_defs["EvidenceIds"]["minItems"] == 1

    serialized = json.dumps(schemas, ensure_ascii=False).lower()
    assert "api_key" not in serialized
    assert "access_token" not in serialized
    assert "base_url" not in serialized

    status = next(tool for tool in tools if tool.name == "yanzhang_get_status")
    literature = next(tool for tool in tools if tool.name == "yanzhang_search_literature")
    cancel = next(tool for tool in tools if tool.name == "yanzhang_cancel_workflow")
    list_terms = next(tool for tool in tools if tool.name == "yanzhang_list_project_terms")
    delete_term = next(tool for tool in tools if tool.name == "yanzhang_delete_project_term")
    assert status.annotations is not None and status.annotations.readOnlyHint is True
    assert literature.annotations is not None and literature.annotations.openWorldHint is True
    assert literature.annotations.readOnlyHint is False
    assert "cursor" not in schemas["yanzhang_search_literature"]["properties"]
    literature_defs = cast(
        dict[str, dict[str, object]], schemas["yanzhang_search_literature"]["$defs"]
    )
    assert literature_defs["LiteratureQuery"]["maxLength"] == 1_000
    for name in (
        "yanzhang_list_literature",
        "yanzhang_get_literature",
        "yanzhang_list_evidence",
        "yanzhang_get_evidence",
        "yanzhang_list_literature_matrices",
        "yanzhang_get_literature_matrix",
        "yanzhang_list_research_claims",
        "yanzhang_get_research_claim",
        "yanzhang_list_citation_links",
        "yanzhang_get_citation_link",
    ):
        tool = next(item for item in tools if item.name == name)
        assert tool.annotations is not None and tool.annotations.readOnlyHint is True
    assert cancel.annotations is not None and cancel.annotations.readOnlyHint is False
    assert list_terms.annotations is not None and list_terms.annotations.readOnlyHint is True
    assert delete_term.annotations is not None
    assert delete_term.annotations.readOnlyHint is False
    assert delete_term.annotations.destructiveHint is True
    for name in (
        "yanzhang_run_workflow",
        "yanzhang_get_workflow",
        "yanzhang_cancel_workflow",
    ):
        assert "project_id" in schemas[name]["required"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "arguments", "request_type"),
    [
        ("yanzhang_get_status", {}, StatusRequest),
        ("yanzhang_list_scene_packs", {"channel": "document"}, ListScenePacksRequest),
        (
            "yanzhang_create_project",
            {"name": "综合写作项目", "scenario_pack_id": "workplace"},
            CreateProjectRequest,
        ),
        (
            "yanzhang_upsert_project_term",
            {
                "project_id": "project-1",
                "term": "月报",
                "preferred_form": "月度工作报告",
                "discouraged_variants": ["月度报表"],
            },
            UpsertProjectTermRequest,
        ),
        (
            "yanzhang_list_project_terms",
            {"project_id": "project-1", "limit": 10},
            ListProjectTermsRequest,
        ),
        (
            "yanzhang_delete_project_term",
            {"project_id": "project-1", "term_id": "term-1"},
            DeleteProjectTermRequest,
        ),
        (
            "yanzhang_add_material",
            {"project_id": "project-1", "title": "会议记录", "content": "形成三项决定。"},
            AddMaterialRequest,
        ),
        (
            "yanzhang_search",
            {"project_id": "project-1", "query": "三项决定", "scope": "materials"},
            UnifiedSearchRequest,
        ),
        (
            "yanzhang_generate_titles",
            {
                "project_id": "project-1",
                "topic": "年度复盘",
                "goal": "形成管理层汇报",
                "audience": "管理层",
                "content_type": "工作总结",
                "scenario_pack_id": "gongwen",
                "recipe_id": "work-summary",
                "count": 3,
                "formula_ids": ["parallel-triad"],
            },
            GenerateTitlesRequest,
        ),
        (
            "yanzhang_create_workflow",
            {
                "project_id": "project-1",
                "topic": "年度复盘",
                "goal": "形成管理层汇报",
                "audience": "管理层",
                "content_type": "工作总结",
                "scenario_pack_id": "gongwen",
                "recipe_id": "work-summary",
                "requested_exports": ["docx"],
            },
            CreateWorkflowRequest,
        ),
        (
            "yanzhang_cancel_workflow",
            {"project_id": "project-1", "workflow_id": "workflow-1"},
            CancelWorkflowRequest,
        ),
        (
            "yanzhang_create_variant",
            {
                "project_id": "project-1",
                "asset_id": "asset-1",
                "target_channel": "email",
                "live": False,
            },
            CreateVariantRequest,
        ),
        (
            "yanzhang_review_asset",
            {
                "project_id": "project-1",
                "asset_id": "asset-1",
                "checks": ["facts"],
                "model_profile_id": "configured-quality",
                "live": True,
            },
            ReviewAssetRequest,
        ),
        (
            "yanzhang_export_asset",
            {"project_id": "project-1", "asset_id": "asset-1", "format": "docx"},
            ExportAssetRequest,
        ),
        (
            "yanzhang_import_literature",
            {
                "project_id": "project-1",
                "content": "@article{fixture, title={Offline Fixture}}",
                "format": "bibtex",
            },
            ImportLiteratureRequest,
        ),
        (
            "yanzhang_list_literature",
            {"project_id": "project-1", "query": "research", "limit": 10},
            ListLiteratureRequest,
        ),
        (
            "yanzhang_list_evidence",
            {"project_id": "project-1", "record_id": "ref-1"},
            ListEvidenceRequest,
        ),
        (
            "yanzhang_get_evidence",
            {"project_id": "project-1", "evidence_id": "evidence-1"},
            GetEvidenceRequest,
        ),
        (
            "yanzhang_build_literature_matrix",
            {"project_id": "project-1", "record_ids": ["ref-1"], "query": "研究主题"},
            BuildLiteratureMatrixRequest,
        ),
        (
            "yanzhang_list_literature_matrices",
            {"project_id": "project-1", "limit": 10},
            ListLiteratureMatricesRequest,
        ),
        (
            "yanzhang_get_literature_matrix",
            {"project_id": "project-1", "matrix_id": "matrix-1"},
            GetLiteratureMatrixRequest,
        ),
        (
            "yanzhang_list_research_claims",
            {"project_id": "project-1", "limit": 10},
            ListResearchClaimsRequest,
        ),
        (
            "yanzhang_get_research_claim",
            {"project_id": "project-1", "claim_id": "claim-1"},
            GetResearchClaimRequest,
        ),
        (
            "yanzhang_list_citation_links",
            {"project_id": "project-1", "evidence_id": "evidence-1"},
            ListCitationLinksRequest,
        ),
        (
            "yanzhang_get_citation_link",
            {"project_id": "project-1", "link_id": "link-1"},
            GetCitationLinkRequest,
        ),
        (
            "yanzhang_verify_citations",
            {
                "project_id": "project-1",
                "record_ids": ["ref-1"],
                "evidence_ids": ["evidence-1"],
                "claims": [{"text": "该结论得到证据支持。"}],
            },
            VerifyCitationsRequest,
        ),
    ],
)
async def test_tools_delegate_typed_requests(
    name: str,
    arguments: dict[str, object],
    request_type: type[WritingRequest],
) -> None:
    platform = FakePlatform()
    server = _server(platform)

    call_result = await server.call_tool(name, arguments)
    _, result = cast(tuple[object, dict[str, object]], call_result)

    assert result["ok"] is True
    assert platform.calls[-1][0] == name
    assert isinstance(platform.calls[-1][1], request_type)
    if name == "yanzhang_generate_titles":
        title_request = cast(GenerateTitlesRequest, platform.calls[-1][1])
        assert title_request.formula_ids == ["parallel-triad"]


@pytest.mark.asyncio
async def test_registration_composes_with_existing_tools_without_count_assumptions() -> None:
    server = FastMCP("combined-fixture")

    @server.tool(name="existing_tool")
    async def existing_tool() -> dict[str, object]:
        return {"ok": True}

    names = register_writing_tools(server, cast(YanzhangPlatform, FakePlatform()))
    registered = {tool.name for tool in await server.list_tools()}

    assert names == YANZHANG_TOOL_NAMES
    assert "existing_tool" in registered
    assert set(YANZHANG_TOOL_NAMES) <= registered


@pytest.mark.asyncio
async def test_extra_arguments_and_validation_fail_before_platform_side_effects() -> None:
    platform = FakePlatform()
    server = _server(platform)

    with pytest.raises(ToolError) as extra_error:
        await server.call_tool(
            "yanzhang_create_project",
            {
                "name": "项目",
                "bad_field": "SECRET-MATERIAL-sk-private-value",
            },
        )
    assert "未定义字段" in str(extra_error.value)
    assert "SECRET-MATERIAL" not in str(extra_error.value)
    assert platform.calls == []

    with pytest.raises(ToolError) as type_error:
        await server.call_tool(
            "yanzhang_create_project",
            {"name": {"secret": "SECRET-MATERIAL-sk-private-value"}},
        )
    assert "invalid_request" in str(type_error.value)
    assert "SECRET-MATERIAL" not in str(type_error.value)
    assert platform.calls == []


@pytest.mark.asyncio
async def test_backend_errors_and_invalid_results_are_stable_and_non_reflective() -> None:
    platform = FakePlatform()
    platform.fail_operation = "yanzhang_get_status"
    server = _server(platform)

    with pytest.raises(ToolError) as backend_error:
        await server.call_tool("yanzhang_get_status", {})
    assert "internal_error" in str(backend_error.value)
    assert "SECRET-MATERIAL" not in str(backend_error.value)


def test_request_models_reject_duplicates_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        GenerateTitlesRequest(
            project_id="project-1",
            topic="主题",
            goal="目标",
            audience="读者",
            content_type="工作总结",
            scenario_pack_id="gongwen",
            recipe_id="work-summary",
            material_ids=["material-1", "material-1"],
        )

    with pytest.raises(ValidationError):
        UnifiedSearchRequest(
            project_id="project-1",
            query="主题",
            scope="all",
            unexpected=True,  # type: ignore[call-arg]
        )

    with pytest.raises(ValidationError):
        SearchLiteratureRequest(project_id="project-1", query="研" * 1_001)

    with pytest.raises(ValidationError):
        GenerateTitlesRequest(
            project_id="project-1",
            topic="主题",
            goal="目标",
            audience="读者",
            content_type="工作总结",
            scenario_pack_id="gongwen",
            recipe_id="work-summary",
            count=13,
        )

    with pytest.raises(ValidationError):
        ExportAssetRequest(
            project_id="project-1",
            asset_id="asset-1",
            format="markdown",
            template_id="brief",
        )
