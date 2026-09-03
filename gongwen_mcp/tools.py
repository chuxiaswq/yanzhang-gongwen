"""Transport-neutral implementations of the Gongwen MCP tools."""

# Chinese punctuation is intentional in public tool messages.
# ruff: noqa: RUF001

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar, cast

from pydantic import BaseModel, ValidationError

from gongwen_mcp.artifacts import (
    DOCX_MIME,
    ZIP_MIME,
    ArtifactError,
    ArtifactStore,
)
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
    TemplateStyle,
    TestModelRequest,
)
from gongwen_web.articles import (
    ArticleLibrary,
    ArticleLibraryError,
    SQLiteArticleRepository,
)
from gongwen_web.collection import (
    ArticleCollectionError,
    ArticleCollectionScope,
    ArticleCollectionService,
)
from gongwen_web.demo import supported_document_types
from gongwen_web.docx import build_batch_zip, build_docx, unique_filename
from gongwen_web.live import LiveRequestError
from gongwen_web.methodologies import methodology_catalog
from gongwen_web.models import BatchExportRequest, ExportDocument
from gongwen_web.runtime import RuntimeSettings
from gongwen_web.service import GongwenService
from gongwen_web.storage import (
    DocumentRecord,
    DocumentVersion,
    DocumentVersionConflict,
    GongwenStorage,
    default_data_dir,
)
from yanzhang.providers.content import ArticleDiscoveryProvider, ArticleFetcherProvider
from yanzhang.providers.errors import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderTransportError,
)
from yanzhang.providers.registry import ProviderRegistry, get_default_registry

_DATABASE_FILENAME = "gongwen.sqlite3"
_GENERATION_PREVIEW_CHARS = 4_000
_SAFE_MESSAGE_CHARS = 500
_BEARER_PATTERN = re.compile(r"(?i)bearer\s+[^\s,;]+")
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|authorization|secret)\s*[:=]\s*[^\s,;]+"
)
_KEY_PATTERN = re.compile(r"\b(?:sk|key|token)-[A-Za-z0-9._-]{8,}\b", re.IGNORECASE)
_URL_PATTERN = re.compile(r"https?://[^\s\]\[(){}<>]+", re.IGNORECASE)
_PATH_PATTERN = re.compile(
    r"(?:(?<![A-Za-z0-9])/(?:[^/\s:;,]+/)+[^/\s:;,]+|[A-Za-z]:\\(?:[^\\\s:;,]+\\)+[^\\\s:;,]+)"
)

T = TypeVar("T")


class GongwenToolError(RuntimeError):
    """Stable, sanitized error surfaced by a Gongwen MCP tool."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(slots=True)
class GongwenMCPContext:
    """Application dependencies shared by all Gongwen MCP calls."""

    service: GongwenService
    storage: GongwenStorage
    article_library: ArticleLibrary
    article_collection: ArticleCollectionService
    artifact_store: ArtifactStore
    settings: RuntimeSettings
    _article_repository: SQLiteArticleRepository | None = field(default=None, repr=False)

    def close(self) -> None:
        """Release the article connection owned by :func:`build_context`."""

        if self._article_repository is not None:
            self._article_repository.close()


def build_context(
    *,
    settings: RuntimeSettings | None = None,
    data_dir: str | Path | None = None,
    article_discovery: ArticleDiscoveryProvider | None = None,
    article_fetcher: ArticleFetcherProvider | None = None,
    provider_registry: ProviderRegistry | None = None,
) -> GongwenMCPContext:
    """Build a local persistent MCP context without making a network request."""

    runtime = settings or RuntimeSettings.from_env()
    root = Path(data_dir).expanduser() if data_dir is not None else default_data_dir()
    storage = GongwenStorage(root / _DATABASE_FILENAME)
    article_repository = SQLiteArticleRepository(storage.path)
    try:
        registry = provider_registry
        if article_discovery is None or article_fetcher is None:
            registry = registry or get_default_registry()
        if article_discovery is None:
            discovery = cast(ProviderRegistry, registry).create_article_discovery(
                "official_search",
                enable_insecure_people_search=runtime.enable_insecure_people_search,
            )
        else:
            discovery = article_discovery
        if article_fetcher is None:
            fetcher = cast(ProviderRegistry, registry).create_article_fetcher("official_http")
        else:
            fetcher = article_fetcher
        article_library = ArticleLibrary(article_repository, fetcher=fetcher)
        article_collection = ArticleCollectionService(
            article_library,
            discovery,
        )
        return GongwenMCPContext(
            service=GongwenService(storage, runtime),
            storage=storage,
            article_library=article_library,
            article_collection=article_collection,
            artifact_store=ArtifactStore(root),
            settings=runtime,
            _article_repository=article_repository,
        )
    except BaseException:
        article_repository.close()
        raise


class GongwenTools:
    """Directly testable implementations for every public Gongwen MCP tool."""

    def __init__(self, context: GongwenMCPContext) -> None:
        self.context = context

    async def gongwen_get_status(self, request: StatusRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            _ = request
            await asyncio.to_thread(self.context.storage.check_ready)
            return {
                "ok": True,
                "service": "gongwen-mcp",
                "storage": "ready",
                "environment": self.context.settings.environment,
                "model": self.context.settings.public_model_configuration(),
                "document_types": list(supported_document_types()),
                "capabilities": {
                    "local_generation": True,
                    "server_model": self.context.settings.server_provider_configured,
                    "document_storage": True,
                    "article_library": True,
                    "article_collection": True,
                    "people_auto_discovery": (self.context.settings.enable_insecure_people_search),
                    "fact_audit": True,
                    "docx_artifacts": True,
                },
            }

        return await self._guard(action)

    async def gongwen_get_methods(self, request: MethodsRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            result = await asyncio.to_thread(methodology_catalog, request.document_type)
            return _model_dict(result)

        return await self._guard(action)

    async def gongwen_generate_titles(self, request: GenerateTitlesRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            references = await self._style_references(request.style_reference_ids)
            payload = request.model_dump(mode="json", exclude={"engine", "style_reference_ids"})
            payload["style_references"] = references
            payload["live"] = self._use_server(request.engine)
            return _model_dict(await self.context.service.generate_titles(payload))

        return await self._guard(action)

    async def gongwen_generate_document(
        self, request: GenerateDocumentRequest
    ) -> dict[str, object]:
        async def action() -> dict[str, object]:
            references = await self._style_references(request.style_reference_ids)
            payload = request.model_dump(
                mode="json",
                exclude={
                    "engine",
                    "style_reference_ids",
                    "document_id",
                    "expected_version",
                    "version_note",
                },
            )
            payload["style_references"] = references
            payload["live"] = self._use_server(request.engine)
            result = await self.context.service.generate(payload)
            result_data = _model_dict(result)
            metadata: dict[str, object] = {
                "generation_meta": result_data["meta"],
                "title_candidates": result_data["title_candidates"],
                "facts": result_data["facts"],
                "source_cards": result_data["source_cards"],
                "placeholders": result_data["placeholders"],
                "content_methodology": result_data["content_methodology"],
            }
            saved = await asyncio.to_thread(
                self.context.storage.save_document,
                title=result.title,
                content=result.content,
                document_type=request.document_type,
                metadata=metadata,
                document_id=request.document_id,
                version_note=request.version_note,
                expected_version=request.expected_version,
            )
            return {
                "id": saved["id"],
                "version": saved["current_version"],
                "title": saved["title"],
                "document_type": saved["document_type"],
                "preview": result.content[:_GENERATION_PREVIEW_CHARS],
                "character_count": len(result.content),
                "preview_truncated": len(result.content) > _GENERATION_PREVIEW_CHARS,
                "outline": [item.heading for item in result.outline],
                "title_candidates": result_data["title_candidates"],
                "meta": result_data["meta"],
            }

        return await self._guard(action)

    async def gongwen_rewrite_text(self, request: RewriteTextRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            payload = request.model_dump(mode="json", exclude={"engine"})
            payload["live"] = self._use_server(request.engine)
            return _model_dict(await self.context.service.rewrite(payload))

        return await self._guard(action)

    async def gongwen_review_document(self, request: ReviewDocumentRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            payload = request.model_dump(mode="json", exclude={"engine", "compact"})
            payload["live"] = self._use_server(request.engine)
            result = _model_dict(await self.context.service.review(payload))
            if request.compact:
                result["issues"] = cast(list[object], result["issues"])[:20]
            return result

        return await self._guard(action)

    async def gongwen_audit_document(self, request: AuditDocumentRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            result = _model_dict(
                await self.context.service.fact_audit(
                    request.model_dump(mode="json", exclude={"compact"})
                )
            )
            if request.compact:
                return {
                    "metrics": result["metrics"],
                    "issues": cast(list[object], result["issues"])[:100],
                    "details_available": True,
                }
            return result

        return await self._guard(action)

    async def gongwen_save_document(self, request: SaveDocumentRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            record = await asyncio.to_thread(
                self.context.storage.save_document,
                title=request.title,
                content=request.content,
                document_type=request.document_type,
                metadata=request.metadata,
                document_id=request.document_id,
                version_note=request.version_note,
                expected_version=request.expected_version,
            )
            return _saved_document_result(record)

        return await self._guard(action)

    async def gongwen_list_documents(self, request: ListDocumentsRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            items = await asyncio.to_thread(
                self.context.storage.list_documents,
                limit=request.limit + 1,
                offset=request.offset,
                search=request.search,
            )
            return {
                "items": list(items[: request.limit]),
                "limit": request.limit,
                "offset": request.offset,
                "has_more": len(items) > request.limit,
            }

        return await self._guard(action)

    async def gongwen_read_document(self, request: ReadDocumentRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            record = await asyncio.to_thread(self.context.storage.get_document, request.document_id)
            if record is None:
                raise GongwenToolError("document_not_found", "未找到该文稿")
            return _chunked_document(record, request.chunk_offset, request.chunk_size)

        return await self._guard(action)

    async def gongwen_list_versions(self, request: ListVersionsRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            exists = await asyncio.to_thread(self.context.storage.get_document, request.document_id)
            if exists is None:
                raise GongwenToolError("document_not_found", "未找到该文稿")
            versions = await asyncio.to_thread(
                self.context.storage.list_versions,
                request.document_id,
                limit=request.limit + 1,
                offset=request.offset,
            )
            return {
                "items": [_version_summary(item) for item in versions[: request.limit]],
                "limit": request.limit,
                "offset": request.offset,
                "has_more": len(versions) > request.limit,
            }

        return await self._guard(action)

    async def gongwen_read_version(self, request: ReadVersionRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            version = await asyncio.to_thread(
                self.context.storage.get_version,
                request.document_id,
                request.version,
            )
            if version is None:
                raise GongwenToolError("version_not_found", "未找到该文稿版本")
            return _chunked_version(version, request.chunk_offset, request.chunk_size)

        return await self._guard(action)

    async def gongwen_delete_document(self, request: DeleteDocumentRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            deleted = await asyncio.to_thread(
                self.context.storage.delete_document, request.document_id
            )
            if not deleted:
                raise GongwenToolError("document_not_found", "未找到该文稿")
            return {"deleted": True, "document_id": request.document_id}

        return await self._guard(action)

    async def gongwen_list_article_sources(
        self, request: ListArticleSourcesRequest
    ) -> dict[str, object]:
        async def action() -> dict[str, object]:
            _ = request
            items = await asyncio.to_thread(self.context.article_library.list_sources)
            return {"items": items}

        return await self._guard(action)

    async def gongwen_search_articles(self, request: SearchArticlesRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            page = await asyncio.to_thread(
                self.context.article_library.search_page,
                request.query,
                limit=request.limit,
                offset=request.offset,
                source_id=request.source_id,
            )
            result = page.to_dict()
            result["has_more"] = request.offset + len(page.items) < page.total
            return result

        return await self._guard(action)

    async def gongwen_read_article(self, request: ReadArticleRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            record = await asyncio.to_thread(
                self.context.article_library.get_article, request.article_id
            )
            if record is None:
                raise GongwenToolError("article_not_found", "未找到该参考文章")
            metadata = record.to_dict(include_content=False)
            return {
                "article": metadata,
                "content": _text_chunk(record.content, request.chunk_offset, request.chunk_size),
            }

        return await self._guard(action)

    async def gongwen_get_style_references(
        self, request: GetStyleReferencesRequest
    ) -> dict[str, object]:
        async def action() -> dict[str, object]:
            items = await asyncio.to_thread(
                self.context.article_library.references,
                request.article_ids,
                max_excerpt_chars=request.max_excerpt_chars,
            )
            return {"items": items}

        return await self._guard(action)

    async def gongwen_import_article_text(
        self, request: ImportArticleTextRequest
    ) -> dict[str, object]:
        async def action() -> dict[str, object]:
            record = await asyncio.to_thread(
                self.context.article_library.import_text,
                title=request.title,
                content=request.content,
                source_id=request.source_id,
                source_name=request.source_name,
                url=request.url,
                published_date=request.published_date,
                summary=request.summary,
                style_features=request.style_features,
            )
            return record.to_dict(include_content=False)

        return await self._guard(action)

    async def gongwen_import_article_url(
        self, request: ImportArticleURLRequest
    ) -> dict[str, object]:
        async def action() -> dict[str, object]:
            record = await self.context.article_library.import_url(
                request.url,
                source_id=request.source_id,
                style_features=request.style_features,
            )
            return record.to_dict(include_content=False)

        return await self._guard(action)

    async def gongwen_collect_articles(self, request: CollectArticlesRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            scope = ArticleCollectionScope.create(
                keywords=request.keywords,
                source_ids=request.source_ids,
                start_date=request.start_date,
                end_date=request.end_date,
                limit=request.limit,
            )
            return (await self.context.article_collection.collect(scope)).to_dict()

        return await self._guard(action)

    async def gongwen_delete_article(self, request: DeleteArticleRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            deleted = await asyncio.to_thread(
                self.context.article_library.delete_article, request.article_id
            )
            if not deleted:
                raise GongwenToolError("article_not_found", "未找到该参考文章")
            return {"deleted": True, "article_id": request.article_id}

        return await self._guard(action)

    async def gongwen_export_docx(self, request: ExportDocxRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            document = await self._export_document(
                request.document_id,
                request.version,
                template_style=request.template_style,
                filename=request.filename,
            )
            filename = unique_filename(document.filename or document.title, suffix=".docx")
            content = await asyncio.to_thread(build_docx, document)
            metadata = await asyncio.to_thread(
                self.context.artifact_store.put,
                content,
                filename=filename,
                mime=DOCX_MIME,
            )
            return _model_dict(metadata)

        return await self._guard(action)

    async def gongwen_export_documents_zip(
        self, request: ExportDocumentsZipRequest
    ) -> dict[str, object]:
        async def action() -> dict[str, object]:
            documents = [await self._export_ref(item) for item in request.documents]
            batch = BatchExportRequest(documents=documents, filename=request.filename)
            content, names = await asyncio.to_thread(build_batch_zip, batch)
            filename = unique_filename(request.filename, suffix=".zip")
            metadata = await asyncio.to_thread(
                self.context.artifact_store.put,
                content,
                filename=filename,
                mime=ZIP_MIME,
            )
            result = _model_dict(metadata)
            result["files"] = names
            return result

        return await self._guard(action)

    async def gongwen_mail_merge_docx(self, request: MailMergeDocxRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            template = await self._export_document(
                request.document_id,
                request.version,
                template_style=request.template_style,
                filename=None,
            )
            rows = [cast(dict[str, object], dict(row)) for row in request.rows]
            batch = BatchExportRequest(
                template=template,
                rows=rows,
                filename=request.filename,
            )
            content, names = await asyncio.to_thread(build_batch_zip, batch)
            filename = unique_filename(request.filename, suffix=".zip")
            metadata = await asyncio.to_thread(
                self.context.artifact_store.put,
                content,
                filename=filename,
                mime=ZIP_MIME,
            )
            result = _model_dict(metadata)
            result["files"] = names
            return result

        return await self._guard(action)

    async def gongwen_test_model(self, request: TestModelRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            if not self._use_server(request.engine):
                return {
                    "ok": True,
                    "engine": "local",
                    "message": "本地确定性写作引擎已就绪。",
                    "model": self.context.settings.public_model_configuration(),
                }
            result = _model_dict(await self.context.service.probe_provider())
            result["engine"] = "server"
            return result

        return await self._guard(action)

    async def gongwen_get_model_usage(self, request: GetModelUsageRequest) -> dict[str, object]:
        async def action() -> dict[str, object]:
            summary = await asyncio.to_thread(
                self.context.storage.summarize_model_usage,
            )
            items = await asyncio.to_thread(
                self.context.storage.list_model_usage,
                limit=request.limit + 1,
                offset=request.offset,
            )
            return {
                "summary": dict(summary),
                "items": list(items[: request.limit]),
                "limit": request.limit,
                "offset": request.offset,
                "has_more": len(items) > request.limit,
            }

        return await self._guard(action)

    async def _style_references(self, article_ids: Sequence[str]) -> list[dict[str, object]]:
        if not article_ids:
            return []
        raw = await asyncio.to_thread(self.context.article_library.references, article_ids)
        return [
            {
                "id": str(item.get("id", "")),
                "title": str(item.get("title", "")),
                "source_name": str(item.get("source_name", "")),
                "url": str(item.get("url", "")),
                "published_at": str(item.get("published_at", "")),
                "excerpt": str(item.get("excerpt", "")),
                "style_features": list(cast(Sequence[object], item.get("style_features", []))),
            }
            for item in raw
        ]

    async def _export_ref(self, request: ExportDocumentRef) -> ExportDocument:
        return await self._export_document(
            request.document_id,
            request.version,
            template_style=request.template_style,
            filename=request.filename,
        )

    async def _export_document(
        self,
        document_id: str,
        version: int | None,
        *,
        template_style: TemplateStyle,
        filename: str | None,
    ) -> ExportDocument:
        record = await self._document_or_version(document_id, version)
        return ExportDocument(
            title=record["title"],
            content=record["content"],
            metadata=record["metadata"],
            template_style=template_style,
            filename=filename or record["title"],
        )

    async def _document_or_version(
        self, document_id: str, version: int | None
    ) -> DocumentRecord | DocumentVersion:
        record: DocumentRecord | DocumentVersion | None
        if version is None:
            record = await asyncio.to_thread(self.context.storage.get_document, document_id)
        else:
            record = await asyncio.to_thread(self.context.storage.get_version, document_id, version)
        if record is None:
            code = "version_not_found" if version is not None else "document_not_found"
            message = "未找到该文稿版本" if version is not None else "未找到该文稿"
            raise GongwenToolError(code, message)
        return record

    def _use_server(self, engine: str) -> bool:
        if engine == "local":
            return False
        if self.context.settings.server_provider_configured:
            return True
        if engine == "server":
            raise GongwenToolError("model_not_configured", "服务端模型尚未配置")
        return False

    async def _guard(self, action: Callable[[], Awaitable[dict[str, object]]]) -> dict[str, object]:
        try:
            result = await action()
            _ensure_json_safe(result)
            return result
        except GongwenToolError:
            raise
        except Exception as exc:
            raise _public_error(exc) from None


def _saved_document_result(record: DocumentRecord) -> dict[str, object]:
    return {
        "id": record["id"],
        "version": record["current_version"],
        "title": record["title"],
        "document_type": record["document_type"],
        "character_count": len(record["content"]),
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


def _chunked_document(record: DocumentRecord, offset: int, size: int) -> dict[str, object]:
    metadata = {key: value for key, value in record.items() if key != "content"}
    return {"document": metadata, "content": _text_chunk(record["content"], offset, size)}


def _chunked_version(record: DocumentVersion, offset: int, size: int) -> dict[str, object]:
    metadata = {key: value for key, value in record.items() if key != "content"}
    return {"version": metadata, "content": _text_chunk(record["content"], offset, size)}


def _version_summary(record: DocumentVersion) -> dict[str, object]:
    return {
        "id": record["id"],
        "document_id": record["document_id"],
        "version": record["version"],
        "title": record["title"],
        "document_type": record["document_type"],
        "character_count": len(record["content"]),
        "note": record["note"],
        "created_at": record["created_at"],
    }


def _text_chunk(text: str, offset: int, size: int) -> dict[str, object]:
    chunk = text[offset : offset + size]
    next_offset = offset + len(chunk)
    has_more = next_offset < len(text)
    return {
        "text": chunk,
        "offset": offset,
        "size": len(chunk),
        "total_characters": len(text),
        "has_more": has_more,
        "next_offset": next_offset if has_more else None,
    }


def _model_dict(model: BaseModel) -> dict[str, object]:
    return cast(dict[str, object], model.model_dump(mode="json"))


def _ensure_json_safe(value: object) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise GongwenToolError("invalid_result", "工具结果包含无效数值")
        return
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise GongwenToolError("invalid_result", "工具结果包含非文本字段名")
        for item in value.values():
            _ensure_json_safe(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _ensure_json_safe(item)
        return
    raise GongwenToolError("invalid_result", "工具结果包含非 JSON 数据")


def _public_error(exc: Exception) -> GongwenToolError:
    if isinstance(exc, ValidationError):
        details = []
        for error in exc.errors(include_url=False, include_input=False)[:20]:
            field_name = ".".join(str(item) for item in error["loc"])
            details.append(f"{field_name}: {error['msg']}")
        return GongwenToolError("invalid_request", _sanitize("；".join(details)))
    if isinstance(exc, DocumentVersionConflict):
        return GongwenToolError("version_conflict", "文稿已产生新版本，请重新读取后再保存")
    if isinstance(exc, ProviderAuthenticationError):
        return GongwenToolError("provider_auth_error", "模型接口验证失败，请检查服务端配置")
    if isinstance(exc, ProviderRateLimitError):
        return GongwenToolError("provider_rate_limit", "模型接口请求较多，请稍后再试")
    if isinstance(exc, ProviderConfigurationError):
        return GongwenToolError("provider_configuration_error", "模型服务端配置不完整")
    if isinstance(exc, ProviderTimeoutError):
        return GongwenToolError("provider_timeout", "模型接口响应超时，请稍后再试")
    if isinstance(exc, ProviderTransportError):
        return GongwenToolError("provider_transport_error", "模型接口连接异常，请稍后再试")
    if isinstance(exc, ProviderError):
        return GongwenToolError("provider_error", "模型接口返回异常，请稍后再试")
    if isinstance(exc, LiveRequestError):
        return GongwenToolError("model_response_error", "模型结构化结果未通过校验")
    if isinstance(exc, ArtifactError):
        return GongwenToolError("artifact_error", _sanitize(str(exc)))
    if isinstance(exc, (ArticleLibraryError, ArticleCollectionError, ValueError)):
        return GongwenToolError("invalid_request", _sanitize(str(exc)))
    return GongwenToolError("internal_error", "操作执行异常，请稍后重试")


def _sanitize(message: str) -> str:
    clean = " ".join(message.split())
    clean = _BEARER_PATTERN.sub("Bearer [已隐藏]", clean)
    clean = _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[已隐藏]", clean)
    clean = _KEY_PATTERN.sub("[已隐藏]", clean)
    clean = _URL_PATTERN.sub("[地址]", clean)
    clean = _PATH_PATTERN.sub("[路径]", clean)
    return clean[:_SAFE_MESSAGE_CHARS] or "请求参数有误"


__all__ = [
    "GongwenMCPContext",
    "GongwenToolError",
    "GongwenTools",
    "build_context",
]
