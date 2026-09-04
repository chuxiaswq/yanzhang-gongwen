"""Pure, bounded exporters for provider-neutral Yanzhang text assets."""

from __future__ import annotations

import csv
import hashlib
import html
import importlib
import io
import re
import unicodedata
from collections.abc import Buffer, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from yanzhang_core.models import ContentBlock, Evidence, TextAsset

type ExportFormat = Literal[
    "markdown",
    "md",
    "txt",
    "text",
    "html",
    "latex",
    "tex",
    "pdf",
    "citation_csv",
    "literature_matrix_csv",
    "csv",
]

_MAX_CONFIGURED_OUTPUT_BYTES: Final = 100 * 1024 * 1024
_MAX_CONFIGURED_CHARACTERS: Final = 10_000_000
_DEFAULT_MAX_CHARACTERS: Final = 2_000_000
_DEFAULT_MAX_OUTPUT_BYTES: Final = 20 * 1024 * 1024
_MAX_EVIDENCE_ITEMS: Final = 100_000
_WINDOWS_RESERVED_NAMES: Final = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{value}" for value in range(1, 10)),
        *(f"LPT{value}" for value in range(1, 10)),
    }
)
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]<>#+.!|~()-])")
_BIDI_CONTROL_CHARACTERS: Final = frozenset(
    {
        "\ufeff",
        *(chr(value) for value in range(0x202A, 0x202F)),
        *(chr(value) for value in range(0x2066, 0x206A)),
    }
)


class ExportError(ValueError):
    """Base class for a stable export failure."""

    def __init__(self, message: str, *, code: str = "export_error") -> None:
        self.code = code
        super().__init__(message)


class UnsupportedExportFormatError(ExportError):
    """Raised when the requested output identifier has no exporter."""

    def __init__(self) -> None:
        super().__init__(
            "可导出格式为 Markdown、TXT、HTML、LaTeX、PDF 和文献矩阵 CSV",
            code="unsupported_export_format",
        )


class ExportTooLargeError(ExportError):
    """Raised before returning content beyond a configured export budget."""

    def __init__(self, message: str = "导出内容超过安全处理上限") -> None:
        super().__init__(message, code="export_too_large")


class ExportDependencyError(ExportError):
    """Raised when a lazily loaded optional exporter dependency is absent."""

    def __init__(self, dependency: str, feature: str) -> None:
        self.dependency = dependency
        self.feature = feature
        super().__init__(
            f"{feature}需要安装可选依赖 {dependency}",
            code="export_dependency_missing",
        )


@dataclass(frozen=True, slots=True)
class ExportOptions:
    """Presentation and output-size settings shared by all exporters."""

    filename_stem: str | None = None
    include_title: bool = True
    max_characters: int = _DEFAULT_MAX_CHARACTERS
    max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES

    def __post_init__(self) -> None:
        if self.filename_stem is not None:
            if not isinstance(self.filename_stem, str):
                raise TypeError("filename_stem 应为 str")
            if not self.filename_stem.strip():
                raise ValueError("filename_stem 应包含文本")
        if not isinstance(self.include_title, bool):
            raise TypeError("include_title 应为 bool")
        if (
            type(self.max_characters) is not int
            or self.max_characters < 1
            or self.max_characters > _MAX_CONFIGURED_CHARACTERS
        ):
            raise ValueError("max_characters 应位于 1 到 10000000 之间")
        if (
            type(self.max_output_bytes) is not int
            or self.max_output_bytes < 1
            or self.max_output_bytes > _MAX_CONFIGURED_OUTPUT_BYTES
        ):
            raise ValueError("max_output_bytes 应位于 1 到 104857600 之间")


@dataclass(frozen=True, slots=True)
class ExportArtifact:
    """One complete in-memory export with integrity metadata."""

    filename: str
    media_type: str
    data: bytes
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.filename, str):
            raise TypeError("filename 应为 str")
        if not self.filename or "/" in self.filename or "\\" in self.filename:
            raise ValueError("filename 应为单个安全文件名")
        if not isinstance(self.media_type, str):
            raise TypeError("media_type 应为 str")
        if not self.media_type:
            raise ValueError("media_type 应包含文本")
        if not isinstance(self.data, bytes):
            raise TypeError("data 应为 bytes")
        if not isinstance(self.sha256, str):
            raise TypeError("sha256 应为 str")
        expected = hashlib.sha256(self.data).hexdigest()
        if self.sha256 != expected:
            raise ValueError("sha256 与导出内容不一致")

    @property
    def size(self) -> int:
        """Return the exact payload size in bytes."""

        return len(self.data)


def supported_export_formats() -> tuple[str, ...]:
    """Return canonical output identifiers suitable for an API capability list."""

    return ("markdown", "txt", "html", "latex", "pdf", "citation_csv")


def export_asset(
    asset: TextAsset,
    *,
    format: ExportFormat,
    options: ExportOptions | None = None,
    evidence: Mapping[str, Evidence] | Sequence[Evidence] = (),
) -> ExportArtifact:
    """Render a text asset without database, provider or filesystem access."""

    if not isinstance(asset, TextAsset):
        raise TypeError("asset 应为 TextAsset")
    if not isinstance(format, str):
        raise TypeError("format 应为 str")
    if options is not None and not isinstance(options, ExportOptions):
        raise TypeError("options 应为 ExportOptions")
    active_options = options or ExportOptions()
    _validate_character_budget(asset, active_options)
    normalized = format.strip().casefold()
    if normalized in {"markdown", "md"}:
        payload = _render_markdown(asset, active_options).encode("utf-8")
        return _artifact(asset, active_options, "md", "text/markdown; charset=utf-8", payload)
    if normalized in {"txt", "text"}:
        payload = _render_text(asset, active_options).encode("utf-8")
        return _artifact(asset, active_options, "txt", "text/plain; charset=utf-8", payload)
    if normalized == "html":
        payload = _render_html(asset, active_options).encode("utf-8")
        return _artifact(asset, active_options, "html", "text/html; charset=utf-8", payload)
    if normalized in {"latex", "tex"}:
        payload = _render_latex(asset, active_options).encode("utf-8")
        return _artifact(asset, active_options, "tex", "application/x-latex", payload)
    if normalized == "pdf":
        payload = _render_pdf(asset, active_options)
        return _artifact(asset, active_options, "pdf", "application/pdf", payload)
    if normalized in {"citation_csv", "literature_matrix_csv", "csv"}:
        return export_citation_matrix(asset, evidence=evidence, options=active_options)
    raise UnsupportedExportFormatError


def export_citation_matrix(
    asset: TextAsset,
    *,
    evidence: Mapping[str, Evidence] | Sequence[Evidence] = (),
    options: ExportOptions | None = None,
) -> ExportArtifact:
    """Export one spreadsheet-safe row for every block/evidence relation."""

    if not isinstance(asset, TextAsset):
        raise TypeError("asset 应为 TextAsset")
    if options is not None and not isinstance(options, ExportOptions):
        raise TypeError("options 应为 ExportOptions")
    active_options = options or ExportOptions()
    _validate_character_budget(asset, active_options)
    evidence_index = _evidence_index(evidence)
    stream = _BoundedCSVBuffer(active_options.max_output_bytes)
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(
        (
            "block_id",
            "block_order",
            "block_kind",
            "block_text",
            "evidence_id",
            "knowledge_item_id",
            "locator",
            "source_url",
            "source_hash",
            "evidence_excerpt",
        )
    )
    for block in asset.blocks:
        evidence_ids = block.evidence_ids or ("",)
        for evidence_id in evidence_ids:
            item = evidence_index.get(evidence_id)
            writer.writerow(
                tuple(
                    _spreadsheet_safe(value)
                    for value in (
                        block.id,
                        str(block.order),
                        block.kind,
                        block.text,
                        evidence_id,
                        item.knowledge_item_id if item is not None else "",
                        item.locator if item is not None else "",
                        item.source_url if item is not None else "",
                        item.source_hash if item is not None else "",
                        item.excerpt if item is not None else "",
                    )
                )
            )
    payload = stream.to_bytes()
    return _artifact(
        asset,
        active_options,
        "citations.csv",
        "text/csv; charset=utf-8",
        payload,
        compound_suffix=True,
    )


def _validate_character_budget(asset: TextAsset, options: ExportOptions) -> None:
    character_count = len(asset.title) + sum(len(block.text) for block in asset.blocks)
    if character_count > options.max_characters:
        raise ExportTooLargeError("导出文本超过字符上限")


def _artifact(
    asset: TextAsset,
    options: ExportOptions,
    suffix: str,
    media_type: str,
    payload: bytes,
    *,
    compound_suffix: bool = False,
) -> ExportArtifact:
    if len(payload) > options.max_output_bytes:
        raise ExportTooLargeError("导出文件超过字节上限")
    stem = _safe_filename_stem(options.filename_stem or asset.title)
    filename = f"{stem}-{suffix}" if compound_suffix else f"{stem}.{suffix}"
    return ExportArtifact(
        filename=filename,
        media_type=media_type,
        data=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _safe_filename_stem(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\\", "/").rsplit("/", 1)[-1]
    normalized = "".join(
        character for character in normalized if unicodedata.category(character) not in {"Cc", "Cf"}
    )
    normalized = re.sub(r"\s+", "-", normalized.strip())
    normalized = re.sub(r"[^\w\-\u3400-\u9fff]", "-", normalized, flags=re.UNICODE)
    normalized = re.sub(r"-+", "-", normalized).strip(" .-_")[:100]
    if not normalized:
        normalized = "yanzhang-export"
    if normalized.upper() in _WINDOWS_RESERVED_NAMES:
        normalized = f"yanzhang-{normalized}"
    return normalized


def _normalized_export_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        character
        for character in normalized
        if character in {"\n", "\t"}
        or (
            unicodedata.category(character) not in {"Cc", "Cs"}
            and character not in _BIDI_CONTROL_CHARACTERS
        )
    )


def _blocks_without_duplicate_title(asset: TextAsset) -> tuple[ContentBlock, ...]:
    blocks = asset.blocks
    if blocks and blocks[0].kind == "title" and blocks[0].text.strip() == asset.title.strip():
        return blocks[1:]
    return blocks


def _render_text(asset: TextAsset, options: ExportOptions) -> str:
    parts: list[str] = (
        [_normalized_export_text(asset.title).strip()] if options.include_title else []
    )
    parts.extend(
        _normalized_export_text(block.text).strip()
        for block in _blocks_without_duplicate_title(asset)
        if block.text
    )
    return "\n\n".join(parts).rstrip() + "\n"


def _markdown_escape(value: str) -> str:
    return _MARKDOWN_SPECIAL.sub(r"\\\1", value)


def _render_markdown(asset: TextAsset, options: ExportOptions) -> str:
    parts: list[str] = []
    if options.include_title:
        parts.append(f"# {_markdown_escape(_normalized_export_text(asset.title).strip())}")
    for block in _blocks_without_duplicate_title(asset):
        text = _normalized_export_text(block.text).strip()
        if not text:
            continue
        escaped = _markdown_escape(text)
        if block.kind == "heading":
            parts.append(f"{'#' * (block.heading_level or 2)} {escaped}")
        elif block.kind == "subtitle":
            parts.append(f"## {escaped}")
        elif block.kind == "quote":
            parts.append("\n".join(f"> {line}" for line in escaped.splitlines()))
        elif block.kind in {"list", "action_item"}:
            parts.append("\n".join(f"- {line}" for line in escaped.splitlines() if line.strip()))
        else:
            parts.append(escaped)
    return "\n\n".join(parts).rstrip() + "\n"


def _html_text(value: str) -> str:
    return html.escape(value, quote=True).replace("\n", "<br>\n")


def _render_html(asset: TextAsset, options: ExportOptions) -> str:
    body: list[str] = []
    if options.include_title:
        body.append(f"<h1>{_html_text(_normalized_export_text(asset.title).strip())}</h1>")
    for block in _blocks_without_duplicate_title(asset):
        text = _normalized_export_text(block.text).strip()
        if not text:
            continue
        escaped = _html_text(text)
        if block.kind == "heading":
            level = block.heading_level or 2
            body.append(f"<h{level}>{escaped}</h{level}>")
        elif block.kind == "subtitle":
            body.append(f'<h2 class="subtitle">{escaped}</h2>')
        elif block.kind == "quote":
            body.append(f"<blockquote><p>{escaped}</p></blockquote>")
        elif block.kind in {"list", "action_item"}:
            items = "".join(
                f"<li>{_html_text(line.strip())}</li>" for line in text.splitlines() if line.strip()
            )
            body.append(f"<ul>{items}</ul>")
        else:
            css_class = html.escape(block.kind, quote=True)
            body.append(f'<p class="{css_class}">{escaped}</p>')
    title = html.escape(_normalized_export_text(asset.title), quote=True)
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{title}</title>\n"
        '<meta name="referrer" content="no-referrer">\n'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'">\n'
        "</head>\n<body>\n" + "\n".join(body) + "\n</body>\n</html>\n"
    )


_LATEX_ESCAPES: Final[Mapping[str, str]] = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "_": r"\_",
    "%": r"\%",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "<": r"\textless{}",
    ">": r"\textgreater{}",
}


def _latex_escape(value: str) -> str:
    return "".join(_LATEX_ESCAPES.get(character, character) for character in value).replace(
        "\n", "\\\\\n"
    )


def _render_latex(asset: TextAsset, options: ExportOptions) -> str:
    parts = [r"\documentclass[UTF8]{ctexart}"]
    if options.include_title:
        parts.extend(
            (
                f"\\title{{{_latex_escape(_normalized_export_text(asset.title))}}}",
                r"\author{}",
            )
        )
    parts.append(r"\begin{document}")
    if options.include_title:
        parts.append(r"\maketitle")
    commands = {1: "section", 2: "subsection", 3: "subsubsection"}
    for block in _blocks_without_duplicate_title(asset):
        text = _normalized_export_text(block.text).strip()
        if not text:
            continue
        escaped = _latex_escape(text)
        if block.kind == "heading":
            command = commands.get(block.heading_level or 2, "paragraph")
            parts.append(f"\\{command}{{{escaped}}}")
        elif block.kind in {"list", "action_item"}:
            parts.append(r"\begin{itemize}")
            parts.extend(
                f"\\item {_latex_escape(line.strip())}"
                for line in text.splitlines()
                if line.strip()
            )
            parts.append(r"\end{itemize}")
        elif block.kind == "quote":
            parts.extend((r"\begin{quote}", escaped, r"\end{quote}"))
        else:
            parts.append(escaped)
    parts.append(r"\end{document}")
    return "\n\n".join(parts) + "\n"


def _load_reportlab() -> tuple[Any, Any, Any, Any, Any]:
    try:
        platypus = importlib.import_module("reportlab.platypus")
        styles = importlib.import_module("reportlab.lib.styles")
        pagesizes = importlib.import_module("reportlab.lib.pagesizes")
        pdfmetrics = importlib.import_module("reportlab.pdfbase.pdfmetrics")
        cidfonts = importlib.import_module("reportlab.pdfbase.cidfonts")
    except (ImportError, ModuleNotFoundError) as exc:
        raise ExportDependencyError("reportlab", "PDF 导出") from exc
    return platypus, styles, pagesizes, pdfmetrics, cidfonts


def _render_pdf(asset: TextAsset, options: ExportOptions) -> bytes:
    platypus, styles, pagesizes, pdfmetrics, cidfonts = _load_reportlab()
    font_name = "STSong-Light"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(cidfonts.UnicodeCIDFont(font_name))
    body_style = styles.ParagraphStyle(
        "YanzhangBody",
        fontName=font_name,
        fontSize=11,
        leading=18,
        spaceAfter=8,
        wordWrap="CJK",
    )
    title_style = styles.ParagraphStyle(
        "YanzhangTitle",
        parent=body_style,
        fontSize=18,
        leading=26,
        alignment=1,
        spaceAfter=18,
    )
    heading_styles = {
        level: styles.ParagraphStyle(
            f"YanzhangHeading{level}",
            parent=body_style,
            fontSize=max(11, 17 - level),
            leading=max(18, 24 - level),
            spaceBefore=10,
            spaceAfter=6,
        )
        for level in range(1, 7)
    }

    def paragraph(value: str, style: Any) -> Any:
        escaped = html.escape(value, quote=True).replace("\n", "<br/>")
        return platypus.Paragraph(escaped, style)

    story: list[Any] = []
    if options.include_title:
        story.append(paragraph(_normalized_export_text(asset.title), title_style))
    for block in _blocks_without_duplicate_title(asset):
        text = _normalized_export_text(block.text).strip()
        if not text:
            continue
        if block.kind == "heading":
            story.append(paragraph(text, heading_styles[block.heading_level or 2]))
        elif block.kind in {"list", "action_item"}:
            items = [
                platypus.ListItem(paragraph(line.strip(), body_style))
                for line in text.splitlines()
                if line.strip()
            ]
            if items:
                story.append(platypus.ListFlowable(items, bulletType="bullet"))
        else:
            story.append(paragraph(text, body_style))
    buffer = _BoundedBytesIO(options.max_output_bytes)
    document = platypus.SimpleDocTemplate(
        buffer,
        pagesize=pagesizes.A4,
        title=_normalized_export_text(asset.title),
        author="",
        creator="Yanzhang",
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
        pageCompression=1,
    )
    try:
        document.build(story)
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError("PDF 渲染失败") from exc
    return buffer.getvalue()


def _evidence_index(
    evidence: Mapping[str, Evidence] | Sequence[Evidence],
) -> dict[str, Evidence]:
    if len(evidence) > _MAX_EVIDENCE_ITEMS:
        raise ExportTooLargeError("文献矩阵证据条目数量超过上限")
    values = evidence.values() if isinstance(evidence, Mapping) else evidence
    result: dict[str, Evidence] = {}
    for item in values:
        if not isinstance(item, Evidence):
            raise TypeError("evidence 应包含 Evidence")
        if item.id in result:
            raise ExportError("evidence 含重复标识")
        result[item.id] = item
    return result


def _spreadsheet_safe(value: str) -> str:
    normalized = "".join(
        character
        for character in _normalized_export_text(value)
        if unicodedata.category(character) != "Cf"
    )
    stripped = normalized.lstrip()
    if stripped.startswith(("=", "+", "-", "@", "\t")):
        return "'" + normalized
    return normalized


class _BoundedCSVBuffer(io.StringIO):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(newline="")
        self._max_bytes = max_bytes
        self._byte_count = len("\ufeff".encode("utf-8"))

    def write(self, value: str) -> int:
        encoded_size = len(value.encode("utf-8"))
        if self._byte_count + encoded_size > self._max_bytes:
            raise ExportTooLargeError("导出文件超过字节上限")
        self._byte_count += encoded_size
        return super().write(value)

    def to_bytes(self) -> bytes:
        return ("\ufeff" + self.getvalue()).encode("utf-8")


class _BoundedBytesIO(io.BytesIO):
    def __init__(self, max_bytes: int) -> None:
        super().__init__()
        self._max_bytes = max_bytes

    def write(self, data: Buffer, /) -> int:
        projected_size = max(len(self.getbuffer()), self.tell() + memoryview(data).nbytes)
        if projected_size > self._max_bytes:
            raise ExportTooLargeError("导出文件超过字节上限")
        return super().write(data)


__all__ = [
    "ExportArtifact",
    "ExportDependencyError",
    "ExportError",
    "ExportFormat",
    "ExportOptions",
    "ExportTooLargeError",
    "UnsupportedExportFormatError",
    "export_asset",
    "export_citation_matrix",
    "supported_export_formats",
]
