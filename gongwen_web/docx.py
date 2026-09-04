"""Dependency-free OOXML and batch ZIP generation."""

# Chinese punctuation is intentional in the generated document text.
# ruff: noqa: E501, RUF001

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import PurePath
from xml.sax.saxutils import escape

from gongwen_web.models import BatchExportRequest, ExportDocument
from gongwen_web.resource_limits import MAX_BATCH_EXPANDED_CHARACTERS
from yanzhang_core.models import ContentBlock

_HEADING = re.compile(r"^(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\d+[.、])")
_INVALID_FILENAME = re.compile(r"[\\/:*?\"<>|\x00-\x1f]+")
_MERGE_FIELD = re.compile(r"\{\{\s*([^{}\r\n]{1,80}?)\s*\}\}")


def build_docx(document: ExportDocument) -> bytes:
    """Return a valid minimal DOCX package using only the standard library."""

    return _build_docx_package(document, _document_xml(document))


def build_docx_from_blocks(
    title: str,
    blocks: Sequence[ContentBlock],
    *,
    template_style: str = "standard",
) -> bytes:
    """Build a DOCX from typed blocks while preserving explicit heading levels."""

    if template_style not in {"standard", "brief"}:
        raise ValueError("template_style 应为 standard 或 brief")
    document = ExportDocument(
        title=title,
        content="structured-block-export",
        template_style=template_style,
    )
    return _build_docx_package(document, _structured_document_xml(document, blocks))


def _build_docx_package(document: ExportDocument, document_xml: str) -> bytes:
    """Write the shared deterministic OOXML package around one document body."""

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        _write_part(archive, "[Content_Types].xml", _content_types())
        _write_part(archive, "_rels/.rels", _package_relationships())
        _write_part(archive, "docProps/core.xml", _core_properties(document))
        _write_part(archive, "docProps/app.xml", _app_properties())
        _write_part(archive, "word/document.xml", document_xml)
        _write_part(archive, "word/styles.xml", _styles_xml())
        _write_part(archive, "word/settings.xml", _settings_xml())
        _write_part(archive, "word/_rels/document.xml.rels", _document_relationships())
    return stream.getvalue()


def build_batch_zip(request: BatchExportRequest) -> tuple[bytes, list[str]]:
    """Merge rows into a template and return a ZIP containing DOCX files."""

    documents = _batch_documents(request)
    if not documents:
        raise ValueError("批量导出至少需要一个数据行或一份文档")
    stream = io.BytesIO()
    names: list[str] = []
    used: set[str] = set()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, document in enumerate(documents, start=1):
            desired = document.filename or document.title or f"公文-{index}"
            name = unique_filename(desired, used, suffix=".docx")
            used.add(name)
            names.append(name)
            _write_part(archive, name, build_docx(document))
        manifest = "\n".join(f"{index}. {name}" for index, name in enumerate(names, start=1))
        _write_part(archive, "生成清单.txt", manifest)
    return stream.getvalue(), names


def unique_filename(value: str, used: set[str] | None = None, *, suffix: str) -> str:
    """Normalize an attachment name and avoid duplicate ZIP entries."""

    leaf = PurePath(value.strip()).name
    cleaned = _INVALID_FILENAME.sub("_", leaf).strip(" ._") or "公文"
    if cleaned.casefold().endswith(suffix.casefold()):
        cleaned = cleaned[: -len(suffix)]
    cleaned = cleaned[:80].rstrip(" ._") or "公文"
    candidate = f"{cleaned}{suffix}"
    used_folded = {name.casefold() for name in used or set()}
    if candidate.casefold() not in used_folded:
        return candidate
    counter = 2
    while f"{cleaned}-{counter}{suffix}".casefold() in used_folded:
        counter += 1
    return f"{cleaned}-{counter}{suffix}"


def _batch_documents(request: BatchExportRequest) -> list[ExportDocument]:
    if request.documents:
        _enforce_expanded_character_budget(request.documents)
        return request.documents
    template_value = request.document or request.template
    if isinstance(template_value, ExportDocument):
        template = template_value
    elif isinstance(template_value, str):
        template = ExportDocument(title="{{DOC_TITLE}}", content=template_value)
    else:
        return []
    rows = request.rows or [{}]
    required_fields = _document_field_names(template)
    content_fields = _field_names(template.content)
    metadata_fields = {
        name
        for value in template.metadata.values()
        if isinstance(value, str)
        for name in _field_names(value)
    }
    if _is_single_field(template.title, "DOC_TITLE") and "DOC_TITLE" not in (
        content_fields | metadata_fields
    ):
        required_fields.discard("DOC_TITLE")
    documents: list[ExportDocument] = []
    expanded_characters = 0
    for index, row in enumerate(rows, start=1):
        available = {" ".join(str(key).split()): value for key, value in row.items()}
        missing = sorted(
            name
            for name in required_fields
            if name not in available or not _value_text(available[name]).strip()
        )
        if missing:
            raise ValueError(f"第 {index} 行缺少字段：{'、'.join(missing)}")
        projected_title_characters = _rendered_character_count(template.title, row)
        if _is_single_field(template.title, "DOC_TITLE"):
            projected_title_characters = max(
                projected_title_characters,
                len(_row_text(row, "DOC_TITLE", "title") or f"公文-{index}"),
            )
        requested_name = _row_text(row, "filename", "FILE_NAME")
        projected_filename = requested_name or template.filename
        projected_characters = projected_title_characters
        projected_characters += _rendered_character_count(template.content, row)
        projected_characters += sum(
            _rendered_character_count(value, row)
            if isinstance(value, str)
            else len(_value_text(value))
            for value in template.metadata.values()
        )
        projected_characters += len(projected_filename or "")
        if not projected_filename:
            projected_characters += projected_title_characters
        expanded_characters += projected_characters
        if expanded_characters > MAX_BATCH_EXPANDED_CHARACTERS:
            raise ValueError(f"批量导出展开后的内容超过 {MAX_BATCH_EXPANDED_CHARACTERS} 个字符预算")
        title = render_fields(template.title, row)
        if not title or title == "{{DOC_TITLE}}":
            title = _row_text(row, "DOC_TITLE", "title") or f"公文-{index}"
        content = render_fields(template.content, row)
        metadata = {
            key: render_fields(str(value), row) if isinstance(value, str) else value
            for key, value in template.metadata.items()
        }
        documents.append(
            ExportDocument(
                title=title,
                content=content,
                metadata=metadata,
                template_style=template.template_style,
                filename=requested_name or template.filename or title,
            )
        )
    return documents


def _enforce_expanded_character_budget(documents: list[ExportDocument]) -> None:
    expanded_characters = 0
    for document in documents:
        expanded_characters += len(document.title) + len(document.content)
        expanded_characters += sum(len(_value_text(value)) for value in document.metadata.values())
        expanded_characters += len(document.filename or "")
        if expanded_characters > MAX_BATCH_EXPANDED_CHARACTERS:
            raise ValueError(f"批量导出展开后的内容超过 {MAX_BATCH_EXPANDED_CHARACTERS} 个字符预算")


def _rendered_character_count(template: str, row: Mapping[str, object]) -> int:
    """Predict one rendered value without allocating the expanded string."""

    values = {
        " ".join(str(raw_key).split()): _value_text(raw_value) for raw_key, raw_value in row.items()
    }
    total = 0
    previous_end = 0
    for match in _MERGE_FIELD.finditer(template):
        total += match.start() - previous_end
        name = " ".join(match.group(1).split())
        total += len(values.get(name, match.group(0)))
        previous_end = match.end()
    return total + len(template) - previous_end


def _document_field_names(document: ExportDocument) -> set[str]:
    values = [document.title, document.content]
    values.extend(str(value) for value in document.metadata.values() if isinstance(value, str))
    return {name for value in values for name in _field_names(value)}


def _field_names(value: str) -> set[str]:
    return {" ".join(match.group(1).split()) for match in _MERGE_FIELD.finditer(value)}


def _is_single_field(value: str, name: str) -> bool:
    match = _MERGE_FIELD.fullmatch(value.strip())
    return bool(match and " ".join(match.group(1).split()) == name)


def render_fields(template: str, row: Mapping[str, object]) -> str:
    """Replace documented ``{{ field }}`` markers once from one data row."""

    values = {
        " ".join(str(raw_key).split()): _value_text(raw_value)
        for raw_key, raw_value in row.items()
        if str(raw_key).strip()
    }

    def replace(match: re.Match[str]) -> str:
        name = " ".join(match.group(1).split())
        return values.get(name, match.group(0))

    return _MERGE_FIELD.sub(replace, template)


def _row_text(row: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return _value_text(value).strip()
    return ""


def _value_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, list):
        return "、".join(_value_text(item) for item in value)
    return str(value)


def _write_part(archive: zipfile.ZipFile, name: str, content: str | bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, content.encode("utf-8") if isinstance(content, str) else content)


def _document_xml(document: ExportDocument) -> str:
    style: str = document.template_style
    metadata_style = _metadata_text(document.metadata, "template_style", "template", "layout")
    if metadata_style in {"standard", "brief"}:
        style = metadata_style
    paragraphs = [_paragraph(document.title, "title", style)]
    doc_number = _metadata_text(document.metadata, "doc_number", "DOC_NUMBER")
    if doc_number:
        paragraphs.append(_paragraph(doc_number, "center", style))
    paragraphs.extend(
        _paragraph(line, "heading" if _HEADING.match(line.strip()) else "body", style)
        for line in document.content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    )
    issuer = _metadata_text(document.metadata, "issuing_org", "ISSUING_ORG", "issuer")
    issue_date = _metadata_text(document.metadata, "issue_date", "ISSUE_DATE", "date")
    if issuer:
        paragraphs.append(_paragraph(issuer, "right", style))
    if issue_date:
        paragraphs.append(_paragraph(issue_date, "right", style))
    return _wrap_document_xml("".join(paragraphs), style)


def _structured_document_xml(
    document: ExportDocument,
    blocks: Sequence[ContentBlock],
) -> str:
    style: str = document.template_style
    paragraphs = [_paragraph(document.title, "title", style)]
    normalized_title = _normalized_text(document.title)
    for block in sorted(blocks, key=lambda item: item.order):
        text = block.text.strip()
        if not text:
            continue
        if block.kind == "title" and _normalized_text(text) == normalized_title:
            continue
        lines = tuple(line.strip() for line in text.splitlines() if line.strip()) or (text,)
        if block.kind == "heading":
            paragraphs.append(
                _paragraph(
                    lines[0],
                    "heading",
                    style,
                    heading_level=block.heading_level or 1,
                )
            )
            paragraphs.extend(_paragraph(line, "body", style) for line in lines[1:])
        elif block.kind == "title":
            paragraphs.extend(_paragraph(line, "title", style) for line in lines)
        elif block.kind == "subtitle":
            paragraphs.extend(_paragraph(line, "center", style) for line in lines)
        else:
            paragraphs.extend(_paragraph(line, "body", style) for line in lines)
    return _wrap_document_xml("".join(paragraphs), style)


def _normalized_text(value: str) -> str:
    return "".join(value.split())


def _wrap_document_xml(body: str, style: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}"
        "<w:sectPr>"
        '<w:pgSz w:w="11906" w:h="16838"/>'
        f'<w:pgMar w:top="{1440 if style == "brief" else 2098}" '
        f'w:right="{1440 if style == "brief" else 1588}" '
        f'w:bottom="{1440 if style == "brief" else 1984}" '
        f'w:left="{1440 if style == "brief" else 1588}" '
        'w:header="851" w:footer="992" w:gutter="0"/>'
        '<w:cols w:space="425"/><w:docGrid w:type="lines" w:linePitch="560"/>'
        "</w:sectPr></w:body></w:document>"
    )


def _paragraph(
    text: str,
    kind: str,
    template_style: str,
    *,
    heading_level: int = 1,
) -> str:
    clean = text.strip()
    if not clean:
        return "<w:p/>"
    if kind == "title":
        properties = (
            '<w:pPr><w:pStyle w:val="Title"/><w:jc w:val="center"/>'
            '<w:spacing w:before="0" w:after="560" '
            'w:line="560" w:lineRule="exact"/></w:pPr>'
        )
        run = _runs(
            clean,
            font="黑体" if template_style == "brief" else "方正小标宋简体",
            size=36 if template_style == "brief" else 44,
            bold=template_style == "brief",
        )
    elif kind == "heading":
        level = min(max(heading_level, 1), 6)
        properties = (
            f'<w:pPr><w:pStyle w:val="Heading{level}"/><w:outlineLvl w:val="{level - 1}"/>'
            '<w:keepNext/><w:spacing w:before="280" w:after="0" '
            'w:line="560" w:lineRule="exact"/></w:pPr>'
        )
        run = _runs(
            clean,
            font="黑体",
            size=30 if template_style == "brief" else 32,
            bold=template_style == "brief",
        )
    elif kind in {"center", "right"}:
        properties = (
            f'<w:pPr><w:jc w:val="{kind}"/><w:spacing w:line="560" w:lineRule="exact"/></w:pPr>'
        )
        run = _runs(
            clean,
            font="宋体" if template_style == "brief" else "仿宋_GB2312",
            size=28 if template_style == "brief" else 32,
            bold=False,
        )
    else:
        properties = (
            '<w:pPr><w:ind w:firstLineChars="200"/><w:spacing w:before="0" w:after="0" '
            'w:line="560" w:lineRule="exact"/></w:pPr>'
        )
        run = _runs(
            clean,
            font="宋体" if template_style == "brief" else "仿宋_GB2312",
            size=28 if template_style == "brief" else 32,
            bold=False,
        )
    return f"<w:p>{properties}{run}</w:p>"


def _runs(text: str, *, font: str, size: int, bold: bool) -> str:
    """Render text while turning ``{{name}}`` placeholders into Word fields."""

    runs: list[str] = []
    cursor = 0
    for match in _MERGE_FIELD.finditer(text):
        if match.start() > cursor:
            runs.append(_text_run(text[cursor : match.start()], font=font, size=size, bold=bold))
        field_name = " ".join(match.group(1).split())
        runs.append(_merge_field_runs(field_name, font=font, size=size, bold=bold))
        cursor = match.end()
    if cursor < len(text):
        runs.append(_text_run(text[cursor:], font=font, size=size, bold=bold))
    return "".join(runs)


def _text_run(text: str, *, font: str, size: int, bold: bool) -> str:
    bold_xml = "<w:b/>" if bold else ""
    return (
        "<w:r><w:rPr>"
        f'<w:rFonts w:ascii="{_xml_escape(font)}" w:hAnsi="{_xml_escape(font)}" '
        f'w:eastAsia="{_xml_escape(font)}"/>{bold_xml}<w:sz w:val="{size}"/>'
        f'<w:szCs w:val="{size}"/></w:rPr><w:t xml:space="preserve">{_xml_escape(text)}</w:t></w:r>'
    )


def _merge_field_runs(field_name: str, *, font: str, size: int, bold: bool) -> str:
    """Build the five-run complex-field form understood by Word and WPS."""

    safe_name = field_name.replace('"', "'")
    properties = _run_properties(font=font, size=size, bold=bold)
    instruction = _xml_escape(f' MERGEFIELD "{safe_name}" \\* MERGEFORMAT ')
    result = _xml_escape(f"«{safe_name}»")
    return (
        f'<w:r>{properties}<w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r>{properties}<w:instrText xml:space="preserve">{instruction}</w:instrText></w:r>'
        f'<w:r>{properties}<w:fldChar w:fldCharType="separate"/></w:r>'
        f"<w:r>{properties}<w:t>{result}</w:t></w:r>"
        f'<w:r>{properties}<w:fldChar w:fldCharType="end"/></w:r>'
    )


def _run_properties(*, font: str, size: int, bold: bool) -> str:
    bold_xml = "<w:b/>" if bold else ""
    return (
        "<w:rPr>"
        f'<w:rFonts w:ascii="{_xml_escape(font)}" w:hAnsi="{_xml_escape(font)}" '
        f'w:eastAsia="{_xml_escape(font)}"/>{bold_xml}<w:sz w:val="{size}"/>'
        f'<w:szCs w:val="{size}"/></w:rPr>'
    )


def _xml_escape(value: str) -> str:
    """Remove characters disallowed by XML 1.0, then escape markup."""

    clean = "".join(
        character
        for character in value
        if character in "\t\n\r"
        or "\u0020" <= character <= "\ud7ff"
        or "\ue000" <= character <= "\ufffd"
        or "\U00010000" <= character <= "\U0010ffff"
    )
    return escape(clean)


def _metadata_text(metadata: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        if key in metadata:
            return _value_text(metadata[key]).strip()
    return ""


def _content_types() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""


def _package_relationships() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""


def _document_relationships() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>
</Relationships>"""


def _styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="仿宋_GB2312" w:hAnsi="仿宋_GB2312" w:eastAsia="仿宋_GB2312"/><w:sz w:val="32"/><w:lang w:val="zh-CN" w:eastAsia="zh-CN"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:line="560" w:lineRule="exact"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="正文"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="标题"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="标题 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="标题 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="标题 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Heading4"><w:name w:val="标题 4"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Heading5"><w:name w:val="标题 5"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Heading6"><w:name w:val="标题 6"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/></w:style>
</w:styles>"""


def _settings_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:characterSpacingControl w:val="doNotCompress"/><w:updateFields w:val="true"/><w:compat/><w:decimalSymbol w:val="."/><w:listSeparator w:val=","/></w:settings>"""


def _core_properties(document: ExportDocument) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{_xml_escape(document.title)}</dc:title><dc:creator>砚章公文写作工作台</dc:creator>"
        "<cp:lastModifiedBy>砚章公文写作工作台</cp:lastModifiedBy>"
        '<dcterms:created xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:created>'
        "</cp:coreProperties>"
    )


def _app_properties() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>砚章公文写作工作台</Application><AppVersion>1.0</AppVersion></Properties>"""


__all__ = [
    "build_batch_zip",
    "build_docx",
    "build_docx_from_blocks",
    "render_fields",
    "unique_filename",
]
