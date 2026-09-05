"""Strict, bounded input contracts for the Gongwen MCP boundary."""

from __future__ import annotations

import json
from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from gongwen_web.methodologies import CustomContentMethodology, CustomTitleFormula
from gongwen_web.resource_limits import (
    MAX_FACT_AUDIT_CONTENT_CHARACTERS,
    MAX_FACT_AUDIT_MATERIAL_CHARACTERS,
    MAX_FACT_AUDIT_MATERIAL_ITEM_CHARACTERS,
    MAX_FACT_AUDIT_MATERIAL_ITEMS,
    MAX_FACT_AUDIT_TOTAL_CHARACTERS,
)

type EngineMode = Literal["auto", "server", "local"]
type TemplateStyle = Literal["standard", "brief"]

_MAX_METADATA_JSON_CHARACTERS = 100_000
_MAX_MAIL_MERGE_ROWS_JSON_CHARACTERS = 1_000_000
_MAX_MAPPING_KEYS = 100
_MAX_MAPPING_KEY_CHARACTERS = 100
_MAX_MAPPING_VALUE_JSON_CHARACTERS = 100_000


class MCPModel(BaseModel):
    """Closed MCP input model with predictable JSON values."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class EmptyRequest(MCPModel):
    """An explicitly empty request used by discovery/status tools."""


class StatusRequest(EmptyRequest):
    """Read deployment and model readiness without exposing secrets."""


class MethodsRequest(MCPModel):
    document_type: str | None = Field(default=None, min_length=1, max_length=100)


class _WritingContext(MCPModel):
    document_type: str = Field(default="工作总结", min_length=1, max_length=100)
    topic: str = Field(min_length=1, max_length=300)
    purpose: str = Field(default="", max_length=2_000)
    audience: str = Field(default="", max_length=500)
    materials: str | list[str] = Field(default="")
    tone: str = Field(default="稳健规范", max_length=100)
    reference_style: str = Field(default="权威媒体综合写法", max_length=100)
    style_reference_ids: list[str] = Field(default_factory=list, max_length=8)
    engine: EngineMode = "auto"

    @field_validator("style_reference_ids")
    @classmethod
    def _unique_reference_ids(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, name="style_reference_ids", maximum=128)

    @field_validator("materials")
    @classmethod
    def _bound_materials(cls, value: str | list[str]) -> str | list[str]:
        items = [value] if isinstance(value, str) else value
        if len(items) > MAX_FACT_AUDIT_MATERIAL_ITEMS:
            raise ValueError(f"materials 最多 {MAX_FACT_AUDIT_MATERIAL_ITEMS} 项")
        if any(len(item) > MAX_FACT_AUDIT_MATERIAL_ITEM_CHARACTERS for item in items):
            raise ValueError(f"materials 单项最多 {MAX_FACT_AUDIT_MATERIAL_ITEM_CHARACTERS} 个字符")
        if sum(len(item) for item in items) > MAX_FACT_AUDIT_MATERIAL_CHARACTERS:
            raise ValueError(f"materials 合计最多 {MAX_FACT_AUDIT_MATERIAL_CHARACTERS} 个字符")
        return value


class GenerateTitlesRequest(_WritingContext):
    count: int = Field(default=5, ge=1, le=20)
    formula_ids: list[str] = Field(default_factory=list, max_length=12)
    custom_title_formula: CustomTitleFormula | str | None = None

    @field_validator("formula_ids")
    @classmethod
    def _unique_formula_ids(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, name="formula_ids", maximum=80)

    @field_validator("custom_title_formula")
    @classmethod
    def _bound_custom_title_formula(
        cls, value: CustomTitleFormula | str | None
    ) -> CustomTitleFormula | str | None:
        if isinstance(value, str) and len(value) > 500:
            raise ValueError("custom_title_formula 最多 500 个字符")
        return value


class GenerateDocumentRequest(_WritingContext):
    requirements: str = Field(default="", max_length=4_000)
    fact_lock: bool = True
    length: str = Field(default="标准", max_length=50)
    title_count: int = Field(default=5, ge=1, le=20)
    title_formula_ids: list[str] = Field(default_factory=list, max_length=12)
    custom_title_formula: CustomTitleFormula | str | None = None
    selected_title: str | None = Field(default=None, min_length=1, max_length=300)
    content_methodology_id: str | None = Field(default=None, min_length=1, max_length=80)
    custom_methodology: CustomContentMethodology | None = None
    document_id: str | None = Field(default=None, min_length=1, max_length=128)
    expected_version: int | None = Field(default=None, ge=0)
    version_note: str = Field(default="MCP 自动生成", max_length=500)

    @field_validator("title_formula_ids")
    @classmethod
    def _unique_title_formula_ids(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, name="title_formula_ids", maximum=80)

    @field_validator("custom_title_formula")
    @classmethod
    def _bound_custom_title_formula(
        cls, value: CustomTitleFormula | str | None
    ) -> CustomTitleFormula | str | None:
        if isinstance(value, str) and len(value) > 500:
            raise ValueError("custom_title_formula 最多 500 个字符")
        return value

    @model_validator(mode="after")
    def _require_explicit_version_intent(self) -> Self:
        _validate_document_version_intent(self.document_id, self.expected_version)
        return self


class RewriteTextRequest(MCPModel):
    document_type: str = Field(default="", max_length=100)
    text: str = Field(min_length=1, max_length=100_000)
    instruction: str = Field(default="提升表达的规范性、准确性和凝练度", max_length=2_000)
    mode: str = Field(default="polish", max_length=80)
    tone: str = Field(default="稳健规范", max_length=100)
    engine: EngineMode = "auto"


class ReviewDocumentRequest(MCPModel):
    title: str = Field(default="", max_length=300)
    content: str = Field(min_length=1, max_length=200_000)
    document_type: str = Field(default="", max_length=100)
    materials: str = Field(default="", max_length=50_000)
    engine: EngineMode = "auto"
    compact: bool = True


class AuditDocumentRequest(MCPModel):
    title: str = Field(default="", max_length=300)
    content: str = Field(min_length=1, max_length=MAX_FACT_AUDIT_CONTENT_CHARACTERS)
    materials: str | list[str] = Field(default="")
    compact: bool = True

    @field_validator("materials")
    @classmethod
    def _bound_materials(cls, value: str | list[str]) -> str | list[str]:
        items = [value] if isinstance(value, str) else value
        if len(items) > MAX_FACT_AUDIT_MATERIAL_ITEMS:
            raise ValueError(f"materials 最多 {MAX_FACT_AUDIT_MATERIAL_ITEMS} 项")
        if any(len(item) > MAX_FACT_AUDIT_MATERIAL_ITEM_CHARACTERS for item in items):
            raise ValueError(f"materials 单项最多 {MAX_FACT_AUDIT_MATERIAL_ITEM_CHARACTERS} 个字符")
        if sum(len(item) for item in items) > MAX_FACT_AUDIT_MATERIAL_CHARACTERS:
            raise ValueError(f"materials 合计最多 {MAX_FACT_AUDIT_MATERIAL_CHARACTERS} 个字符")
        return value

    @model_validator(mode="after")
    def _bound_total(self) -> Self:
        items = [self.materials] if isinstance(self.materials, str) else self.materials
        if len(self.content) + sum(len(item) for item in items) > MAX_FACT_AUDIT_TOTAL_CHARACTERS:
            raise ValueError(
                f"content 和 materials 合计最多 {MAX_FACT_AUDIT_TOTAL_CHARACTERS} 个字符"
            )
        return self


class SaveDocumentRequest(MCPModel):
    document_id: str | None = Field(default=None, min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=500_000)
    document_type: str = Field(default="", max_length=100)
    metadata: dict[str, JsonValue] = Field(default_factory=dict, max_length=100)
    version_note: str = Field(default="", max_length=500)
    expected_version: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _bound_metadata(self) -> Self:
        _validate_mapping(self.metadata, name="metadata")
        if _json_characters(self.metadata) > _MAX_METADATA_JSON_CHARACTERS:
            raise ValueError(f"metadata 最多 {_MAX_METADATA_JSON_CHARACTERS} 个 JSON 字符")
        _validate_document_version_intent(self.document_id, self.expected_version)
        return self


class ListDocumentsRequest(MCPModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)
    search: str | None = Field(default=None, min_length=1, max_length=200)


class ReadDocumentRequest(MCPModel):
    document_id: str = Field(min_length=1, max_length=128)
    chunk_offset: int = Field(default=0, ge=0, le=500_000)
    chunk_size: int = Field(default=8_000, ge=500, le=20_000)


class ListVersionsRequest(MCPModel):
    document_id: str = Field(min_length=1, max_length=128)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class ReadVersionRequest(ReadDocumentRequest):
    version: int = Field(ge=1)


class DeleteDocumentRequest(MCPModel):
    document_id: str = Field(min_length=1, max_length=128)


class ListArticleSourcesRequest(EmptyRequest):
    """List configured source boundaries without initiating network activity."""


class SearchArticlesRequest(MCPModel):
    query: str = Field(default="", max_length=200)
    source_id: str | None = Field(default=None, min_length=1, max_length=50)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class ReadArticleRequest(MCPModel):
    article_id: str = Field(min_length=1, max_length=128)
    chunk_offset: int = Field(default=0, ge=0, le=2_000_000)
    chunk_size: int = Field(default=8_000, ge=500, le=20_000)


class GetStyleReferencesRequest(MCPModel):
    article_ids: list[str] = Field(min_length=1, max_length=8)
    max_excerpt_chars: int = Field(default=360, ge=80, le=1_000)

    @field_validator("article_ids")
    @classmethod
    def _unique_article_ids(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, name="article_ids", maximum=128)


class ImportArticleTextRequest(MCPModel):
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=2_000_000)
    source_id: str = Field(default="manual", min_length=1, max_length=50)
    source_name: str = Field(default="用户导入", min_length=1, max_length=100)
    url: str | None = Field(default=None, min_length=1, max_length=2_000)
    published_date: str | None = Field(default=None, min_length=1, max_length=50)
    summary: str | None = Field(default=None, min_length=1, max_length=500)
    style_features: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("style_features")
    @classmethod
    def _bound_style_features(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, name="style_features", maximum=80)


class ImportArticleURLRequest(MCPModel):
    url: str = Field(min_length=1, max_length=2_000)
    source_id: str | None = Field(default=None, min_length=1, max_length=50)
    style_features: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("style_features")
    @classmethod
    def _bound_style_features(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, name="style_features", maximum=80)


class CollectArticlesRequest(MCPModel):
    keywords: list[str] = Field(min_length=1, max_length=20)
    source_ids: list[str] = Field(min_length=1, max_length=10)
    start_date: date | None = None
    end_date: date | None = None
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator("keywords")
    @classmethod
    def _unique_keywords(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, name="keywords", maximum=100)

    @field_validator("source_ids")
    @classmethod
    def _unique_source_ids(cls, values: list[str]) -> list[str]:
        return _unique_ids(values, name="source_ids", maximum=50)

    @model_validator(mode="after")
    def _ordered_dates(self) -> Self:
        if self.start_date is not None and self.end_date is not None:
            if self.start_date > self.end_date:
                raise ValueError("start_date 应早于或等于 end_date")
        return self


class DeleteArticleRequest(MCPModel):
    article_id: str = Field(min_length=1, max_length=128)


class ExportDocxRequest(MCPModel):
    document_id: str = Field(min_length=1, max_length=128)
    version: int | None = Field(default=None, ge=1)
    template_style: TemplateStyle = "standard"
    filename: str | None = Field(default=None, min_length=1, max_length=120)


class ExportDocumentRef(MCPModel):
    document_id: str = Field(min_length=1, max_length=128)
    version: int | None = Field(default=None, ge=1)
    template_style: TemplateStyle = "standard"
    filename: str | None = Field(default=None, min_length=1, max_length=120)


class ExportDocumentsZipRequest(MCPModel):
    documents: list[ExportDocumentRef] = Field(min_length=1, max_length=50)
    filename: str = Field(default="批量公文.zip", min_length=1, max_length=120)


class MailMergeDocxRequest(MCPModel):
    document_id: str = Field(min_length=1, max_length=128)
    version: int | None = Field(default=None, ge=1)
    rows: list[dict[str, JsonValue]] = Field(min_length=1, max_length=200)
    template_style: TemplateStyle = "standard"
    filename: str = Field(default="批量公文.zip", min_length=1, max_length=120)

    @model_validator(mode="after")
    def _bound_rows(self) -> Self:
        for index, row in enumerate(self.rows, start=1):
            _validate_mapping(row, name=f"rows[{index}]")
        if _json_characters(self.rows) > _MAX_MAIL_MERGE_ROWS_JSON_CHARACTERS:
            raise ValueError(f"rows 最多 {_MAX_MAIL_MERGE_ROWS_JSON_CHARACTERS} 个 JSON 字符")
        return self


class TestModelRequest(MCPModel):
    engine: EngineMode = "auto"


class GetModelUsageRequest(MCPModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


def _unique_ids(values: list[str], *, name: str, maximum: int) -> list[str]:
    normalized = [" ".join(value.split()) for value in values]
    if any(not value or len(value) > maximum for value in normalized):
        raise ValueError(f"{name} 应包含长度不超过 {maximum} 的非空文本")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{name} 不应包含重复项")
    return normalized


def _json_characters(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")))


def _validate_mapping(value: dict[str, JsonValue], *, name: str) -> None:
    if len(value) > _MAX_MAPPING_KEYS:
        raise ValueError(f"{name} 最多 {_MAX_MAPPING_KEYS} 个字段")
    if any(not key.strip() or len(key) > _MAX_MAPPING_KEY_CHARACTERS for key in value):
        raise ValueError(f"{name} 字段名应为长度不超过 {_MAX_MAPPING_KEY_CHARACTERS} 的非空文本")
    if any(_json_characters(item) > _MAX_MAPPING_VALUE_JSON_CHARACTERS for item in value.values()):
        raise ValueError(f"{name} 单个字段值最多 {_MAX_MAPPING_VALUE_JSON_CHARACTERS} 个 JSON 字符")


def _validate_document_version_intent(
    document_id: str | None,
    expected_version: int | None,
) -> None:
    if document_id is not None and expected_version is None:
        raise ValueError("提供 document_id 时也应提供 expected_version; 新建使用 0")
    if document_id is None and expected_version is not None:
        raise ValueError("提供 expected_version 时也应提供 document_id")


__all__ = [
    "AuditDocumentRequest",
    "CollectArticlesRequest",
    "DeleteArticleRequest",
    "DeleteDocumentRequest",
    "EmptyRequest",
    "EngineMode",
    "ExportDocumentRef",
    "ExportDocumentsZipRequest",
    "ExportDocxRequest",
    "GenerateDocumentRequest",
    "GenerateTitlesRequest",
    "GetModelUsageRequest",
    "GetStyleReferencesRequest",
    "ImportArticleTextRequest",
    "ImportArticleURLRequest",
    "ListArticleSourcesRequest",
    "ListDocumentsRequest",
    "ListVersionsRequest",
    "MCPModel",
    "MailMergeDocxRequest",
    "MethodsRequest",
    "ReadArticleRequest",
    "ReadDocumentRequest",
    "ReadVersionRequest",
    "ReviewDocumentRequest",
    "RewriteTextRequest",
    "SaveDocumentRequest",
    "SearchArticlesRequest",
    "StatusRequest",
    "TemplateStyle",
    "TestModelRequest",
]
