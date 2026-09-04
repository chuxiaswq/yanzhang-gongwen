"""Stable façade for Web, MCP and local academic-workflow integrations."""

# ruff: noqa: RUF001 -- Chinese user-facing messages use full-width punctuation.

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import PurePath
from typing import Literal

from yanzhang_academic.citations import format_bibliography
from yanzhang_academic.connectors import (
    ArxivConnector,
    CrossrefConnector,
    MetadataConnector,
    OpenAlexConnector,
)
from yanzhang_academic.documents import (
    DOCXTextExtractor,
    ParsedDocument,
    PDFTextExtractor,
    PlainTextExtractor,
)
from yanzhang_academic.evidence import build_literature_matrix, extract_evidence
from yanzhang_academic.formats import (
    export_bibtex,
    export_csl_json,
    export_ris,
    parse_bibtex,
    parse_csl_json,
    parse_ris,
)
from yanzhang_academic.models import (
    AbstractDraft,
    AcademicOutline,
    BibliographicRecord,
    CitationAudit,
    CitationStyle,
    ClaimCitationLink,
    EvidenceSnippet,
    IntegrityReview,
    JournalProfile,
    LiteratureMatrix,
    RebuttalItem,
    ResearchBrief,
    ResearchClaim,
    ReviewComment,
    TitleSuggestion,
)
from yanzhang_academic.verification import review_research_integrity, verify_claim_citations
from yanzhang_academic.writing import (
    create_outline,
    draft_abstract,
    prepare_rebuttal,
    suggest_titles,
)

BibliographyFormat = Literal["bibtex", "ris", "csl-json"]


class AcademicService:
    """Provider-neutral academic pack composed entirely from public contracts."""

    def __init__(self, *, connectors: Mapping[str, MetadataConnector] | None = None) -> None:
        supplied: Mapping[str, MetadataConnector]
        if connectors is None:
            supplied = {
                "crossref": CrossrefConnector(),
                "openalex": OpenAlexConnector(),
                "arxiv": ArxivConnector(),
            }
        else:
            supplied = connectors
        self._connectors = {name.casefold(): connector for name, connector in supplied.items()}

    def list_connectors(self) -> tuple[str, ...]:
        """Return stable metadata connector names."""

        return tuple(sorted(self._connectors))

    async def search_metadata(
        self, provider: str, query: str, *, limit: int = 10
    ) -> list[BibliographicRecord]:
        """Search one explicitly selected metadata provider."""

        return await self._connector(provider).search(query, limit=limit)

    async def lookup_metadata(self, provider: str, identifier: str) -> BibliographicRecord | None:
        """Resolve one DOI or provider identifier."""

        return await self._connector(provider).lookup(identifier)

    def import_records(
        self, content: str | bytes, format: BibliographyFormat
    ) -> list[BibliographicRecord]:
        """Import bibliography data while retaining format provenance."""

        if format == "csl-json":
            return parse_csl_json(content)
        text = _decode_text(content)
        if format == "bibtex":
            return parse_bibtex(text)
        if format == "ris":
            return parse_ris(text)
        raise ValueError(f"未知文献格式：{format}")

    def export_records(
        self, records: Sequence[BibliographicRecord], format: BibliographyFormat
    ) -> str:
        """Export the supplied imported records without metadata completion."""

        if format == "bibtex":
            return export_bibtex(records)
        if format == "ris":
            return export_ris(records)
        if format == "csl-json":
            return export_csl_json(records)
        raise ValueError(f"未知文献格式：{format}")

    def extract_document(self, content: bytes, *, file_name: str) -> ParsedDocument:
        """Extract a local source document through the matching bounded adapter."""

        suffix = PurePath(file_name).suffix.casefold()
        if suffix == ".pdf":
            return PDFTextExtractor().extract(content, file_name=file_name)
        if suffix == ".docx":
            return DOCXTextExtractor().extract(content, file_name=file_name)
        if suffix in {".txt", ".md", ".markdown"}:
            return PlainTextExtractor().extract(content, file_name=file_name)
        raise ValueError("支持的资料文件类型为 PDF、DOCX、TXT 和 Markdown")

    def extract_evidence(
        self,
        record: BibliographicRecord,
        text: str,
        *,
        query: str = "",
        max_snippets: int = 20,
    ) -> list[EvidenceSnippet]:
        """Extract source-bound evidence from one imported record's full text."""

        return extract_evidence(record, text, query=query, max_snippets=max_snippets)

    def build_matrix(
        self,
        records: Sequence[BibliographicRecord],
        evidence: Sequence[EvidenceSnippet] = (),
        *,
        query: str = "",
    ) -> LiteratureMatrix:
        """Build an evidence-led literature matrix."""

        return build_literature_matrix(records, evidence, query=query)

    def create_citation_link(
        self,
        claim: ResearchClaim,
        record: BibliographicRecord,
        evidence: EvidenceSnippet,
        *,
        relation: Literal["supports", "contradicts", "context"] = "supports",
    ) -> ClaimCitationLink:
        """Create a link only when evidence lineage matches the imported record."""

        if evidence.record_id != record.id or evidence.record_source_hash != record.source_hash:
            raise ValueError("证据片段与导入文献记录不匹配")
        return ClaimCitationLink(
            claim_id=claim.id,
            record_id=record.id,
            evidence_id=evidence.id,
            relation=relation,
        )

    def verify_citations(
        self,
        records: Sequence[BibliographicRecord],
        evidence: Sequence[EvidenceSnippet],
        claims: Sequence[ResearchClaim],
        links: Sequence[ClaimCitationLink],
        *,
        minimum_support_score: float = 0.18,
    ) -> CitationAudit:
        """Verify citation identity, lineage and lexical support."""

        return verify_claim_citations(
            records,
            evidence,
            claims,
            links,
            minimum_support_score=minimum_support_score,
        )

    def review_integrity(
        self,
        records: Sequence[BibliographicRecord],
        evidence: Sequence[EvidenceSnippet],
        claims: Sequence[ResearchClaim],
        links: Sequence[ClaimCitationLink],
        *,
        minimum_support_score: float = 0.18,
        manuscript: str | None = None,
        journal: JournalProfile | None = None,
    ) -> IntegrityReview:
        """Run source-lineage and optional manuscript/journal conformance checks."""

        return review_research_integrity(
            records,
            evidence,
            claims,
            links,
            minimum_support_score=minimum_support_score,
            manuscript=manuscript,
            journal=journal,
        )

    def format_bibliography(
        self, records: Sequence[BibliographicRecord], style: CitationStyle
    ) -> list[str]:
        """Render baseline references from supplied imported records."""

        return format_bibliography(records, style)

    def suggest_titles(
        self,
        brief: ResearchBrief,
        records: Sequence[BibliographicRecord] = (),
        *,
        count: int = 5,
    ) -> list[TitleSuggestion]:
        """Create research-title candidates from the confirmed brief."""

        return suggest_titles(brief, records, count=count)

    def create_outline(
        self,
        brief: ResearchBrief,
        records: Sequence[BibliographicRecord] = (),
        evidence: Sequence[EvidenceSnippet] = (),
        *,
        journal: JournalProfile | None = None,
    ) -> AcademicOutline:
        """Create an evidence-aware manuscript outline."""

        return create_outline(brief, records, evidence, journal=journal)

    def draft_abstract(
        self,
        brief: ResearchBrief,
        claims: Sequence[ResearchClaim],
        links: Sequence[ClaimCitationLink],
        records: Sequence[BibliographicRecord],
        *,
        journal: JournalProfile | None = None,
    ) -> AbstractDraft:
        """Assemble an abstract from the brief and verified source links."""

        return draft_abstract(brief, claims, links, records, journal=journal)

    def prepare_rebuttal(
        self,
        comments: Sequence[ReviewComment],
        changes: Mapping[str, str] | None = None,
    ) -> list[RebuttalItem]:
        """Prepare point-by-point reviewer response drafts."""

        return prepare_rebuttal(comments, changes)

    def _connector(self, provider: str) -> MetadataConnector:
        normalized = provider.casefold().strip()
        connector = self._connectors.get(normalized)
        if connector is None:
            available = "、".join(self.list_connectors())
            raise ValueError(f"未知元数据连接器：{provider}；可选项：{available}")
        return connector


def _decode_text(content: str | bytes) -> str:
    if isinstance(content, str):
        return content
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("文献数据需要使用 UTF-8 编码") from exc


__all__ = ["AcademicService", "BibliographyFormat"]
