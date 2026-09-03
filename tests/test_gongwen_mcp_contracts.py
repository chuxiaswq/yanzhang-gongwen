"""High-value offline contracts for the public Gongwen MCP tool surface."""

# Chinese fixture text is intentional.
# ruff: noqa: RUF001

from __future__ import annotations

import inspect
import json
import zipfile
from collections.abc import Iterator, Mapping
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest
from pydantic import BaseModel, ValidationError

from gongwen_mcp.artifacts import DOCX_MIME, ZIP_MIME, ArtifactStore
from gongwen_mcp.schemas import (
    CollectArticlesRequest,
    ExportDocumentRef,
    ExportDocumentsZipRequest,
    ExportDocxRequest,
    GenerateDocumentRequest,
    GenerateTitlesRequest,
    ImportArticleTextRequest,
    ImportArticleURLRequest,
    ListDocumentsRequest,
    ReadArticleRequest,
    ReadDocumentRequest,
    SaveDocumentRequest,
    SearchArticlesRequest,
)
from gongwen_mcp.schemas import (
    TestModelRequest as ModelProbeRequest,
)
from gongwen_mcp.tools import (
    GongwenMCPContext,
    GongwenToolError,
    GongwenTools,
    build_context,
)
from gongwen_web.articles import (
    ArticleFetchError,
    ArticleLibrary,
    FetchedPage,
    SQLiteArticleRepository,
)
from gongwen_web.collection import ArticleCollectionService
from gongwen_web.models import ProviderSettings
from gongwen_web.runtime import RuntimeSettings
from gongwen_web.service import GongwenService
from gongwen_web.storage import GongwenStorage
from gongwen_web.title_engine import (
    TitleGenerationRequest,
    TitleGenerationResult,
    generate_titles_demo,
)
from yanzhang.providers.content.article_discovery import (
    ArticleDiscoveryBatch,
    ArticleDiscoveryQuery,
    DiscoveredArticle,
    EmptyArticleDiscoveryProvider,
)

PUBLIC_TOOL_NAMES = {
    "gongwen_get_status",
    "gongwen_get_methods",
    "gongwen_generate_titles",
    "gongwen_generate_document",
    "gongwen_rewrite_text",
    "gongwen_review_document",
    "gongwen_audit_document",
    "gongwen_save_document",
    "gongwen_list_documents",
    "gongwen_read_document",
    "gongwen_list_versions",
    "gongwen_read_version",
    "gongwen_delete_document",
    "gongwen_list_article_sources",
    "gongwen_search_articles",
    "gongwen_read_article",
    "gongwen_get_style_references",
    "gongwen_import_article_text",
    "gongwen_import_article_url",
    "gongwen_collect_articles",
    "gongwen_delete_article",
    "gongwen_export_docx",
    "gongwen_export_documents_zip",
    "gongwen_mail_merge_docx",
    "gongwen_test_model",
    "gongwen_get_model_usage",
}


@pytest.fixture
def context(tmp_path: Path) -> Iterator[GongwenMCPContext]:
    instance = build_context(
        settings=RuntimeSettings(environment="test"),
        data_dir=tmp_path,
    )
    try:
        yield instance
    finally:
        instance.close()


def test_public_tool_contract_is_exactly_the_26_async_methods() -> None:
    discovered = {
        name
        for name in dir(GongwenTools)
        if name.startswith("gongwen_") and callable(getattr(GongwenTools, name))
    }

    assert discovered == PUBLIC_TOOL_NAMES
    assert len(discovered) == 26
    assert all(inspect.iscoroutinefunction(getattr(GongwenTools, name)) for name in discovered)


def test_engine_schema_accepts_only_auto_server_and_local() -> None:
    for engine in ("auto", "server", "local"):
        assert GenerateTitlesRequest(topic="政绩观建设", engine=engine).engine == engine
        assert ModelProbeRequest(engine=engine).engine == engine

    with pytest.raises(ValidationError):
        GenerateTitlesRequest.model_validate({"topic": "政绩观建设", "engine": "remote"})
    with pytest.raises(ValidationError):
        GenerateTitlesRequest.model_validate(
            {"topic": "政绩观建设", "engine": "local", "api_key": "client-secret"}
        )


@pytest.mark.asyncio
async def test_engine_selection_uses_injected_local_and_server_model_paths(tmp_path: Path) -> None:
    provider = ProviderSettings(
        name="openai",
        model="fixture-model",
        api_key="server-owned-fixture-key",
    )
    settings = RuntimeSettings(environment="test", server_provider=provider)
    instance = build_context(settings=settings, data_dir=tmp_path / "configured")
    calls: list[tuple[str, bool, str | None]] = []

    def local_titles(request: TitleGenerationRequest) -> TitleGenerationResult:
        calls.append(("local", request.live, None))
        return generate_titles_demo(request)

    async def server_titles(request: TitleGenerationRequest) -> TitleGenerationResult:
        calls.append(
            (
                "server",
                request.live,
                request.provider.model if request.provider is not None else None,
            )
        )
        return generate_titles_demo(
            request.model_copy(update={"live": False, "provider": None}, deep=True)
        )

    instance.service = GongwenService(
        instance.storage,
        settings,
        generate_titles_demo_fn=local_titles,
        generate_titles_live_fn=server_titles,
    )
    tools = GongwenTools(instance)
    try:
        results = [
            await tools.gongwen_generate_titles(
                GenerateTitlesRequest(topic="政绩观建设", count=1, engine=engine)
            )
            for engine in ("local", "auto", "server")
        ]
    finally:
        instance.close()

    assert calls == [
        ("local", False, None),
        ("server", True, "fixture-model"),
        ("server", True, "fixture-model"),
    ]
    serialized = json.dumps(results, ensure_ascii=False, allow_nan=False)
    assert "server-owned-fixture-key" not in serialized

    unconfigured = build_context(
        settings=RuntimeSettings(environment="test"),
        data_dir=tmp_path / "unconfigured",
    )
    try:
        unconfigured_tools = GongwenTools(unconfigured)
        auto_result = await unconfigured_tools.gongwen_generate_titles(
            GenerateTitlesRequest(topic="政绩观建设", count=1, engine="auto")
        )
        assert cast(Mapping[str, object], auto_result["meta"])["mode"] == "demo"
        with pytest.raises(GongwenToolError) as raised:
            await unconfigured_tools.gongwen_generate_titles(
                GenerateTitlesRequest(topic="政绩观建设", count=1, engine="server")
            )
        assert raised.value.code == "model_not_configured"
    finally:
        unconfigured.close()


@pytest.mark.asyncio
async def test_generation_auto_saves_and_preserves_history_on_version_conflict(
    context: GongwenMCPContext,
) -> None:
    tools = GongwenTools(context)
    request = GenerateDocumentRequest(
        document_id="mcp-generated-draft",
        expected_version=0,
        document_type="讲话稿",
        topic="树牢和践行正确政绩观",
        materials="本次交流围绕为民造福、真抓实干和久久为功展开。",
        selected_title="以为民之心答好政绩之问",
        engine="local",
    )

    generated = await tools.gongwen_generate_document(request)
    stored = context.storage.get_document("mcp-generated-draft")

    assert generated["id"] == "mcp-generated-draft"
    assert generated["version"] == 1
    assert stored is not None
    assert stored["title"] == generated["title"]
    assert generated["preview"] == stored["content"][:4000]
    assert [item["version"] for item in context.storage.list_versions("mcp-generated-draft")] == [1]

    with pytest.raises(GongwenToolError) as raised:
        await tools.gongwen_generate_document(
            request.model_copy(update={"selected_title": "这次写入应触发版本冲突"})
        )
    assert raised.value.code == "version_conflict"
    assert context.storage.get_document("mcp-generated-draft") == stored
    assert [item["version"] for item in context.storage.list_versions("mcp-generated-draft")] == [1]

    revised = await tools.gongwen_generate_document(
        request.model_copy(
            update={"expected_version": 1, "selected_title": "以实干实绩回应群众期盼"}
        )
    )
    assert revised["version"] == 2
    assert [item["version"] for item in context.storage.list_versions("mcp-generated-draft")] == [
        2,
        1,
    ]


@pytest.mark.asyncio
async def test_document_and_article_reads_are_bounded_character_chunks(
    context: GongwenMCPContext,
) -> None:
    tools = GongwenTools(context)
    document_text = "甲" * 700 + "乙" * 700
    document = await tools.gongwen_save_document(
        SaveDocumentRequest(title="分块文稿", content=document_text)
    )
    document_chunk = await tools.gongwen_read_document(
        ReadDocumentRequest(
            document_id=cast(str, document["id"]),
            chunk_offset=650,
            chunk_size=500,
        )
    )

    assert "content" not in cast(Mapping[str, object], document_chunk["document"])
    assert document_chunk["content"] == {
        "text": document_text[650:1150],
        "offset": 650,
        "size": 500,
        "total_characters": 1400,
        "has_more": True,
        "next_offset": 1150,
    }

    article_text = "丙" * 640 + "丁" * 760
    article = await tools.gongwen_import_article_text(
        ImportArticleTextRequest(title="分块参考文章", content=article_text)
    )
    article_chunk = await tools.gongwen_read_article(
        ReadArticleRequest(
            article_id=cast(str, article["id"]),
            chunk_offset=900,
            chunk_size=500,
        )
    )

    assert "content" not in cast(Mapping[str, object], article_chunk["article"])
    assert article_chunk["content"] == {
        "text": article_text[900:1400],
        "offset": 900,
        "size": 500,
        "total_characters": 1400,
        "has_more": False,
        "next_offset": None,
    }
    json.dumps(document_chunk, ensure_ascii=False, allow_nan=False)
    json.dumps(article_chunk, ensure_ascii=False, allow_nan=False)


@pytest.mark.asyncio
async def test_document_and_article_lists_have_stable_pagination(
    context: GongwenMCPContext,
) -> None:
    tools = GongwenTools(context)
    for index in range(3):
        await tools.gongwen_save_document(
            SaveDocumentRequest(title=f"分页文稿{index}", content=f"第{index}篇正文。")
        )
        await tools.gongwen_import_article_text(
            ImportArticleTextRequest(
                title=f"分页文章{index}",
                content=f"基层治理分页资料，第{index}篇。",
            )
        )

    first_documents = await tools.gongwen_list_documents(ListDocumentsRequest(limit=2, offset=0))
    last_documents = await tools.gongwen_list_documents(ListDocumentsRequest(limit=2, offset=2))
    assert len(cast(list[object], first_documents["items"])) == 2
    assert first_documents["has_more"] is True
    assert len(cast(list[object], last_documents["items"])) == 1
    assert last_documents["has_more"] is False

    first_articles = await tools.gongwen_search_articles(
        SearchArticlesRequest(query="基层治理分页资料", limit=2, offset=0)
    )
    last_articles = await tools.gongwen_search_articles(
        SearchArticlesRequest(query="基层治理分页资料", limit=2, offset=2)
    )
    assert first_articles["total"] == 3
    assert len(cast(list[object], first_articles["items"])) == 2
    assert first_articles["has_more"] is True
    assert len(cast(list[object], last_articles["items"])) == 1
    assert last_articles["has_more"] is False


@pytest.mark.asyncio
async def test_docx_and_batch_zip_exports_return_path_free_artifacts(
    context: GongwenMCPContext,
) -> None:
    tools = GongwenTools(context)
    first = await tools.gongwen_save_document(
        SaveDocumentRequest(title="第一篇公文", content="一、提高站位\n扎实推进重点工作。")
    )
    second = await tools.gongwen_save_document(
        SaveDocumentRequest(title="第二篇公文", content="一、压实责任\n推动各项任务落地。")
    )

    docx = await tools.gongwen_export_docx(
        ExportDocxRequest(document_id=cast(str, first["id"]), filename="单篇导出.docx")
    )
    assert docx["mime"] == DOCX_MIME
    assert cast(str, docx["resource_uri"]).startswith("gongwen://exports/")
    assert not any("path" in key.casefold() for key in docx)
    docx_bytes = context.artifact_store.read_bytes(cast(str, docx["artifact_id"]))
    assert docx_bytes.startswith(b"PK")
    assert len(docx_bytes) == docx["size"]

    archive = await tools.gongwen_export_documents_zip(
        ExportDocumentsZipRequest(
            documents=[
                ExportDocumentRef(document_id=cast(str, first["id"])),
                ExportDocumentRef(document_id=cast(str, second["id"])),
            ],
            filename="批量导出.zip",
        )
    )
    assert archive["mime"] == ZIP_MIME
    assert not any("path" in key.casefold() for key in archive)
    archive_bytes = context.artifact_store.read_bytes(cast(str, archive["artifact_id"]))
    with zipfile.ZipFile(BytesIO(archive_bytes)) as package:
        names = package.namelist()
        assert sorted(name for name in names if name.endswith(".docx")) == sorted(
            cast(list[str], archive["files"])
        )
        assert "生成清单.txt" in names
    json.dumps({"docx": docx, "archive": archive}, ensure_ascii=False, allow_nan=False)


class _InjectedFetcher:
    def __init__(self, pages: Mapping[str, FetchedPage]) -> None:
        self.pages = dict(pages)
        self.calls: list[str] = []

    async def fetch(self, url: str) -> FetchedPage:
        self.calls.append(url)
        return self.pages[url]


class _InjectedDiscovery:
    def __init__(self, article: DiscoveredArticle) -> None:
        self.article = article
        self.calls: list[ArticleDiscoveryQuery] = []

    async def discover(self, query: ArticleDiscoveryQuery) -> ArticleDiscoveryBatch:
        self.calls.append(query)
        return ArticleDiscoveryBatch(articles=(self.article,))


def _html(title: str, paragraph: str) -> bytes:
    return (
        "<!doctype html><html><head>"
        f'<meta property="og:title" content="{title}">'
        "</head><body><article>"
        f"<p>{paragraph}</p><p>坚持问题导向、目标导向、结果导向相统一。</p>"
        "</article></body></html>"
    ).encode()


def _injected_context(
    tmp_path: Path,
    *,
    fetcher: object,
    discovery: object,
) -> GongwenMCPContext:
    storage = GongwenStorage(tmp_path / "gongwen.sqlite3")
    repository = SQLiteArticleRepository(storage.path)
    library = ArticleLibrary(repository, fetcher=fetcher)  # type: ignore[arg-type]
    collection = ArticleCollectionService(library, discovery)  # type: ignore[arg-type]
    settings = RuntimeSettings(environment="test")
    return GongwenMCPContext(
        service=GongwenService(storage, settings),
        storage=storage,
        article_library=library,
        article_collection=collection,
        artifact_store=ArtifactStore(tmp_path),
        settings=settings,
        _article_repository=repository,
    )


@pytest.mark.asyncio
async def test_url_import_and_collection_use_only_injected_network_adapters(tmp_path: Path) -> None:
    direct_url = "https://www.people.com.cn/n1/2026/0904/direct.html"
    collected_url = "https://www.people.com.cn/n1/2026/0904/collected.html"
    fetcher = _InjectedFetcher(
        {
            direct_url: FetchedPage(
                url=direct_url,
                body=_html("以实干实绩践行为民初心", "正确政绩观体现在造福群众的实际成效中。"),
            ),
            collected_url: FetchedPage(
                url=collected_url,
                body=_html("以正确政绩观引领基层治理", "树牢正确政绩观，要把群众满意作为标尺。"),
            ),
        }
    )
    discovery = _InjectedDiscovery(
        DiscoveredArticle(
            url=collected_url,
            source_id="people",
            title="以正确政绩观引领基层治理",
            published_date=date(2026, 9, 4),
            channel="fixture-search",
        )
    )
    context = _injected_context(
        tmp_path,
        fetcher=fetcher,
        discovery=discovery,
    )
    tools = GongwenTools(context)
    try:
        imported = await tools.gongwen_import_article_url(
            ImportArticleURLRequest(url=direct_url, source_id="people")
        )
        collected = await tools.gongwen_collect_articles(
            CollectArticlesRequest(
                keywords=["政绩观"],
                source_ids=["people"],
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 5),
                limit=3,
            )
        )
    finally:
        context.close()

    assert imported["import_method"] == "url"
    assert collected["imported_count"] == 1
    assert fetcher.calls == [direct_url, collected_url]
    assert len(discovery.calls) == 1
    assert discovery.calls[0].keywords == ("政绩观",)
    assert discovery.calls[0].source_ids == ("people",)


class _ExplodingFetcher:
    async def fetch(self, url: str) -> FetchedPage:
        del url
        raise ArticleFetchError(
            "Authorization: Bearer fixture-bearer-redaction-token; "
            "api_key=fixture-model-key-redaction-123456 at https://internal.example/private"
        )


class _UnsafeResult(BaseModel):
    metric: float


class _UnsafeTitleService:
    async def generate_titles(self, payload: Mapping[str, object]) -> BaseModel:
        del payload
        return _UnsafeResult(metric=float("nan"))


@pytest.mark.asyncio
async def test_public_errors_are_sanitized_and_non_json_results_are_rejected(
    tmp_path: Path,
) -> None:
    error_context = _injected_context(
        tmp_path / "error",
        fetcher=_ExplodingFetcher(),
        discovery=EmptyArticleDiscoveryProvider(),
    )
    try:
        with pytest.raises(GongwenToolError) as raised:
            await GongwenTools(error_context).gongwen_import_article_url(
                ImportArticleURLRequest(url="https://www.people.com.cn/error.html")
            )
        assert raised.value.code == "invalid_request"
        message = raised.value.message
        assert "fixture-bearer-redaction-token" not in message
        assert "fixture-model-key-redaction-123456" not in message
        assert "internal.example" not in message
        assert "[已隐藏]" in message
        assert "[地址]" in message
    finally:
        error_context.close()

    unsafe_context = build_context(
        settings=RuntimeSettings(environment="test"),
        data_dir=tmp_path / "unsafe",
    )
    unsafe_context.service = cast(GongwenService, _UnsafeTitleService())
    try:
        with pytest.raises(GongwenToolError) as unsafe:
            await GongwenTools(unsafe_context).gongwen_generate_titles(
                GenerateTitlesRequest(topic="JSON 边界", engine="local")
            )
        assert unsafe.value.code == "invalid_result"
        assert "无效数值" in unsafe.value.message
    finally:
        unsafe_context.close()
