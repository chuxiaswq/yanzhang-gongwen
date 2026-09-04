"""Offline contracts for bounded document import and generic export."""

from __future__ import annotations

import csv
import hashlib
import importlib
import importlib.util
import io
import stat
import zipfile
from collections.abc import Mapping, Sequence
from types import SimpleNamespace
from typing import Any

import pytest

from yanzhang_core.exporters import (
    ExportDependencyError,
    ExportOptions,
    ExportTooLargeError,
    UnsupportedExportFormatError,
    export_asset,
    export_citation_matrix,
    supported_export_formats,
)
from yanzhang_core.models import ContentBlock, Evidence, TextAsset
from yanzhang_core.parsers import (
    DocumentParseError,
    DocumentTooLargeError,
    ParseLimits,
    ParserDependencyError,
    UnsafeDocumentError,
    UnsupportedDocumentFormatError,
    parse_document,
    supported_import_formats,
)

_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _asset(
    *blocks: ContentBlock,
    title: str = "项目复盘",
) -> TextAsset:
    return TextAsset(
        id="asset-1",
        brief_id="brief-1",
        title=title,
        content_type="工作总结",
        blocks=blocks,
    )


def _zip_bytes(
    members: Sequence[tuple[str | zipfile.ZipInfo, bytes]],
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return buffer.getvalue()


def _docx_bytes(
    *,
    document_xml: bytes | None = None,
    document_relationships: bytes | None = None,
    extra_members: Mapping[str, bytes] | None = None,
) -> bytes:
    content_types = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        b'<Default Extension="rels" '
        b'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        b'<Default Extension="xml" ContentType="application/xml"/>'
        b'<Override PartName="/word/document.xml" '
        b'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.'
        b'document.main+xml"/></Types>'
    )
    root_relationships = (
        f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{_REL_NS}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    ).encode()
    default_document = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="{_WORD_NS}"><w:body>
  <w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>治理能力建设</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>一、总体要求</w:t></w:r></w:p>
  <w:p><w:r><w:t>坚持实事求是。</w:t></w:r></w:p>
  <w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>第一项任务</w:t></w:r></w:p>
</w:body></w:document>""".encode()
    members: list[tuple[str | zipfile.ZipInfo, bytes]] = [
        ("[Content_Types].xml", content_types),
        ("_rels/.rels", root_relationships),
        ("word/document.xml", document_xml or default_document),
    ]
    if document_relationships is not None:
        members.append(("word/_rels/document.xml.rels", document_relationships))
    members.extend((extra_members or {}).items())
    return _zip_bytes(members)


def test_supported_format_catalogs_are_canonical() -> None:
    assert supported_import_formats() == ("txt", "markdown", "html", "docx", "pdf")
    assert supported_export_formats() == (
        "markdown",
        "txt",
        "html",
        "latex",
        "pdf",
        "citation_csv",
    )


def test_plain_text_import_is_bounded_normalized_and_traceable() -> None:
    payload = "第一段\r\n\r\n第\u202e二段".encode()
    parsed = parse_document(payload, filename="../../工作记录.txt")

    assert parsed.title == "工作记录"
    assert tuple(block.text for block in parsed.blocks) == ("第一段", "第二段")
    assert parsed.text == "第一段\n\n第二段"
    assert parsed.metadata["source_name"] == "工作记录.txt"
    assert parsed.metadata["source_sha256"] == hashlib.sha256(payload).hexdigest()
    assert parsed.metadata["source_bytes"] == len(payload)
    with pytest.raises(TypeError):
        parsed.metadata["new"] = "value"  # type: ignore[index]


def test_plain_text_can_resolve_media_type_and_decode_gb18030() -> None:
    parsed = parse_document(
        "中文材料".encode("gb18030"),
        filename="upload",
        media_type="text/plain; charset=gb18030",
    )

    assert parsed.text == "中文材料"
    assert parsed.metadata["encoding"] == "gb18030"


def test_markdown_import_preserves_structural_blocks() -> None:
    payload = """# 年度总结

## 一、工作成效

- 完成任务
- 优化流程

> 数据均来自台账。

下一步持续推进。
""".encode()
    parsed = parse_document(payload, filename="summary.md")

    assert parsed.title == "年度总结"
    assert tuple(block.kind for block in parsed.blocks) == (
        "heading",
        "list",
        "quote",
        "paragraph",
    )
    assert parsed.blocks[0].heading_level == 2
    assert parsed.blocks[1].text == "完成任务\n优化流程"


def test_html_import_extracts_loose_and_structured_text() -> None:
    payload = b"""<!doctype html><html><head><title>Policy &amp; Review</title></head>
<body>lead <p>safe &lt;text&gt;<br>next</p> tail <a href="/local">local</a></body></html>"""
    parsed = parse_document(payload, filename="source.html")

    assert parsed.title == "Policy & Review"
    assert tuple(block.text for block in parsed.blocks) == (
        "lead",
        "safe <text>\nnext",
        "tail local",
    )


@pytest.mark.parametrize(
    "payload",
    (
        b'<p><a href="https://example.invalid/private">external</a></p>',
        b'<svg><a xlink:href="//example.invalid/item">external</a></svg>',
        b'<img src="data:image/png;base64,AAAA">',
        b'<p onclick="run()">event</p>',
        b'<p style="background:url(https://example.invalid/a)">style</p>',
        b'<meta http-equiv="refresh" content="0;url=/next"><p>text</p>',
        b"<script>run()</script>",
    ),
)
def test_html_import_rejects_active_content_and_external_references(payload: bytes) -> None:
    with pytest.raises(UnsafeDocumentError) as exc_info:
        parse_document(payload, filename="unsafe.html")

    assert exc_info.value.code == "unsafe_document"


def test_import_limits_and_format_errors_are_typed() -> None:
    with pytest.raises(DocumentTooLargeError) as size_error:
        parse_document(b"abc", filename="source.txt", limits=ParseLimits(max_input_bytes=2))
    assert size_error.value.code == "document_too_large"

    with pytest.raises(DocumentTooLargeError):
        parse_document(
            ("x" * 200_001).encode(),
            filename="single-paragraph.txt",
            limits=ParseLimits(max_text_characters=300_000),
        )

    with pytest.raises(UnsupportedDocumentFormatError) as format_error:
        parse_document(b"content", filename="source.rtf")
    assert format_error.value.code == "unsupported_document_format"

    with pytest.raises(DocumentParseError):
        parse_document(b"", filename="source.txt")


def test_docx_import_extracts_title_headings_lists_and_valid_media_relation() -> None:
    relationships = (
        f'<Relationships xmlns="{_REL_NS}"><Relationship Id="rImg" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        'Target="media/image.png"/></Relationships>'
    ).encode()
    parsed = parse_document(
        _docx_bytes(
            document_relationships=relationships,
            extra_members={"word/media/image.png": b"fixture-image"},
        ),
        filename="report.docx",
    )

    assert parsed.title == "治理能力建设"
    assert tuple(block.kind for block in parsed.blocks) == ("heading", "paragraph", "list")
    assert parsed.blocks[0].heading_level == 1
    assert parsed.metadata["archive_members"] == 5


def test_docx_import_rejects_macro_external_relationship_and_active_field() -> None:
    with pytest.raises(UnsafeDocumentError, match="宏"):
        parse_document(
            _docx_bytes(extra_members={"word/vbaProject.bin": b"macro"}),
            filename="macro.docx",
        )

    external_relationship = (
        f'<Relationships xmlns="{_REL_NS}"><Relationship Id="rExternal" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
        'Target="https://example.invalid/private" TargetMode="External"/></Relationships>'
    ).encode()
    with pytest.raises(UnsafeDocumentError, match="外部关系"):
        parse_document(
            _docx_bytes(document_relationships=external_relationship),
            filename="external.docx",
        )

    active_document = f"""<w:document xmlns:w="{_WORD_NS}"><w:body>
<w:p><w:fldSimple w:instr='HYPERLINK "https://example.invalid/private"'><w:r><w:t>link</w:t></w:r></w:fldSimple></w:p>
</w:body></w:document>""".encode()
    with pytest.raises(UnsafeDocumentError, match="活动字段"):
        parse_document(
            _docx_bytes(document_xml=active_document),
            filename="field.docx",
        )


def test_docx_import_rejects_traversal_links_entities_and_archive_budgets() -> None:
    with pytest.raises(UnsafeDocumentError, match="路径穿越"):
        parse_document(
            _docx_bytes(extra_members={"../private.txt": b"private"}),
            filename="traversal.docx",
        )

    link = zipfile.ZipInfo("word/media/link.png")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    linked_archive = _zip_bytes(
        (
            ("[Content_Types].xml", b"<Types/>"),
            ("_rels/.rels", b"<Relationships/>"),
            ("word/document.xml", b"<document/>"),
            (link, b"../../private"),
        )
    )
    with pytest.raises(UnsafeDocumentError, match="链接或特殊成员"):
        parse_document(linked_archive, filename="link.docx")

    entity_document = b"""<?xml version="1.0"?>
<!DOCTYPE document [<!ENTITY payload "expanded">]><document>&payload;</document>"""
    with pytest.raises(UnsafeDocumentError, match="实体"):
        parse_document(
            _docx_bytes(document_xml=entity_document),
            filename="entity.docx",
        )

    with pytest.raises(DocumentTooLargeError, match="成员数量"):
        parse_document(
            _docx_bytes(),
            filename="large.docx",
            limits=ParseLimits(max_archive_members=2),
        )


def test_pdf_import_dependency_is_lazy_and_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = importlib.import_module

    def missing_pypdf(name: str) -> Any:
        if name == "pypdf":
            raise ModuleNotFoundError(name)
        return original_import(name)

    monkeypatch.setattr(importlib, "import_module", missing_pypdf)
    with pytest.raises(ParserDependencyError) as exc_info:
        parse_document(b"%PDF-fixture", filename="source.pdf")

    assert exc_info.value.code == "parser_dependency_missing"
    assert exc_info.value.dependency == "pypdf"


def test_pdf_import_applies_page_text_and_active_content_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePage(dict[str, object]):
        def __init__(self, text: str, values: Mapping[str, object] | None = None) -> None:
            super().__init__(values or {})
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakeReader:
        def __init__(self, stream: io.BytesIO, *, strict: bool) -> None:
            del stream, strict
            self.is_encrypted = False
            self.pages = [FakePage("第一段\n\n第二段")]
            self.trailer: dict[str, object] = {"/Root": {}}
            self.metadata = SimpleNamespace(title="PDF 标题")

    fake_module = SimpleNamespace(PdfReader=FakeReader)
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)
    parsed = parse_document(b"%PDF-fixture", filename="source.pdf")

    assert parsed.title == "PDF 标题"
    assert parsed.metadata["pages"] == 1
    assert parsed.page_texts == ("第一段\n\n第二段",)
    assert tuple(block.text for block in parsed.blocks) == ("第一段", "第二段")

    class ActiveReader(FakeReader):
        def __init__(self, stream: io.BytesIO, *, strict: bool) -> None:
            super().__init__(stream, strict=strict)
            self.trailer = {"/Root": {"/OpenAction": {"/S": "/JavaScript"}}}

    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: SimpleNamespace(PdfReader=ActiveReader),
    )
    with pytest.raises(UnsafeDocumentError, match="自动执行"):
        parse_document(b"%PDF-active", filename="active.pdf")

    class ExternalLinkReader(FakeReader):
        def __init__(self, stream: io.BytesIO, *, strict: bool) -> None:
            super().__init__(stream, strict=strict)
            self.pages = [
                FakePage(
                    "linked text",
                    {"/Annots": [{"/A": {"/S": "/URI", "/URI": "https://invalid"}}]},
                )
            ]

    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: SimpleNamespace(PdfReader=ExternalLinkReader),
    )
    with pytest.raises(UnsafeDocumentError, match="外部链接"):
        parse_document(b"%PDF-link", filename="link.pdf")


def test_textual_exports_escape_markup_and_return_integrity_metadata() -> None:
    asset = _asset(
        ContentBlock(id="title", kind="title", order=0, text="项目复盘"),
        ContentBlock(id="heading", kind="heading", order=1, text="一、成效_复盘", heading_level=2),
        ContentBlock(
            id="paragraph",
            kind="paragraph",
            order=2,
            text='<script>alert("x")</script> 完成率 50% & 路径_a。',
        ),
        ContentBlock(id="list", kind="list", order=3, text="第一项\n第二项"),
    )

    markdown = export_asset(asset, format="markdown")
    assert markdown.filename == "项目复盘.md"
    assert "## 一、成效\\_复盘" in markdown.data.decode()
    assert "\\<script\\>" in markdown.data.decode()

    plain = export_asset(asset, format="txt", options=ExportOptions(include_title=False))
    assert plain.data.decode().startswith("一、成效_复盘")
    assert export_asset(asset, format="text").media_type == "text/plain; charset=utf-8"

    html_artifact = export_asset(asset, format="html")
    html_text = html_artifact.data.decode()
    assert "<script>" not in html_text
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html_text
    assert "Content-Security-Policy" in html_text

    latex = export_asset(asset, format="latex")
    latex_text = latex.data.decode()
    assert latex.media_type == "application/x-latex"
    assert r"50\% \& 路径\_a" in latex_text
    assert r"\begin{itemize}" in latex_text

    for artifact in (markdown, plain, html_artifact, latex):
        assert artifact.sha256 == hashlib.sha256(artifact.data).hexdigest()
        assert artifact.size == len(artifact.data)


def test_export_filename_is_sanitized_and_unknown_format_is_typed() -> None:
    asset = _asset(ContentBlock(id="body", order=0, text="正文"))
    artifact = export_asset(
        asset,
        format="md",
        options=ExportOptions(filename_stem="../../CON"),
    )

    assert artifact.filename == "yanzhang-CON.md"
    assert "/" not in artifact.filename
    with pytest.raises(UnsupportedExportFormatError) as exc_info:
        export_asset(asset, format="epub")  # type: ignore[arg-type]
    assert exc_info.value.code == "unsupported_export_format"


def test_citation_matrix_is_utf8_bom_csv_and_neutralizes_spreadsheet_formulas() -> None:
    block = ContentBlock(
        id="block-1",
        order=0,
        text='@SUM(1,2)\n"quoted"',
        evidence_ids=("evidence-1",),
    )
    asset = _asset(block)
    evidence = Evidence(
        id="evidence-1",
        knowledge_item_id="source-1",
        excerpt='=HYPERLINK("https://example.invalid")',
        locator="+A1",
        source_url="-external",
        source_hash="a" * 64,
    )

    artifact = export_citation_matrix(asset, evidence=(evidence,))
    rows = list(csv.reader(io.StringIO(artifact.data.decode("utf-8-sig"))))

    assert artifact.filename == "项目复盘-citations.csv"
    assert artifact.data.startswith(b"\xef\xbb\xbf")
    assert rows[0][0:4] == ["block_id", "block_order", "block_kind", "block_text"]
    assert rows[1][3].startswith("'@SUM")
    assert rows[1][6] == "'+A1"
    assert rows[1][7] == "'-external"
    assert rows[1][8] == "a" * 64
    assert rows[1][9].startswith("'=HYPERLINK")


def test_export_character_and_streaming_byte_limits_are_typed() -> None:
    asset = _asset(ContentBlock(id="body", order=0, text="正文内容"))

    with pytest.raises(ExportTooLargeError, match="字符") as character_error:
        export_asset(asset, format="txt", options=ExportOptions(max_characters=4))
    assert character_error.value.code == "export_too_large"

    with pytest.raises(ExportTooLargeError, match="字节"):
        export_citation_matrix(
            asset,
            options=ExportOptions(max_output_bytes=10),
        )


def test_pdf_export_dependency_is_lazy_and_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = importlib.import_module

    def missing_reportlab(name: str) -> Any:
        if name.startswith("reportlab"):
            raise ModuleNotFoundError(name)
        return original_import(name)

    monkeypatch.setattr(importlib, "import_module", missing_reportlab)
    asset = _asset(ContentBlock(id="body", order=0, text="正文"))
    with pytest.raises(ExportDependencyError) as exc_info:
        export_asset(asset, format="pdf")

    assert exc_info.value.code == "export_dependency_missing"
    assert exc_info.value.dependency == "reportlab"


@pytest.mark.skipif(
    importlib.util.find_spec("reportlab") is None,
    reason="reportlab optional dependency is absent",
)
def test_pdf_export_uses_cid_font_and_enforces_output_limit() -> None:
    asset = _asset(ContentBlock(id="body", order=0, text="中文正文"))
    artifact = export_asset(asset, format="pdf")

    assert artifact.filename == "项目复盘.pdf"
    assert artifact.media_type == "application/pdf"
    assert artifact.data.startswith(b"%PDF-")
    assert artifact.sha256 == hashlib.sha256(artifact.data).hexdigest()

    with pytest.raises(ExportTooLargeError):
        export_asset(asset, format="pdf", options=ExportOptions(max_output_bytes=16))


@pytest.mark.skipif(
    importlib.util.find_spec("reportlab") is None or importlib.util.find_spec("pypdf") is None,
    reason="PDF optional dependencies are absent",
)
def test_pdf_export_and_import_round_trip() -> None:
    asset = _asset(ContentBlock(id="body", order=0, text="中文正文。"), title="中文标题")
    exported = export_asset(asset, format="pdf")
    imported = parse_document(exported.data, filename="round-trip.pdf")

    assert imported.title == "中文标题"
    assert "中文正文。" in imported.text
    assert imported.metadata["source_sha256"] == exported.sha256
