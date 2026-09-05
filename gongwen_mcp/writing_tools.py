"""Transport-neutral tool facade for the universal Yanzhang writing platform."""

# Chinese punctuation is intentional in public tool messages.
# ruff: noqa: RUF001

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from gongwen_mcp.writing_schemas import (
    AddMaterialRequest,
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
    PrepareRebuttalRequest,
    ReviewAcademicIntegrityRequest,
    ReviewAssetRequest,
    RunWorkflowRequest,
    SearchLiteratureRequest,
    StatusRequest,
    SuggestAcademicTitlesRequest,
    UnifiedSearchRequest,
    UpsertProjectTermRequest,
    VerifyCitationsRequest,
)
from yanzhang_core.routing import ModelExecutionConfigurationError
from yanzhang_core.storage import BriefConflictError, ProjectScopeError

type PlatformResult = Mapping[str, object]


class YanzhangToolError(RuntimeError):
    """Stable public error emitted by a Yanzhang writing tool."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class YanzhangPlatform(Protocol):
    """Asynchronous application boundary consumed by MCP registrations.

    Implementations may compose local stores, workflow engines, academic
    services and provider adapters.  MCP code never constructs those concrete
    dependencies and never handles credentials.
    """

    async def yanzhang_get_status(self, request: StatusRequest) -> PlatformResult: ...

    async def yanzhang_list_scene_packs(self, request: ListScenePacksRequest) -> PlatformResult: ...

    async def yanzhang_get_scene_pack(self, request: GetScenePackRequest) -> PlatformResult: ...

    async def yanzhang_create_project(self, request: CreateProjectRequest) -> PlatformResult: ...

    async def yanzhang_list_projects(self, request: ListProjectsRequest) -> PlatformResult: ...

    async def yanzhang_get_project(self, request: GetProjectRequest) -> PlatformResult: ...

    async def yanzhang_upsert_project_term(
        self, request: UpsertProjectTermRequest
    ) -> PlatformResult: ...

    async def yanzhang_list_project_terms(
        self, request: ListProjectTermsRequest
    ) -> PlatformResult: ...

    async def yanzhang_delete_project_term(
        self, request: DeleteProjectTermRequest
    ) -> PlatformResult: ...

    async def yanzhang_add_material(self, request: AddMaterialRequest) -> PlatformResult: ...

    async def yanzhang_list_materials(self, request: ListMaterialsRequest) -> PlatformResult: ...

    async def yanzhang_get_material(self, request: GetMaterialRequest) -> PlatformResult: ...

    async def yanzhang_search(self, request: UnifiedSearchRequest) -> PlatformResult: ...

    async def yanzhang_generate_titles(self, request: GenerateTitlesRequest) -> PlatformResult: ...

    async def yanzhang_create_workflow(self, request: CreateWorkflowRequest) -> PlatformResult: ...

    async def yanzhang_run_workflow(self, request: RunWorkflowRequest) -> PlatformResult: ...

    async def yanzhang_get_workflow(self, request: GetWorkflowRequest) -> PlatformResult: ...

    async def yanzhang_cancel_workflow(self, request: CancelWorkflowRequest) -> PlatformResult: ...

    async def yanzhang_list_assets(self, request: ListAssetsRequest) -> PlatformResult: ...

    async def yanzhang_get_asset(self, request: GetAssetRequest) -> PlatformResult: ...

    async def yanzhang_create_variant(self, request: CreateVariantRequest) -> PlatformResult: ...

    async def yanzhang_list_revisions(self, request: ListRevisionsRequest) -> PlatformResult: ...

    async def yanzhang_review_asset(self, request: ReviewAssetRequest) -> PlatformResult: ...

    async def yanzhang_export_asset(self, request: ExportAssetRequest) -> PlatformResult: ...

    async def yanzhang_search_literature(
        self, request: SearchLiteratureRequest
    ) -> PlatformResult: ...

    async def yanzhang_import_literature(
        self, request: ImportLiteratureRequest
    ) -> PlatformResult: ...

    async def yanzhang_get_literature(self, request: GetLiteratureRequest) -> PlatformResult: ...

    async def yanzhang_list_literature(self, request: ListLiteratureRequest) -> PlatformResult: ...

    async def yanzhang_list_evidence(self, request: ListEvidenceRequest) -> PlatformResult: ...

    async def yanzhang_get_evidence(self, request: GetEvidenceRequest) -> PlatformResult: ...

    async def yanzhang_extract_evidence(
        self, request: ExtractEvidenceRequest
    ) -> PlatformResult: ...

    async def yanzhang_build_literature_matrix(
        self, request: BuildLiteratureMatrixRequest
    ) -> PlatformResult: ...

    async def yanzhang_list_literature_matrices(
        self, request: ListLiteratureMatricesRequest
    ) -> PlatformResult: ...

    async def yanzhang_get_literature_matrix(
        self, request: GetLiteratureMatrixRequest
    ) -> PlatformResult: ...

    async def yanzhang_list_research_claims(
        self, request: ListResearchClaimsRequest
    ) -> PlatformResult: ...

    async def yanzhang_get_research_claim(
        self, request: GetResearchClaimRequest
    ) -> PlatformResult: ...

    async def yanzhang_list_citation_links(
        self, request: ListCitationLinksRequest
    ) -> PlatformResult: ...

    async def yanzhang_get_citation_link(
        self, request: GetCitationLinkRequest
    ) -> PlatformResult: ...

    async def yanzhang_verify_citations(
        self, request: VerifyCitationsRequest
    ) -> PlatformResult: ...

    async def yanzhang_format_bibliography(
        self, request: FormatBibliographyRequest
    ) -> PlatformResult: ...

    async def yanzhang_suggest_academic_titles(
        self, request: SuggestAcademicTitlesRequest
    ) -> PlatformResult: ...

    async def yanzhang_create_academic_outline(
        self, request: CreateAcademicOutlineRequest
    ) -> PlatformResult: ...

    async def yanzhang_draft_abstract(self, request: DraftAbstractRequest) -> PlatformResult: ...

    async def yanzhang_review_academic_integrity(
        self, request: ReviewAcademicIntegrityRequest
    ) -> PlatformResult: ...

    async def yanzhang_prepare_rebuttal(
        self, request: PrepareRebuttalRequest
    ) -> PlatformResult: ...


@dataclass(frozen=True, slots=True)
class YanzhangMCPContext:
    """Dependencies shared by the universal writing-tool facade."""

    platform: YanzhangPlatform


class YanzhangWritingTools:
    """Directly testable implementations of the public writing tools."""

    def __init__(self, context: YanzhangMCPContext) -> None:
        self.context = context

    async def yanzhang_get_status(self, request: StatusRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_get_status, request)

    async def yanzhang_list_scene_packs(self, request: ListScenePacksRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_list_scene_packs, request)

    async def yanzhang_get_scene_pack(self, request: GetScenePackRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_get_scene_pack, request)

    async def yanzhang_create_project(self, request: CreateProjectRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_create_project, request)

    async def yanzhang_list_projects(self, request: ListProjectsRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_list_projects, request)

    async def yanzhang_get_project(self, request: GetProjectRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_get_project, request)

    async def yanzhang_upsert_project_term(
        self, request: UpsertProjectTermRequest
    ) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_upsert_project_term, request)

    async def yanzhang_list_project_terms(
        self, request: ListProjectTermsRequest
    ) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_list_project_terms, request)

    async def yanzhang_delete_project_term(
        self, request: DeleteProjectTermRequest
    ) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_delete_project_term, request)

    async def yanzhang_add_material(self, request: AddMaterialRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_add_material, request)

    async def yanzhang_list_materials(self, request: ListMaterialsRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_list_materials, request)

    async def yanzhang_get_material(self, request: GetMaterialRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_get_material, request)

    async def yanzhang_search(self, request: UnifiedSearchRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_search, request)

    async def yanzhang_generate_titles(self, request: GenerateTitlesRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_generate_titles, request)

    async def yanzhang_create_workflow(self, request: CreateWorkflowRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_create_workflow, request)

    async def yanzhang_run_workflow(self, request: RunWorkflowRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_run_workflow, request)

    async def yanzhang_get_workflow(self, request: GetWorkflowRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_get_workflow, request)

    async def yanzhang_cancel_workflow(self, request: CancelWorkflowRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_cancel_workflow, request)

    async def yanzhang_list_assets(self, request: ListAssetsRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_list_assets, request)

    async def yanzhang_get_asset(self, request: GetAssetRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_get_asset, request)

    async def yanzhang_create_variant(self, request: CreateVariantRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_create_variant, request)

    async def yanzhang_list_revisions(self, request: ListRevisionsRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_list_revisions, request)

    async def yanzhang_review_asset(self, request: ReviewAssetRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_review_asset, request)

    async def yanzhang_export_asset(self, request: ExportAssetRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_export_asset, request)

    async def yanzhang_search_literature(
        self, request: SearchLiteratureRequest
    ) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_search_literature, request)

    async def yanzhang_import_literature(
        self, request: ImportLiteratureRequest
    ) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_import_literature, request)

    async def yanzhang_get_literature(self, request: GetLiteratureRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_get_literature, request)

    async def yanzhang_list_literature(self, request: ListLiteratureRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_list_literature, request)

    async def yanzhang_list_evidence(self, request: ListEvidenceRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_list_evidence, request)

    async def yanzhang_get_evidence(self, request: GetEvidenceRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_get_evidence, request)

    async def yanzhang_extract_evidence(self, request: ExtractEvidenceRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_extract_evidence, request)

    async def yanzhang_build_literature_matrix(
        self, request: BuildLiteratureMatrixRequest
    ) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_build_literature_matrix, request)

    async def yanzhang_list_literature_matrices(
        self, request: ListLiteratureMatricesRequest
    ) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_list_literature_matrices, request)

    async def yanzhang_get_literature_matrix(
        self, request: GetLiteratureMatrixRequest
    ) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_get_literature_matrix, request)

    async def yanzhang_list_research_claims(
        self, request: ListResearchClaimsRequest
    ) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_list_research_claims, request)

    async def yanzhang_get_research_claim(
        self, request: GetResearchClaimRequest
    ) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_get_research_claim, request)

    async def yanzhang_list_citation_links(
        self, request: ListCitationLinksRequest
    ) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_list_citation_links, request)

    async def yanzhang_get_citation_link(
        self, request: GetCitationLinkRequest
    ) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_get_citation_link, request)

    async def yanzhang_verify_citations(self, request: VerifyCitationsRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_verify_citations, request)

    async def yanzhang_format_bibliography(
        self, request: FormatBibliographyRequest
    ) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_format_bibliography, request)

    async def yanzhang_suggest_academic_titles(
        self, request: SuggestAcademicTitlesRequest
    ) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_suggest_academic_titles, request)

    async def yanzhang_create_academic_outline(
        self, request: CreateAcademicOutlineRequest
    ) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_create_academic_outline, request)

    async def yanzhang_draft_abstract(self, request: DraftAbstractRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_draft_abstract, request)

    async def yanzhang_review_academic_integrity(
        self, request: ReviewAcademicIntegrityRequest
    ) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_review_academic_integrity, request)

    async def yanzhang_prepare_rebuttal(self, request: PrepareRebuttalRequest) -> dict[str, object]:
        return await self._invoke(self.context.platform.yanzhang_prepare_rebuttal, request)

    async def _invoke[RequestT](
        self,
        action: Callable[[RequestT], Awaitable[PlatformResult]],
        request: RequestT,
    ) -> dict[str, object]:
        try:
            result = dict(await action(request))
            _ensure_json_safe(result)
            return result
        except YanzhangToolError:
            raise
        except ValidationError as exc:
            raise YanzhangToolError("invalid_request", _validation_details(exc)) from None
        except TimeoutError:
            raise YanzhangToolError("operation_timeout", "操作超时，请稍后重试") from None
        except BriefConflictError:
            raise YanzhangToolError("brief_conflict", "任务简报标识已绑定其他内容") from None
        except ProjectScopeError:
            raise YanzhangToolError("project_scope_error", "资源不属于当前项目") from None
        except ModelExecutionConfigurationError:
            raise YanzhangToolError(
                "model_configuration_error",
                "当前任务需要可用的服务端模型。请检查模型配置与路由设置",
            ) from None
        except (KeyError, LookupError):
            raise YanzhangToolError("not_found", "未找到指定资源") from None
        except ValueError:
            raise YanzhangToolError("invalid_request", "请求参数或资源状态不符合要求") from None
        except Exception:
            raise YanzhangToolError("internal_error", "操作执行异常，请稍后重试") from None


def _validation_details(exc: ValidationError) -> str:
    details = [
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors(include_url=False, include_input=False)[:20]
    ]
    return "；".join(details)[:500] or "请求参数有误"


def _ensure_json_safe(value: object) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise YanzhangToolError("invalid_result", "工具结果包含无效数值")
        return
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise YanzhangToolError("invalid_result", "工具结果包含非文本字段名")
        for item in value.values():
            _ensure_json_safe(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _ensure_json_safe(item)
        return
    raise YanzhangToolError("invalid_result", "工具结果包含非 JSON 数据")


__all__ = [
    "PlatformResult",
    "YanzhangMCPContext",
    "YanzhangPlatform",
    "YanzhangToolError",
    "YanzhangWritingTools",
]
