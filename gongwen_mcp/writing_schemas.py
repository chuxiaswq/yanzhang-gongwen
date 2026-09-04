"""Strict input contracts for the provider-neutral Yanzhang MCP surface."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from yanzhang_academic.models import (
    CitationStyle,
    ClaimCitationLink,
    JournalProfile,
    ResearchClaim,
    ReviewComment,
)
from yanzhang_core.models import AssetStatus, Channel, KnowledgeKind
from yanzhang_core.packs import HeadlineKind, ScenarioPackId

type SearchScope = Literal["all", "materials", "assets", "literature"]
type WorkflowMode = Literal["sync", "background"]
type WorkflowResumeStep = Literal[
    "research",
    "titles",
    "outline",
    "draft",
    "review",
    "export",
]
type ReviewCheck = Literal[
    "structure",
    "style",
    "facts",
    "citations",
    "terminology",
]
type AssetExportFormat = Literal[
    "docx",
    "markdown",
    "text",
    "html",
    "pdf",
    "latex",
    "csv",
]
type AssetTemplateId = Literal["standard", "brief"]
type LiteratureProvider = Literal["crossref", "openalex", "arxiv"]
type LiteratureImportFormat = Literal["bibtex", "ris", "csl-json"]


def _default_review_checks() -> list[ReviewCheck]:
    return ["structure", "style", "facts", "citations"]


class WritingRequest(BaseModel):
    """Closed MCP request model with bounded, predictable JSON input."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class StatusRequest(WritingRequest):
    """Request the public platform readiness summary."""


class ListScenePacksRequest(WritingRequest):
    channel: Channel | None = None
    content_type: str | None = Field(default=None, min_length=1, max_length=100)


class GetScenePackRequest(WritingRequest):
    pack_id: ScenarioPackId


class CreateProjectRequest(WritingRequest):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)
    scenario_pack_id: ScenarioPackId = "gongwen"
    tags: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "tags", max_item_length=100)


class ListProjectsRequest(WritingRequest):
    query: str | None = Field(default=None, min_length=1, max_length=200)
    scenario_pack_id: ScenarioPackId | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class GetProjectRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)


class UpsertProjectTermRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    term_id: str | None = Field(default=None, min_length=1, max_length=128)
    term: str = Field(min_length=1, max_length=200)
    preferred_form: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    discouraged_variants: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("discouraged_variants")
    @classmethod
    def validate_variants(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "discouraged_variants", max_item_length=200)


class ListProjectTermsRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class DeleteProjectTermRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    term_id: str = Field(min_length=1, max_length=128)


class AddMaterialRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=500_000)
    kind: KnowledgeKind = "source"
    source_url: str = Field(default="", max_length=2_000)
    tags: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "tags", max_item_length=100)


class ListMaterialsRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    query: str | None = Field(default=None, min_length=1, max_length=2_000)
    kind: KnowledgeKind | None = None
    tags: list[str] = Field(default_factory=list, max_length=32)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "tags", max_item_length=100)


class GetMaterialRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    material_id: str = Field(min_length=1, max_length=128)
    chunk_offset: int = Field(default=0, ge=0, le=500_000)
    chunk_size: int = Field(default=8_000, ge=500, le=20_000)


class UnifiedSearchRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=2_000)
    scope: SearchScope = "all"
    tags: list[str] = Field(default_factory=list, max_length=32)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "tags", max_item_length=100)


class _BriefRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    topic: str = Field(min_length=1, max_length=500)
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
    material_ids: list[str] = Field(default_factory=list, max_length=128)
    model_profile_id: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("constraints", "keywords")
    @classmethod
    def validate_short_lists(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "列表字段", max_item_length=500)

    @field_validator("material_ids")
    @classmethod
    def validate_material_ids(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "material_ids", max_item_length=128)


class GenerateTitlesRequest(_BriefRequest):
    count: int = Field(default=8, ge=1, le=12)
    headline_kind: HeadlineKind = "title"
    formula_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("formula_ids")
    @classmethod
    def validate_formula_ids(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "formula_ids", max_item_length=100)


class CreateWorkflowRequest(_BriefRequest):
    auto_review: bool = True
    requested_exports: list[AssetExportFormat] = Field(default_factory=list, max_length=7)

    @field_validator("requested_exports")
    @classmethod
    def validate_exports(cls, values: list[AssetExportFormat]) -> list[AssetExportFormat]:
        if len(values) != len(set(values)):
            raise ValueError("requested_exports 不得重复")
        return values


class RunWorkflowRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=128)
    mode: WorkflowMode = "sync"
    resume_from: WorkflowResumeStep | None = None


class GetWorkflowRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=128)


class CancelWorkflowRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=128)


class ListAssetsRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    status: AssetStatus | None = None
    content_type: str | None = Field(default=None, min_length=1, max_length=100)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class GetAssetRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    asset_id: str = Field(min_length=1, max_length=128)
    revision: int | None = Field(default=None, ge=1)
    chunk_offset: int = Field(default=0, ge=0, le=500_000)
    chunk_size: int = Field(default=8_000, ge=500, le=20_000)


class CreateVariantRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    asset_id: str = Field(min_length=1, max_length=128)
    target_channel: Channel
    instruction: str = Field(default="", max_length=4_000)
    source_revision: int | None = Field(default=None, ge=1)
    model_profile_id: str | None = Field(default=None, min_length=1, max_length=100)
    live: bool = False


class ListRevisionsRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    asset_id: str = Field(min_length=1, max_length=128)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class ReviewAssetRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    asset_id: str = Field(min_length=1, max_length=128)
    checks: list[ReviewCheck] = Field(
        default_factory=_default_review_checks,
        min_length=1,
        max_length=5,
    )
    material_ids: list[str] = Field(default_factory=list, max_length=128)
    model_profile_id: str | None = Field(default=None, min_length=1, max_length=100)
    live: bool = False

    @field_validator("checks")
    @classmethod
    def validate_checks(cls, values: list[ReviewCheck]) -> list[ReviewCheck]:
        if len(values) != len(set(values)):
            raise ValueError("checks 不得重复")
        return values

    @field_validator("material_ids")
    @classmethod
    def validate_material_ids(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "material_ids", max_item_length=128)


class ExportAssetRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    asset_id: str = Field(min_length=1, max_length=128)
    format: AssetExportFormat = "docx"
    revision: int | None = Field(default=None, ge=1)
    template_id: AssetTemplateId | None = None
    filename: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_template_format(self) -> Self:
        if self.template_id is not None and self.format != "docx":
            raise ValueError("template_id 仅适用于 DOCX 导出")
        return self


class SearchLiteratureRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=1_000)
    provider: LiteratureProvider = "crossref"
    limit: int = Field(default=10, ge=1, le=50)


class ImportLiteratureRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=2_000_000)
    format: LiteratureImportFormat
    tags: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "tags", max_item_length=100)


class GetLiteratureRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    record_id: str = Field(min_length=1, max_length=200)
    include_abstract: bool = True


class ListLiteratureRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    query: str | None = Field(default=None, min_length=1, max_length=1_000)
    include_abstract: bool = False
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class ListEvidenceRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    record_id: str | None = Field(default=None, min_length=1, max_length=200)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class GetEvidenceRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    evidence_id: str = Field(min_length=1, max_length=200)


class ExtractEvidenceRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    record_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=500_000)
    query: str = Field(default="", max_length=2_000)
    max_snippets: int = Field(default=20, ge=1, le=100)


class BuildLiteratureMatrixRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    record_ids: list[str] = Field(min_length=1, max_length=1_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=1_000)
    query: str = Field(default="", max_length=2_000)

    @field_validator("record_ids", "evidence_ids")
    @classmethod
    def validate_ids(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "引用标识", max_item_length=200)


class ListLiteratureMatricesRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class GetLiteratureMatrixRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    matrix_id: str = Field(min_length=1, max_length=200)


class ListResearchClaimsRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class GetResearchClaimRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    claim_id: str = Field(min_length=1, max_length=200)


class ListCitationLinksRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    claim_id: str | None = Field(default=None, min_length=1, max_length=200)
    record_id: str | None = Field(default=None, min_length=1, max_length=200)
    evidence_id: str | None = Field(default=None, min_length=1, max_length=200)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class GetCitationLinkRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    link_id: str = Field(min_length=1, max_length=200)


class VerifyCitationsRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    record_ids: list[str] = Field(min_length=1, max_length=1_000)
    evidence_ids: list[str] = Field(min_length=1, max_length=1_000)
    claims: list[ResearchClaim] = Field(min_length=1, max_length=500)
    links: list[ClaimCitationLink] = Field(default_factory=list, max_length=1_000)

    @field_validator("record_ids", "evidence_ids")
    @classmethod
    def validate_ids(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "引用标识", max_item_length=200)


class FormatBibliographyRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    record_ids: list[str] = Field(min_length=1, max_length=1_000)
    style: CitationStyle = "gb-t-7714"

    @field_validator("record_ids")
    @classmethod
    def validate_record_ids(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "record_ids", max_item_length=200)


class _AcademicBriefRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    research_question: str = Field(min_length=1, max_length=2_000)
    discipline: str = Field(default="", max_length=200)
    purpose: str = Field(default="", max_length=2_000)
    audience: str = Field(default="学术读者", min_length=1, max_length=200)
    document_type: str = Field(default="研究论文", min_length=1, max_length=100)
    language: str = Field(default="zh-CN", min_length=2, max_length=20)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    constraints: list[str] = Field(default_factory=list, max_length=30)
    method_notes: str = Field(default="", max_length=10_000)
    record_ids: list[str] = Field(default_factory=list, max_length=1_000)

    @field_validator("keywords", "constraints")
    @classmethod
    def validate_terms(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "列表字段", max_item_length=500)

    @field_validator("record_ids")
    @classmethod
    def validate_record_ids(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "record_ids", max_item_length=200)


class SuggestAcademicTitlesRequest(_AcademicBriefRequest):
    count: int = Field(default=5, ge=1, le=10)


class CreateAcademicOutlineRequest(_AcademicBriefRequest):
    evidence_ids: list[str] = Field(default_factory=list, max_length=1_000)

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "evidence_ids", max_item_length=200)


class DraftAbstractRequest(_AcademicBriefRequest):
    claims: list[ResearchClaim] = Field(default_factory=list, max_length=500)
    links: list[ClaimCitationLink] = Field(default_factory=list, max_length=1_000)
    max_characters: int = Field(default=800, ge=100, le=20_000)


class ReviewAcademicIntegrityRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    manuscript: str = Field(min_length=1, max_length=1_000_000)
    record_ids: list[str] = Field(default_factory=list, max_length=1_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=1_000)
    claims: list[ResearchClaim] = Field(default_factory=list, max_length=500)
    links: list[ClaimCitationLink] = Field(default_factory=list, max_length=1_000)
    journal: JournalProfile | None = None

    @field_validator("record_ids", "evidence_ids")
    @classmethod
    def validate_ids(cls, values: list[str]) -> list[str]:
        return _unique_text(values, "引用标识", max_item_length=200)


class PrepareRebuttalRequest(WritingRequest):
    project_id: str = Field(min_length=1, max_length=128)
    comments: list[ReviewComment] = Field(min_length=1, max_length=200)
    changes: dict[str, str] = Field(default_factory=dict, max_length=200)

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        for key, value in self.changes.items():
            if not key.strip() or len(key) > 200:
                raise ValueError("changes 字段名长度须为 1 至 200")
            if len(value) > 20_000:
                raise ValueError("changes 字段值最多 20000 个字符")
        return self


def _unique_text(values: list[str], name: str, *, max_item_length: int) -> list[str]:
    cleaned = [value.strip() for value in values]
    if any(not value for value in cleaned):
        raise ValueError(f"{name} 不得包含空值")
    if any(len(value) > max_item_length for value in cleaned):
        raise ValueError(f"{name} 单项最多 {max_item_length} 个字符")
    if len(cleaned) != len(set(cleaned)):
        raise ValueError(f"{name} 不得重复")
    return cleaned


__all__ = [
    "AddMaterialRequest",
    "AssetExportFormat",
    "AssetTemplateId",
    "BuildLiteratureMatrixRequest",
    "CancelWorkflowRequest",
    "CreateAcademicOutlineRequest",
    "CreateProjectRequest",
    "CreateVariantRequest",
    "CreateWorkflowRequest",
    "DeleteProjectTermRequest",
    "DraftAbstractRequest",
    "ExportAssetRequest",
    "ExtractEvidenceRequest",
    "FormatBibliographyRequest",
    "GenerateTitlesRequest",
    "GetAssetRequest",
    "GetCitationLinkRequest",
    "GetEvidenceRequest",
    "GetLiteratureMatrixRequest",
    "GetLiteratureRequest",
    "GetMaterialRequest",
    "GetProjectRequest",
    "GetResearchClaimRequest",
    "GetScenePackRequest",
    "GetWorkflowRequest",
    "ImportLiteratureRequest",
    "ListAssetsRequest",
    "ListCitationLinksRequest",
    "ListEvidenceRequest",
    "ListLiteratureMatricesRequest",
    "ListLiteratureRequest",
    "ListMaterialsRequest",
    "ListProjectTermsRequest",
    "ListProjectsRequest",
    "ListResearchClaimsRequest",
    "ListRevisionsRequest",
    "ListScenePacksRequest",
    "LiteratureImportFormat",
    "LiteratureProvider",
    "PrepareRebuttalRequest",
    "ReviewAcademicIntegrityRequest",
    "ReviewAssetRequest",
    "ReviewCheck",
    "RunWorkflowRequest",
    "SearchLiteratureRequest",
    "SearchScope",
    "StatusRequest",
    "SuggestAcademicTitlesRequest",
    "UnifiedSearchRequest",
    "UpsertProjectTermRequest",
    "VerifyCitationsRequest",
    "WorkflowMode",
    "WorkflowResumeStep",
    "WritingRequest",
]
