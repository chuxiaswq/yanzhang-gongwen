"""FastMCP registration for the provider-neutral Yanzhang writing platform."""

# Chinese punctuation is intentional in public tool metadata.
# ruff: noqa: RUF001

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ContentBlock, ToolAnnotations
from mcp.types import Tool as MCPTool
from pydantic import BaseModel, Field, ValidationError

from gongwen_mcp.writing_schemas import (
    AddMaterialRequest,
    AssetExportFormat,
    AssetTemplateId,
    BuildLiteratureMatrixRequest,
    CancelWorkflowRequest,
    CreateAcademicOutlineRequest,
    CreateProjectRequest,
    CreateVariantRequest,
    CreateWorkflowRequest,
    DeleteProjectTermRequest,
    DraftAbstractRequest,
    ExportAssetRequest,
    ExtractEvidenceRequest,
    FormatBibliographyRequest,
    GenerateTitlesRequest,
    GetAssetRequest,
    GetCitationLinkRequest,
    GetEvidenceRequest,
    GetLiteratureMatrixRequest,
    GetLiteratureRequest,
    GetMaterialRequest,
    GetProjectRequest,
    GetResearchClaimRequest,
    GetScenePackRequest,
    GetWorkflowRequest,
    ImportLiteratureRequest,
    ListAssetsRequest,
    ListCitationLinksRequest,
    ListEvidenceRequest,
    ListLiteratureMatricesRequest,
    ListLiteratureRequest,
    ListMaterialsRequest,
    ListProjectsRequest,
    ListProjectTermsRequest,
    ListResearchClaimsRequest,
    ListRevisionsRequest,
    ListScenePacksRequest,
    LiteratureImportFormat,
    LiteratureProvider,
    PrepareRebuttalRequest,
    ReviewAcademicIntegrityRequest,
    ReviewAssetRequest,
    ReviewCheck,
    RunWorkflowRequest,
    SearchLiteratureRequest,
    SearchScope,
    StatusRequest,
    SuggestAcademicTitlesRequest,
    UnifiedSearchRequest,
    UpsertProjectTermRequest,
    VerifyCitationsRequest,
    WorkflowMode,
    WorkflowResumeStep,
)
from gongwen_mcp.writing_tools import (
    YanzhangMCPContext,
    YanzhangPlatform,
    YanzhangToolError,
    YanzhangWritingTools,
)
from yanzhang_academic.models import (
    CitationStyle,
    ClaimCitationLink,
    JournalProfile,
    ResearchClaim,
    ReviewComment,
)
from yanzhang_core.models import AssetStatus, Channel, KnowledgeKind, WritingStructureSection
from yanzhang_core.packs import HeadlineKind, ScenarioPackId

type ProjectId = Annotated[str, Field(min_length=1, max_length=128)]
type ResourceId = Annotated[str, Field(min_length=1, max_length=200)]
type ShortId = Annotated[str, Field(min_length=1, max_length=128)]
type ProjectName = Annotated[str, Field(min_length=1, max_length=200)]
type Topic = Annotated[str, Field(min_length=1, max_length=300)]
type Goal = Annotated[str, Field(min_length=1, max_length=2_000)]
type Audience = Annotated[str, Field(min_length=1, max_length=500)]
type Query = Annotated[str, Field(min_length=1, max_length=2_000)]
type LiteratureQuery = Annotated[str, Field(min_length=1, max_length=1_000)]
type MaterialContent = Annotated[str, Field(min_length=1, max_length=500_000)]
type ImportContent = Annotated[str, Field(min_length=1, max_length=2_000_000)]
type Manuscript = Annotated[str, Field(min_length=1, max_length=1_000_000)]
type PageLimit = Annotated[int, Field(ge=1, le=100)]
type SearchLimit = Annotated[int, Field(ge=1, le=50)]
type PageOffset = Annotated[int, Field(ge=0, le=1_000_000)]
type ChunkOffset = Annotated[int, Field(ge=0, le=500_000)]
type ChunkSize = Annotated[int, Field(ge=500, le=20_000)]
type CandidateCount = Annotated[int, Field(ge=1, le=12)]
type AcademicCandidateCount = Annotated[int, Field(ge=1, le=10)]
type SnippetCount = Annotated[int, Field(ge=1, le=100)]
type AbstractLength = Annotated[int, Field(ge=100, le=20_000)]
type RecordIds = Annotated[list[str], Field(min_length=1, max_length=1_000)]
type EvidenceIds = Annotated[list[str], Field(min_length=1, max_length=1_000)]
type Claims = Annotated[list[ResearchClaim], Field(min_length=1, max_length=500)]
type ReviewComments = Annotated[list[ReviewComment], Field(min_length=1, max_length=200)]
type StructureOverride = Annotated[list[WritingStructureSection], Field(max_length=24)]

YANZHANG_TOOL_NAMES: tuple[str, ...] = (
    "yanzhang_get_status",
    "yanzhang_list_scene_packs",
    "yanzhang_get_scene_pack",
    "yanzhang_create_project",
    "yanzhang_list_projects",
    "yanzhang_get_project",
    "yanzhang_upsert_project_term",
    "yanzhang_list_project_terms",
    "yanzhang_delete_project_term",
    "yanzhang_add_material",
    "yanzhang_list_materials",
    "yanzhang_get_material",
    "yanzhang_search",
    "yanzhang_generate_titles",
    "yanzhang_create_workflow",
    "yanzhang_run_workflow",
    "yanzhang_get_workflow",
    "yanzhang_cancel_workflow",
    "yanzhang_list_assets",
    "yanzhang_get_asset",
    "yanzhang_create_variant",
    "yanzhang_list_revisions",
    "yanzhang_review_asset",
    "yanzhang_export_asset",
    "yanzhang_search_literature",
    "yanzhang_import_literature",
    "yanzhang_list_literature",
    "yanzhang_get_literature",
    "yanzhang_list_evidence",
    "yanzhang_get_evidence",
    "yanzhang_extract_evidence",
    "yanzhang_build_literature_matrix",
    "yanzhang_list_literature_matrices",
    "yanzhang_get_literature_matrix",
    "yanzhang_list_research_claims",
    "yanzhang_get_research_claim",
    "yanzhang_list_citation_links",
    "yanzhang_get_citation_link",
    "yanzhang_verify_citations",
    "yanzhang_format_bibliography",
    "yanzhang_suggest_academic_titles",
    "yanzhang_create_academic_outline",
    "yanzhang_draft_abstract",
    "yanzhang_review_academic_integrity",
    "yanzhang_prepare_rebuttal",
)


class _WritingFastMCP(FastMCP):
    """Standalone server with closed schemas and non-reflective errors."""

    async def list_tools(self) -> list[MCPTool]:
        tools = await super().list_tools()
        return [
            tool.model_copy(
                update={
                    "inputSchema": {
                        **tool.inputSchema,
                        "additionalProperties": False,
                    }
                }
            )
            for tool in tools
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        registered = self._tool_manager.get_tool(name)
        if registered is not None:
            properties = registered.parameters.get("properties", {})
            allowed = set(properties) if isinstance(properties, dict) else set()
            extra_count = len(set(arguments).difference(allowed))
            if extra_count:
                raise ToolError(f"invalid_request: 请求包含 {extra_count} 个未定义字段") from None
        try:
            return await super().call_tool(name, arguments)
        except ToolError as exc:
            cause = exc.__cause__
            if isinstance(cause, YanzhangToolError):
                raise ToolError(f"{cause.code}: {cause.message}") from None
            if isinstance(cause, ValidationError):
                raise ToolError(f"invalid_request: {_validation_details(cause)}") from None
            raise ToolError("internal_error: 工具调用异常，请检查工具名和参数类型") from None


def register_writing_tools(
    server: FastMCP,
    platform: YanzhangPlatform | YanzhangMCPContext,
) -> tuple[str, ...]:
    """Register the universal writing tool group on an existing FastMCP server."""

    context = platform if isinstance(platform, YanzhangMCPContext) else YanzhangMCPContext(platform)
    tools = YanzhangWritingTools(context)

    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    mutate = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
    mutate_network = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
    destructive = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    )

    @server.tool(
        name="yanzhang_get_status",
        title="查看砚章平台状态",
        description="查看通用写作、项目、工作流、学术研究和导出能力，不返回服务端密钥。",
        annotations=read_only,
    )
    async def yanzhang_get_status() -> dict[str, object]:
        return await tools.yanzhang_get_status(_request(StatusRequest))

    @server.tool(
        name="yanzhang_list_scene_packs",
        title="列出写作场景包",
        description="列出公文、职场、媒体和学术场景包及其配方，可按渠道或文种筛选。",
        annotations=read_only,
    )
    async def yanzhang_list_scene_packs(
        channel: Channel | None = None,
        content_type: str | None = None,
    ) -> dict[str, object]:
        return await tools.yanzhang_list_scene_packs(
            _request(ListScenePacksRequest, channel=channel, content_type=content_type)
        )

    @server.tool(
        name="yanzhang_get_scene_pack",
        title="读取写作场景包",
        description="读取一个场景包的受众、配方、结构和事实约束。",
        annotations=read_only,
    )
    async def yanzhang_get_scene_pack(pack_id: ScenarioPackId) -> dict[str, object]:
        return await tools.yanzhang_get_scene_pack(_request(GetScenePackRequest, pack_id=pack_id))

    @server.tool(
        name="yanzhang_create_project",
        title="创建写作项目",
        description="创建隔离的写作项目，用于组织资料、工作流、资产和学术记录。",
        annotations=mutate,
    )
    async def yanzhang_create_project(
        name: ProjectName,
        description: str = "",
        scenario_pack_id: ScenarioPackId = "gongwen",
        tags: list[str] | None = None,
    ) -> dict[str, object]:
        return await tools.yanzhang_create_project(
            _request(
                CreateProjectRequest,
                name=name,
                description=description,
                scenario_pack_id=scenario_pack_id,
                tags=tags or [],
            )
        )

    @server.tool(
        name="yanzhang_list_projects",
        title="列出写作项目",
        description="分页列出项目，可按文本或场景包筛选。",
        annotations=read_only,
    )
    async def yanzhang_list_projects(
        query: str | None = None,
        scenario_pack_id: ScenarioPackId | None = None,
        limit: PageLimit = 20,
        offset: PageOffset = 0,
    ) -> dict[str, object]:
        return await tools.yanzhang_list_projects(
            _request(
                ListProjectsRequest,
                query=query,
                scenario_pack_id=scenario_pack_id,
                limit=limit,
                offset=offset,
            )
        )

    @server.tool(
        name="yanzhang_get_project",
        title="读取写作项目",
        description="读取项目摘要与其资源统计。",
        annotations=read_only,
    )
    async def yanzhang_get_project(project_id: ProjectId) -> dict[str, object]:
        return await tools.yanzhang_get_project(_request(GetProjectRequest, project_id=project_id))

    @server.tool(
        name="yanzhang_upsert_project_term",
        title="保存项目术语",
        description="新增或更新项目首选表达和不建议使用的变体，供术语审校直接使用。",
        annotations=mutate,
    )
    async def yanzhang_upsert_project_term(
        project_id: ProjectId,
        term: Annotated[str, Field(min_length=1, max_length=200)],
        preferred_form: Annotated[str, Field(min_length=1, max_length=200)],
        description: Annotated[str, Field(max_length=500)] = "",
        discouraged_variants: list[str] | None = None,
        term_id: ShortId | None = None,
    ) -> dict[str, object]:
        return await tools.yanzhang_upsert_project_term(
            _request(
                UpsertProjectTermRequest,
                project_id=project_id,
                term_id=term_id,
                term=term,
                preferred_form=preferred_form,
                description=description,
                discouraged_variants=discouraged_variants or [],
            )
        )

    @server.tool(
        name="yanzhang_list_project_terms",
        title="列出项目术语",
        description="分页读取项目术语、首选表达和不建议使用的变体。",
        annotations=read_only,
    )
    async def yanzhang_list_project_terms(
        project_id: ProjectId,
        limit: PageLimit = 20,
        offset: PageOffset = 0,
    ) -> dict[str, object]:
        return await tools.yanzhang_list_project_terms(
            _request(
                ListProjectTermsRequest,
                project_id=project_id,
                limit=limit,
                offset=offset,
            )
        )

    @server.tool(
        name="yanzhang_delete_project_term",
        title="删除项目术语",
        description="按项目和术语标识删除一条术语规则。",
        annotations=destructive,
    )
    async def yanzhang_delete_project_term(
        project_id: ProjectId,
        term_id: ShortId,
    ) -> dict[str, object]:
        return await tools.yanzhang_delete_project_term(
            _request(DeleteProjectTermRequest, project_id=project_id, term_id=term_id)
        )

    @server.tool(
        name="yanzhang_add_material",
        title="添加项目资料",
        description="向项目资料库写入来源、风格参考、既有稿件、术语或笔记。",
        annotations=mutate,
    )
    async def yanzhang_add_material(
        project_id: ProjectId,
        title: Annotated[str, Field(min_length=1, max_length=500)],
        content: MaterialContent,
        kind: KnowledgeKind = "source",
        source_url: str = "",
        tags: list[str] | None = None,
        material_id: ShortId | None = None,
    ) -> dict[str, object]:
        return await tools.yanzhang_add_material(
            _request(
                AddMaterialRequest,
                project_id=project_id,
                title=title,
                content=content,
                kind=kind,
                source_url=source_url,
                tags=tags or [],
                material_id=material_id,
            )
        )

    @server.tool(
        name="yanzhang_list_materials",
        title="列出项目资料",
        description="按资料类型和标签分页列出项目资料。",
        annotations=read_only,
    )
    async def yanzhang_list_materials(
        project_id: ProjectId,
        kind: KnowledgeKind | None = None,
        tags: list[str] | None = None,
        limit: PageLimit = 20,
        offset: PageOffset = 0,
    ) -> dict[str, object]:
        return await tools.yanzhang_list_materials(
            _request(
                ListMaterialsRequest,
                project_id=project_id,
                kind=kind,
                tags=tags or [],
                limit=limit,
                offset=offset,
            )
        )

    @server.tool(
        name="yanzhang_get_material",
        title="分块读取项目资料",
        description="按字符偏移分块读取资料全文，适合上下文受限的 MCP 客户端。",
        annotations=read_only,
    )
    async def yanzhang_get_material(
        project_id: ProjectId,
        material_id: ShortId,
        chunk_offset: ChunkOffset = 0,
        chunk_size: ChunkSize = 8_000,
    ) -> dict[str, object]:
        return await tools.yanzhang_get_material(
            _request(
                GetMaterialRequest,
                project_id=project_id,
                material_id=material_id,
                chunk_offset=chunk_offset,
                chunk_size=chunk_size,
            )
        )

    @server.tool(
        name="yanzhang_search",
        title="检索项目知识与资产",
        description="在项目资料、写作资产和学术记录中统一检索，结果保持项目隔离。",
        annotations=read_only,
    )
    async def yanzhang_search(
        project_id: ProjectId,
        query: Query,
        scope: SearchScope = "all",
        tags: list[str] | None = None,
        limit: PageLimit = 20,
        offset: PageOffset = 0,
    ) -> dict[str, object]:
        return await tools.yanzhang_search(
            _request(
                UnifiedSearchRequest,
                project_id=project_id,
                query=query,
                scope=scope,
                tags=tags or [],
                limit=limit,
                offset=offset,
            )
        )

    @server.tool(
        name="yanzhang_generate_titles",
        title="生成多场景标题候选",
        description=(
            "基于任务简报与场景公式生成可比较候选；已采用标题和自定义结构为非标题表达"
            "提供上下文，明确关联的事实资料只参与保守的焦点兜底与事实评分。"
        ),
        annotations=mutate_network,
    )
    async def yanzhang_generate_titles(
        project_id: ProjectId,
        topic: Topic,
        goal: Goal,
        audience: Audience,
        content_type: Annotated[str, Field(min_length=1, max_length=100)],
        scenario_pack_id: ScenarioPackId,
        recipe_id: Annotated[str, Field(min_length=1, max_length=100)],
        channel: Channel = "document",
        tone: str = "准确、清晰、得体",
        length: str = "standard",
        target_language: str = "zh-CN",
        constraints: list[str] | None = None,
        keywords: list[str] | None = None,
        material_ids: list[str] | None = None,
        model_profile_id: str | None = None,
        selected_title: Annotated[str, Field(min_length=1, max_length=300)] | None = None,
        structure_override: StructureOverride | None = None,
        count: CandidateCount = 8,
        headline_kind: HeadlineKind = "title",
        formula_ids: list[str] | None = None,
    ) -> dict[str, object]:
        return await tools.yanzhang_generate_titles(
            _request(
                GenerateTitlesRequest,
                project_id=project_id,
                topic=topic,
                goal=goal,
                audience=audience,
                channel=channel,
                content_type=content_type,
                scenario_pack_id=scenario_pack_id,
                recipe_id=recipe_id,
                tone=tone,
                length=length,
                target_language=target_language,
                constraints=constraints or [],
                keywords=keywords or [],
                material_ids=material_ids or [],
                model_profile_id=model_profile_id,
                selected_title=selected_title,
                structure_override=structure_override or [],
                count=count,
                headline_kind=headline_kind,
                formula_ids=formula_ids or [],
            )
        )

    @server.tool(
        name="yanzhang_create_workflow",
        title="创建写作工作流",
        description="用结构化写作任务创建可查询、可恢复的工作流。",
        annotations=mutate,
    )
    async def yanzhang_create_workflow(
        project_id: ProjectId,
        topic: Topic,
        goal: Goal,
        audience: Audience,
        content_type: Annotated[str, Field(min_length=1, max_length=100)],
        scenario_pack_id: ScenarioPackId,
        recipe_id: Annotated[str, Field(min_length=1, max_length=100)],
        channel: Channel = "document",
        tone: str = "准确、清晰、得体",
        length: str = "standard",
        target_language: str = "zh-CN",
        constraints: list[str] | None = None,
        keywords: list[str] | None = None,
        material_ids: list[str] | None = None,
        model_profile_id: str | None = None,
        brief_id: ShortId | None = None,
        selected_title: Annotated[str, Field(min_length=1, max_length=300)] | None = None,
        structure_override: StructureOverride | None = None,
        auto_review: bool = True,
        requested_exports: list[AssetExportFormat] | None = None,
    ) -> dict[str, object]:
        return await tools.yanzhang_create_workflow(
            _request(
                CreateWorkflowRequest,
                project_id=project_id,
                topic=topic,
                goal=goal,
                audience=audience,
                channel=channel,
                content_type=content_type,
                scenario_pack_id=scenario_pack_id,
                recipe_id=recipe_id,
                tone=tone,
                length=length,
                target_language=target_language,
                constraints=constraints or [],
                keywords=keywords or [],
                material_ids=material_ids or [],
                model_profile_id=model_profile_id,
                brief_id=brief_id,
                selected_title=selected_title,
                structure_override=structure_override or [],
                auto_review=auto_review,
                requested_exports=requested_exports or [],
            )
        )

    @server.tool(
        name="yanzhang_run_workflow",
        title="运行或恢复写作工作流",
        description="同步或后台运行工作流，并可从明确步骤恢复。",
        annotations=mutate_network,
    )
    async def yanzhang_run_workflow(
        project_id: ProjectId,
        workflow_id: ShortId,
        mode: WorkflowMode = "sync",
        resume_from: WorkflowResumeStep | None = None,
    ) -> dict[str, object]:
        return await tools.yanzhang_run_workflow(
            _request(
                RunWorkflowRequest,
                project_id=project_id,
                workflow_id=workflow_id,
                mode=mode,
                resume_from=resume_from,
            )
        )

    @server.tool(
        name="yanzhang_get_workflow",
        title="查询写作工作流",
        description="读取工作流状态、步骤进度、错误摘要和输出资产标识。",
        annotations=read_only,
    )
    async def yanzhang_get_workflow(
        project_id: ProjectId,
        workflow_id: ShortId,
    ) -> dict[str, object]:
        return await tools.yanzhang_get_workflow(
            _request(GetWorkflowRequest, project_id=project_id, workflow_id=workflow_id)
        )

    @server.tool(
        name="yanzhang_cancel_workflow",
        title="取消写作工作流",
        description="请求取消尚未完成的工作流并返回最新状态。",
        annotations=mutate,
    )
    async def yanzhang_cancel_workflow(
        project_id: ProjectId,
        workflow_id: ShortId,
    ) -> dict[str, object]:
        return await tools.yanzhang_cancel_workflow(
            _request(CancelWorkflowRequest, project_id=project_id, workflow_id=workflow_id)
        )

    @server.tool(
        name="yanzhang_list_assets",
        title="列出写作资产",
        description="分页列出项目主稿和渠道变体，可按状态与文种筛选。",
        annotations=read_only,
    )
    async def yanzhang_list_assets(
        project_id: ProjectId,
        status: AssetStatus | None = None,
        content_type: str | None = None,
        limit: PageLimit = 20,
        offset: PageOffset = 0,
    ) -> dict[str, object]:
        return await tools.yanzhang_list_assets(
            _request(
                ListAssetsRequest,
                project_id=project_id,
                status=status,
                content_type=content_type,
                limit=limit,
                offset=offset,
            )
        )

    @server.tool(
        name="yanzhang_get_asset",
        title="分块读取写作资产",
        description="读取指定资产或修订版本，并按字符偏移返回正文块。",
        annotations=read_only,
    )
    async def yanzhang_get_asset(
        project_id: ProjectId,
        asset_id: ShortId,
        revision: int | None = None,
        chunk_offset: ChunkOffset = 0,
        chunk_size: ChunkSize = 8_000,
    ) -> dict[str, object]:
        return await tools.yanzhang_get_asset(
            _request(
                GetAssetRequest,
                project_id=project_id,
                asset_id=asset_id,
                revision=revision,
                chunk_offset=chunk_offset,
                chunk_size=chunk_size,
            )
        )

    @server.tool(
        name="yanzhang_create_variant",
        title="创建渠道内容变体",
        description="从既有资产生成邮件、会议、演示、网页、社交或学术渠道变体。",
        annotations=mutate_network,
    )
    async def yanzhang_create_variant(
        project_id: ProjectId,
        asset_id: ShortId,
        target_channel: Channel,
        instruction: str = "",
        source_revision: int | None = None,
        model_profile_id: str | None = None,
        live: bool = False,
    ) -> dict[str, object]:
        return await tools.yanzhang_create_variant(
            _request(
                CreateVariantRequest,
                project_id=project_id,
                asset_id=asset_id,
                target_channel=target_channel,
                instruction=instruction,
                source_revision=source_revision,
                model_profile_id=model_profile_id,
                live=live,
            )
        )

    @server.tool(
        name="yanzhang_list_revisions",
        title="列出资产修订历史",
        description="分页列出一个写作资产的不可变修订版本。",
        annotations=read_only,
    )
    async def yanzhang_list_revisions(
        project_id: ProjectId,
        asset_id: ShortId,
        limit: PageLimit = 20,
        offset: PageOffset = 0,
    ) -> dict[str, object]:
        return await tools.yanzhang_list_revisions(
            _request(
                ListRevisionsRequest,
                project_id=project_id,
                asset_id=asset_id,
                limit=limit,
                offset=offset,
            )
        )

    @server.tool(
        name="yanzhang_review_asset",
        title="审校写作资产",
        description="按结构、风格、事实、引用和术语检查资产并返回可定位问题。",
        annotations=mutate_network,
    )
    async def yanzhang_review_asset(
        project_id: ProjectId,
        asset_id: ShortId,
        checks: list[ReviewCheck] | None = None,
        material_ids: list[str] | None = None,
        model_profile_id: str | None = None,
        live: bool = False,
    ) -> dict[str, object]:
        return await tools.yanzhang_review_asset(
            _request(
                ReviewAssetRequest,
                project_id=project_id,
                asset_id=asset_id,
                checks=checks or ["structure", "style", "facts", "citations"],
                material_ids=material_ids or [],
                model_profile_id=model_profile_id,
                live=live,
            )
        )

    @server.tool(
        name="yanzhang_export_asset",
        title="导出写作资产",
        description="把指定资产版本导出为 Word、Markdown、文本、HTML 或 PDF 工件。",
        annotations=mutate,
    )
    async def yanzhang_export_asset(
        project_id: ProjectId,
        asset_id: ShortId,
        format: AssetExportFormat = "docx",
        revision: int | None = None,
        template_id: AssetTemplateId | None = None,
        filename: str | None = None,
    ) -> dict[str, object]:
        return await tools.yanzhang_export_asset(
            _request(
                ExportAssetRequest,
                project_id=project_id,
                asset_id=asset_id,
                format=format,
                revision=revision,
                template_id=template_id,
                filename=filename,
            )
        )

    _register_academic_tools(server, tools, read_only, mutate, mutate_network)
    return YANZHANG_TOOL_NAMES


def _register_academic_tools(
    server: FastMCP,
    tools: YanzhangWritingTools,
    read_only: ToolAnnotations,
    mutate: ToolAnnotations,
    mutate_network: ToolAnnotations,
) -> None:
    @server.tool(
        name="yanzhang_search_literature",
        title="检索学术文献",
        description="通过 Crossref、OpenAlex 或 arXiv 检索文献元数据并保存到当前项目。",
        annotations=mutate_network,
    )
    async def yanzhang_search_literature(
        project_id: ProjectId,
        query: LiteratureQuery,
        provider: LiteratureProvider = "crossref",
        limit: SearchLimit = 10,
    ) -> dict[str, object]:
        return await tools.yanzhang_search_literature(
            _request(
                SearchLiteratureRequest,
                project_id=project_id,
                query=query,
                provider=provider,
                limit=limit,
            )
        )

    @server.tool(
        name="yanzhang_import_literature",
        title="导入学术文献",
        description="把 BibTeX、RIS 或 CSL-JSON 元数据解析并保存到项目文献库。",
        annotations=mutate,
    )
    async def yanzhang_import_literature(
        project_id: ProjectId,
        content: ImportContent,
        format: LiteratureImportFormat,
        tags: list[str] | None = None,
    ) -> dict[str, object]:
        return await tools.yanzhang_import_literature(
            _request(
                ImportLiteratureRequest,
                project_id=project_id,
                content=content,
                format=format,
                tags=tags or [],
            )
        )

    @server.tool(
        name="yanzhang_list_literature",
        title="列出项目学术文献",
        description="分页列出或检索项目已保存的标准化文献记录，便于刷新后恢复工作。",
        annotations=read_only,
    )
    async def yanzhang_list_literature(
        project_id: ProjectId,
        query: str | None = None,
        include_abstract: bool = False,
        limit: PageLimit = 20,
        offset: PageOffset = 0,
    ) -> dict[str, object]:
        return await tools.yanzhang_list_literature(
            _request(
                ListLiteratureRequest,
                project_id=project_id,
                query=query,
                include_abstract=include_abstract,
                limit=limit,
                offset=offset,
            )
        )

    @server.tool(
        name="yanzhang_get_literature",
        title="读取学术文献记录",
        description="读取一条已导入文献的标准化元数据和来源追踪信息。",
        annotations=read_only,
    )
    async def yanzhang_get_literature(
        project_id: ProjectId,
        record_id: ResourceId,
        include_abstract: bool = True,
    ) -> dict[str, object]:
        return await tools.yanzhang_get_literature(
            _request(
                GetLiteratureRequest,
                project_id=project_id,
                record_id=record_id,
                include_abstract=include_abstract,
            )
        )

    @server.tool(
        name="yanzhang_list_evidence",
        title="列出项目证据片段",
        description="分页列出项目证据片段，可按文献记录筛选。",
        annotations=read_only,
    )
    async def yanzhang_list_evidence(
        project_id: ProjectId,
        record_id: ResourceId | None = None,
        limit: PageLimit = 20,
        offset: PageOffset = 0,
    ) -> dict[str, object]:
        return await tools.yanzhang_list_evidence(
            _request(
                ListEvidenceRequest,
                project_id=project_id,
                record_id=record_id,
                limit=limit,
                offset=offset,
            )
        )

    @server.tool(
        name="yanzhang_get_evidence",
        title="读取项目证据片段",
        description="按项目和证据标识读取带来源谱系的证据片段。",
        annotations=read_only,
    )
    async def yanzhang_get_evidence(
        project_id: ProjectId,
        evidence_id: ResourceId,
    ) -> dict[str, object]:
        return await tools.yanzhang_get_evidence(
            _request(
                GetEvidenceRequest,
                project_id=project_id,
                evidence_id=evidence_id,
            )
        )

    @server.tool(
        name="yanzhang_extract_evidence",
        title="提取文献证据片段",
        description="从指定文献正文提取带来源哈希和位置的证据片段。",
        annotations=mutate,
    )
    async def yanzhang_extract_evidence(
        project_id: ProjectId,
        record_id: ResourceId,
        text: MaterialContent,
        query: str = "",
        max_snippets: SnippetCount = 20,
    ) -> dict[str, object]:
        return await tools.yanzhang_extract_evidence(
            _request(
                ExtractEvidenceRequest,
                project_id=project_id,
                record_id=record_id,
                text=text,
                query=query,
                max_snippets=max_snippets,
            )
        )

    @server.tool(
        name="yanzhang_build_literature_matrix",
        title="构建文献矩阵",
        description="按研究对象、方法、发现、局限和主题比较已导入文献。",
        annotations=mutate,
    )
    async def yanzhang_build_literature_matrix(
        project_id: ProjectId,
        record_ids: RecordIds,
        evidence_ids: list[str] | None = None,
        query: str = "",
    ) -> dict[str, object]:
        return await tools.yanzhang_build_literature_matrix(
            _request(
                BuildLiteratureMatrixRequest,
                project_id=project_id,
                record_ids=record_ids,
                evidence_ids=evidence_ids or [],
                query=query,
            )
        )

    @server.tool(
        name="yanzhang_list_literature_matrices",
        title="列出项目文献矩阵",
        description="分页列出项目中已持久化的文献比较矩阵。",
        annotations=read_only,
    )
    async def yanzhang_list_literature_matrices(
        project_id: ProjectId,
        limit: PageLimit = 20,
        offset: PageOffset = 0,
    ) -> dict[str, object]:
        return await tools.yanzhang_list_literature_matrices(
            _request(
                ListLiteratureMatricesRequest,
                project_id=project_id,
                limit=limit,
                offset=offset,
            )
        )

    @server.tool(
        name="yanzhang_get_literature_matrix",
        title="读取项目文献矩阵",
        description="按项目和矩阵标识读取完整文献矩阵。",
        annotations=read_only,
    )
    async def yanzhang_get_literature_matrix(
        project_id: ProjectId,
        matrix_id: ResourceId,
    ) -> dict[str, object]:
        return await tools.yanzhang_get_literature_matrix(
            _request(
                GetLiteratureMatrixRequest,
                project_id=project_id,
                matrix_id=matrix_id,
            )
        )

    @server.tool(
        name="yanzhang_list_research_claims",
        title="列出项目研究主张",
        description="分页列出项目中已保存、可继续核验的研究主张。",
        annotations=read_only,
    )
    async def yanzhang_list_research_claims(
        project_id: ProjectId,
        limit: PageLimit = 20,
        offset: PageOffset = 0,
    ) -> dict[str, object]:
        return await tools.yanzhang_list_research_claims(
            _request(
                ListResearchClaimsRequest,
                project_id=project_id,
                limit=limit,
                offset=offset,
            )
        )

    @server.tool(
        name="yanzhang_get_research_claim",
        title="读取项目研究主张",
        description="按项目和主张标识读取一条研究主张。",
        annotations=read_only,
    )
    async def yanzhang_get_research_claim(
        project_id: ProjectId,
        claim_id: ResourceId,
    ) -> dict[str, object]:
        return await tools.yanzhang_get_research_claim(
            _request(
                GetResearchClaimRequest,
                project_id=project_id,
                claim_id=claim_id,
            )
        )

    @server.tool(
        name="yanzhang_list_citation_links",
        title="列出项目引用链",
        description="分页列出项目主张、文献与证据之间的引用关系，可按谱系筛选。",
        annotations=read_only,
    )
    async def yanzhang_list_citation_links(
        project_id: ProjectId,
        claim_id: ResourceId | None = None,
        record_id: ResourceId | None = None,
        evidence_id: ResourceId | None = None,
        limit: PageLimit = 20,
        offset: PageOffset = 0,
    ) -> dict[str, object]:
        return await tools.yanzhang_list_citation_links(
            _request(
                ListCitationLinksRequest,
                project_id=project_id,
                claim_id=claim_id,
                record_id=record_id,
                evidence_id=evidence_id,
                limit=limit,
                offset=offset,
            )
        )

    @server.tool(
        name="yanzhang_get_citation_link",
        title="读取项目引用链",
        description="按项目和引用链标识读取完整来源关系。",
        annotations=read_only,
    )
    async def yanzhang_get_citation_link(
        project_id: ProjectId,
        link_id: ResourceId,
    ) -> dict[str, object]:
        return await tools.yanzhang_get_citation_link(
            _request(
                GetCitationLinkRequest,
                project_id=project_id,
                link_id=link_id,
            )
        )

    @server.tool(
        name="yanzhang_verify_citations",
        title="核验主张与引用",
        description="逐项核验研究主张、文献记录和证据片段的引用链并计算覆盖率。",
        annotations=mutate,
    )
    async def yanzhang_verify_citations(
        project_id: ProjectId,
        record_ids: RecordIds,
        evidence_ids: EvidenceIds,
        claims: Claims,
        links: list[ClaimCitationLink] | None = None,
    ) -> dict[str, object]:
        return await tools.yanzhang_verify_citations(
            _request(
                VerifyCitationsRequest,
                project_id=project_id,
                record_ids=record_ids,
                evidence_ids=evidence_ids,
                claims=claims,
                links=links or [],
            )
        )

    @server.tool(
        name="yanzhang_format_bibliography",
        title="格式化参考文献",
        description="按 GB/T 7714、APA、MLA 或 Chicago 格式化已导入记录。",
        annotations=read_only,
    )
    async def yanzhang_format_bibliography(
        project_id: ProjectId,
        record_ids: RecordIds,
        style: CitationStyle = "gb-t-7714",
    ) -> dict[str, object]:
        return await tools.yanzhang_format_bibliography(
            _request(
                FormatBibliographyRequest,
                project_id=project_id,
                record_ids=record_ids,
                style=style,
            )
        )

    @server.tool(
        name="yanzhang_suggest_academic_titles",
        title="生成学术标题候选",
        description="基于研究问题和已导入文献生成有来源边界的学术标题。",
        annotations=mutate_network,
    )
    async def yanzhang_suggest_academic_titles(
        project_id: ProjectId,
        title: Topic,
        research_question: Query,
        discipline: str = "",
        purpose: str = "",
        audience: str = "学术读者",
        document_type: str = "研究论文",
        language: str = "zh-CN",
        keywords: list[str] | None = None,
        constraints: list[str] | None = None,
        method_notes: str = "",
        record_ids: list[str] | None = None,
        count: AcademicCandidateCount = 5,
    ) -> dict[str, object]:
        return await tools.yanzhang_suggest_academic_titles(
            _request(
                SuggestAcademicTitlesRequest,
                project_id=project_id,
                title=title,
                research_question=research_question,
                discipline=discipline,
                purpose=purpose,
                audience=audience,
                document_type=document_type,
                language=language,
                keywords=keywords or [],
                constraints=constraints or [],
                method_notes=method_notes,
                record_ids=record_ids or [],
                count=count,
            )
        )

    @server.tool(
        name="yanzhang_create_academic_outline",
        title="创建证据化学术提纲",
        description="把研究问题、文献和证据组织为可追溯的论文提纲。",
        annotations=mutate_network,
    )
    async def yanzhang_create_academic_outline(
        project_id: ProjectId,
        title: Topic,
        research_question: Query,
        discipline: str = "",
        purpose: str = "",
        audience: str = "学术读者",
        document_type: str = "研究论文",
        language: str = "zh-CN",
        keywords: list[str] | None = None,
        constraints: list[str] | None = None,
        method_notes: str = "",
        record_ids: list[str] | None = None,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, object]:
        return await tools.yanzhang_create_academic_outline(
            _request(
                CreateAcademicOutlineRequest,
                project_id=project_id,
                title=title,
                research_question=research_question,
                discipline=discipline,
                purpose=purpose,
                audience=audience,
                document_type=document_type,
                language=language,
                keywords=keywords or [],
                constraints=constraints or [],
                method_notes=method_notes,
                record_ids=record_ids or [],
                evidence_ids=evidence_ids or [],
            )
        )

    @server.tool(
        name="yanzhang_draft_abstract",
        title="起草学术摘要",
        description="根据研究简报、主张和引用链起草有占位提示的学术摘要。",
        annotations=mutate_network,
    )
    async def yanzhang_draft_abstract(
        project_id: ProjectId,
        title: Topic,
        research_question: Query,
        discipline: str = "",
        purpose: str = "",
        audience: str = "学术读者",
        document_type: str = "研究论文",
        language: str = "zh-CN",
        keywords: list[str] | None = None,
        constraints: list[str] | None = None,
        method_notes: str = "",
        record_ids: list[str] | None = None,
        claims: list[ResearchClaim] | None = None,
        links: list[ClaimCitationLink] | None = None,
        max_characters: AbstractLength = 800,
    ) -> dict[str, object]:
        return await tools.yanzhang_draft_abstract(
            _request(
                DraftAbstractRequest,
                project_id=project_id,
                title=title,
                research_question=research_question,
                discipline=discipline,
                purpose=purpose,
                audience=audience,
                document_type=document_type,
                language=language,
                keywords=keywords or [],
                constraints=constraints or [],
                method_notes=method_notes,
                record_ids=record_ids or [],
                claims=claims or [],
                links=links or [],
                max_characters=max_characters,
            )
        )

    @server.tool(
        name="yanzhang_review_academic_integrity",
        title="审查学术引用完整性",
        description="检查稿件引用谱系、证据一致性、元数据和期刊格式要求。",
        annotations=mutate,
    )
    async def yanzhang_review_academic_integrity(
        project_id: ProjectId,
        manuscript: Manuscript,
        record_ids: list[str] | None = None,
        evidence_ids: list[str] | None = None,
        claims: list[ResearchClaim] | None = None,
        links: list[ClaimCitationLink] | None = None,
        journal: JournalProfile | None = None,
    ) -> dict[str, object]:
        return await tools.yanzhang_review_academic_integrity(
            _request(
                ReviewAcademicIntegrityRequest,
                project_id=project_id,
                manuscript=manuscript,
                record_ids=record_ids or [],
                evidence_ids=evidence_ids or [],
                claims=claims or [],
                links=links or [],
                journal=journal,
            )
        )

    @server.tool(
        name="yanzhang_prepare_rebuttal",
        title="准备审稿意见回复",
        description="根据审稿意见与实际修改记录生成逐条、可定位的回复草稿。",
        annotations=mutate_network,
    )
    async def yanzhang_prepare_rebuttal(
        project_id: ProjectId,
        comments: ReviewComments,
        changes: dict[str, str] | None = None,
    ) -> dict[str, object]:
        return await tools.yanzhang_prepare_rebuttal(
            _request(
                PrepareRebuttalRequest,
                project_id=project_id,
                comments=comments,
                changes=changes or {},
            )
        )


def create_writing_server(platform: YanzhangPlatform | YanzhangMCPContext) -> FastMCP:
    """Create a standalone in-process server for tests and local composition."""

    server = _WritingFastMCP(
        "砚章通用写作",
        instructions=(
            "先选择场景包和写作配方，再以项目资料为事实边界运行工作流；"
            "学术引用须关联已导入文献和证据片段。"
        ),
    )
    register_writing_tools(server, platform)
    return server


def _request[RequestT: BaseModel](model: type[RequestT], **payload: object) -> RequestT:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise YanzhangToolError("invalid_request", _validation_details(exc)) from None


def _validation_details(exc: ValidationError) -> str:
    details = [
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors(include_url=False, include_input=False)[:20]
    ]
    return "；".join(details)[:500] or "请求参数有误"


__all__ = [
    "YANZHANG_TOOL_NAMES",
    "create_writing_server",
    "register_writing_tools",
]
