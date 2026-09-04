"""Typed domain models for the academic-research writing pack.

The models deliberately keep bibliographic metadata, evidence excerpts and manuscript
claims separate.  A citation can therefore be created only by linking a claim to an
excerpt that belongs to an imported bibliographic record.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ImportSource = Literal["bibtex", "ris", "csl-json", "crossref", "openalex", "arxiv", "manual"]
RecordType = Literal[
    "article-journal",
    "book",
    "chapter",
    "paper-conference",
    "report",
    "thesis",
    "webpage",
    "preprint",
    "document",
]
EvidenceKind = Literal["background", "method", "finding", "limitation", "definition", "other"]
CitationStyle = Literal["gb-t-7714", "apa", "mla", "chicago"]
ReviewSeverity = Literal["info", "warning", "error"]
ReviewCategory = Literal[
    "citation",
    "metadata",
    "evidence",
    "consistency",
    "integrity",
    "style",
    "method",
]
LinkStatus = Literal["verified", "needs-review", "invalid"]


class AcademicModel(BaseModel):
    """Strict public base model with predictable serialization."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def stable_id(prefix: str, *parts: str) -> str:
    """Create a stable, opaque identifier without exposing source text."""

    payload = "\x1f".join(part.strip() for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def normalize_doi(value: str | None) -> str | None:
    """Normalize common DOI URL and label forms."""

    if value is None:
        return None
    normalized = value.strip()
    normalized = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", normalized, flags=re.I)
    normalized = normalized.strip().rstrip(". ").lower()
    return normalized or None


class Author(AcademicModel):
    """One structured or literal creator name."""

    family: str = ""
    given: str = ""
    literal: str = ""
    sequence: Literal["first", "additional"] = "additional"

    @model_validator(mode="after")
    def require_name(self) -> Self:
        if not (self.literal or self.family or self.given):
            raise ValueError("作者姓名至少需要一个有效字段")
        return self

    def display_name(self, *, family_first: bool = False) -> str:
        """Return a human-readable name for citation rendering."""

        if self.literal:
            return self.literal
        if family_first:
            return " ".join(part for part in (self.family, self.given) if part)
        return " ".join(part for part in (self.given, self.family) if part)


class ResearchBrief(AcademicModel):
    """Human-confirmed research scope for one writing task."""

    id: str = ""
    title: str = Field(min_length=1, max_length=500)
    discipline: str = Field(default="", max_length=200)
    research_question: str = Field(min_length=1, max_length=2_000)
    purpose: str = Field(default="", max_length=2_000)
    audience: str = Field(default="学术读者", max_length=200)
    document_type: str = Field(default="研究论文", max_length=100)
    language: str = Field(default="zh-CN", max_length=20)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    constraints: list[str] = Field(default_factory=list, max_length=30)
    method_notes: str = Field(default="", max_length=10_000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("keywords", "constraints")
    @classmethod
    def normalize_terms(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def assign_id(self) -> Self:
        if not self.id:
            self.id = stable_id("brief", self.title, self.research_question)
        return self


class BibliographicRecord(AcademicModel):
    """An imported source record used as the only citation authority."""

    id: str = ""
    type: RecordType = "document"
    title: str = Field(min_length=1, max_length=2_000)
    authors: list[Author] = Field(default_factory=list, max_length=100)
    editors: list[Author] = Field(default_factory=list, max_length=100)
    issued_year: int | None = Field(default=None, ge=1000, le=3000)
    issued_month: int | None = Field(default=None, ge=1, le=12)
    issued_day: int | None = Field(default=None, ge=1, le=31)
    container_title: str = Field(default="", max_length=1_000)
    publisher: str = Field(default="", max_length=1_000)
    publisher_place: str = Field(default="", max_length=500)
    volume: str = Field(default="", max_length=100)
    issue: str = Field(default="", max_length=100)
    pages: str = Field(default="", max_length=100)
    edition: str = Field(default="", max_length=100)
    doi: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=4_000)
    abstract: str = Field(default="", max_length=100_000)
    keywords: list[str] = Field(default_factory=list, max_length=100)
    language: str = Field(default="", max_length=30)
    import_source: ImportSource
    source_key: str = Field(default="", max_length=500)
    source_hash: str = Field(default="", min_length=0, max_length=64)
    metadata_verified: bool = False
    imported_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("doi", mode="before")
    @classmethod
    def normalize_doi_field(cls, value: object) -> object:
        return normalize_doi(value if isinstance(value, str) else None)

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def assign_lineage(self) -> Self:
        canonical = json.dumps(
            {
                "authors": [author.model_dump(mode="json") for author in self.authors],
                "doi": self.doi,
                "source_key": self.source_key,
                "title": self.title,
                "year": self.issued_year,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if not self.source_hash:
            self.source_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if not self.id:
            primary_key = self.doi or self.source_key or self.source_hash
            self.id = stable_id("ref", self.import_source, primary_key)
        return self


class EvidenceSnippet(AcademicModel):
    """Exact excerpt and location from one imported source."""

    id: str = ""
    record_id: str = Field(min_length=1, max_length=200)
    record_source_hash: str = Field(min_length=16, max_length=64)
    text: str = Field(min_length=1, max_length=20_000)
    kind: EvidenceKind = "other"
    section: str = Field(default="", max_length=500)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    paragraph_index: int | None = Field(default=None, ge=1)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    content_hash: str = Field(default="", min_length=0, max_length=64)
    extraction_method: Literal["manual", "deterministic", "parser"] = "deterministic"

    @model_validator(mode="after")
    def validate_location_and_assign_id(self) -> Self:
        if self.page_start is not None and self.page_end is not None:
            if self.page_end < self.page_start:
                raise ValueError("证据结束页不得早于起始页")
        if self.char_start is not None and self.char_end is not None:
            if self.char_end < self.char_start:
                raise ValueError("证据结束位置不得早于起始位置")
        if not self.content_hash:
            self.content_hash = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if not self.id:
            location = ":".join(
                str(part)
                for part in (self.page_start, self.paragraph_index, self.char_start)
                if part is not None
            )
            self.id = stable_id("evidence", self.record_id, location, self.content_hash)
        return self


class ResearchClaim(AcademicModel):
    """One manuscript assertion that may require source support."""

    id: str = ""
    text: str = Field(min_length=1, max_length=20_000)
    section: str = Field(default="", max_length=500)
    requires_citation: bool = True
    claim_type: Literal["background", "method", "result", "interpretation", "other"] = "other"

    @model_validator(mode="after")
    def assign_id(self) -> Self:
        if not self.id:
            self.id = stable_id("claim", self.section, self.text)
        return self


class ClaimCitationLink(AcademicModel):
    """Auditable link from a manuscript claim to one exact source excerpt."""

    id: str = ""
    claim_id: str = Field(min_length=1, max_length=200)
    record_id: str = Field(min_length=1, max_length=200)
    evidence_id: str = Field(min_length=1, max_length=200)
    relation: Literal["supports", "contradicts", "context"] = "supports"
    support_score: float = Field(default=0.0, ge=0.0, le=1.0)
    status: LinkStatus = "needs-review"
    issues: list[str] = Field(default_factory=list, max_length=20)
    verified_at: datetime | None = None

    @model_validator(mode="after")
    def assign_id(self) -> Self:
        if not self.id:
            self.id = stable_id("link", self.claim_id, self.record_id, self.evidence_id)
        return self


class LiteratureMatrixRow(AcademicModel):
    """One source summarized into comparable research dimensions."""

    record_id: str
    citation_label: str
    research_object: str = ""
    methods: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class LiteratureMatrix(AcademicModel):
    """Comparable evidence-led view of an imported literature collection."""

    id: str = ""
    query: str = ""
    rows: list[LiteratureMatrixRow] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    record_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def assign_id(self) -> Self:
        if not self.id:
            self.id = stable_id("matrix", self.query, *self.record_ids)
        return self


class JournalProfile(AcademicModel):
    """Target journal and manuscript-shape constraints."""

    id: str = ""
    name: str = Field(min_length=1, max_length=500)
    citation_style: CitationStyle = "gb-t-7714"
    language: str = Field(default="zh-CN", max_length=20)
    required_sections: list[str] = Field(default_factory=list, max_length=30)
    abstract_max_characters: int | None = Field(default=None, ge=100, le=20_000)
    manuscript_max_words: int | None = Field(default=None, ge=500, le=500_000)
    title_max_characters: int | None = Field(default=None, ge=5, le=1_000)
    custom_rules: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def assign_id(self) -> Self:
        if not self.id:
            self.id = stable_id("journal", self.name, self.language, self.citation_style)
        return self


class ReviewComment(AcademicModel):
    """Machine-detected or imported review item requiring human disposition."""

    id: str = ""
    category: ReviewCategory
    severity: ReviewSeverity = "warning"
    message: str = Field(min_length=1, max_length=5_000)
    recommendation: str = Field(default="", max_length=5_000)
    location: str = Field(default="", max_length=1_000)
    claim_id: str | None = None
    record_id: str | None = None
    evidence_id: str | None = None
    resolved: bool = False

    @model_validator(mode="after")
    def assign_id(self) -> Self:
        if not self.id:
            self.id = stable_id(
                "review",
                self.category,
                self.message,
                self.location,
                self.claim_id or "",
            )
        return self


class RebuttalItem(AcademicModel):
    """One tracked response to a reviewer comment."""

    id: str = ""
    comment_id: str = Field(min_length=1, max_length=200)
    reviewer_comment: str = Field(min_length=1, max_length=20_000)
    response: str = Field(min_length=1, max_length=20_000)
    manuscript_change: str = Field(default="", max_length=20_000)
    location: str = Field(default="", max_length=1_000)
    status: Literal["draft", "confirmed", "completed"] = "draft"

    @model_validator(mode="after")
    def assign_id(self) -> Self:
        if not self.id:
            self.id = stable_id("rebuttal", self.comment_id, self.response)
        return self


class CitationAudit(AcademicModel):
    """Aggregate result of checking a set of claim-to-source links."""

    links: list[ClaimCitationLink]
    comments: list[ReviewComment]
    required_claim_count: int = Field(ge=0)
    supported_claim_count: int = Field(ge=0)
    coverage: float = Field(ge=0.0, le=1.0)


class IntegrityReview(AcademicModel):
    """Citation lineage and manuscript-consistency review."""

    citation_audit: CitationAudit
    comments: list[ReviewComment]
    passed: bool


class OutlineSection(AcademicModel):
    """One evidence-aware manuscript section plan."""

    heading: str
    purpose: str
    questions: list[str] = Field(default_factory=list)
    record_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class AcademicOutline(AcademicModel):
    """Structured manuscript plan tied to imported records."""

    title: str
    sections: list[OutlineSection]
    record_ids: list[str] = Field(default_factory=list)


class TitleSuggestion(AcademicModel):
    """One deterministic research-title suggestion."""

    title: str
    rationale: str
    record_ids: list[str] = Field(default_factory=list)


class AbstractDraft(AcademicModel):
    """Evidence-bounded abstract draft and its source lineage."""

    text: str
    record_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    placeholders: list[str] = Field(default_factory=list)


__all__ = [
    "AbstractDraft",
    "AcademicModel",
    "AcademicOutline",
    "Author",
    "BibliographicRecord",
    "CitationAudit",
    "CitationStyle",
    "ClaimCitationLink",
    "EvidenceKind",
    "EvidenceSnippet",
    "ImportSource",
    "IntegrityReview",
    "JournalProfile",
    "LinkStatus",
    "LiteratureMatrix",
    "LiteratureMatrixRow",
    "OutlineSection",
    "RebuttalItem",
    "RecordType",
    "ResearchBrief",
    "ResearchClaim",
    "ReviewCategory",
    "ReviewComment",
    "ReviewSeverity",
    "TitleSuggestion",
    "normalize_doi",
    "stable_id",
]
