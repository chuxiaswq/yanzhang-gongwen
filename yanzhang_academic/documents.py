"""Academic document API backed by the shared bounded core parser."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol, runtime_checkable

from pydantic import Field

from yanzhang_academic.models import AcademicModel
from yanzhang_core.parsers import (
    DocumentParseError,
    ParseLimits,
    ParserDependencyError,
    parse_document,
)
from yanzhang_core.parsers import ParsedDocument as CoreParsedDocument

_DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_CORE_LIMITS = ParseLimits()


class DocumentExtractionError(ValueError):
    """Raised when an input document is malformed or exceeds a bound."""


class OptionalDocumentDependencyError(DocumentExtractionError):
    """Raised when a selected parser's optional runtime is absent."""


class ParsedPage(AcademicModel):
    """Text recovered from one logical source page."""

    number: int = Field(ge=1)
    text: str


class ParsedDocument(AcademicModel):
    """Normalized local document text with optional page boundaries."""

    file_name: str
    media_type: str
    text: str
    pages: list[ParsedPage] = Field(default_factory=list)


@runtime_checkable
class DocumentTextExtractor(Protocol):
    """Boundary for local PDF, DOCX and text extraction."""

    def extract(self, payload: bytes, *, file_name: str) -> ParsedDocument:
        """Extract normalized text without network access."""


class PlainTextExtractor:
    """Text/Markdown adapter over :func:`yanzhang_core.parse_document`."""

    def __init__(self, *, max_bytes: int = 20 * 1024 * 1024) -> None:
        active_max = _validate_max_bytes(max_bytes)
        self._limits = replace(
            _CORE_LIMITS,
            max_input_bytes=min(active_max, _CORE_LIMITS.max_input_bytes),
        )

    def extract(self, payload: bytes, *, file_name: str) -> ParsedDocument:
        media_type = (
            "text/markdown" if file_name.casefold().endswith((".md", ".markdown")) else "text/plain"
        )
        return _extract_with_core(
            payload,
            file_name=file_name,
            media_type=media_type,
            limits=self._limits,
        )


class DOCXTextExtractor:
    """DOCX adapter that shares the core archive and active-content checks."""

    def __init__(
        self,
        *,
        max_bytes: int = 20 * 1024 * 1024,
        max_uncompressed_bytes: int = 100 * 1024 * 1024,
        max_archive_entries: int = 2_000,
    ) -> None:
        active_max = _validate_max_bytes(max_bytes)
        if max_uncompressed_bytes < 1_024 or max_uncompressed_bytes > 500 * 1024 * 1024:
            raise ValueError("max_uncompressed_bytes 必须在 1 KB 到 500 MB 之间")
        if max_archive_entries < 1 or max_archive_entries > 10_000:
            raise ValueError("max_archive_entries 必须在 1 到 10000 之间")
        self._limits = replace(
            _CORE_LIMITS,
            max_input_bytes=min(active_max, _CORE_LIMITS.max_input_bytes),
            max_archive_members=min(max_archive_entries, _CORE_LIMITS.max_archive_members),
            max_archive_uncompressed_bytes=min(
                max_uncompressed_bytes,
                _CORE_LIMITS.max_archive_uncompressed_bytes,
            ),
        )

    def extract(self, payload: bytes, *, file_name: str) -> ParsedDocument:
        return _extract_with_core(
            payload,
            file_name=file_name,
            media_type=_DOCX_MEDIA_TYPE,
            limits=self._limits,
        )


class PDFTextExtractor:
    """PDF adapter that shares the core structural and active-content checks."""

    def __init__(self, *, max_bytes: int = 50 * 1024 * 1024, max_pages: int = 1_000) -> None:
        active_max = _validate_max_bytes(max_bytes)
        if max_pages < 1 or max_pages > 10_000:
            raise ValueError("max_pages 必须在 1 到 10000 之间")
        self._limits = replace(
            _CORE_LIMITS,
            max_input_bytes=min(active_max, _CORE_LIMITS.max_input_bytes),
            max_pdf_pages=min(max_pages, _CORE_LIMITS.max_pdf_pages),
        )

    def extract(self, payload: bytes, *, file_name: str) -> ParsedDocument:
        return _extract_with_core(
            payload,
            file_name=file_name,
            media_type="application/pdf",
            limits=self._limits,
        )


def _extract_with_core(
    payload: bytes,
    *,
    file_name: str,
    media_type: str,
    limits: ParseLimits,
) -> ParsedDocument:
    try:
        parsed = parse_document(
            payload,
            filename=file_name,
            media_type=media_type,
            limits=limits,
        )
    except ParserDependencyError as exc:
        raise OptionalDocumentDependencyError(str(exc)) from exc
    except DocumentParseError as exc:
        raise DocumentExtractionError(str(exc)) from exc
    return _to_academic_document(parsed, fallback_file_name=file_name)


def _to_academic_document(
    parsed: CoreParsedDocument,
    *,
    fallback_file_name: str,
) -> ParsedDocument:
    source_name = parsed.metadata.get("source_name", fallback_file_name)
    safe_name = source_name if isinstance(source_name, str) else fallback_file_name
    pages = [
        ParsedPage(number=index, text=_normalize_text(text))
        for index, text in enumerate(parsed.page_texts, start=1)
    ]
    if pages:
        text = "\n\f\n".join(page.text for page in pages)
    else:
        text = _normalize_text("\n".join(block.text for block in parsed.blocks))
    return ParsedDocument(
        file_name=safe_name,
        media_type=parsed.content_type,
        text=text,
        pages=pages,
    )


def _validate_max_bytes(value: int) -> int:
    if value < 1_024 or value > 500 * 1024 * 1024:
        raise ValueError("max_bytes 必须在 1 KB 到 500 MB 之间")
    return value


def _normalize_text(value: str) -> str:
    lines = [" ".join(line.replace("\x00", "").split()) for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()


__all__ = [
    "DOCXTextExtractor",
    "DocumentExtractionError",
    "DocumentTextExtractor",
    "OptionalDocumentDependencyError",
    "PDFTextExtractor",
    "ParsedDocument",
    "ParsedPage",
    "PlainTextExtractor",
]
