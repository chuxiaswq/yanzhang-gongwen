"""Bounded, offline parsers for documents imported into the Yanzhang core.

The public entry point accepts bytes rather than paths.  Callers therefore keep
filesystem access at their transport boundary, while this module applies one set
of limits before parsing untrusted text, HTML, OPC/ZIP or PDF structures.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import posixpath
import re
import stat
import unicodedata
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Final, Literal
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from yanzhang_core.models import ContentBlock, ContentBlockKind

type DocumentFormat = Literal["txt", "markdown", "html", "docx", "pdf"]
type MetadataValue = str | int | bool

_DOCX_MEDIA_TYPE: Final = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_WORD_NS: Final = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_DC_TITLE: Final = "{http://purl.org/dc/elements/1.1/}title"
_HEADING = re.compile(r"^(?:heading|标题)[ _-]*([1-6])$", re.IGNORECASE)
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_MARKDOWN_LIST = re.compile(r"^[ \t]*(?:[-+*]|\d+[.)])[ \t]+(.+)$")
_ACTIVE_RELATIONSHIP_MARKERS = (
    "attachedtemplate",
    "afchunk",
    "control",
    "oleobject",
    "package",
    "vbaproject",
)
_ACTIVE_PART_MARKERS = (
    "/activex/",
    "/embeddings/",
    "/macros/",
    "vbadata.xml",
    "vbaproject.bin",
)
_MAX_BLOCK_CHARACTERS: Final = 200_000
_MAX_DOCX_MEMBER_NAME_CHARACTERS: Final = 512
_BIDI_CONTROL_CHARACTERS: Final = frozenset(
    {
        "\ufeff",
        *(chr(value) for value in range(0x202A, 0x202F)),
        *(chr(value) for value in range(0x2066, 0x206A)),
    }
)


class DocumentParseError(ValueError):
    """Base class for a stable, user-facing import failure."""

    def __init__(self, message: str, *, code: str = "document_parse_error") -> None:
        self.code = code
        super().__init__(message)


class UnsupportedDocumentFormatError(DocumentParseError):
    """Raised when the supplied extension/media type has no registered parser."""

    def __init__(self) -> None:
        super().__init__(
            "可导入格式为 TXT、Markdown、HTML、DOCX 和 PDF",
            code="unsupported_document_format",
        )


class DocumentTooLargeError(DocumentParseError):
    """Raised before a configured byte, member, page or text budget is exceeded."""

    def __init__(self, message: str = "导入文件超过安全处理上限") -> None:
        super().__init__(message, code="document_too_large")


class UnsafeDocumentError(DocumentParseError):
    """Raised for active content, external relationships or unsafe archive paths."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="unsafe_document")


class ParserDependencyError(DocumentParseError):
    """Raised when a lazily loaded optional parser dependency is absent."""

    def __init__(self, dependency: str, feature: str) -> None:
        self.dependency = dependency
        self.feature = feature
        super().__init__(
            f"{feature}需要安装可选依赖 {dependency}",
            code="parser_dependency_missing",
        )


@dataclass(frozen=True, slots=True)
class ParseLimits:
    """Resource limits shared by every import format."""

    max_input_bytes: int = 12 * 1024 * 1024
    max_text_characters: int = 2_000_000
    max_archive_members: int = 512
    max_archive_member_bytes: int = 8 * 1024 * 1024
    max_archive_uncompressed_bytes: int = 32 * 1024 * 1024
    max_pdf_pages: int = 500
    max_blocks: int = 10_000

    def __post_init__(self) -> None:
        for name, value in (
            ("max_input_bytes", self.max_input_bytes),
            ("max_text_characters", self.max_text_characters),
            ("max_archive_members", self.max_archive_members),
            ("max_archive_member_bytes", self.max_archive_member_bytes),
            ("max_archive_uncompressed_bytes", self.max_archive_uncompressed_bytes),
            ("max_pdf_pages", self.max_pdf_pages),
            ("max_blocks", self.max_blocks),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} 应为正整数")


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Normalized text blocks returned by an import parser."""

    title: str
    content_type: str
    blocks: tuple[ContentBlock, ...]
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    page_texts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("title 应包含文本")
        if not self.blocks:
            raise ValueError("blocks 至少包含一个文本块")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def text(self) -> str:
        """Return stable plain text without transport-specific markup."""

        return "\n\n".join(block.text for block in self.blocks if block.text)


def supported_import_formats() -> tuple[DocumentFormat, ...]:
    """Return the stable import format identifiers."""

    return ("txt", "markdown", "html", "docx", "pdf")


def parse_document(
    data: bytes,
    *,
    filename: str,
    media_type: str | None = None,
    limits: ParseLimits | None = None,
) -> ParsedDocument:
    """Parse one bounded document entirely from caller-owned bytes."""

    if not isinstance(data, bytes):
        raise TypeError("data 应为 bytes")
    if media_type is not None and not isinstance(media_type, str):
        raise TypeError("media_type 应为 str")
    if limits is not None and not isinstance(limits, ParseLimits):
        raise TypeError("limits 应为 ParseLimits")
    active_limits = limits or ParseLimits()
    if not data:
        raise DocumentParseError("导入文件为空")
    if len(data) > active_limits.max_input_bytes:
        raise DocumentTooLargeError("导入文件超过字节上限")
    safe_name = _safe_source_name(filename)
    document_format = _resolve_format(safe_name, media_type)
    if document_format == "txt":
        parsed = _parse_plain_text(data, safe_name, active_limits)
    elif document_format == "markdown":
        parsed = _parse_markdown(data, safe_name, active_limits)
    elif document_format == "html":
        parsed = _parse_html(data, safe_name, active_limits)
    elif document_format == "docx":
        parsed = _parse_docx(data, safe_name, active_limits)
    else:
        parsed = _parse_pdf(data, safe_name, active_limits)
    metadata = {
        **parsed.metadata,
        "source_name": safe_name,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_bytes": len(data),
        "format": document_format,
    }
    return ParsedDocument(
        title=parsed.title,
        content_type=parsed.content_type,
        blocks=parsed.blocks,
        metadata=metadata,
        warnings=parsed.warnings,
        page_texts=parsed.page_texts,
    )


def _safe_source_name(filename: str) -> str:
    if not isinstance(filename, str):
        raise TypeError("filename 应为 str")
    if "\x00" in filename:
        raise UnsafeDocumentError("文件名含无效字符")
    normalized = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not normalized or len(normalized) > 255:
        raise DocumentParseError("文件名为空或过长")
    return normalized


def _resolve_format(filename: str, media_type: str | None) -> DocumentFormat:
    extension = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    extensions: dict[str, DocumentFormat] = {
        "txt": "txt",
        "text": "txt",
        "md": "markdown",
        "markdown": "markdown",
        "html": "html",
        "htm": "html",
        "docx": "docx",
        "pdf": "pdf",
    }
    if extension in extensions:
        return extensions[extension]
    normalized_media = (media_type or "").split(";", 1)[0].strip().casefold()
    media_types: dict[str, DocumentFormat] = {
        "text/plain": "txt",
        "text/markdown": "markdown",
        "text/x-markdown": "markdown",
        "text/html": "html",
        _DOCX_MEDIA_TYPE.casefold(): "docx",
        "application/pdf": "pdf",
    }
    try:
        return media_types[normalized_media]
    except KeyError as exc:
        raise UnsupportedDocumentFormatError from exc


def _decode_text(data: bytes) -> tuple[str, str]:
    if b"\x00" in data and not (data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff")):
        raise UnsafeDocumentError("文本文件含 NUL 字节")
    encodings = (
        ("utf-16", "utf-8-sig", "gb18030")
        if data.startswith((b"\xff\xfe", b"\xfe\xff"))
        else ("utf-8-sig", "gb18030")
    )
    for encoding in encodings:
        try:
            return _clean_text(data.decode(encoding)), encoding
        except UnicodeDecodeError:
            continue
    raise DocumentParseError("文本编码应为 UTF-8、UTF-16 或 GB18030")


def _clean_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        character
        for character in normalized
        if character in {"\n", "\t"}
        or (unicodedata.category(character) != "Cc" and character not in _BIDI_CONTROL_CHARACTERS)
    ).strip()


def _clean_html_text(value: str) -> str:
    cleaned = _clean_text(value)
    return "\n".join(
        re.sub(r"[ \t\f\v]+", " ", line).strip() for line in cleaned.splitlines()
    ).strip()


def _check_text_budget(text: str, limits: ParseLimits) -> None:
    if len(text) > limits.max_text_characters:
        raise DocumentTooLargeError("解析后的文本超过字符上限")


def _check_block_budget(count: int, limits: ParseLimits) -> None:
    if count > limits.max_blocks:
        raise DocumentTooLargeError("解析后的文本块数量超过上限")


def _fallback_title(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0].strip() if "." in filename else filename.strip()
    return (stem or "导入文档")[:300]


def _block(
    order: int,
    text: str,
    *,
    kind: ContentBlockKind = "paragraph",
    heading_level: int | None = None,
) -> ContentBlock:
    normalized = _clean_text(text)
    if len(normalized) > _MAX_BLOCK_CHARACTERS:
        raise DocumentTooLargeError("单个文本块超过字符上限")
    identity = f"{order}\x00{kind}\x00{heading_level or 0}\x00{normalized}"
    return ContentBlock(
        id="import_" + hashlib.sha256(identity.encode()).hexdigest()[:24],
        kind=kind,
        order=order,
        text=normalized,
        heading_level=heading_level,
    )


def _paragraph_blocks(text: str) -> tuple[ContentBlock, ...]:
    paragraphs = tuple(item.strip() for item in re.split(r"\n[ \t]*\n+", text) if item.strip())
    if not paragraphs and text.strip():
        paragraphs = (text.strip(),)
    return tuple(_block(index, paragraph) for index, paragraph in enumerate(paragraphs))


def _parse_plain_text(data: bytes, filename: str, limits: ParseLimits) -> ParsedDocument:
    text, encoding = _decode_text(data)
    _check_text_budget(text, limits)
    blocks = _paragraph_blocks(text)
    _check_block_budget(len(blocks), limits)
    if not blocks:
        raise DocumentParseError("文本文件没有可导入的正文")
    return ParsedDocument(
        title=_fallback_title(filename),
        content_type="text/plain",
        blocks=blocks,
        metadata={"encoding": encoding},
    )


def _parse_markdown(data: bytes, filename: str, limits: ParseLimits) -> ParsedDocument:
    text, encoding = _decode_text(data)
    _check_text_budget(text, limits)
    items: list[tuple[ContentBlockKind, str, int | None]] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        heading = _MARKDOWN_HEADING.fullmatch(line)
        if heading:
            items.append(("heading", heading.group(2).strip(), len(heading.group(1))))
            _check_block_budget(len(items), limits)
            index += 1
            continue
        list_match = _MARKDOWN_LIST.fullmatch(line)
        if list_match:
            values: list[str] = []
            while index < len(lines):
                current = _MARKDOWN_LIST.fullmatch(lines[index])
                if current is None:
                    break
                values.append(current.group(1).strip())
                index += 1
            items.append(("list", "\n".join(values), None))
            _check_block_budget(len(items), limits)
            continue
        if line.lstrip().startswith(">"):
            values = []
            while index < len(lines) and lines[index].lstrip().startswith(">"):
                values.append(lines[index].lstrip()[1:].lstrip())
                index += 1
            items.append(("quote", "\n".join(values), None))
            _check_block_budget(len(items), limits)
            continue
        values = [line]
        index += 1
        while index < len(lines) and lines[index].strip():
            if _MARKDOWN_HEADING.fullmatch(lines[index]) or _MARKDOWN_LIST.fullmatch(lines[index]):
                break
            if lines[index].lstrip().startswith(">"):
                break
            values.append(lines[index])
            index += 1
        items.append(("paragraph", "\n".join(values).strip(), None))
        _check_block_budget(len(items), limits)
    if not items:
        raise DocumentParseError("Markdown 文件没有可导入的正文")
    title = _fallback_title(filename)
    if items[0][0] == "heading" and items[0][2] == 1:
        title = items.pop(0)[1][:300]
    if not items:
        items.append(("paragraph", title, None))
    _check_block_budget(len(items), limits)
    blocks = tuple(
        _block(order, value, kind=kind, heading_level=level)
        for order, (kind, value, level) in enumerate(items)
        if value
    )
    return ParsedDocument(
        title=title,
        content_type="text/markdown",
        blocks=blocks,
        metadata={"encoding": encoding},
    )


class _SafeHTMLTextParser(HTMLParser):
    _ACTIVE_TAGS = frozenset(
        {"applet", "base", "embed", "form", "iframe", "object", "script", "style"}
    )
    _URL_ATTRIBUTES = frozenset(
        {
            "action",
            "background",
            "cite",
            "formaction",
            "href",
            "longdesc",
            "manifest",
            "ping",
            "poster",
            "src",
        }
    )
    _VOID_TAGS = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
    )
    _BLOCK_TAGS: Mapping[str, tuple[ContentBlockKind, int | None]] = MappingProxyType(
        {
            "p": ("paragraph", None),
            "li": ("list", None),
            "blockquote": ("quote", None),
            "h1": ("heading", 1),
            "h2": ("heading", 2),
            "h3": ("heading", 3),
            "h4": ("heading", 4),
            "h5": ("heading", 5),
            "h6": ("heading", 6),
        }
    )

    def __init__(self, *, max_blocks: int) -> None:
        super().__init__(convert_charrefs=True)
        self._max_blocks = max_blocks
        self.items: list[tuple[ContentBlockKind, str, int | None]] = []
        self._title = io.StringIO()
        self._current = io.StringIO()
        self._loose = io.StringIO()
        self._current_tag: str | None = None
        self._current_kind: ContentBlockKind = "paragraph"
        self._current_level: int | None = None
        self._title_depth = 0
        self._head_depth = 0
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag not in self._VOID_TAGS:
            self._depth += 1
            if self._depth > 128:
                raise UnsafeDocumentError("HTML 嵌套层级超过上限")
        if normalized_tag in self._ACTIVE_TAGS:
            raise UnsafeDocumentError("HTML 含活动内容")
        normalized_attrs = tuple((name.casefold(), value or "") for name, value in attrs)
        if normalized_tag == "meta" and any(
            name == "http-equiv" and value.strip().casefold() == "refresh"
            for name, value in normalized_attrs
        ):
            raise UnsafeDocumentError("HTML 含自动跳转指令")
        if any(name == "srcdoc" for name, _ in normalized_attrs):
            raise UnsafeDocumentError("HTML 含嵌入页面")
        for name, value in normalized_attrs:
            if name.startswith("on"):
                raise UnsafeDocumentError("HTML 含事件处理代码")
            if name in self._URL_ATTRIBUTES or name.endswith(":href") or name == "srcset":
                _validate_html_reference(value)
            if name == "style" and re.search(r"(?i)(?:url\s*\(|@import|expression\s*\()", value):
                raise UnsafeDocumentError("HTML 行内样式含外部资源或表达式")
        if normalized_tag == "head":
            self._head_depth += 1
        elif normalized_tag == "title":
            self._title_depth += 1
        if normalized_tag in self._BLOCK_TAGS:
            kind, level = self._BLOCK_TAGS[normalized_tag]
            if self._current_tag is None:
                self._flush_loose()
                self._current_tag = normalized_tag
                self._current_kind = kind
                self._current_level = level
        elif normalized_tag == "br" and self._current_tag is not None:
            self._current.write("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag == "title" and self._title_depth:
            self._title_depth -= 1
        elif normalized_tag == "head" and self._head_depth:
            self._head_depth -= 1
        if normalized_tag == self._current_tag:
            self._flush()
        if normalized_tag not in self._VOID_TAGS:
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self._title.write(data)
            return
        if self._head_depth:
            return
        if self._current_tag is not None:
            self._current.write(data)
        else:
            self._loose.write(data)

    def handle_decl(self, decl: str) -> None:
        if decl.strip().casefold() != "doctype html":
            raise UnsafeDocumentError("HTML 含外部声明")

    def handle_pi(self, data: str) -> None:
        del data
        raise UnsafeDocumentError("HTML 含处理指令")

    def unknown_decl(self, data: str) -> None:
        del data
        raise UnsafeDocumentError("HTML 含未知声明")

    def finish(self) -> None:
        self._flush()
        self._flush_loose()

    @property
    def title(self) -> str:
        return _clean_html_text(self._title.getvalue())

    def _flush(self) -> None:
        value = _clean_html_text(self._current.getvalue())
        if value:
            self._append_item(self._current_kind, value, self._current_level)
        self._current.seek(0)
        self._current.truncate(0)
        self._current_tag = None
        self._current_kind = "paragraph"
        self._current_level = None

    def _flush_loose(self) -> None:
        value = _clean_html_text(self._loose.getvalue())
        if value:
            self._append_item("paragraph", value, None)
        self._loose.seek(0)
        self._loose.truncate(0)

    def _append_item(
        self,
        kind: ContentBlockKind,
        value: str,
        level: int | None,
    ) -> None:
        if len(self.items) >= self._max_blocks:
            raise DocumentTooLargeError("HTML 文本块数量超过上限")
        self.items.append((kind, value, level))


def _validate_html_reference(value: str) -> None:
    candidate = value.strip()
    if not candidate or candidate.startswith("#"):
        return
    if "," in candidate:
        candidates = tuple(part.strip().split(" ", 1)[0] for part in candidate.split(","))
    else:
        candidates = (candidate,)
    for reference in candidates:
        parsed = urlsplit(reference)
        if parsed.scheme or parsed.netloc or reference.startswith("//"):
            raise UnsafeDocumentError("HTML 含外部链接或资源")


def _parse_html(data: bytes, filename: str, limits: ParseLimits) -> ParsedDocument:
    text, encoding = _decode_text(data)
    _check_text_budget(text, limits)
    parser = _SafeHTMLTextParser(max_blocks=limits.max_blocks)
    try:
        parser.feed(text)
        parser.close()
        parser.finish()
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError("HTML 结构解析失败") from exc
    items = parser.items
    if not items:
        raise DocumentParseError("HTML 文件没有可导入的正文")
    _check_block_budget(len(items), limits)
    title = parser.title[:300]
    if not title and items[0][0] == "heading" and items[0][2] == 1:
        title = items.pop(0)[1][:300]
    title = title or _fallback_title(filename)
    if not items:
        items.append(("paragraph", title, None))
    blocks = tuple(
        _block(order, value, kind=kind, heading_level=level)
        for order, (kind, value, level) in enumerate(items)
    )
    _check_text_budget("\n".join(block.text for block in blocks), limits)
    return ParsedDocument(
        title=title,
        content_type="text/html",
        blocks=blocks,
        metadata={"encoding": encoding},
    )


def _parse_docx(data: bytes, filename: str, limits: ParseLimits) -> ParsedDocument:
    members = _read_safe_docx_members(data, limits)
    content_types = members.get("[Content_Types].xml")
    document_xml = members.get("word/document.xml")
    if content_types is None or document_xml is None:
        raise DocumentParseError("DOCX 缺少必要的 Open XML 部件")
    _safe_xml(content_types)
    lowered_types = content_types.lower()
    if b"macroenabled" in lowered_types or b"vbaproject" in lowered_types:
        raise UnsafeDocumentError("DOCX 含宏内容类型")
    names = frozenset(members)
    for name, payload in members.items():
        if name.casefold().endswith(".rels"):
            _validate_relationships(name, payload, names)
    root = _safe_xml(document_xml)
    _validate_word_xml(root)
    items: list[tuple[ContentBlockKind, str, int | None]] = []
    for paragraph in root.iter(f"{{{_WORD_NS}}}p"):
        value = _word_paragraph_text(paragraph)
        if not value:
            continue
        kind, level = _word_paragraph_kind(paragraph)
        items.append((kind, value, level))
        _check_block_budget(len(items), limits)
    if not items:
        raise DocumentParseError("DOCX 没有可导入的正文")
    title = ""
    core = members.get("docProps/core.xml")
    if core is not None:
        core_root = _safe_xml(core)
        title_node = core_root.find(f".//{_DC_TITLE}")
        if title_node is not None and title_node.text:
            title = _clean_text(title_node.text)[:300]
    if not title and items[0][0] in {"title", "heading"} and items[0][2] in {None, 1}:
        title = items.pop(0)[1][:300]
    title = title or _fallback_title(filename)
    if not items:
        items.append(("paragraph", title, None))
    blocks = tuple(
        _block(order, value, kind=kind, heading_level=level)
        for order, (kind, value, level) in enumerate(items)
    )
    _check_text_budget("\n".join(block.text for block in blocks), limits)
    return ParsedDocument(
        title=title,
        content_type=_DOCX_MEDIA_TYPE,
        blocks=blocks,
        metadata={"archive_members": len(members)},
    )


def _read_safe_docx_members(data: bytes, limits: ParseLimits) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DocumentParseError("DOCX ZIP 容器损坏") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > limits.max_archive_members:
            raise DocumentTooLargeError("DOCX ZIP 成员数量超过上限")
        names: set[str] = set()
        total = 0
        selected: dict[str, bytes] = {}
        for info in infos:
            name = info.filename
            is_directory = info.is_dir()
            checked_name = name[:-1] if is_directory and name.endswith("/") else name
            pure = PurePosixPath(name)
            parts = checked_name.split("/")
            if (
                not checked_name
                or len(name) > _MAX_DOCX_MEMBER_NAME_CHARACTERS
                or "\x00" in name
                or pure.is_absolute()
                or "\\" in name
                or any(part in {"", ".", ".."} for part in parts)
            ):
                raise UnsafeDocumentError("DOCX ZIP 含路径穿越或无效成员名")
            folded = checked_name.casefold()
            if folded in names:
                raise UnsafeDocumentError("DOCX ZIP 含重复成员名")
            names.add(folded)
            mode = info.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            expected_types = {0, stat.S_IFDIR} if is_directory else {0, stat.S_IFREG}
            if file_type not in expected_types:
                raise UnsafeDocumentError("DOCX ZIP 含链接或特殊成员")
            if is_directory:
                continue
            if info.flag_bits & 0x1:
                raise UnsafeDocumentError("DOCX ZIP 含加密成员")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise UnsafeDocumentError("DOCX ZIP 使用未批准的压缩算法")
            if info.file_size > limits.max_archive_member_bytes:
                raise DocumentTooLargeError("DOCX ZIP 单个成员超过解压上限")
            total += info.file_size
            if total > limits.max_archive_uncompressed_bytes:
                raise DocumentTooLargeError("DOCX ZIP 解压总量超过上限")
            if folded.endswith(".bin") or any(
                marker in f"/{folded}" for marker in _ACTIVE_PART_MARKERS
            ):
                raise UnsafeDocumentError("DOCX 含宏或嵌入活动内容")
            selected[name] = b""
            if (
                folded.endswith(".xml")
                or folded.endswith(".rels")
                or folded == "[content_types].xml"
            ):
                selected[name] = _read_archive_member(archive, info, limits)
        return selected


def _read_archive_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    limits: ParseLimits,
) -> bytes:
    try:
        with archive.open(info, "r") as member:
            payload = member.read(limits.max_archive_member_bytes + 1)
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, NotImplementedError) as exc:
        raise DocumentParseError("DOCX ZIP 成员读取失败") from exc
    if len(payload) > limits.max_archive_member_bytes:
        raise DocumentTooLargeError("DOCX ZIP 单个成员超过解压上限")
    return payload


def _safe_xml(payload: bytes) -> ElementTree.Element:
    if b"\x00" in payload or re.search(rb"<!\s*(?:doctype|entity)\b", payload, re.IGNORECASE):
        raise UnsafeDocumentError("DOCX XML 含实体或不受支持的编码")
    try:
        return ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise DocumentParseError("DOCX XML 部件解析失败") from exc


def _validate_relationships(name: str, payload: bytes, names: frozenset[str]) -> None:
    root = _safe_xml(payload)
    for relationship in root.iter():
        if relationship.tag.rsplit("}", 1)[-1] != "Relationship":
            continue
        target = relationship.attrib.get("Target", "").strip()
        target_mode = relationship.attrib.get("TargetMode", "").strip().casefold()
        relation_type = relationship.attrib.get("Type", "").casefold()
        if target_mode not in {"", "internal"}:
            raise UnsafeDocumentError("DOCX 含外部关系")
        if any(marker in relation_type for marker in _ACTIVE_RELATIONSHIP_MARKERS):
            raise UnsafeDocumentError("DOCX 含活动关系")
        if not target:
            raise UnsafeDocumentError("DOCX 关系目标为空")
        decoded = unquote(target)
        parsed = urlsplit(decoded)
        if (
            parsed.scheme
            or parsed.netloc
            or decoded.startswith("//")
            or "\\" in decoded
            or any(unicodedata.category(character) in {"Cc", "Cf"} for character in decoded)
        ):
            raise UnsafeDocumentError("DOCX 含外部关系")
        if parsed.query or parsed.fragment:
            raise UnsafeDocumentError("DOCX 关系目标含参数或片段")
        if decoded.startswith("/") or name == "_rels/.rels":
            base = ""
        else:
            base = PurePosixPath(name).parent.parent.as_posix()
        normalized = posixpath.normpath(posixpath.join(base, decoded.lstrip("/")))
        if normalized == ".." or normalized.startswith("../"):
            raise UnsafeDocumentError("DOCX 关系目标越过包边界")
        if normalized not in names:
            raise UnsafeDocumentError("DOCX 关系指向缺失部件")


def _validate_word_xml(root: ElementTree.Element) -> None:
    active_field_markers = (
        "database",
        "dde",
        "ddeauto",
        "hyperlink",
        "includepicture",
        "includetext",
        "link",
    )
    for node in root.iter():
        local_name = node.tag.rsplit("}", 1)[-1].casefold()
        if local_name == "altchunk":
            raise UnsafeDocumentError("DOCX 含外部或活动字段")
        if local_name not in {"fldsimple", "instrtext"}:
            continue
        instruction = " ".join((node.text or "", *node.attrib.values())).strip().casefold()
        if any(re.search(rf"\b{marker}\b", instruction) for marker in active_field_markers):
            raise UnsafeDocumentError("DOCX 含外部或活动字段")


def _word_paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        local_name = node.tag.rsplit("}", 1)[-1]
        if local_name == "t" and node.text:
            parts.append(node.text)
        elif local_name == "tab":
            parts.append("\t")
        elif local_name in {"br", "cr"}:
            parts.append("\n")
    return _clean_text("".join(parts))


def _word_paragraph_kind(
    paragraph: ElementTree.Element,
) -> tuple[ContentBlockKind, int | None]:
    properties = paragraph.find(f"{{{_WORD_NS}}}pPr")
    if properties is None:
        return "paragraph", None
    style = properties.find(f"{{{_WORD_NS}}}pStyle")
    style_name = ""
    if style is not None:
        style_name = style.attrib.get(f"{{{_WORD_NS}}}val", "").strip()
    heading = _HEADING.fullmatch(style_name)
    if heading:
        return "heading", int(heading.group(1))
    if style_name.casefold() in {"title", "标题"}:
        return "title", None
    outline = properties.find(f"{{{_WORD_NS}}}outlineLvl")
    if outline is not None:
        raw_level = outline.attrib.get(f"{{{_WORD_NS}}}val", "")
        if raw_level.isdigit() and 0 <= int(raw_level) <= 5:
            return "heading", int(raw_level) + 1
    if properties.find(f"{{{_WORD_NS}}}numPr") is not None:
        return "list", None
    if "quote" in style_name.casefold() or "引用" in style_name:
        return "quote", None
    return "paragraph", None


def _load_pypdf() -> Any:
    try:
        return importlib.import_module("pypdf")
    except (ImportError, ModuleNotFoundError) as exc:
        raise ParserDependencyError("pypdf", "PDF 导入") from exc


def _parse_pdf(data: bytes, filename: str, limits: ParseLimits) -> ParsedDocument:
    pypdf = _load_pypdf()
    try:
        reader = pypdf.PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise UnsafeDocumentError("PDF 已加密")
        pages: Sequence[Any] = reader.pages
        if len(pages) > limits.max_pdf_pages:
            raise DocumentTooLargeError("PDF 页数超过上限")
        _validate_pdf_catalog(reader)
        blocks: list[ContentBlock] = []
        warnings: list[str] = []
        page_texts: list[str] = []
        character_count = 0
        for page_number, page in enumerate(pages, start=1):
            _validate_pdf_page(page)
            extracted = _clean_text(page.extract_text() or "")
            page_texts.append(extracted)
            if not extracted:
                warnings.append(f"第 {page_number} 页没有可提取文本")
                continue
            character_count += len(extracted)
            if character_count > limits.max_text_characters:
                raise DocumentTooLargeError("PDF 提取文本超过字符上限")
            paragraphs = _paragraph_blocks(extracted)
            _check_block_budget(len(blocks) + len(paragraphs), limits)
            for paragraph in paragraphs:
                blocks.append(
                    _block(
                        len(blocks),
                        paragraph.text,
                        kind=paragraph.kind,
                        heading_level=paragraph.heading_level,
                    )
                )
        if not blocks:
            raise DocumentParseError("PDF 没有可提取的文本")
        metadata = getattr(reader, "metadata", None)
        raw_title = getattr(metadata, "title", "") if metadata is not None else ""
        title = _clean_text(raw_title)[:300] if isinstance(raw_title, str) else ""
        return ParsedDocument(
            title=title or _fallback_title(filename),
            content_type="application/pdf",
            blocks=tuple(blocks),
            metadata={"pages": len(pages)},
            warnings=tuple(warnings),
            page_texts=tuple(page_texts),
        )
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError("PDF 结构解析失败") from exc


def _pdf_object(value: Any) -> Any:
    getter = getattr(value, "get_object", None)
    return getter() if callable(getter) else value


def _validate_pdf_catalog(reader: Any) -> None:
    trailer = _pdf_object(reader.trailer)
    root = _pdf_object(trailer.get("/Root")) if hasattr(trailer, "get") else None
    root_get = getattr(root, "get", None)
    if not callable(root_get):
        return
    if root_get("/OpenAction") is not None or root_get("/AA") is not None:
        raise UnsafeDocumentError("PDF 含自动执行动作")
    names = _pdf_object(root_get("/Names"))
    if hasattr(names, "get") and (
        names.get("/JavaScript") is not None or names.get("/EmbeddedFiles") is not None
    ):
        raise UnsafeDocumentError("PDF 含脚本或嵌入文件")
    form = _pdf_object(root_get("/AcroForm"))
    if hasattr(form, "get"):
        if form.get("/XFA") is not None:
            raise UnsafeDocumentError("PDF 含活动表单")
        _validate_pdf_fields(_pdf_object(form.get("/Fields")))


def _validate_pdf_fields(fields: Any, *, depth: int = 0, seen: int = 0) -> int:
    if fields is None:
        return seen
    if depth > 32 or seen > 10_000:
        raise DocumentTooLargeError("PDF 表单结构超过上限")
    if not isinstance(fields, Sequence) or isinstance(fields, (str, bytes)):
        return seen
    for field_ref in fields:
        seen += 1
        if seen > 10_000:
            raise DocumentTooLargeError("PDF 表单结构超过上限")
        field = _pdf_object(field_ref)
        if not hasattr(field, "get"):
            continue
        if field.get("/AA") is not None or field.get("/A") is not None:
            raise UnsafeDocumentError("PDF 含活动表单")
        if field.get("/JS") is not None:
            raise UnsafeDocumentError("PDF 含脚本")
        seen = _validate_pdf_fields(_pdf_object(field.get("/Kids")), depth=depth + 1, seen=seen)
    return seen


def _validate_pdf_page(page: Any) -> None:
    page_object = _pdf_object(page)
    if not hasattr(page_object, "get"):
        return
    if page_object.get("/AA") is not None:
        raise UnsafeDocumentError("PDF 页面含自动执行动作")
    annotations = _pdf_object(page_object.get("/Annots"))
    if not isinstance(annotations, Sequence) or isinstance(annotations, (str, bytes)):
        return
    for annotation_ref in annotations:
        annotation = _pdf_object(annotation_ref)
        if not hasattr(annotation, "get"):
            continue
        subtype = str(annotation.get("/Subtype", ""))
        if subtype in {"/3D", "/FileAttachment", "/Movie", "/RichMedia", "/Screen", "/Sound"}:
            raise UnsafeDocumentError("PDF 含附件或活动媒体")
        if annotation.get("/AA") is not None or annotation.get("/FS") is not None:
            raise UnsafeDocumentError("PDF 含附件或活动动作")
        action = _pdf_object(annotation.get("/A"))
        if not hasattr(action, "get"):
            continue
        action_type = str(action.get("/S", ""))
        if action_type and action_type != "/GoTo":
            raise UnsafeDocumentError("PDF 含外部链接或活动动作")


__all__ = [
    "DocumentFormat",
    "DocumentParseError",
    "DocumentTooLargeError",
    "ParseLimits",
    "ParsedDocument",
    "ParserDependencyError",
    "UnsafeDocumentError",
    "UnsupportedDocumentFormatError",
    "parse_document",
    "supported_import_formats",
]
