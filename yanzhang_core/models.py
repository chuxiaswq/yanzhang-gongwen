"""Strict, provider-neutral data contracts for the Yanzhang writing core."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal, Self, get_origin
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

type Channel = Literal[
    "document",
    "email",
    "meeting",
    "presentation",
    "web",
    "social",
    "academic",
]
type ContentBlockKind = Literal[
    "title",
    "subtitle",
    "abstract",
    "heading",
    "paragraph",
    "list",
    "table",
    "quote",
    "callout",
    "action_item",
    "references",
]
type KnowledgeKind = Literal[
    "source",
    "style_reference",
    "prior_asset",
    "terminology",
    "note",
]
type AssetStatus = Literal["draft", "reviewed", "final", "archived"]
type ClaimKind = Literal["fact", "number", "date", "name", "quotation", "analysis"]
type ClaimStatus = Literal["supported", "partial", "unsupported", "conflict"]
type ModelTier = Literal["local", "economy", "balanced", "quality"]
type PrivacyMode = Literal["local", "explicit_remote", "server_managed"]


def _new_id() -> str:
    return uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CoreModel(BaseModel):
    """Closed, immutable base model shared by all core contracts."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

    @model_validator(mode="before")
    @classmethod
    def accept_json_arrays_for_tuples(cls, data: object) -> object:
        """Accept JSON arrays at tuple fields while retaining strict scalar validation."""

        if not isinstance(data, Mapping):
            return data
        normalized: dict[object, object] = dict(data)
        for field_name, field in cls.model_fields.items():
            value = normalized.get(field_name)
            if isinstance(value, list) and get_origin(field.annotation) is tuple:
                normalized[field_name] = tuple(value)
        return normalized


def _clean_unique(values: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    cleaned = tuple(value.strip() for value in values)
    if any(not value for value in cleaned):
        raise ValueError(f"{field_name} 不得包含空值")
    if len(cleaned) != len(set(cleaned)):
        raise ValueError(f"{field_name} 不得重复")
    return cleaned


class WritingStructureSection(CoreModel):
    """One bounded section supplied as an explicit writing-structure override."""

    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=500)
    required: bool = True


class WritingBrief(CoreModel):
    """A complete, channel-independent description of one writing task."""

    id: str = Field(default_factory=_new_id, min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    goal: str = Field(min_length=1, max_length=2_000)
    audience: str = Field(min_length=1, max_length=500)
    channel: Channel = "document"
    content_type: str = Field(min_length=1, max_length=100)
    scenario_pack_id: str = Field(min_length=1, max_length=80)
    recipe_id: str = Field(min_length=1, max_length=100)
    tone: str = Field(default="准确、清晰、得体", min_length=1, max_length=100)
    length: str = Field(default="standard", min_length=1, max_length=80)
    target_language: str = Field(default="zh-CN", min_length=2, max_length=35)
    constraints: tuple[str, ...] = Field(default=(), max_length=32)
    keywords: tuple[str, ...] = Field(default=(), max_length=32)
    knowledge_item_ids: tuple[str, ...] = Field(default=(), max_length=128)
    model_profile_id: str | None = Field(default=None, min_length=1, max_length=100)
    selected_title: str | None = Field(default=None, min_length=1, max_length=300)
    structure_override: tuple[WritingStructureSection, ...] = Field(default=(), max_length=24)

    @field_validator("constraints", "keywords", "knowledge_item_ids")
    @classmethod
    def validate_unique_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique(values, field_name="列表字段")

    @field_validator("structure_override")
    @classmethod
    def validate_structure_override(
        cls, values: tuple[WritingStructureSection, ...]
    ) -> tuple[WritingStructureSection, ...]:
        ids = tuple(value.id for value in values)
        titles = tuple(value.title for value in values)
        if len(ids) != len(set(ids)):
            raise ValueError("structure_override 的章节标识不得重复")
        if len(titles) != len(set(titles)):
            raise ValueError("structure_override 的章节标题不得重复")
        return values


class WritingProject(CoreModel):
    """A private workspace that isolates briefs, sources, and text assets."""

    id: str = Field(default_factory=_new_id, min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)
    tags: tuple[str, ...] = Field(default=(), max_length=64)
    default_pack_id: str = Field(default="workplace", min_length=1, max_length=80)
    default_model_profile_id: str | None = Field(default=None, min_length=1, max_length=100)
    archived: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique(values, field_name="tags")

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at 不得早于 created_at")
        return self


class ProjectTerm(CoreModel):
    """A project-specific preferred term and its discouraged variants."""

    id: str = Field(default_factory=_new_id, min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    term: str = Field(min_length=1, max_length=200)
    preferred_form: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    discouraged_variants: tuple[str, ...] = Field(default=(), max_length=32)

    @field_validator("discouraged_variants")
    @classmethod
    def validate_variants(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique(values, field_name="discouraged_variants")


class ContentBlock(CoreModel):
    """One independently editable and traceable unit of a text asset."""

    id: str = Field(default_factory=_new_id, min_length=1, max_length=128)
    kind: ContentBlockKind = "paragraph"
    order: int = Field(ge=0, le=100_000)
    text: str = Field(default="", max_length=200_000)
    heading_level: int | None = Field(default=None, ge=1, le=6)
    locked: bool = False
    knowledge_item_ids: tuple[str, ...] = Field(default=(), max_length=128)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=256)

    @field_validator("knowledge_item_ids", "evidence_ids")
    @classmethod
    def validate_reference_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique(values, field_name="引用标识")

    @model_validator(mode="after")
    def validate_heading_level(self) -> Self:
        if self.kind == "heading" and self.heading_level is None:
            raise ValueError("heading 内容块必须提供 heading_level")
        if self.kind != "heading" and self.heading_level is not None:
            raise ValueError("只有 heading 内容块可以设置 heading_level")
        return self


class Revision(CoreModel):
    """An immutable version snapshot of a text asset."""

    id: str = Field(default_factory=_new_id, min_length=1, max_length=128)
    asset_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    note: str = Field(default="", max_length=500)
    blocks: tuple[ContentBlock, ...] = Field(min_length=1, max_length=10_000)
    created_at: datetime = Field(default_factory=_utcnow)
    model_profile_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_blocks(self) -> Self:
        _validate_block_sequence(self.blocks)
        return self


class TextAsset(CoreModel):
    """A master draft or channel variant composed of ordered content blocks."""

    id: str = Field(default_factory=_new_id, min_length=1, max_length=128)
    brief_id: str = Field(min_length=1, max_length=128)
    parent_asset_id: str | None = Field(default=None, min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    content_type: str = Field(min_length=1, max_length=100)
    channel: Channel = "document"
    status: AssetStatus = "draft"
    blocks: tuple[ContentBlock, ...] = Field(min_length=1, max_length=10_000)
    current_revision: int = Field(default=1, ge=0)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @model_validator(mode="after")
    def validate_asset(self) -> Self:
        _validate_block_sequence(self.blocks)
        if self.updated_at < self.created_at:
            raise ValueError("updated_at 不得早于 created_at")
        return self

    def plain_text(self) -> str:
        """Render the asset as stable plain text without transport concerns."""

        return "\n\n".join(block.text for block in self.blocks if block.text)


class KnowledgeItem(CoreModel):
    """A project-isolated source, reference, prior draft, term list, or note."""

    id: str = Field(default_factory=_new_id, min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    kind: KnowledgeKind = "source"
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=500_000)
    source_url: str = Field(default="", max_length=2_000)
    published_at: datetime | None = None
    tags: tuple[str, ...] = Field(default=(), max_length=64)
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique(values, field_name="tags")


class Evidence(CoreModel):
    """A bounded excerpt that can support or challenge one or more claims."""

    id: str = Field(default_factory=_new_id, min_length=1, max_length=128)
    knowledge_item_id: str = Field(min_length=1, max_length=128)
    excerpt: str = Field(min_length=1, max_length=8_000)
    locator: str = Field(default="", max_length=500)
    source_url: str = Field(default="", max_length=2_000)
    source_hash: str = Field(default="", pattern=r"^(?:[0-9a-f]{64})?$")
    published_at: datetime | None = None


class Claim(CoreModel):
    """A checkable statement extracted from a generated asset."""

    id: str = Field(default_factory=_new_id, min_length=1, max_length=128)
    asset_id: str = Field(min_length=1, max_length=128)
    block_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=8_000)
    kind: ClaimKind = "fact"
    status: ClaimStatus = "unsupported"
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=256)
    confidence: int = Field(default=0, ge=0, le=100)

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique(values, field_name="evidence_ids")

    @model_validator(mode="after")
    def validate_support(self) -> Self:
        if self.status == "supported" and not self.evidence_ids:
            raise ValueError("supported claim 必须关联 evidence_ids")
        return self


class Citation(CoreModel):
    """A stable relation from an asset claim to its supporting evidence."""

    id: str = Field(default_factory=_new_id, min_length=1, max_length=128)
    asset_id: str = Field(min_length=1, max_length=128)
    block_id: str = Field(min_length=1, max_length=128)
    claim_id: str = Field(min_length=1, max_length=128)
    evidence_id: str = Field(min_length=1, max_length=128)
    label: str = Field(default="", max_length=300)


class ModelProfile(CoreModel):
    """Non-secret model capabilities used by provider-neutral routing."""

    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(default="", max_length=2_000)
    tier: ModelTier
    capabilities: tuple[str, ...] = Field(min_length=1, max_length=32)
    privacy_mode: PrivacyMode
    enabled: bool = True
    cost_rank: int = Field(default=0, ge=0, le=100)
    quality_rank: int = Field(default=50, ge=0, le=100)
    latency_rank: int = Field(default=50, ge=0, le=100)
    max_context_tokens: int = Field(default=8_192, ge=1)

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_unique(values, field_name="capabilities")

    @model_validator(mode="after")
    def validate_local_profile(self) -> Self:
        if self.privacy_mode == "local" and self.tier != "local":
            raise ValueError("local privacy profile 必须使用 local tier")
        return self


def _validate_block_sequence(blocks: tuple[ContentBlock, ...]) -> None:
    ids = tuple(block.id for block in blocks)
    orders = tuple(block.order for block in blocks)
    if len(ids) != len(set(ids)):
        raise ValueError("内容块 id 不得重复")
    if len(orders) != len(set(orders)):
        raise ValueError("内容块 order 不得重复")
    if tuple(sorted(orders)) != orders:
        raise ValueError("内容块必须按 order 升序排列")


__all__ = [
    "AssetStatus",
    "Channel",
    "Citation",
    "Claim",
    "ClaimKind",
    "ClaimStatus",
    "ContentBlock",
    "ContentBlockKind",
    "CoreModel",
    "Evidence",
    "KnowledgeItem",
    "KnowledgeKind",
    "ModelProfile",
    "ModelTier",
    "PrivacyMode",
    "ProjectTerm",
    "Revision",
    "TextAsset",
    "WritingBrief",
    "WritingProject",
]
