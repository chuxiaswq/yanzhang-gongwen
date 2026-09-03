"""Typed request and response models for the personal writing service."""

from __future__ import annotations

from datetime import date
from typing import Literal, Self

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from gongwen_web.methodologies import (
    AppliedContentMethodology,
    CustomContentMethodology,
    CustomTitleFormula,
)
from gongwen_web.resource_limits import (
    MAX_FACT_AUDIT_CONTENT_CHARACTERS,
    MAX_FACT_AUDIT_MATERIAL_CHARACTERS,
    MAX_FACT_AUDIT_MATERIAL_ITEM_CHARACTERS,
    MAX_FACT_AUDIT_MATERIAL_ITEMS,
    MAX_FACT_AUDIT_TITLE_CHARACTERS,
    MAX_FACT_AUDIT_TOTAL_CHARACTERS,
)


class APIModel(BaseModel):
    """Base model with browser-friendly coercion and harmless extra fields."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True, str_strip_whitespace=True)


class ProviderSettings(APIModel):
    """Provider-neutral LLM settings supplied only for an explicit live request."""

    name: str = "openai"
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)
    options: dict[str, object] = Field(default_factory=dict)


class ProviderProbeRequest(APIModel):
    """One explicit, minimal live-provider connectivity check."""

    provider: ProviderSettings


class StyleReference(APIModel):
    """A locally selected article used only for structure and language patterns."""

    id: str = ""
    title: str = Field(default="", max_length=MAX_FACT_AUDIT_TITLE_CHARACTERS)
    source_name: str = Field(
        default="",
        max_length=100,
        validation_alias=AliasChoices("source_name", "source", "publisher"),
    )
    url: str = Field(default="", max_length=2_000)
    published_at: str = Field(default="", max_length=50)
    excerpt: str = Field(default="", max_length=2_000)
    style_features: list[str] = Field(default_factory=list, max_length=12)


class GenerateRequest(APIModel):
    """Inputs used to assemble a complete first draft."""

    document_type: str = Field(
        default="工作总结",
        validation_alias=AliasChoices("document_type", "documentType", "doc_type", "type"),
    )
    topic: str = Field(
        min_length=1,
        max_length=300,
        validation_alias=AliasChoices("topic", "subject", "theme"),
    )
    purpose: str = ""
    audience: str = Field(
        default="",
        validation_alias=AliasChoices("audience", "recipient", "target_audience"),
    )
    materials: str | list[str] = Field(
        default="",
        validation_alias=AliasChoices("materials", "material", "source_materials", "facts"),
    )
    requirements: str = Field(
        default="", validation_alias=AliasChoices("requirements", "instructions", "notes")
    )
    reference_style: str = Field(
        default="权威媒体综合写法",
        validation_alias=AliasChoices("reference_style", "referenceStyle"),
    )
    style_references: list[StyleReference] = Field(
        default_factory=list,
        max_length=8,
        validation_alias=AliasChoices("style_references", "styleReferences", "articles"),
    )
    fact_lock: bool = Field(
        default=True,
        validation_alias=AliasChoices("fact_lock", "factLock"),
    )
    tone: str = "稳健规范"
    length: str = Field(default="标准", validation_alias=AliasChoices("length", "length_level"))
    title_count: int = Field(
        default=5,
        ge=1,
        le=20,
        validation_alias=AliasChoices("title_count", "titleCount"),
    )
    title_formula_ids: list[str] = Field(
        default_factory=list,
        max_length=12,
        validation_alias=AliasChoices("title_formula_ids", "titleFormulaIds"),
    )
    custom_title_formula: CustomTitleFormula | str | None = Field(
        default=None,
        validation_alias=AliasChoices("custom_title_formula", "customTitleFormula"),
    )
    selected_title: str | None = Field(
        default=None,
        max_length=300,
        validation_alias=AliasChoices("selected_title", "selectedTitle", "chosen_title"),
    )
    content_methodology_id: str | None = Field(
        default=None,
        max_length=80,
        validation_alias=AliasChoices("content_methodology_id", "contentMethodologyId"),
    )
    custom_methodology: CustomContentMethodology | None = Field(
        default=None,
        validation_alias=AliasChoices("custom_methodology", "customMethodology"),
    )
    live: bool = False
    provider: ProviderSettings | None = None

    @field_validator("title_formula_ids")
    @classmethod
    def validate_title_formula_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 80 for value in normalized):
            raise ValueError("标题公式标识必须是长度不超过80的非空文本")
        if len(normalized) != len(set(normalized)):
            raise ValueError("标题公式标识不得重复")
        return normalized

    def material_text(self) -> str:
        """Return all supplied material as one normalized block."""

        if isinstance(self.materials, str):
            return self.materials.strip()
        return "\n".join(item.strip() for item in self.materials if item.strip())


class OutlineItem(APIModel):
    """One editable heading and its draft paragraphs."""

    heading: str
    content: str


class TitleCandidate(APIModel):
    """One selectable title proposal with a short editorial rationale."""

    title: str
    style: str
    reason: str
    selected: bool = False
    formula_id: str = ""
    formula_name: str = ""
    score: int | None = Field(default=None, ge=0, le=100)
    score_dimensions: dict[str, int] = Field(default_factory=dict)
    rank: int | None = Field(default=None, ge=1, le=20)


class SourceCard(APIModel):
    """Traceable material card used while constructing the draft."""

    id: str
    label: str
    excerpt: str
    source_type: str = "用户材料"
    url: str = ""
    published_at: str = ""


class GenerationMeta(APIModel):
    """Non-secret lineage metadata shown by the demo UI."""

    mode: Literal["demo", "live"]
    provider: str | None = None
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class GeneratedDocument(APIModel):
    """Complete editable document returned by the drafting endpoint."""

    title: str
    title_candidates: list[TitleCandidate]
    outline: list[OutlineItem]
    content: str
    facts: list[str] = Field(default_factory=list)
    source_cards: list[SourceCard] = Field(default_factory=list)
    placeholders: list[str] = Field(default_factory=list)
    content_methodology: AppliedContentMethodology | None = None
    meta: GenerationMeta


class RewriteRequest(APIModel):
    """A local selection and the requested editing operation."""

    text: str = Field(min_length=1, max_length=100_000)
    instruction: str = "提升表达的规范性、准确性和凝练度"
    mode: str = "polish"
    tone: str = "稳健规范"
    live: bool = False
    provider: ProviderSettings | None = None


class RewriteResult(APIModel):
    """Rewritten text with a compact, user-facing change list."""

    text: str
    changes: list[str]
    meta: GenerationMeta


class ReviewRequest(APIModel):
    """Document content to inspect before Word export."""

    title: str = ""
    content: str = Field(min_length=1, max_length=200_000)
    document_type: str = ""
    materials: str = ""
    live: bool = False
    provider: ProviderSettings | None = None


class FactAuditRequest(APIModel):
    """Content and source materials for deterministic evidence tracing."""

    title: str = Field(default="", max_length=300)
    content: str = Field(min_length=1, max_length=MAX_FACT_AUDIT_CONTENT_CHARACTERS)
    materials: str | list[str] = ""

    @field_validator("materials")
    @classmethod
    def _bound_materials(cls, value: str | list[str]) -> str | list[str]:
        items = [value] if isinstance(value, str) else value
        if len(items) > MAX_FACT_AUDIT_MATERIAL_ITEMS:
            raise ValueError(f"参考材料最多 {MAX_FACT_AUDIT_MATERIAL_ITEMS} 项")
        if any(len(item) > MAX_FACT_AUDIT_MATERIAL_ITEM_CHARACTERS for item in items):
            raise ValueError(f"单项参考材料最多 {MAX_FACT_AUDIT_MATERIAL_ITEM_CHARACTERS} 个字符")
        if sum(len(item) for item in items) > MAX_FACT_AUDIT_MATERIAL_CHARACTERS:
            raise ValueError(f"参考材料合计最多 {MAX_FACT_AUDIT_MATERIAL_CHARACTERS} 个字符")
        return value

    @model_validator(mode="after")
    def _bound_total_characters(self) -> Self:
        material_items = [self.materials] if isinstance(self.materials, str) else self.materials
        total = len(self.content) + sum(len(item) for item in material_items)
        if total > MAX_FACT_AUDIT_TOTAL_CHARACTERS:
            raise ValueError(f"正文和参考材料合计最多 {MAX_FACT_AUDIT_TOTAL_CHARACTERS} 个字符")
        return self


class DocumentSaveRequest(APIModel):
    """A server-side document snapshot with optimistic version metadata."""

    id: str | None = Field(default=None, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=500_000)
    document_type: str = Field(default="", max_length=100)
    metadata: dict[str, object] = Field(default_factory=dict)
    version_note: str = Field(default="", max_length=500)
    expected_version: int | None = Field(default=None, ge=0)


class ArticleTextImportRequest(APIModel):
    """An article the user explicitly pasted into the local reference library."""

    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=2_000_000)
    source_id: str = Field(default="manual", max_length=50)
    source_name: str = Field(default="用户导入", max_length=100)
    url: str | None = Field(default=None, max_length=2_000)
    published_date: str | None = Field(default=None, max_length=50)
    summary: str | None = Field(default=None, max_length=500)
    style_features: list[str] = Field(default_factory=list, max_length=20)


class ArticleURLImportRequest(APIModel):
    """A user-triggered official article URL import."""

    url: str = Field(min_length=1, max_length=2_000)
    source_id: str | None = Field(default=None, max_length=50)
    style_features: list[str] = Field(default_factory=list, max_length=20)


class ArticleAutoCollectRequest(APIModel):
    """Strict, bounded scope for one provider-backed article collection run."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    keywords: list[StrictStr] = Field(min_length=1, max_length=20)
    source_ids: list[StrictStr] = Field(
        min_length=1,
        max_length=10,
        validation_alias=AliasChoices("source_ids", "sources"),
    )
    start_date: date | None = Field(
        default=None,
        validation_alias=AliasChoices("start_date", "date_from"),
    )
    end_date: date | None = Field(
        default=None,
        validation_alias=AliasChoices("end_date", "date_to"),
    )
    limit: StrictInt = Field(default=20, ge=1, le=100)

    @field_validator("keywords", "source_ids")
    @classmethod
    def _normalize_unique_values(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(" ".join(value.split()) for value in values))
        if any(not value for value in normalized):
            raise ValueError("列表项不能为空")
        return normalized

    @field_validator("keywords")
    @classmethod
    def _bound_keywords(cls, values: list[str]) -> list[str]:
        if any(len(value) > 100 for value in values):
            raise ValueError("单个检索关键词不能超过 100 个字符")
        return values

    @field_validator("source_ids")
    @classmethod
    def _bound_source_ids(cls, values: list[str]) -> list[str]:
        if any(len(value) > 50 for value in values):
            raise ValueError("文章来源标识不能超过 50 个字符")
        return values

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _require_iso_date_input(cls, value: object) -> object:
        if value is None or isinstance(value, (str, date)):
            return value
        raise ValueError("日期必须使用 YYYY-MM-DD 格式")

    @model_validator(mode="after")
    def _validate_date_range(self) -> Self:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("start_date 不能晚于 end_date")
        return self


class ReviewIssue(APIModel):
    """One actionable writing or completeness observation."""

    level: Literal["error", "warning", "suggestion"]
    category: str
    message: str
    suggestion: str


class ReviewMetrics(APIModel):
    """Deterministic document-quality counters."""

    character_count: int
    paragraph_count: int
    heading_count: int
    long_sentence_count: int
    vague_expression_count: int
    placeholder_count: int


class ReviewResult(APIModel):
    """Review score, observations and measurable document properties."""

    score: int = Field(ge=0, le=100)
    summary: str
    issues: list[ReviewIssue]
    metrics: ReviewMetrics
    meta: GenerationMeta


class ExportDocument(APIModel):
    """Content and optional metadata for one generated Word file."""

    title: str = Field(default="公文", max_length=300)
    content: str = Field(min_length=1, max_length=500_000)
    metadata: dict[str, object] = Field(default_factory=dict)
    template_style: Literal["standard", "brief"] = Field(
        default="standard",
        validation_alias=AliasChoices(
            "template_style", "templateStyle", "template", "style", "layout"
        ),
    )
    filename: str | None = None


class BatchExportRequest(APIModel):
    """A mail-merge style template, data rows, or ready-made documents."""

    template: ExportDocument | str | None = None
    document: ExportDocument | None = None
    rows: list[dict[str, object]] = Field(default_factory=list, max_length=200)
    documents: list[ExportDocument] = Field(default_factory=list, max_length=200)
    filename: str = "批量公文.zip"


__all__ = [
    "AppliedContentMethodology",
    "ArticleAutoCollectRequest",
    "ArticleTextImportRequest",
    "ArticleURLImportRequest",
    "BatchExportRequest",
    "CustomContentMethodology",
    "CustomTitleFormula",
    "DocumentSaveRequest",
    "ExportDocument",
    "FactAuditRequest",
    "GenerateRequest",
    "GeneratedDocument",
    "GenerationMeta",
    "OutlineItem",
    "ProviderProbeRequest",
    "ProviderSettings",
    "ReviewIssue",
    "ReviewMetrics",
    "ReviewRequest",
    "ReviewResult",
    "RewriteRequest",
    "RewriteResult",
    "SourceCard",
    "StyleReference",
    "TitleCandidate",
]
