"""Offline contract tests for the academic research scene pack."""

# ruff: noqa: RUF001 -- Chinese research fixtures use full-width punctuation.

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import AsyncIterator, Mapping

import httpx
import pytest

import yanzhang_academic.documents as academic_documents
from yanzhang_academic import (
    AcademicService,
    ArxivConnector,
    AsyncRateLimiter,
    Author,
    BibliographicRecord,
    BibliographyParseError,
    ClaimCitationLink,
    CrossrefConnector,
    DocumentExtractionError,
    DOCXTextExtractor,
    EvidenceSnippet,
    JournalProfile,
    MetadataConnectorError,
    MetadataRateLimitError,
    MetadataTimeoutError,
    OpenAlexConnector,
    PDFTextExtractor,
    PlainTextExtractor,
    ResearchBrief,
    ResearchClaim,
    ReviewComment,
    build_literature_matrix,
    draft_abstract,
    export_bibtex,
    export_csl_json,
    export_ris,
    extract_evidence,
    format_bibliography,
    format_in_text_citation,
    manuscript_word_count,
    parse_bibtex,
    parse_csl_json,
    parse_ris,
    prepare_rebuttal,
    review_research_integrity,
    suggest_titles,
    verify_claim_citations,
)
from yanzhang_core.models import ContentBlock
from yanzhang_core.parsers import ParsedDocument as CoreParsedDocument
from yanzhang_core.parsers import ParseLimits


class _ChunkedResponseStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.chunks_read = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.chunks_read += 1
            yield chunk


def _record(*, verified: bool = False) -> BibliographicRecord:
    return BibliographicRecord(
        type="article-journal",
        title="数字平台如何提升基层公共服务效能",
        authors=[Author(literal="王明", sequence="first"), Author(family="Smith", given="Jane")],
        issued_year=2025,
        container_title="公共管理研究",
        volume="12",
        issue="3",
        pages="21-38",
        doi="https://doi.org/10.1234/EXAMPLE.1",
        url="https://doi.org/10.1234/example.1",
        abstract="本研究分析数字平台与基层公共服务之间的关系。",
        keywords=["数字治理", "公共服务"],
        import_source="crossref" if verified else "manual",
        source_key="wang2025",
        metadata_verified=verified,
    )


def test_models_normalize_doi_and_create_stable_lineage() -> None:
    first = _record()
    second = _record()
    assert first.doi == "10.1234/example.1"
    assert first.id == second.id
    assert len(first.source_hash) == 64

    brief = ResearchBrief(title="数字治理", research_question="数字平台如何提升公共服务效能？")
    assert brief.id.startswith("brief_")
    assert brief.created_at.tzinfo is not None


def test_bibtex_round_trip_preserves_core_metadata() -> None:
    payload = r"""
    @article{wang2025,
      title = {{数字平台与基层治理}},
      author = {王明 and Smith, Jane},
      year = {2025},
      journal = {公共管理研究},
      volume = {12},
      number = {3},
      pages = {21--38},
      doi = {10.1234/EXAMPLE.1},
      keywords = {数字治理, 公共服务}
    }
    """
    records = parse_bibtex(payload)
    assert len(records) == 1
    record = records[0]
    assert record.title == "数字平台与基层治理"
    assert record.authors[0].literal == "王明"
    assert record.authors[1].family == "Smith"
    assert record.pages == "21-38"
    assert record.import_source == "bibtex"
    exported = export_bibtex(records)
    reparsed = parse_bibtex(exported)[0]
    assert reparsed.title == record.title
    assert reparsed.doi == record.doi


def test_ris_round_trip_preserves_repeated_fields() -> None:
    payload = """TY  - JOUR
ID  - wang2025
TI  - 数字平台与基层治理
AU  - 王明
AU  - Smith, Jane
PY  - 2025/01/01
JO  - 公共管理研究
VL  - 12
IS  - 3
SP  - 21
EP  - 38
DO  - 10.1234/example.1
KW  - 数字治理
KW  - 公共服务
ER  -
"""
    record = parse_ris(payload)[0]
    assert len(record.authors) == 2
    assert record.issued_year == 2025
    assert record.pages == "21-38"
    assert record.keywords == ["数字治理", "公共服务"]
    reparsed = parse_ris(export_ris([record]))[0]
    assert reparsed.title == record.title
    assert reparsed.doi == record.doi


def test_csl_json_round_trip_handles_structured_authors_and_date() -> None:
    payload = json.dumps(
        [
            {
                "id": "wang2025",
                "type": "article-journal",
                "title": "数字平台与基层治理",
                "author": [{"family": "Wang", "given": "Ming"}],
                "issued": {"date-parts": [[2025, 3, 1]]},
                "container-title": "Public Administration Review",
                "DOI": "10.1234/EXAMPLE.1",
                "keyword": "digital governance; public service",
            }
        ]
    )
    record = parse_csl_json(payload)[0]
    assert (record.issued_year, record.issued_month, record.issued_day) == (2025, 3, 1)
    assert record.authors[0].family == "Wang"
    exported = export_csl_json([record])
    reparsed = parse_csl_json(exported)[0]
    assert reparsed.title == record.title
    assert reparsed.doi == "10.1234/example.1"


@pytest.mark.parametrize(
    "parser,payload",
    [
        (parse_bibtex, "plain text"),
        (parse_ris, "TY  - JOUR\nTI  - Missing end"),
        (parse_csl_json, "[1, 2, 3]"),
    ],
)
def test_bibliography_parsers_reject_malformed_payloads(parser: object, payload: str) -> None:
    assert callable(parser)
    with pytest.raises(BibliographyParseError):
        parser(payload)  # type: ignore[operator]


@pytest.mark.asyncio
async def test_crossref_connector_maps_verified_metadata_offline() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.crossref.org"
        assert request.url.params["rows"] == "2"
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [
                        {
                            "type": "journal-article",
                            "title": ["Platform Governance"],
                            "author": [{"family": "Wang", "given": "Ming"}],
                            "issued": {"date-parts": [[2025, 3, 1]]},
                            "container-title": ["Policy Studies"],
                            "DOI": "10.1234/ABC.2",
                            "URL": "https://doi.org/10.1234/abc.2",
                        }
                    ]
                }
            },
        )

    connector = CrossrefConnector(transport=httpx.MockTransport(handler), min_interval_seconds=0)
    records = await connector.search("platform governance", limit=2)
    assert records[0].metadata_verified is True
    assert records[0].import_source == "crossref"
    assert records[0].doi == "10.1234/abc.2"


@pytest.mark.asyncio
async def test_crossref_lookup_percent_encodes_doi_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/works/10.1234/abc.2"
        return httpx.Response(
            200,
            json={"message": {"title": ["One work"], "DOI": "10.1234/abc.2"}},
        )

    connector = CrossrefConnector(transport=httpx.MockTransport(handler), min_interval_seconds=0)
    record = await connector.lookup("https://doi.org/10.1234/ABC.2")
    assert record is not None
    assert record.title == "One work"


@pytest.mark.asyncio
async def test_openalex_connector_reconstructs_abstract_offline() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["per-page"] == "1"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W123",
                        "type": "article",
                        "title": "Evidence-led writing",
                        "publication_year": 2024,
                        "doi": "https://doi.org/10.1000/openalex",
                        "authorships": [{"author": {"display_name": "Ada Li"}}],
                        "primary_location": {
                            "landing_page_url": "https://example.test/paper",
                            "source": {"display_name": "Research Journal"},
                        },
                        "biblio": {"volume": "4", "issue": "2", "first_page": "1"},
                        "abstract_inverted_index": {"Evidence": [0], "matters": [1]},
                        "keywords": [{"display_name": "Evidence"}],
                    }
                ]
            },
        )

    connector = OpenAlexConnector(transport=httpx.MockTransport(handler), min_interval_seconds=0)
    record = (await connector.search("evidence", limit=1))[0]
    assert record.abstract == "Evidence matters"
    assert record.source_key == "W123"
    assert record.metadata_verified is True


@pytest.mark.asyncio
async def test_arxiv_connector_parses_atom_offline() -> None:
    atom = b"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>https://arxiv.org/abs/2501.01234v2</id>
        <published>2025-01-03T00:00:00Z</published>
        <title> Reliable Citation Workflows </title>
        <summary> Evidence must remain traceable. </summary>
        <author><name>Ada Li</name></author>
        <category term="cs.DL" />
      </entry>
    </feed>"""

    connector = ArxivConnector(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=atom)),
        min_interval_seconds=0,
    )
    record = await connector.lookup("arXiv:2501.01234v2")
    assert record is not None
    assert record.type == "preprint"
    assert record.title == "Reliable Citation Workflows"
    assert record.keywords == ["cs.DL"]


@pytest.mark.asyncio
async def test_metadata_connector_timeout_and_rate_limit_are_explicit() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("fixture timeout", request=request)

    timeout_connector = CrossrefConnector(
        transport=httpx.MockTransport(timeout_handler), min_interval_seconds=0, max_attempts=1
    )
    with pytest.raises(MetadataTimeoutError):
        await timeout_connector.search("test")

    rate_connector = CrossrefConnector(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429, headers={"Retry-After": "3"})
        ),
        min_interval_seconds=0,
        max_attempts=1,
    )
    with pytest.raises(MetadataRateLimitError) as error:
        await rate_connector.search("test")
    assert error.value.retry_after_seconds == 3


@pytest.mark.asyncio
async def test_metadata_connector_retries_rate_limits_and_transient_statuses_with_bounds() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        if attempts == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"message": {"items": []}})

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)

    connector = CrossrefConnector(
        transport=httpx.MockTransport(handler),
        min_interval_seconds=0,
        max_attempts=3,
        retry_backoff_seconds=0.25,
        max_retry_delay_seconds=1,
        sleeper=sleeper,
    )

    assert await connector.search("bounded retry") == []
    assert attempts == 3
    assert sleeps == [1, 0.5]


@pytest.mark.asyncio
async def test_metadata_connector_stops_after_configured_attempt_limit() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)

    connector = CrossrefConnector(
        transport=httpx.MockTransport(handler),
        min_interval_seconds=0,
        max_attempts=2,
        retry_backoff_seconds=0.1,
        sleeper=sleeper,
    )

    with pytest.raises(MetadataConnectorError, match="状态码 503"):
        await connector.search("bounded retry")
    assert attempts == 2
    assert sleeps == [0.1]


@pytest.mark.asyncio
async def test_metadata_connector_retries_all_5xx_but_not_other_4xx() -> None:
    attempts = 0

    def transient_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(501)
        return httpx.Response(200, json={"message": {"items": []}})

    connector = CrossrefConnector(
        transport=httpx.MockTransport(transient_handler),
        min_interval_seconds=0,
        retry_backoff_seconds=0,
    )
    assert await connector.search("all server failures") == []
    assert attempts == 2

    client_attempts = 0
    sleeps: list[float] = []

    def client_handler(request: httpx.Request) -> httpx.Response:
        nonlocal client_attempts
        client_attempts += 1
        return httpx.Response(408)

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)

    connector = CrossrefConnector(
        transport=httpx.MockTransport(client_handler),
        min_interval_seconds=0,
        max_attempts=3,
        sleeper=sleeper,
    )
    with pytest.raises(MetadataConnectorError, match="状态码 408"):
        await connector.search("non retryable client error")
    assert client_attempts == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_metadata_connector_rejects_oversized_declared_body_before_reading() -> None:
    stream = _ChunkedResponseStream([b"{}"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": str(2 * 1024 * 1024 + 1)},
            stream=stream,
        )

    connector = CrossrefConnector(
        transport=httpx.MockTransport(handler),
        min_interval_seconds=0,
    )
    with pytest.raises(MetadataConnectorError, match="超过大小上限"):
        await connector.search("bounded response")
    assert stream.chunks_read == 0


@pytest.mark.asyncio
async def test_metadata_connector_enforces_streamed_body_limit_without_length_header() -> None:
    stream = _ChunkedResponseStream([b"x" * 700, b"y" * 700])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    connector = CrossrefConnector(
        transport=httpx.MockTransport(handler),
        min_interval_seconds=0,
        max_response_bytes=1_024,
    )
    with pytest.raises(MetadataConnectorError, match="超过大小上限"):
        await connector.search("bounded response")
    assert stream.chunks_read == 2

    with pytest.raises(ValueError, match="1 KB 到 2 MB"):
        CrossrefConnector(max_response_bytes=2 * 1024 * 1024 + 1)


@pytest.mark.asyncio
async def test_rate_limiter_waits_for_remaining_interval() -> None:
    current = [10.0]
    sleeps: list[float] = []

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)
        current[0] += delay

    limiter = AsyncRateLimiter(2.0, clock=lambda: current[0], sleeper=sleeper)
    await limiter.wait()
    current[0] += 0.5
    await limiter.wait()
    assert sleeps == [1.5]


def test_evidence_extraction_and_matrix_keep_source_lineage() -> None:
    record = _record()
    text = (
        "近年来，数字平台成为基层治理的重要基础设施。\n\n"
        "本研究采用问卷方法调查300名工作人员。\n\n"
        "结果表明，数字平台显著提升公共服务效率。\n\n"
        "研究局限在于样本仅来自一个地区。"
    )
    snippets = extract_evidence(record, text, query="数字平台 公共服务", max_snippets=10)
    assert snippets
    assert all(snippet.record_id == record.id for snippet in snippets)
    assert all(snippet.record_source_hash == record.source_hash for snippet in snippets)
    all_snippets = extract_evidence(record, text, max_snippets=10)
    matrix = build_literature_matrix([record], all_snippets, query="数字治理")
    row = matrix.rows[0]
    assert row.methods
    assert row.findings
    assert row.limitations
    assert row.record_id == record.id


def test_citation_verification_accepts_only_imported_source_bound_evidence() -> None:
    record = _record(verified=True)
    snippet = EvidenceSnippet(
        record_id=record.id,
        record_source_hash=record.source_hash,
        text="结果表明数字平台显著提升公共服务效率。",
        kind="finding",
        page_start=23,
        page_end=23,
    )
    claim = ResearchClaim(text="数字平台显著提升公共服务效率。", section="研究发现")
    service = AcademicService(connectors={})
    link = service.create_citation_link(claim, record, snippet)
    audit = verify_claim_citations([record], [snippet], [claim], [link])
    assert audit.coverage == 1.0
    assert audit.links[0].status == "verified"
    assert audit.links[0].verified_at is not None

    invented = link.model_copy(update={"record_id": "ref_not_imported"})
    rejected = verify_claim_citations([record], [snippet], [claim], [invented])
    assert rejected.coverage == 0.0
    assert rejected.links[0].status == "invalid"
    assert "未导入" in "".join(rejected.links[0].issues)


def test_low_support_and_source_hash_mismatch_are_reported() -> None:
    record = _record()
    snippet = EvidenceSnippet(
        record_id=record.id,
        record_source_hash="0" * 64,
        text="另一项研究讨论了完全不同的主题。",
    )
    claim = ResearchClaim(text="数字平台提升了服务效率。")
    link = ClaimCitationLink(claim_id=claim.id, record_id=record.id, evidence_id=snippet.id)
    audit = verify_claim_citations([record], [snippet], [claim], [link])
    assert audit.links[0].status == "invalid"
    assert any("哈希" in issue for issue in audit.links[0].issues)


def test_integrity_review_flags_missing_metadata_and_quote_location() -> None:
    record = BibliographicRecord(
        type="article-journal",
        title="本地导入研究",
        import_source="manual",
        source_key="local-1",
    )
    snippet = EvidenceSnippet(
        record_id=record.id,
        record_source_hash=record.source_hash,
        text="研究结果表明数字平台提升效率。",
    )
    claim = ResearchClaim(text="“数字平台提升效率”", section="研究发现")
    link = ClaimCitationLink(claim_id=claim.id, record_id=record.id, evidence_id=snippet.id)
    review = review_research_integrity(
        [record], [snippet], [claim], [link], minimum_support_score=0.05
    )
    messages = "\n".join(comment.message for comment in review.comments)
    assert "缺少作者、年份、刊名" in messages
    assert "题录状态为待交叉核验" in messages
    assert "缺少页码" in messages


def test_integrity_review_checks_manuscript_and_every_journal_constraint() -> None:
    abstract = "研" * 110
    manuscript = (
        "# 数字治理视角下跨部门协同机制及其公共服务效能影响研究\n\n"
        f"## 摘要\n{abstract}\n\n"
        "## 一、引言\n研究问题说明。\n\n"
        "## 结论\n" + "治" * 520
    )
    journal = JournalProfile(
        name="治理研究",
        required_sections=["摘要", "引言", "研究方法", "结论"],
        title_max_characters=12,
        abstract_max_characters=100,
        manuscript_max_words=500,
        custom_rules=["提交匿名稿", "附作者贡献声明"],
    )

    review = AcademicService(connectors={}).review_integrity(
        [],
        [],
        [],
        [],
        manuscript=manuscript,
        journal=journal,
    )

    messages = [comment.message for comment in review.comments]
    assert any("题名共" in message and "上限 12" in message for message in messages)
    assert any("摘要共 110 个字符" in message for message in messages)
    assert any("研究方法" in message and "缺少" in message for message in messages)
    assert not any("“引言”" in message and "缺少" in message for message in messages)
    assert not any("“结论”" in message and "缺少" in message for message in messages)
    assert any("超过《治理研究》上限 500 词" in message for message in messages)
    manual_items = [message for message in messages if "需人工逐项核对" in message]
    assert manual_items == [
        "期刊自定义要求需人工逐项核对：提交匿名稿",
        "期刊自定义要求需人工逐项核对：附作者贡献声明",
    ]
    manual_comments = [
        comment for comment in review.comments if "需人工逐项核对" in comment.message
    ]
    assert all(
        comment.severity == "info" and comment.resolved is False for comment in manual_comments
    )
    assert not any("已经满足" in message for message in manual_items)
    assert review.passed is False
    assert manuscript_word_count("中文 mixed-method 2026") == 4


def test_integrity_review_uses_manuscript_claim_text_without_changing_legacy_default() -> None:
    claim = ResearchClaim(
        text="跨部门协同提升了信息共享质量。",
        section="研究发现",
        requires_citation=False,
    )

    legacy = review_research_integrity([], [], [claim], [])
    with_manuscript = review_research_integrity(
        [],
        [],
        [claim],
        [],
        manuscript="本文讨论其他研究问题。",
    )

    assert legacy.comments == []
    assert any(comment.category == "consistency" for comment in with_manuscript.comments)


def test_baseline_citation_styles_use_only_record_metadata() -> None:
    record = _record()
    for style in ("gb-t-7714", "apa", "mla", "chicago"):
        rendered = format_bibliography([record], style)[0]
        assert record.title in rendered
        assert "2025" in rendered
        assert "10.1234/example.1" in rendered
    assert format_in_text_citation(record, "gb-t-7714", index=3) == "[3]"
    assert "2025" in format_in_text_citation(record, "apa")


def test_title_outline_abstract_and_rebuttal_workflow_is_evidence_bounded() -> None:
    record = _record(verified=True)
    brief = ResearchBrief(
        title="数字平台与基层治理",
        discipline="公共管理",
        research_question="数字平台如何提升基层公共服务效能？",
        purpose="解释数字平台影响服务效能的作用机制",
        keywords=["数字平台", "公共服务"],
        method_notes="问卷与访谈相结合的方法",
    )
    snippet = EvidenceSnippet(
        record_id=record.id,
        record_source_hash=record.source_hash,
        text="结果表明数字平台显著提升公共服务效率。",
        kind="finding",
        page_start=23,
    )
    claim = ResearchClaim(text="数字平台显著提升公共服务效率。", claim_type="result")
    link = verify_claim_citations(
        [record],
        [snippet],
        [claim],
        [ClaimCitationLink(claim_id=claim.id, record_id=record.id, evidence_id=snippet.id)],
    ).links[0]

    titles = suggest_titles(brief, [record], count=4)
    assert len(titles) == 4
    assert all(item.record_ids == [record.id] for item in titles)
    outline = AcademicService(connectors={}).create_outline(brief, [record], [snippet])
    assert outline.record_ids == [record.id]
    assert any(section.evidence_ids for section in outline.sections)

    profile = JournalProfile(name="示例期刊", abstract_max_characters=500)
    abstract = draft_abstract(brief, [claim], [link], [record], journal=profile)
    assert claim.id in abstract.claim_ids
    assert abstract.record_ids == [record.id]
    assert "10.1234/example.1" not in abstract.text
    assert "(王明 & Smith, 2025)" in abstract.text

    unchecked = link.model_copy(update={"verified_at": None})
    guarded = draft_abstract(brief, [claim], [unchecked], [record])
    assert guarded.record_ids == []
    assert "待补充" in guarded.text

    comment = ReviewComment(
        category="citation",
        message="请补充该论断的来源。",
        location="第3页",
    )
    draft_reply = prepare_rebuttal([comment])[0]
    assert "请补充具体修改内容" in draft_reply.manuscript_change
    completed_reply = prepare_rebuttal([comment], {comment.id: "第3页补充两条引用"})[0]
    assert completed_reply.status == "confirmed"


def test_docx_and_plain_text_extractors_are_bounded_and_offline() -> None:
    document_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>第一段研究资料</w:t></w:r></w:p>
        <w:p><w:r><w:t>第二段证据</w:t></w:r></w:p>
      </w:body>
    </w:document>""".encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
              <Default Extension="xml" ContentType="application/xml"/>
              <Override PartName="/word/document.xml"
                ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
            </Types>""",
        )
        archive.writestr("word/document.xml", document_xml)
    parsed = DOCXTextExtractor().extract(buffer.getvalue(), file_name="../../paper.docx")
    assert parsed.text == "第一段研究资料\n第二段证据"
    assert parsed.file_name == "paper.docx"

    text = PlainTextExtractor().extract("研究笔记".encode(), file_name="notes.md")
    assert text.media_type == "text/markdown"
    with pytest.raises(DocumentExtractionError):
        PlainTextExtractor().extract(b"", file_name="empty.txt")
    with pytest.raises(DocumentExtractionError, match="超过字节上限"):
        PlainTextExtractor(max_bytes=1_024).extract(b"x" * 1_025, file_name="large.txt")

    unsafe = io.BytesIO()
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/vbaProject.bin", b"macro")
    with pytest.raises(DocumentExtractionError, match="宏或嵌入活动内容"):
        DOCXTextExtractor().extract(unsafe.getvalue(), file_name="unsafe.docx")

    too_many_members = io.BytesIO()
    with zipfile.ZipFile(too_many_members, "w") as archive:
        for index in range(513):
            archive.writestr(f"fixture/{index}.xml", "<fixture/>")
    with pytest.raises(DocumentExtractionError, match="成员数量超过上限"):
        DOCXTextExtractor(max_archive_entries=10_000).extract(
            too_many_members.getvalue(),
            file_name="oversized.docx",
        )


def test_academic_pdf_adapter_delegates_and_preserves_page_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[bytes, str, str | None, ParseLimits | None]] = []

    def fixture_parser(
        data: bytes,
        *,
        filename: str,
        media_type: str | None = None,
        limits: ParseLimits | None = None,
    ) -> CoreParsedDocument:
        calls.append((data, filename, media_type, limits))
        return CoreParsedDocument(
            title="研究资料",
            content_type="application/pdf",
            blocks=(ContentBlock(id="block-1", order=0, text="第一页\n\n第二段"),),
            metadata={"source_name": "paper.pdf", "pages": 2},
            page_texts=("第一页\n\n第二段", "第二页"),
        )

    monkeypatch.setattr(academic_documents, "parse_document", fixture_parser)
    parsed = PDFTextExtractor().extract(b"%PDF-fixture", file_name="../paper.pdf")

    assert len(calls) == 1
    assert calls[0][1:3] == ("../paper.pdf", "application/pdf")
    assert isinstance(calls[0][3], ParseLimits)
    assert calls[0][3].max_input_bytes == 12 * 1024 * 1024
    assert parsed.file_name == "paper.pdf"
    assert [page.number for page in parsed.pages] == [1, 2]
    assert [page.text for page in parsed.pages] == ["第一页\n第二段", "第二页"]
    assert parsed.text == "第一页\n第二段\n\f\n第二页"


class _FixtureConnector:
    name = "fixture"

    def __init__(self, record: BibliographicRecord) -> None:
        self.record = record

    async def search(self, query: str, *, limit: int = 10) -> list[BibliographicRecord]:
        del query
        return [self.record][:limit]

    async def lookup(self, identifier: str) -> BibliographicRecord | None:
        return self.record if identifier == self.record.source_key else None


@pytest.mark.asyncio
async def test_academic_service_is_a_small_web_and_mcp_facade() -> None:
    record = _record(verified=True)
    service = AcademicService(connectors={"fixture": _FixtureConnector(record)})
    assert service.list_connectors() == ("fixture",)
    assert (await service.search_metadata("fixture", "query"))[0].id == record.id
    assert await service.lookup_metadata("fixture", record.source_key) == record
    exported = service.export_records([record], "csl-json")
    imported = service.import_records(exported, "csl-json")
    assert imported[0].title == record.title
    with pytest.raises(ValueError, match="未知元数据连接器"):
        await service.search_metadata("missing", "query")


def test_csl_sequence_input_accepts_mapping_without_json_transport() -> None:
    data: list[Mapping[str, object]] = [
        {"id": "fixture", "type": "report", "title": "Research report"}
    ]
    record = parse_csl_json(data)[0]
    assert record.type == "report"
    assert record.import_source == "csl-json"
    direct = parse_csl_json({"id": "single", "title": "Single CSL object"})[0]
    assert direct.source_key == "single"
