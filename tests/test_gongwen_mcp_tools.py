"""Offline contract tests for the transport-neutral Gongwen MCP tools."""

# Chinese fixtures and public messages intentionally use full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from gongwen_mcp.artifacts import DOCX_MIME, ZIP_MIME, ArtifactStore
from gongwen_mcp.schemas import (
    AuditDocumentRequest,
    CollectArticlesRequest,
    DeleteArticleRequest,
    DeleteDocumentRequest,
    ExportDocumentRef,
    ExportDocumentsZipRequest,
    ExportDocxRequest,
    GenerateDocumentRequest,
    GenerateTitlesRequest,
    GetModelUsageRequest,
    GetStyleReferencesRequest,
    ImportArticleTextRequest,
    ImportArticleURLRequest,
    ListArticleSourcesRequest,
    ListDocumentsRequest,
    ListVersionsRequest,
    MailMergeDocxRequest,
    MethodsRequest,
    ReadArticleRequest,
    ReadDocumentRequest,
    ReadVersionRequest,
    ReviewDocumentRequest,
    RewriteTextRequest,
    SaveDocumentRequest,
    SearchArticlesRequest,
    StatusRequest,
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
    ArticleLibrary,
    ArticleLibraryError,
    FetchedPage,
    SQLiteArticleRepository,
)
from gongwen_web.collection import ArticleCollectionService
from gongwen_web.demo import generate_demo
from gongwen_web.models import GeneratedDocument, GenerateRequest
from gongwen_web.runtime import RuntimeSettings
from gongwen_web.service import GongwenService
from gongwen_web.storage import GongwenStorage
from yanzhang.providers.content import ArticleDiscoveryQuery, DiscoveredArticle

_URL_ARTICLE = "https://news.gmw.cn/2026-09/04/url-import.htm"
_COLLECTED_ARTICLE = "https://www.people.com.cn/n1/2026/0904/collected.html"


class _FakeFetcher:
    def __init__(self, pages: dict[str, FetchedPage]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    async def fetch(self, url: str) -> FetchedPage:
        self.calls.append(url)
        return self.pages[url]


class _FakeDiscovery:
    def __init__(self, items: Sequence[DiscoveredArticle]) -> None:
        self.items = tuple(items)
        self.queries: list[ArticleDiscoveryQuery] = []

    async def discover(self, query: ArticleDiscoveryQuery) -> Sequence[DiscoveredArticle]:
        self.queries.append(query)
        return self.items


def _page(url: str, *, title: str, text: str) -> FetchedPage:
    paragraphs = "".join(f"<p>{part}</p>" for part in text.split("\n\n"))
    return FetchedPage(
        url=url,
        body=(
            "<html><head>"
            f"<meta property='og:title' content='{title}'>"
            "<meta name='publishdate' content='2026-09-04'>"
            "</head><body><article>"
            f"{paragraphs}"
            "</article></body></html>"
        ).encode(),
    )


def _long_generate(request: GenerateRequest) -> GeneratedDocument:
    generated = generate_demo(request)
    content = "一、总体要求\n" + "持续提升基层治理效能。" * 500
    return generated.model_copy(update={"content": content})


@contextmanager
def _tool_context(
    tmp_path: Path,
) -> Iterator[tuple[GongwenMCPContext, _FakeFetcher, _FakeDiscovery]]:
    settings = RuntimeSettings(environment="test")
    storage = GongwenStorage(tmp_path / "gongwen.sqlite3")
    repository = SQLiteArticleRepository(storage.path)
    fetcher = _FakeFetcher(
        {
            _URL_ARTICLE: _page(
                _URL_ARTICLE,
                title="以数字技术提升公共服务质效",
                text=(
                    "数字技术应服务群众实际需求，推动公共服务流程持续优化。\n\n"
                    "要完善协同机制，明确责任分工，形成闭环管理。"
                ),
            ),
            _COLLECTED_ARTICLE: _page(
                _COLLECTED_ARTICLE,
                title="以协同机制提升基层治理效能",
                text=(
                    "基层治理需要完善协同机制，推动资源下沉和服务提质。\n\n"
                    "各单位要加强统筹衔接，持续解决群众关切问题。"
                ),
            ),
        }
    )
    discovery = _FakeDiscovery(
        (
            DiscoveredArticle(
                url=_COLLECTED_ARTICLE,
                source_id="people",
                title="以协同机制提升基层治理效能",
                published_date=date(2026, 9, 4),
            ),
        )
    )
    library = ArticleLibrary(repository, fetcher=fetcher)
    context = GongwenMCPContext(
        service=GongwenService(storage, settings, generate_demo_fn=_long_generate),
        storage=storage,
        article_library=library,
        article_collection=ArticleCollectionService(library, discovery),
        artifact_store=ArtifactStore(tmp_path),
        settings=settings,
        _article_repository=repository,
    )
    try:
        yield context, fetcher, discovery
    finally:
        context.close()


def _as_dict(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _as_list(value: object) -> list[Any]:
    assert isinstance(value, list)
    return cast(list[Any], value)


def test_request_models_forbid_unknown_and_client_secret_fields() -> None:
    with pytest.raises(ValidationError) as extra_error:
        StatusRequest.model_validate({"unexpected": True})
    assert extra_error.value.errors()[0]["type"] == "extra_forbidden"

    engine_requests: tuple[tuple[type[object], dict[str, object]], ...] = (
        (GenerateTitlesRequest, {"topic": "基层治理"}),
        (GenerateDocumentRequest, {"topic": "基层治理"}),
        (RewriteTextRequest, {"text": "原文"}),
        (ReviewDocumentRequest, {"content": "正文"}),
        (ModelProbeRequest, {}),
    )
    for model, payload in engine_requests:
        validator = cast(Any, model).model_validate
        for secret_field in ("provider", "api_key", "base_url", "access_token"):
            with pytest.raises(ValidationError) as secret_error:
                validator({**payload, secret_field: "SECRET_VALUE"})
            assert secret_error.value.errors()[0]["type"] == "extra_forbidden"

    with pytest.raises(ValidationError):
        GenerateDocumentRequest(topic="基层治理", engine="remote")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        GenerateTitlesRequest(topic="基层治理", formula_ids=["same", "same"])
    with pytest.raises(ValidationError):
        CollectArticlesRequest(
            keywords=["治理"],
            source_ids=["people"],
            start_date=date(2026, 9, 5),
            end_date=date(2026, 9, 4),
        )
    with pytest.raises(ValidationError):
        GenerateDocumentRequest(topic="基层治理", document_id="draft")
    with pytest.raises(ValidationError):
        GenerateDocumentRequest(topic="基层治理", expected_version=0)
    with pytest.raises(ValidationError):
        SaveDocumentRequest(document_id="draft", title="标题", content="正文")
    with pytest.raises(ValidationError):
        SaveDocumentRequest(title="标题", content="正文", expected_version=0)
    assert (
        GenerateDocumentRequest(
            topic="基层治理",
            document_id="draft",
            expected_version=0,
        ).expected_version
        == 0
    )
    assert (
        SaveDocumentRequest(
            document_id="draft",
            expected_version=0,
            title="标题",
            content="正文",
        ).expected_version
        == 0
    )
    with pytest.raises(ValidationError):
        GetModelUsageRequest.model_validate({"document_id": "draft"})


def test_import_has_no_data_directory_side_effect_and_context_close_is_explicit(
    tmp_path: Path,
) -> None:
    import_only_dir = tmp_path / "import-only"
    environment = dict(os.environ)
    environment["GONGWEN_DATA_DIR"] = str(import_only_dir)
    completed = subprocess.run(
        [sys.executable, "-c", "import gongwen_mcp.schemas; import gongwen_mcp.tools"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert not import_only_dir.exists()

    data_dir = tmp_path / "explicit-context"
    context = build_context(settings=RuntimeSettings(environment="test"), data_dir=data_dir)
    assert context.storage.path == data_dir / "gongwen.sqlite3"
    assert context.storage.path.is_file()
    context.close()
    context.close()
    with pytest.raises(ArticleLibraryError, match="已经关闭"):
        context.article_library.get_article("missing")


@pytest.mark.asyncio
async def test_writing_storage_audit_and_usage_tools_cover_local_flow(tmp_path: Path) -> None:
    with _tool_context(tmp_path) as (context, _, _):
        tools = GongwenTools(context)

        status = await tools.gongwen_get_status(StatusRequest())
        assert status["ok"] is True
        assert status["model"] == {
            "server_provider_configured": False,
            "provider_name": None,
            "default_model": None,
        }
        assert "api_key" not in str(status)

        methods = await tools.gongwen_get_methods(MethodsRequest(document_type="通知"))
        assert methods["document_type"] == "通知"
        assert _as_list(methods["title_formulas"])
        assert _as_list(methods["content_methodologies"])

        titles = await tools.gongwen_generate_titles(
            GenerateTitlesRequest(
                topic="基层治理提质增效",
                document_type="通知",
                count=3,
                engine="local",
            )
        )
        assert len(_as_list(titles["candidates"])) == 3
        assert _as_dict(titles["meta"])["mode"] == "demo"

        generated = await tools.gongwen_generate_document(
            GenerateDocumentRequest(
                document_id="generated-draft",
                expected_version=0,
                topic="基层治理提质增效",
                document_type="通知",
                materials="已完成18项任务。",
                engine="local",
            )
        )
        assert generated["id"] == "generated-draft"
        assert generated["version"] == 1
        assert generated["preview_truncated"] is True
        assert len(cast(str, generated["preview"])) == 4_000
        assert cast(int, generated["character_count"]) > 4_000
        stored = context.storage.get_document("generated-draft")
        assert stored is not None
        assert len(stored["content"]) == generated["character_count"]

        first_chunk = await tools.gongwen_read_document(
            ReadDocumentRequest(
                document_id="generated-draft",
                chunk_offset=0,
                chunk_size=500,
            )
        )
        chunk = _as_dict(first_chunk["content"])
        assert chunk["size"] == 500
        assert chunk["has_more"] is True
        assert chunk["next_offset"] == 500
        assert "content" not in _as_dict(first_chunk["document"])

        rewritten = await tools.gongwen_rewrite_text(
            RewriteTextRequest(text="我们要做好相关工作。", engine="local")
        )
        assert rewritten["text"] != "我们要做好相关工作。"
        reviewed = await tools.gongwen_review_document(
            ReviewDocumentRequest(
                title="工作通知",
                content="一、总体要求\n做好相关工作。",
                engine="local",
                compact=True,
            )
        )
        assert len(_as_list(reviewed["issues"])) <= 20

        compact_audit = await tools.gongwen_audit_document(
            AuditDocumentRequest(
                title="任务进展",
                content="截至2026年9月4日，已完成18项任务。",
                materials="截至2026年9月4日，已完成18项任务。",
                compact=True,
            )
        )
        assert set(compact_audit) == {"metrics", "issues", "details_available"}
        assert compact_audit["details_available"] is True
        assert _as_dict(compact_audit["metrics"])["supported_claim_count"] >= 1

        with pytest.raises(GongwenToolError) as conflict:
            await tools.gongwen_save_document(
                SaveDocumentRequest(
                    document_id="generated-draft",
                    expected_version=0,
                    title="过期覆盖",
                    content="这次写入不应成功。",
                )
            )
        assert conflict.value.code == "version_conflict"
        assert context.storage.get_document("generated-draft") == stored

        saved = await tools.gongwen_save_document(
            SaveDocumentRequest(
                document_id="generated-draft",
                expected_version=1,
                title="关于基层治理提质增效的通知（修订）",
                document_type="通知",
                content="二次修订正文。",
                metadata={"source": "fixture", "approved": True},
                version_note="MCP 修订",
            )
        )
        assert saved["version"] == 2

        documents = await tools.gongwen_list_documents(
            ListDocumentsRequest(search="基层治理", limit=10)
        )
        assert [item["id"] for item in _as_list(documents["items"])] == ["generated-draft"]
        versions = await tools.gongwen_list_versions(
            ListVersionsRequest(document_id="generated-draft")
        )
        assert [item["version"] for item in _as_list(versions["items"])] == [2, 1]
        first_version = await tools.gongwen_read_version(
            ReadVersionRequest(
                document_id="generated-draft",
                version=1,
                chunk_size=500,
            )
        )
        assert _as_dict(first_version["version"])["version"] == 1
        assert _as_dict(first_version["content"])["has_more"] is True

        model = await tools.gongwen_test_model(ModelProbeRequest(engine="local"))
        assert model["ok"] is True
        assert model["engine"] == "local"
        with pytest.raises(GongwenToolError) as missing_model:
            await tools.gongwen_test_model(ModelProbeRequest(engine="server"))
        assert missing_model.value.code == "model_not_configured"

        usage = await tools.gongwen_get_model_usage(GetModelUsageRequest(limit=20))
        operations = {item["operation"] for item in _as_list(usage["items"])}
        assert {"titles", "generate", "rewrite", "review"} <= operations
        assert _as_dict(usage["summary"])["call_count"] >= 4

        deleted = await tools.gongwen_delete_document(
            DeleteDocumentRequest(document_id="generated-draft")
        )
        assert deleted == {"deleted": True, "document_id": "generated-draft"}
        with pytest.raises(GongwenToolError) as missing_document:
            await tools.gongwen_read_document(ReadDocumentRequest(document_id="generated-draft"))
        assert missing_document.value.code == "document_not_found"


@pytest.mark.asyncio
async def test_article_tools_import_search_read_reference_collect_and_delete(
    tmp_path: Path,
) -> None:
    with _tool_context(tmp_path) as (context, fetcher, discovery):
        tools = GongwenTools(context)

        sources = await tools.gongwen_list_article_sources(ListArticleSourcesRequest())
        assert {item["id"] for item in _as_list(sources["items"])} == {
            "people",
            "gmw",
            "qiushi",
        }

        manual = await tools.gongwen_import_article_text(
            ImportArticleTextRequest(
                title="以数字化提升基层治理效能",
                content="基层治理需要坚持需求导向。\n\n" + "持续优化服务流程。" * 80,
                source_id="manual",
                source_name="测试资料",
                published_date="2026-09-03",
                style_features=["分层论述", "行动导向"],
            )
        )
        manual_id = cast(str, manual["id"])
        assert manual_id.startswith("article_")
        assert "content" not in manual

        search = await tools.gongwen_search_articles(
            SearchArticlesRequest(query="基层治理", source_id="manual", limit=1)
        )
        assert search["total"] == 1
        assert _as_list(search["items"])[0]["id"] == manual_id
        assert search["has_more"] is False

        article = await tools.gongwen_read_article(
            ReadArticleRequest(article_id=manual_id, chunk_size=500)
        )
        assert _as_dict(article["article"])["id"] == manual_id
        assert _as_dict(article["content"])["has_more"] is True
        assert "content" not in _as_dict(article["article"])

        references = await tools.gongwen_get_style_references(
            GetStyleReferencesRequest(article_ids=[manual_id], max_excerpt_chars=100)
        )
        reference = _as_list(references["items"])[0]
        assert reference["id"] == manual_id
        assert len(reference["excerpt"]) <= 100

        imported_url = await tools.gongwen_import_article_url(
            ImportArticleURLRequest(
                url=_URL_ARTICLE,
                source_id="gmw",
                style_features=["结构清晰"],
            )
        )
        assert imported_url["source_id"] == "gmw"
        assert imported_url["import_method"] == "url"
        assert fetcher.calls == [_URL_ARTICLE]

        collected = await tools.gongwen_collect_articles(
            CollectArticlesRequest(
                keywords=["基层治理"],
                source_ids=["people"],
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 5),
                limit=5,
            )
        )
        assert collected["imported_count"] == 1
        assert collected["failed_count"] == 0
        assert fetcher.calls == [_URL_ARTICLE, _COLLECTED_ARTICLE]
        assert len(discovery.queries) == 1
        assert discovery.queries[0].keywords == ("基层治理",)

        deletion = await tools.gongwen_delete_article(DeleteArticleRequest(article_id=manual_id))
        assert deletion == {"deleted": True, "article_id": manual_id}
        with pytest.raises(GongwenToolError) as missing_article:
            await tools.gongwen_read_article(ReadArticleRequest(article_id=manual_id))
        assert missing_article.value.code == "article_not_found"


@pytest.mark.asyncio
async def test_export_tools_return_path_free_metadata_and_persist_readable_bytes(
    tmp_path: Path,
) -> None:
    with _tool_context(tmp_path) as (context, _, _):
        tools = GongwenTools(context)
        first = context.storage.save_document(
            document_id="export-one",
            title="第一份通知",
            content="一、总体要求\n扎实推进工作。",
            metadata={"issuer": "测试单位"},
        )
        second = context.storage.save_document(
            document_id="export-two",
            title="第二份报告",
            content="一、基本情况\n各项任务有序推进。",
        )

        docx = await tools.gongwen_export_docx(
            ExportDocxRequest(
                document_id=cast(str, first["id"]),
                template_style="brief",
                filename="工作通知.docx",
            )
        )
        assert docx["mime"] == DOCX_MIME
        assert docx["filename"] == "工作通知.docx"
        assert "path" not in docx
        docx_bytes = context.artifact_store.read_bytes(cast(str, docx["artifact_id"]))
        assert docx_bytes.startswith(b"PK")
        with zipfile.ZipFile(BytesIO(docx_bytes)) as archive:
            assert "word/document.xml" in archive.namelist()

        batch = await tools.gongwen_export_documents_zip(
            ExportDocumentsZipRequest(
                documents=[
                    ExportDocumentRef(document_id="export-one", filename="通知"),
                    ExportDocumentRef(document_id="export-two", filename="报告"),
                ],
                filename="两份材料.zip",
            )
        )
        assert batch["mime"] == ZIP_MIME
        assert batch["filename"] == "两份材料.zip"
        assert batch["files"] == ["通知.docx", "报告.docx"]
        batch_bytes = context.artifact_store.read_bytes(cast(str, batch["artifact_id"]))
        with zipfile.ZipFile(BytesIO(batch_bytes)) as archive:
            assert set(cast(list[str], batch["files"])) <= set(archive.namelist())
            assert "生成清单.txt" in archive.namelist()

        context.storage.save_document(
            document_id="mail-template",
            title="致{{姓名}}的工作通知",
            content="{{姓名}}同志：请于{{日期}}前完成有关工作。",
        )
        merged = await tools.gongwen_mail_merge_docx(
            MailMergeDocxRequest(
                document_id="mail-template",
                rows=[
                    {"姓名": "张三", "日期": "9月10日", "filename": "张三通知"},
                    {"姓名": "李四", "日期": "9月11日", "filename": "李四通知"},
                ],
                filename="通知汇总.zip",
            )
        )
        assert merged["mime"] == ZIP_MIME
        assert merged["files"] == ["张三通知.docx", "李四通知.docx"]
        merged_bytes = context.artifact_store.read_bytes(cast(str, merged["artifact_id"]))
        with zipfile.ZipFile(BytesIO(merged_bytes)) as archive:
            first_docx = archive.read("张三通知.docx")
        with zipfile.ZipFile(BytesIO(first_docx)) as document:
            xml = document.read("word/document.xml").decode()
        assert "张三" in xml
        assert "9月10日" in xml

        # Public metadata is JSON-compatible and exposes an opaque resource URI only.
        assert cast(str, merged["resource_uri"]).startswith("gongwen://exports/")
        assert str(tmp_path) not in str(merged)
        assert second["id"] == "export-two"


@pytest.mark.asyncio
async def test_tool_errors_redact_credentials_urls_and_internal_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _tool_context(tmp_path) as (context, _, _):
        tools = GongwenTools(context)
        secret = "fixture-model-key-abcdefgh12345678"
        endpoint = "https://private.example.test/v1"

        def fail_import(**_: object) -> object:
            raise ArticleLibraryError(f"api_key={secret}; Bearer PRIVATE_BEARER; source={endpoint}")

        monkeypatch.setattr(context.article_library, "import_text", fail_import)
        with pytest.raises(GongwenToolError) as sanitized:
            await tools.gongwen_import_article_text(
                ImportArticleTextRequest(title="测试文章", content="测试正文。")
            )
        assert sanitized.value.code == "invalid_request"
        public_message = sanitized.value.message
        assert "[已隐藏]" in public_message
        assert "[地址]" in public_message
        assert secret not in public_message
        assert "PRIVATE_BEARER" not in public_message
        assert endpoint not in public_message

        def crash(**_: object) -> object:
            raise RuntimeError(f"unexpected internal detail {secret}")

        monkeypatch.setattr(context.article_library, "import_text", crash)
        with pytest.raises(GongwenToolError) as internal:
            await tools.gongwen_import_article_text(
                ImportArticleTextRequest(title="测试文章", content="测试正文。")
            )
        assert internal.value.code == "internal_error"
        assert secret not in internal.value.message
