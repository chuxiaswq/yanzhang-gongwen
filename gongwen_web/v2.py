"""Versioned HTTP transport for the provider-neutral Yanzhang writing platform.

The module deliberately owns transport concerns only: bounded JSON parsing,
path/body identity checks, DTO validation, stable error responses and artifact
downloads.  Application services remain behind :class:`YanzhangPlatform`.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Final, Literal, cast
from urllib.parse import quote

from pydantic import AliasChoices, Field, ValidationError, field_validator
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from gongwen_mcp.artifacts import (
    ArtifactCorrupt,
    ArtifactNotFound,
    ArtifactStore,
    InvalidArtifactId,
)
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
    WritingRequest,
)
from gongwen_mcp.writing_tools import (
    YanzhangMCPContext,
    YanzhangPlatform,
    YanzhangToolError,
    YanzhangWritingTools,
)
from yanzhang_core.models import (
    AssetStatus,
    Channel,
    ContentBlock,
    KnowledgeKind,
    WritingStructureSection,
)
from yanzhang_core.packs import ScenarioPackId, list_recipes
from yanzhang_core.parsers import DocumentParseError, parse_document
from yanzhang_core.storage import BriefConflictError, ProjectScopeError

_DEFAULT_MAX_REQUEST_BYTES: Final = 8 * 1024 * 1024
_MAX_BASE64_CHARACTERS: Final = 16 * 1024 * 1024
_NO_STORE_HEADERS: Final = {"Cache-Control": "no-store"}


class ImportDocumentRequest(WritingRequest):
    """Closed JSON envelope for a document imported through the Web API."""

    project_id: str = Field(min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=255)
    media_type: str | None = Field(default=None, min_length=1, max_length=200)
    content_base64: str = Field(
        min_length=1,
        max_length=_MAX_BASE64_CHARACTERS,
        validation_alias=AliasChoices("content_base64", "data_base64"),
    )
    mode: Literal["merge", "blocks"] = "merge"
    title: str | None = Field(default=None, min_length=1, max_length=500)
    kind: KnowledgeKind = "source"
    source_url: str = Field(default="", max_length=2_000)
    tags: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 100 for value in cleaned):
            raise ValueError("tags 单项长度须为 1 至 100")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("tags 不得重复")
        return cleaned


class CreateBriefRequest(WritingRequest):
    """Persist one normalized writing brief inside a project."""

    project_id: str = Field(min_length=1, max_length=128)
    brief_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        validation_alias=AliasChoices("brief_id", "id"),
    )
    title: str = Field(
        min_length=1,
        max_length=300,
        validation_alias=AliasChoices("title", "topic"),
    )
    goal: str = Field(min_length=1, max_length=2_000)
    audience: str = Field(min_length=1, max_length=500)
    channel: Channel = "document"
    content_type: str = Field(min_length=1, max_length=100)
    scenario_pack_id: ScenarioPackId
    recipe_id: str = Field(min_length=1, max_length=100)
    tone: str = Field(default="准确、清晰、得体", min_length=1, max_length=100)
    length: str = Field(default="standard", min_length=1, max_length=80)
    target_language: str = Field(default="zh-CN", min_length=2, max_length=35)
    constraints: list[str] = Field(default_factory=list, max_length=32)
    keywords: list[str] = Field(default_factory=list, max_length=32)
    material_ids: list[str] = Field(
        default_factory=list,
        max_length=128,
        validation_alias=AliasChoices("material_ids", "knowledge_item_ids"),
    )
    model_profile_id: str | None = Field(default=None, min_length=1, max_length=100)
    selected_title: str | None = Field(default=None, min_length=1, max_length=300)
    structure_override: list[WritingStructureSection] = Field(
        default_factory=list,
        max_length=24,
    )

    @field_validator("constraints", "keywords")
    @classmethod
    def validate_text_lists(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 500 for value in cleaned):
            raise ValueError("列表单项长度须为 1 至 500")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("列表字段不得重复")
        return cleaned

    @field_validator("material_ids")
    @classmethod
    def validate_material_ids(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 128 for value in cleaned):
            raise ValueError("material_ids 单项长度须为 1 至 128")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("material_ids 不得重复")
        return cleaned

    @field_validator("structure_override")
    @classmethod
    def validate_structure_override(
        cls, values: list[WritingStructureSection]
    ) -> list[WritingStructureSection]:
        ids = [value.id for value in values]
        titles = [value.title for value in values]
        if len(ids) != len(set(ids)):
            raise ValueError("structure_override 的章节标识不得重复")
        if len(titles) != len(set(titles)):
            raise ValueError("structure_override 的章节标题不得重复")
        return values


class CreateAssetRequest(WritingRequest):
    """Generate and persist a master asset from an existing brief."""

    project_id: str = Field(min_length=1, max_length=128)
    brief_id: str = Field(min_length=1, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    live: bool = False


class CreateRevisionRequest(WritingRequest):
    """Persist an edited snapshot while enforcing optimistic revision checks."""

    project_id: str = Field(min_length=1, max_length=128)
    asset_id: str = Field(min_length=1, max_length=128)
    blocks: list[ContentBlock] | None = Field(default=None, min_length=1, max_length=10_000)
    note: str = Field(default="保存修订", max_length=500)
    model_profile_id: str | None = Field(default=None, min_length=1, max_length=100)
    expected_revision: int | None = Field(default=None, ge=0)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: AssetStatus | None = None


class ListWorkflowDefinitionsRequest(WritingRequest):
    """Bounded query for the built-in executable recipe catalog."""

    scenario_pack_id: ScenarioPackId | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class _TransportProblem(RuntimeError):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(code)


async def _bootstrap(request: Request) -> Response:
    return await _dispatch(request, StatusRequest, "yanzhang_get_status", {})


async def _scene_packs(request: Request) -> Response:
    payload = _copy_query(request, "channel", "content_type")
    return await _dispatch(
        request,
        ListScenePacksRequest,
        "yanzhang_list_scene_packs",
        payload,
    )


async def _scene_pack(request: Request) -> Response:
    return await _dispatch(
        request,
        GetScenePackRequest,
        "yanzhang_get_scene_pack",
        {"pack_id": request.path_params["pack_id"]},
    )


async def _projects(request: Request) -> Response:
    if request.method == "GET":
        payload = _copy_query(request, "query", "scenario_pack_id", "limit", "offset")
        return await _dispatch(
            request,
            ListProjectsRequest,
            "yanzhang_list_projects",
            payload,
        )
    return await _dispatch_body(
        request,
        CreateProjectRequest,
        "yanzhang_create_project",
        status_code=201,
    )


async def _project(request: Request) -> Response:
    return await _dispatch(
        request,
        GetProjectRequest,
        "yanzhang_get_project",
        {"project_id": request.path_params["project_id"]},
    )


async def _project_terms(request: Request) -> Response:
    project_id = request.path_params["project_id"]
    if request.method == "GET":
        payload = _copy_query(request, "limit", "offset")
        payload["project_id"] = project_id
        return await _dispatch(
            request,
            ListProjectTermsRequest,
            "yanzhang_list_project_terms",
            payload,
        )
    return await _dispatch_body(
        request,
        UpsertProjectTermRequest,
        "yanzhang_upsert_project_term",
        path_values={"project_id": project_id},
        status_code=201,
    )


async def _project_term(request: Request) -> Response:
    return await _dispatch(
        request,
        DeleteProjectTermRequest,
        "yanzhang_delete_project_term",
        {
            "project_id": request.path_params["project_id"],
            "term_id": request.path_params["term_id"],
        },
    )


async def _briefs(request: Request) -> Response:
    return await _dispatch_extension_body(
        request,
        CreateBriefRequest,
        "create_brief",
        path_values=_optional_path_value(request, "project_id"),
        status_code=201,
    )


async def _materials(request: Request) -> Response:
    project_id = _path_or_query_project_id(request)
    if request.method == "GET":
        payload = _copy_query(request, "query", "kind", "limit", "offset")
        payload["tags"] = _query_list(request, "tags")
        if project_id is not None:
            payload["project_id"] = project_id
        return await _dispatch(
            request,
            ListMaterialsRequest,
            "yanzhang_list_materials",
            payload,
        )
    return await _dispatch_body(
        request,
        AddMaterialRequest,
        "yanzhang_add_material",
        path_values={"project_id": project_id} if project_id is not None else None,
        status_code=201,
    )


async def _material(request: Request) -> Response:
    payload = _copy_query(request, "chunk_offset", "chunk_size")
    payload.update(
        project_id=request.path_params["project_id"],
        material_id=request.path_params["material_id"],
    )
    return await _dispatch(
        request,
        GetMaterialRequest,
        "yanzhang_get_material",
        payload,
    )


async def _search(request: Request) -> Response:
    payload = _copy_query(request, "query", "scope", "limit", "offset")
    payload["tags"] = _query_list(request, "tags")
    project_id = _path_or_query_project_id(request)
    if project_id is not None:
        payload["project_id"] = project_id
    return await _dispatch(request, UnifiedSearchRequest, "yanzhang_search", payload)


async def _import_material(request: Request) -> Response:
    try:
        payload = await _read_json_object(request)
        _inject_path_values(payload, {"project_id": request.path_params["project_id"]})
        command = ImportDocumentRequest.model_validate(payload)
        try:
            raw = base64.b64decode(command.content_base64, validate=True)
        except (binascii.Error, ValueError):
            raise _TransportProblem(
                422,
                "invalid_base64",
                "文件内容应为有效的 Base64 数据",
            ) from None
        parsed = parse_document(raw, filename=command.filename, media_type=command.media_type)
        title = command.title or parsed.title
        blocks = [block for block in parsed.blocks if block.text.strip()]
        if command.mode == "blocks":
            results: list[dict[str, object]] = []
            for index, block in enumerate(blocks, start=1):
                block_title = (
                    block.text.strip() if block.kind == "heading" else f"{title} · {index}"
                )
                block_title = block_title.splitlines()[0][:500]
                add = AddMaterialRequest(
                    project_id=command.project_id,
                    title=block_title,
                    content=block.text,
                    kind=command.kind,
                    source_url=command.source_url,
                    tags=command.tags,
                )
                results.append(await _invoke_platform(request, "yanzhang_add_material", add))
        else:
            add = AddMaterialRequest(
                project_id=command.project_id,
                title=title,
                content=parsed.text,
                kind=command.kind,
                source_url=command.source_url,
                tags=command.tags,
            )
            results = [await _invoke_platform(request, "yanzhang_add_material", add)]
        return _json_response(
            {
                "mode": command.mode,
                "document": {
                    "title": parsed.title,
                    "content_type": parsed.content_type,
                    "block_count": len(parsed.blocks),
                    "metadata": dict(parsed.metadata),
                    "warnings": list(parsed.warnings),
                },
                "items": results,
            },
            status_code=201,
        )
    except Exception as exc:
        return _exception_response(exc)


async def _headlines(request: Request) -> Response:
    return await _dispatch_body(
        request,
        GenerateTitlesRequest,
        "yanzhang_generate_titles",
        path_values=_optional_path_value(request, "project_id"),
    )


async def _project_workflows(request: Request) -> Response:
    return await _dispatch_body(
        request,
        CreateWorkflowRequest,
        "yanzhang_create_workflow",
        path_values={"project_id": request.path_params["project_id"]},
        status_code=201,
    )


async def _workflow(request: Request) -> Response:
    payload = _copy_query(request, "project_id")
    _set_optional_path(payload, request, "project_id")
    payload["workflow_id"] = request.path_params["workflow_id"]
    return await _dispatch(
        request,
        GetWorkflowRequest,
        "yanzhang_get_workflow",
        payload,
    )


async def _run_workflow(request: Request) -> Response:
    return await _dispatch_body(
        request,
        RunWorkflowRequest,
        "yanzhang_run_workflow",
        path_values=_workflow_path_values(request),
    )


async def _cancel_workflow(request: Request) -> Response:
    return await _dispatch_body(
        request,
        CancelWorkflowRequest,
        "yanzhang_cancel_workflow",
        path_values=_workflow_path_values(request),
    )


async def _assets(request: Request) -> Response:
    if request.method == "POST":
        return await _dispatch_extension_body(
            request,
            CreateAssetRequest,
            "create_asset",
            path_values=_optional_path_value(request, "project_id"),
            status_code=201,
        )
    payload = _copy_query(request, "status", "content_type", "limit", "offset")
    project_id = _path_or_query_project_id(request)
    if project_id is not None:
        payload["project_id"] = project_id
    return await _dispatch(request, ListAssetsRequest, "yanzhang_list_assets", payload)


async def _asset(request: Request) -> Response:
    payload = _copy_query(request, "project_id", "revision", "chunk_offset", "chunk_size")
    _set_optional_path(payload, request, "project_id")
    payload["asset_id"] = request.path_params["asset_id"]
    return await _dispatch(request, GetAssetRequest, "yanzhang_get_asset", payload)


async def _variant(request: Request) -> Response:
    return await _dispatch_body(
        request,
        CreateVariantRequest,
        "yanzhang_create_variant",
        path_values=_asset_path_values(request),
        status_code=201,
    )


async def _revisions(request: Request) -> Response:
    if request.method == "POST":
        return await _dispatch_extension_body(
            request,
            CreateRevisionRequest,
            "create_revision",
            path_values=_asset_path_values(request),
            status_code=201,
        )
    payload = _copy_query(request, "project_id", "limit", "offset")
    _set_optional_path(payload, request, "project_id")
    payload["asset_id"] = request.path_params["asset_id"]
    return await _dispatch(
        request,
        ListRevisionsRequest,
        "yanzhang_list_revisions",
        payload,
    )


async def _review_asset(request: Request) -> Response:
    return await _dispatch_body(
        request,
        ReviewAssetRequest,
        "yanzhang_review_asset",
        path_values=_asset_path_values(request),
    )


async def _export_asset(request: Request) -> Response:
    return await _dispatch_body(
        request,
        ExportAssetRequest,
        "yanzhang_export_asset",
        path_values=_asset_path_values(request),
        status_code=201,
    )


async def _download_export(request: Request) -> Response:
    return await _download_export_for_scope(
        request,
        project_id=request.path_params["project_id"],
    )


async def _download_legacy_export(request: Request) -> Response:
    return await _download_export_for_scope(request, legacy_only=True)


async def _download_export_for_scope(
    request: Request,
    *,
    project_id: str | None = None,
    legacy_only: bool = False,
) -> Response:
    try:
        store = _artifact_store(request)
        artifact_id = request.path_params["artifact_id"]
        metadata = store.get_metadata(
            artifact_id,
            project_id=project_id,
            legacy_only=legacy_only,
        )
        payload = store.read_bytes(
            artifact_id,
            project_id=project_id,
            legacy_only=legacy_only,
        )
        ascii_name = "download" + _filename_suffix(metadata.filename)
        disposition = (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(metadata.filename, safe='')}"
        )
        return Response(
            payload,
            media_type=metadata.mime,
            headers={
                **_NO_STORE_HEADERS,
                "Content-Disposition": disposition,
                "X-Content-Type-Options": "nosniff",
                "Content-Length": str(metadata.size),
            },
        )
    except Exception as exc:
        return _exception_response(exc)


async def _academic_search(request: Request) -> Response:
    return await _dispatch_body(
        request,
        SearchLiteratureRequest,
        "yanzhang_search_literature",
        path_values=_optional_path_value(request, "project_id"),
    )


async def _academic_import(request: Request) -> Response:
    return await _dispatch_body(
        request,
        ImportLiteratureRequest,
        "yanzhang_import_literature",
        path_values=_optional_path_value(request, "project_id"),
        status_code=201,
    )


async def _academic_record(request: Request) -> Response:
    payload = _copy_query(request, "project_id", "include_abstract")
    _set_optional_path(payload, request, "project_id")
    payload["record_id"] = request.path_params["record_id"]
    return await _dispatch(
        request,
        GetLiteratureRequest,
        "yanzhang_get_literature",
        payload,
    )


async def _academic_records(request: Request) -> Response:
    payload = _copy_query(
        request,
        "project_id",
        "query",
        "include_abstract",
        "limit",
        "offset",
    )
    _set_optional_path(payload, request, "project_id")
    return await _dispatch(
        request,
        ListLiteratureRequest,
        "yanzhang_list_literature",
        payload,
    )


async def _academic_evidence_list(request: Request) -> Response:
    payload = _copy_query(request, "project_id", "record_id", "limit", "offset")
    _set_optional_path(payload, request, "project_id")
    return await _dispatch(
        request,
        ListEvidenceRequest,
        "yanzhang_list_evidence",
        payload,
    )


async def _academic_evidence_item(request: Request) -> Response:
    payload = _copy_query(request, "project_id")
    _set_optional_path(payload, request, "project_id")
    payload["evidence_id"] = request.path_params["evidence_id"]
    return await _dispatch(
        request,
        GetEvidenceRequest,
        "yanzhang_get_evidence",
        payload,
    )


async def _academic_evidence(request: Request) -> Response:
    return await _academic_action(
        request,
        ExtractEvidenceRequest,
        "yanzhang_extract_evidence",
    )


async def _academic_matrix(request: Request) -> Response:
    return await _academic_action(
        request,
        BuildLiteratureMatrixRequest,
        "yanzhang_build_literature_matrix",
    )


async def _academic_matrices(request: Request) -> Response:
    payload = _copy_query(request, "project_id", "limit", "offset")
    _set_optional_path(payload, request, "project_id")
    return await _dispatch(
        request,
        ListLiteratureMatricesRequest,
        "yanzhang_list_literature_matrices",
        payload,
    )


async def _academic_matrix_item(request: Request) -> Response:
    payload = _copy_query(request, "project_id")
    _set_optional_path(payload, request, "project_id")
    payload["matrix_id"] = request.path_params["matrix_id"]
    return await _dispatch(
        request,
        GetLiteratureMatrixRequest,
        "yanzhang_get_literature_matrix",
        payload,
    )


async def _academic_claims(request: Request) -> Response:
    payload = _copy_query(request, "project_id", "limit", "offset")
    _set_optional_path(payload, request, "project_id")
    return await _dispatch(
        request,
        ListResearchClaimsRequest,
        "yanzhang_list_research_claims",
        payload,
    )


async def _academic_claim(request: Request) -> Response:
    payload = _copy_query(request, "project_id")
    _set_optional_path(payload, request, "project_id")
    payload["claim_id"] = request.path_params["claim_id"]
    return await _dispatch(
        request,
        GetResearchClaimRequest,
        "yanzhang_get_research_claim",
        payload,
    )


async def _academic_links(request: Request) -> Response:
    payload = _copy_query(
        request,
        "project_id",
        "claim_id",
        "record_id",
        "evidence_id",
        "limit",
        "offset",
    )
    _set_optional_path(payload, request, "project_id")
    return await _dispatch(
        request,
        ListCitationLinksRequest,
        "yanzhang_list_citation_links",
        payload,
    )


async def _academic_link(request: Request) -> Response:
    payload = _copy_query(request, "project_id")
    _set_optional_path(payload, request, "project_id")
    payload["link_id"] = request.path_params["link_id"]
    return await _dispatch(
        request,
        GetCitationLinkRequest,
        "yanzhang_get_citation_link",
        payload,
    )


async def _academic_verify(request: Request) -> Response:
    return await _academic_action(
        request,
        VerifyCitationsRequest,
        "yanzhang_verify_citations",
    )


async def _academic_bibliography(request: Request) -> Response:
    return await _academic_action(
        request,
        FormatBibliographyRequest,
        "yanzhang_format_bibliography",
    )


async def _academic_titles(request: Request) -> Response:
    return await _academic_action(
        request,
        SuggestAcademicTitlesRequest,
        "yanzhang_suggest_academic_titles",
    )


async def _academic_outline(request: Request) -> Response:
    return await _academic_action(
        request,
        CreateAcademicOutlineRequest,
        "yanzhang_create_academic_outline",
    )


async def _academic_abstract(request: Request) -> Response:
    return await _academic_action(
        request,
        DraftAbstractRequest,
        "yanzhang_draft_abstract",
    )


async def _academic_integrity(request: Request) -> Response:
    return await _academic_action(
        request,
        ReviewAcademicIntegrityRequest,
        "yanzhang_review_academic_integrity",
    )


async def _academic_rebuttal(request: Request) -> Response:
    return await _academic_action(
        request,
        PrepareRebuttalRequest,
        "yanzhang_prepare_rebuttal",
    )


async def _workflow_definitions(request: Request) -> Response:
    try:
        command = ListWorkflowDefinitionsRequest.model_validate(
            _copy_query(request, "scenario_pack_id", "limit", "offset")
        )
        definitions = list_recipes(command.scenario_pack_id)
        page = definitions[command.offset : command.offset + command.limit]
        items = [
            {
                "id": recipe.id,
                "version": "2",
                "name": recipe.name,
                "description": recipe.summary,
                "scenario_pack_id": recipe.pack_id,
                "content_type": recipe.content_type,
                "channels": list(recipe.channels),
                "steps": [
                    {
                        "id": section.id,
                        "name": section.title,
                        "description": section.purpose,
                        "required": section.required,
                    }
                    for section in recipe.sections
                ],
                "output_formats": list(recipe.output_formats),
            }
            for recipe in page
        ]
        return _json_response(
            {
                "items": items,
                "count": len(items),
                "total": len(definitions),
                "limit": command.limit,
                "offset": command.offset,
            }
        )
    except Exception as exc:
        return _exception_response(exc)


async def _academic_action(
    request: Request,
    model: type[WritingRequest],
    operation: str,
) -> Response:
    return await _dispatch_body(
        request,
        model,
        operation,
        path_values=_optional_path_value(request, "project_id"),
    )


async def _dispatch_body(
    request: Request,
    model: type[WritingRequest],
    operation: str,
    *,
    path_values: Mapping[str, object] | None = None,
    status_code: int = 200,
) -> Response:
    try:
        payload = await _read_json_object(request)
        if path_values:
            _inject_path_values(payload, path_values)
        return await _dispatch(
            request,
            model,
            operation,
            payload,
            status_code=status_code,
        )
    except Exception as exc:
        return _exception_response(exc)


async def _dispatch_extension_body(
    request: Request,
    model: type[WritingRequest],
    operation: str,
    *,
    path_values: Mapping[str, object] | None = None,
    status_code: int = 200,
) -> Response:
    try:
        payload = await _read_json_object(request)
        if path_values:
            _inject_path_values(payload, path_values)
        command = model.model_validate(payload)
        result = await _invoke_platform_extension(request, operation, command)
        return _json_response(result, status_code=status_code)
    except Exception as exc:
        return _exception_response(exc)


async def _dispatch(
    request: Request,
    model: type[WritingRequest],
    operation: str,
    payload: Mapping[str, object],
    *,
    status_code: int = 200,
) -> Response:
    try:
        command = model.model_validate(payload)
        result = await _invoke_platform(request, operation, command)
        return _json_response(result, status_code=status_code)
    except Exception as exc:
        return _exception_response(exc)


async def _invoke_platform(
    request: Request,
    operation: str,
    command: WritingRequest,
) -> dict[str, object]:
    tools = YanzhangWritingTools(YanzhangMCPContext(platform=_platform(request)))
    action = cast(
        Callable[[WritingRequest], Awaitable[dict[str, object]]],
        getattr(tools, operation),
    )
    return await action(command)


async def _invoke_platform_extension(
    request: Request,
    operation: str,
    command: WritingRequest,
) -> dict[str, object]:
    platform = _platform(request)
    raw_action = getattr(platform, operation, None)
    if not callable(raw_action):
        raise _TransportProblem(
            501,
            "platform_capability_unavailable",
            "当前平台实现尚未注册该持久化能力",
        )
    action = cast(
        Callable[[WritingRequest], Awaitable[Mapping[str, object]]],
        raw_action,
    )
    try:
        result = dict(await action(command))
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        return result
    except YanzhangToolError:
        raise
    except ValidationError as exc:
        raise YanzhangToolError("invalid_request", _validation_summary(exc)) from None
    except TimeoutError:
        raise YanzhangToolError("operation_timeout", "操作超时。请稍后重试") from None
    except BriefConflictError:
        raise YanzhangToolError("brief_conflict", "任务简报标识已绑定其他内容") from None
    except ProjectScopeError:
        raise YanzhangToolError("project_scope_error", "资源不属于当前项目") from None
    except (KeyError, LookupError):
        raise YanzhangToolError("not_found", "未找到指定资源") from None
    except ValueError:
        raise YanzhangToolError("invalid_request", "请求参数或资源状态不符合要求") from None
    except (TypeError, OverflowError):
        raise YanzhangToolError("invalid_result", "平台结果包含非 JSON 数据") from None
    except Exception:
        raise YanzhangToolError("internal_error", "操作执行异常。请稍后重试") from None


async def _read_json_object(request: Request) -> dict[str, object]:
    maximum = _max_request_bytes(request)
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            raise _TransportProblem(
                400,
                "invalid_content_length",
                "Content-Length 格式有误",
            ) from None
        if declared < 0:
            raise _TransportProblem(400, "invalid_content_length", "Content-Length 格式有误")
        if declared > maximum:
            raise _TransportProblem(413, "request_too_large", "请求内容超过服务端字节上限")
    body = await request.body()
    if len(body) > maximum:
        raise _TransportProblem(413, "request_too_large", "请求内容超过服务端字节上限")
    if not body:
        return {}
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
    if content_type != "application/json":
        raise _TransportProblem(415, "unsupported_media_type", "请求应使用 application/json")
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise _TransportProblem(400, "invalid_json", "请求正文不是有效 JSON") from None
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        raise _TransportProblem(400, "invalid_json_shape", "请求正文应为 JSON 对象")
    return cast(dict[str, object], parsed)


def _inject_path_values(payload: dict[str, object], values: Mapping[str, object]) -> None:
    for key, value in values.items():
        if key in payload and payload[key] != value:
            raise _TransportProblem(409, "identity_mismatch", f"{key} 与请求路径不一致")
        payload[key] = value


def _optional_path_value(request: Request, name: str) -> dict[str, object]:
    value = request.path_params.get(name)
    return {name: value} if isinstance(value, str) else {}


def _asset_path_values(request: Request) -> dict[str, object]:
    values = _optional_path_value(request, "project_id")
    values["asset_id"] = request.path_params["asset_id"]
    return values


def _workflow_path_values(request: Request) -> dict[str, object]:
    values = _optional_path_value(request, "project_id")
    values["workflow_id"] = request.path_params["workflow_id"]
    return values


def _set_optional_path(payload: dict[str, object], request: Request, name: str) -> None:
    value = request.path_params.get(name)
    if isinstance(value, str):
        payload[name] = value


def _path_or_query_project_id(request: Request) -> str | None:
    path_value = request.path_params.get("project_id")
    if isinstance(path_value, str):
        return path_value
    return request.query_params.get("project_id")


def _copy_query(request: Request, *names: str) -> dict[str, object]:
    return {name: value for name in names if (value := request.query_params.get(name)) is not None}


def _query_list(request: Request, name: str) -> list[str]:
    values = request.query_params.getlist(name)
    if len(values) == 1 and "," in values[0]:
        values = values[0].split(",")
    return [value.strip() for value in values if value.strip()]


def _platform(request: Request) -> YanzhangPlatform:
    platform = getattr(request.app.state, "yanzhang_platform", None)
    if platform is None:
        raise _TransportProblem(503, "platform_unavailable", "V2 写作平台尚未注册")
    return cast(YanzhangPlatform, platform)


def _artifact_store(request: Request) -> ArtifactStore:
    store = getattr(request.app.state, "gongwen_artifact_store", None)
    if not isinstance(store, ArtifactStore):
        raise _TransportProblem(503, "artifact_store_unavailable", "导出文件服务尚未注册")
    return store


def _max_request_bytes(request: Request) -> int:
    runtime = getattr(request.app.state, "gongwen_runtime", None)
    maximum = getattr(runtime, "max_request_bytes", _DEFAULT_MAX_REQUEST_BYTES)
    return maximum if isinstance(maximum, int) and maximum > 0 else _DEFAULT_MAX_REQUEST_BYTES


def _filename_suffix(filename: str) -> str:
    if "." not in filename:
        return ""
    suffix = filename.rsplit(".", 1)[-1]
    return f".{suffix}" if suffix.isalnum() and len(suffix) <= 10 else ""


def _exception_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, _TransportProblem):
        return _error_response(exc.status, exc.code, exc.message)
    if isinstance(exc, ValidationError):
        details = [
            {
                "field": ".".join(str(part) for part in item["loc"]),
                "message": item["msg"],
                "type": item["type"],
            }
            for item in exc.errors(include_url=False, include_input=False)[:20]
        ]
        return _error_response(422, "validation_error", "请求字段校验失败", details=details)
    if isinstance(exc, DocumentParseError):
        code = getattr(exc, "code", "document_parse_error")
        status = 413 if code == "document_too_large" else 422
        return _error_response(status, code, str(exc)[:300])
    if isinstance(exc, YanzhangToolError):
        status_by_code = {
            "invalid_request": 422,
            "brief_conflict": 409,
            "project_scope_error": 409,
            "not_found": 404,
            "operation_timeout": 504,
            "invalid_result": 502,
            "internal_error": 500,
        }
        return _error_response(
            status_by_code.get(exc.code, 500),
            exc.code,
            exc.message,
        )
    if isinstance(exc, (ArtifactNotFound, InvalidArtifactId)):
        return _error_response(404, "artifact_not_found", "未找到指定导出文件")
    if isinstance(exc, ArtifactCorrupt):
        return _error_response(500, "artifact_corrupt", "导出文件完整性校验失败")
    return _error_response(500, "internal_error", "服务执行异常。请稍后重试")


def _validation_summary(exc: ValidationError) -> str:
    messages = [
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in exc.errors(include_url=False, include_input=False)[:20]
    ]
    return ";".join(messages)[:500] or "请求字段校验失败"


def _json_response(payload: Mapping[str, object], *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(dict(payload), status_code=status_code, headers=_NO_STORE_HEADERS)


def _error_response(
    status: int,
    code: str,
    message: str,
    *,
    details: list[dict[str, str]] | None = None,
) -> JSONResponse:
    error: dict[str, object] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return JSONResponse(
        {"error": error},
        status_code=status,
        headers=_NO_STORE_HEADERS,
    )


def v2_routes() -> list[BaseRoute]:
    """Return the complete V2 route table for mounting in ``create_app``."""

    routes: list[BaseRoute] = [
        Route("/api/v2/bootstrap", _bootstrap, methods=["GET"]),
        Route("/api/v2/scene-packs", _scene_packs, methods=["GET"]),
        Route("/api/v2/scene-packs/{pack_id:str}", _scene_pack, methods=["GET"]),
        Route("/api/v2/projects", _projects, methods=["GET", "POST"]),
        Route("/api/v2/projects/{project_id:str}", _project, methods=["GET"]),
        Route(
            "/api/v2/projects/{project_id:str}/terms/{term_id:str}",
            _project_term,
            methods=["DELETE"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/terms",
            _project_terms,
            methods=["GET", "POST"],
        ),
        Route("/api/v2/projects/{project_id:str}/briefs", _briefs, methods=["POST"]),
        Route(
            "/api/v2/projects/{project_id:str}/materials/import",
            _import_material,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/materials/{material_id:str}",
            _material,
            methods=["GET"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/materials",
            _materials,
            methods=["GET", "POST"],
        ),
        Route("/api/v2/projects/{project_id:str}/search", _search, methods=["GET"]),
        Route("/api/v2/projects/{project_id:str}/headlines", _headlines, methods=["POST"]),
        Route(
            "/api/v2/projects/{project_id:str}/workflows",
            _project_workflows,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/workflows/{workflow_id:str}/run",
            _run_workflow,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/workflows/{workflow_id:str}/cancel",
            _cancel_workflow,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/workflows/{workflow_id:str}",
            _workflow,
            methods=["GET"],
        ),
        Route("/api/v2/projects/{project_id:str}/assets", _assets, methods=["GET", "POST"]),
        Route(
            "/api/v2/projects/{project_id:str}/assets/{asset_id:str}/variants",
            _variant,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/assets/{asset_id:str}/revisions",
            _revisions,
            methods=["GET", "POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/assets/{asset_id:str}/review",
            _review_asset,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/assets/{asset_id:str}/export",
            _export_asset,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/assets/{asset_id:str}",
            _asset,
            methods=["GET"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/exports/{artifact_id:str}",
            _download_export,
            methods=["GET"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/literature/search",
            _academic_search,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/literature/import",
            _academic_import,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/literature",
            _academic_records,
            methods=["GET"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/literature/{record_id:str}",
            _academic_record,
            methods=["GET"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/evidence/extract",
            _academic_evidence,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/evidence",
            _academic_evidence_list,
            methods=["GET"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/evidence/{evidence_id:str}",
            _academic_evidence_item,
            methods=["GET"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/matrix",
            _academic_matrix,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/matrices",
            _academic_matrices,
            methods=["GET"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/matrices/{matrix_id:str}",
            _academic_matrix_item,
            methods=["GET"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/claims",
            _academic_claims,
            methods=["GET"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/claims/{claim_id:str}",
            _academic_claim,
            methods=["GET"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/citation-links",
            _academic_links,
            methods=["GET"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/citation-links/{link_id:str}",
            _academic_link,
            methods=["GET"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/citations/verify",
            _academic_verify,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/bibliography",
            _academic_bibliography,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/titles",
            _academic_titles,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/outline",
            _academic_outline,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/abstract",
            _academic_abstract,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/integrity",
            _academic_integrity,
            methods=["POST"],
        ),
        Route(
            "/api/v2/projects/{project_id:str}/academic/rebuttal",
            _academic_rebuttal,
            methods=["POST"],
        ),
        # Strict compatibility aliases used by the phase-two browser client.
        Route("/api/v2/headlines/generate", _headlines, methods=["POST"]),
        Route("/api/v2/knowledge/search", _search, methods=["GET"]),
        Route("/api/v2/knowledge", _materials, methods=["GET", "POST"]),
        Route("/api/v2/assets", _assets, methods=["GET", "POST"]),
        Route("/api/v2/assets/{asset_id:str}", _asset, methods=["GET"]),
        Route("/api/v2/assets/{asset_id:str}/variants", _variant, methods=["POST"]),
        Route(
            "/api/v2/assets/{asset_id:str}/revisions",
            _revisions,
            methods=["GET", "POST"],
        ),
        Route("/api/v2/assets/{asset_id:str}/review", _review_asset, methods=["POST"]),
        Route("/api/v2/assets/{asset_id:str}/export", _export_asset, methods=["POST"]),
        Route("/api/v2/academic/search", _academic_search, methods=["POST"]),
        Route("/api/v2/academic/records/import", _academic_import, methods=["POST"]),
        Route(
            "/api/v2/academic/records/{record_id:str}",
            _academic_record,
            methods=["GET"],
        ),
        Route("/api/v2/academic/evidence/extract", _academic_evidence, methods=["POST"]),
        Route("/api/v2/academic/matrix", _academic_matrix, methods=["POST"]),
        Route("/api/v2/academic/claims/verify", _academic_verify, methods=["POST"]),
        Route("/api/v2/academic/citations/format", _academic_bibliography, methods=["POST"]),
        Route("/api/v2/academic/titles", _academic_titles, methods=["POST"]),
        Route("/api/v2/academic/outline", _academic_outline, methods=["POST"]),
        Route("/api/v2/academic/abstract", _academic_abstract, methods=["POST"]),
        Route("/api/v2/academic/integrity", _academic_integrity, methods=["POST"]),
        Route("/api/v2/academic/rebuttal", _academic_rebuttal, methods=["POST"]),
        Route("/api/v2/writing/briefs", _briefs, methods=["POST"]),
        Route("/api/v2/workflow-definitions", _workflow_definitions, methods=["GET"]),
        Route("/api/v2/workflows/{workflow_id:str}/run", _run_workflow, methods=["POST"]),
        Route(
            "/api/v2/workflows/{workflow_id:str}/cancel",
            _cancel_workflow,
            methods=["POST"],
        ),
        Route("/api/v2/workflows/{workflow_id:str}", _workflow, methods=["GET"]),
        Route(
            "/api/v2/exports/{artifact_id:str}",
            _download_legacy_export,
            methods=["GET"],
        ),
    ]
    return routes


V2_ROUTES: Final[tuple[BaseRoute, ...]] = tuple(v2_routes())

__all__ = [
    "V2_ROUTES",
    "CreateAssetRequest",
    "CreateBriefRequest",
    "CreateRevisionRequest",
    "ImportDocumentRequest",
    "ListWorkflowDefinitionsRequest",
    "v2_routes",
]
