"""Starlette entry point for the deployable personal writing service."""

# Chinese punctuation is intentional in UI copy and sample material.
# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

import uvicorn
from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from gongwen_mcp.artifacts import ArtifactStore
from gongwen_mcp.server import create_server as create_mcp_server
from gongwen_mcp.tools import GongwenMCPContext
from gongwen_web.articles import (
    ArticleLibrary,
    SQLiteArticleRepository,
)
from gongwen_web.collection import (
    ArticleCollectionScope,
    ArticleCollectionService,
)
from gongwen_web.demo import (
    generate_demo,
    review_demo,
    rewrite_demo,
    supported_document_types,
)
from gongwen_web.docx import build_batch_zip, build_docx, unique_filename
from gongwen_web.fact_audit import audit_document
from gongwen_web.live import (
    LiveRequestError,
    generate_live,
    generate_titles_live,
    probe_provider,
    review_live,
    rewrite_live,
)
from gongwen_web.methodologies import methodology_catalog
from gongwen_web.models import (
    ArticleAutoCollectRequest,
    ArticleTextImportRequest,
    ArticleURLImportRequest,
    BatchExportRequest,
    DocumentSaveRequest,
    ExportDocument,
)
from gongwen_web.runtime import InMemoryRateLimiter, RuntimeSettings, runtime_middleware
from gongwen_web.service import GongwenService
from gongwen_web.storage import DocumentVersionConflict, GongwenStorage
from gongwen_web.title_engine import generate_titles_demo
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

_STATIC_DIR = Path(__file__).with_name("static")

_DEMO_INPUT: dict[str, object] = {
    "document_type": "工作总结",
    "topic": "2026年上半年数字化转型",
    "purpose": "系统总结阶段性成效，分析问题并部署下一步工作",
    "audience": "各处室、各直属单位",
    "tone": "严谨规范",
    "length": "标准",
    "requirements": "突出数据成效，问题分析客观，下一步任务写明时间节点。",
    "reference_style": "权威媒体综合写法",
    "fact_lock": True,
    "materials": (
        "截至2026年6月30日，统一事项平台已接入18个处室，累计流转事项"
        "12,604件，平均办理时长较去年同期下降31%。完成6个业务系统整合，"
        "清理重复账号241个；开展业务培训8场，覆盖420人次。\n"
        "目前仍存在数据标准不统一、基层重复填报等问题。下一步计划于9月底前"
        "完成数据目录，于10月启动移动审批试点。"
    ),
}


def create_app(
    *,
    storage: GongwenStorage | None = None,
    article_library: ArticleLibrary | None = None,
    article_discovery: ArticleDiscoveryProvider | None = None,
    article_fetcher: ArticleFetcherProvider | None = None,
    settings: RuntimeSettings | None = None,
    rate_limiter: InMemoryRateLimiter | None = None,
    service: GongwenService | None = None,
    artifact_store: ArtifactStore | None = None,
    provider_registry: ProviderRegistry | None = None,
) -> Starlette:
    """Create the personal web application and its persistence services."""

    runtime = settings or (service.runtime if service is not None else RuntimeSettings.from_env())
    document_storage = storage or (service.storage if service is not None else GongwenStorage())
    if service is not None and (
        service.runtime is not runtime or service.storage is not document_storage
    ):
        raise ValueError("注入的 GongwenService 必须与应用使用相同的运行配置和文稿存储")
    content_registry = provider_registry

    def resolve_content_registry() -> ProviderRegistry:
        nonlocal content_registry
        if content_registry is None:
            content_registry = get_default_registry()
        return content_registry

    owned_article_repository: SQLiteArticleRepository | None = None
    if article_library is None:
        owned_article_repository = SQLiteArticleRepository(document_storage.path)
        fetcher = article_fetcher
        if fetcher is None:
            fetcher = resolve_content_registry().create_article_fetcher("official_http")
        article_library = ArticleLibrary(
            owned_article_repository,
            fetcher=fetcher,
        )
    discovery = article_discovery
    if discovery is None:
        discovery = resolve_content_registry().create_article_discovery(
            "official_search",
            enable_insecure_people_search=runtime.enable_insecure_people_search,
        )
    people_auto_discovery_enabled = bool(getattr(discovery, "people_search_enabled", True))
    article_collection = ArticleCollectionService(article_library, discovery)
    writing_service = service or GongwenService(
        document_storage,
        runtime,
        # Resolve these module globals when invoked so existing application-level
        # test seams and downstream embedding hooks remain effective.
        generate_demo_fn=lambda command: generate_demo(command),
        generate_live_fn=lambda command: generate_live(command),
        generate_titles_demo_fn=lambda command: generate_titles_demo(command),
        generate_titles_live_fn=lambda command: generate_titles_live(command),
        rewrite_demo_fn=lambda command: rewrite_demo(command),
        rewrite_live_fn=lambda command: rewrite_live(command),
        review_demo_fn=lambda command: review_demo(command),
        review_live_fn=lambda command: review_live(command),
        fact_audit_fn=lambda *, content, materials, title="": audit_document(
            content=content,
            materials=materials,
            title=title,
        ),
        probe_provider_fn=lambda provider: probe_provider(provider),
    )
    export_artifacts = artifact_store or ArtifactStore(document_storage.path.parent)
    mcp_context = GongwenMCPContext(
        service=writing_service,
        storage=document_storage,
        article_library=article_library,
        article_collection=article_collection,
        artifact_store=export_artifacts,
        settings=runtime,
        _article_repository=owned_article_repository,
    )
    mcp_server = create_mcp_server(mcp_context, settings=runtime)
    mcp_http = mcp_server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        try:
            async with mcp_http.router.lifespan_context(mcp_http):
                yield
        finally:
            mcp_context.close()

    routes = [
        Route("/", _homepage, methods=["GET"]),
        Route("/api/health", _health, methods=["GET"]),
        Route("/api/ready", _ready, methods=["GET"]),
        Route("/api/bootstrap", _bootstrap, methods=["GET"]),
        Route("/api/methodologies", _methodologies, methods=["GET"]),
        Route("/api/titles/generate", _generate_titles, methods=["POST"]),
        Route("/api/generate", _generate, methods=["POST"]),
        Route("/api/rewrite", _rewrite, methods=["POST"]),
        Route("/api/review", _review, methods=["POST"]),
        Route("/api/fact-audit", _fact_audit, methods=["POST"]),
        Route("/api/provider/test", _provider_test, methods=["POST"]),
        Route("/api/documents", _documents, methods=["GET", "POST"]),
        Route("/api/documents/{document_id:str}/versions", _document_versions, methods=["GET"]),
        Route("/api/documents/{document_id:str}", _document, methods=["GET", "DELETE"]),
        Route("/api/model-usage", _model_usage, methods=["GET"]),
        Route("/api/article-sources", _article_sources, methods=["GET"]),
        Route("/api/articles/import-text", _article_import_text, methods=["POST"]),
        Route("/api/articles/import-url", _article_import_url, methods=["POST"]),
        Route("/api/articles/auto-collect", _article_auto_collect, methods=["POST"]),
        Route("/api/articles/collect", _article_auto_collect, methods=["POST"]),
        Route("/api/articles", _articles, methods=["GET"]),
        Route("/api/articles/{article_id:str}", _article, methods=["GET", "DELETE"]),
        Route("/api/export/docx", _export_docx, methods=["POST"]),
        Route("/api/export/batch-docx", _export_batch_docx, methods=["POST"]),
        *mcp_http.routes,
        Mount("/static", app=StaticFiles(directory=_STATIC_DIR), name="static"),
    ]
    application = Starlette(
        debug=False,
        routes=routes,
        middleware=runtime_middleware(runtime, rate_limiter=rate_limiter),
        exception_handlers={
            ValidationError: _validation_exception,
            LiveRequestError: _live_exception,
            DocumentVersionConflict: _version_conflict_exception,
            ProviderError: _provider_exception,
            json.JSONDecodeError: _json_exception,
            ValueError: _value_exception,
        },
        lifespan=lifespan,
    )
    application.state.gongwen_storage = document_storage
    application.state.article_library = article_library
    application.state.article_collection = article_collection
    application.state.gongwen_people_auto_discovery_enabled = people_auto_discovery_enabled
    application.state.gongwen_runtime = runtime
    application.state.gongwen_service = writing_service
    application.state.gongwen_artifact_store = export_artifacts
    application.state.gongwen_mcp_context = mcp_context
    application.state.gongwen_mcp_server = mcp_server
    return application


async def _homepage(_: Request) -> Response:
    return FileResponse(
        _STATIC_DIR / "index.html",
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": (
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
                "frame-ancestors 'none'"
            ),
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _health(_: Request) -> Response:
    return JSONResponse(
        {"ok": True, "service": "gongwen-web", "mode": "single-user"},
        headers={"Cache-Control": "no-store"},
    )


async def _ready(request: Request) -> Response:
    try:
        _storage(request).check_ready()
    except Exception:
        return _error_response(
            "service_not_ready",
            "文稿存储服务尚未就绪",
            503,
        )
    return JSONResponse(
        {
            "ok": True,
            "service": "gongwen-web",
            "checks": {"storage": "ready"},
        },
        headers={"Cache-Control": "no-store"},
    )


async def _bootstrap(request: Request) -> Response:
    runtime = _runtime(request)
    return JSONResponse(
        {
            "app_name": "砚章",
            "environment": runtime.environment,
            "security": {"access_token_required": runtime.access_token_required},
            "model": runtime.public_model_configuration(),
            "document_types": list(supported_document_types()),
            "tones": ["严谨规范", "凝练有力", "务实亲切"],
            "lengths": [
                {"value": "精简", "label": "精简 · 快速提要"},
                {"value": "标准", "label": "标准 · 完整结构"},
                {"value": "详细", "label": "详细 · 深度展开"},
            ],
            "demo_input": _DEMO_INPUT,
            "capabilities": {
                "demo_generation": True,
                "live_provider": True,
                "review": True,
                "docx": True,
                "merge_fields": True,
                "batch_zip": True,
                "server_persistence": True,
                "document_versions": True,
                "article_library": True,
                "automatic_article_discovery": True,
                "people_auto_discovery": bool(
                    request.app.state.gongwen_people_auto_discovery_enabled
                ),
                "title_workbench": True,
                "content_methodologies": True,
                "advanced_fact_audit": True,
                "provider_probe": True,
            },
        }
    )


async def _generate(request: Request) -> Response:
    result = await _service(request).generate(await _request_payload(request))
    return _model_response(result)


async def _methodologies(request: Request) -> Response:
    document_type = request.query_params.get("document_type") or None
    return _model_response(methodology_catalog(document_type))


async def _generate_titles(request: Request) -> Response:
    result = await _service(request).generate_titles(await _request_payload(request))
    return _model_response(result)


async def _rewrite(request: Request) -> Response:
    result = await _service(request).rewrite(await _request_payload(request))
    return _model_response(result)


async def _review(request: Request) -> Response:
    result = await _service(request).review(await _request_payload(request))
    return _model_response(result)


async def _fact_audit(request: Request) -> Response:
    result = await _service(request).fact_audit(await _request_payload(request))
    return _model_response(result)


async def _provider_test(request: Request) -> Response:
    result = await _service(request).probe_provider(await _request_payload(request))
    return _model_response(result)


async def _documents(request: Request) -> Response:
    storage = _storage(request)
    if request.method == "GET":
        limit = _query_int(request, "limit", default=50, minimum=1, maximum=500)
        offset = _query_int(request, "offset", default=0, minimum=0, maximum=1_000_000)
        search = request.query_params.get("q") or request.query_params.get("search")
        items = storage.list_documents(limit=limit, offset=offset, search=search)
        return JSONResponse(
            {"items": items, "limit": limit, "offset": offset},
            headers={"Cache-Control": "no-store"},
        )
    payload = await _request_payload(request)
    command = DocumentSaveRequest.model_validate(payload)
    document = storage.save_document(
        title=command.title,
        content=command.content,
        document_type=command.document_type,
        metadata=command.metadata,
        document_id=command.id,
        version_note=command.version_note,
        expected_version=command.expected_version,
    )
    return JSONResponse(document, status_code=201, headers={"Cache-Control": "no-store"})


async def _document(request: Request) -> Response:
    document_id = request.path_params["document_id"]
    storage = _storage(request)
    if request.method == "DELETE":
        if not storage.delete_document(document_id):
            return _error_response("not_found", "未找到该服务端文稿", 404)
        return JSONResponse({"deleted": True}, headers={"Cache-Control": "no-store"})
    document = storage.get_document(document_id)
    if document is None:
        return _error_response("not_found", "未找到该服务端文稿", 404)
    return JSONResponse(document, headers={"Cache-Control": "no-store"})


async def _document_versions(request: Request) -> Response:
    storage = _storage(request)
    document_id = request.path_params["document_id"]
    if storage.get_document(document_id) is None:
        return _error_response("not_found", "未找到该服务端文稿", 404)
    limit = _query_int(request, "limit", default=100, minimum=1, maximum=1_000)
    items = storage.list_versions(document_id, limit=limit)
    return JSONResponse({"items": items}, headers={"Cache-Control": "no-store"})


async def _model_usage(request: Request) -> Response:
    storage = _storage(request)
    return JSONResponse(
        {
            "summary": storage.summarize_model_usage(),
            "items": storage.list_model_usage(limit=100),
        },
        headers={"Cache-Control": "no-store"},
    )


async def _article_sources(request: Request) -> Response:
    items = await asyncio.to_thread(_articles_service(request).list_sources)
    return JSONResponse(
        {"items": items},
        headers={"Cache-Control": "no-store"},
    )


async def _articles(request: Request) -> Response:
    limit = _query_int(request, "limit", default=50, minimum=1, maximum=100)
    offset = _query_int(request, "offset", default=0, minimum=0, maximum=1_000_000)
    query = request.query_params.get("q", "")
    source_id = request.query_params.get("source_id") or None
    page = await asyncio.to_thread(
        _articles_service(request).search_page,
        query,
        limit=limit,
        offset=offset,
        source_id=source_id,
    )
    return JSONResponse(page.to_dict(), headers={"Cache-Control": "no-store"})


async def _article_import_text(request: Request) -> Response:
    payload = await _request_payload(request)
    command = ArticleTextImportRequest.model_validate(payload)
    record = await asyncio.to_thread(
        _articles_service(request).import_text,
        title=command.title,
        content=command.content,
        source_id=command.source_id,
        source_name=command.source_name,
        url=command.url,
        published_date=command.published_date,
        summary=command.summary,
        style_features=command.style_features,
    )
    return JSONResponse(
        record.to_dict(include_content=False),
        status_code=201,
        headers={"Cache-Control": "no-store"},
    )


async def _article_import_url(request: Request) -> Response:
    payload = await _request_payload(request)
    command = ArticleURLImportRequest.model_validate(payload)
    record = await _articles_service(request).import_url(
        command.url,
        source_id=command.source_id,
        style_features=command.style_features,
    )
    return JSONResponse(
        record.to_dict(include_content=False),
        status_code=201,
        headers={"Cache-Control": "no-store"},
    )


async def _article_auto_collect(request: Request) -> Response:
    payload = await _request_payload(request)
    command = ArticleAutoCollectRequest.model_validate(payload)
    scope = ArticleCollectionScope.create(
        keywords=command.keywords,
        source_ids=command.source_ids,
        start_date=command.start_date,
        end_date=command.end_date,
        limit=command.limit,
    )
    result = await _article_collection_service(request).collect(scope)
    return JSONResponse(result.to_dict(), headers={"Cache-Control": "no-store"})


async def _article(request: Request) -> Response:
    article_id = request.path_params["article_id"]
    library = _articles_service(request)
    if request.method == "DELETE":
        if not await asyncio.to_thread(library.delete_article, article_id):
            return _error_response("not_found", "未找到该参考文章", 404)
        return JSONResponse({"deleted": True}, headers={"Cache-Control": "no-store"})
    record = await asyncio.to_thread(library.get_article, article_id)
    if record is None:
        return _error_response("not_found", "未找到该参考文章", 404)
    return JSONResponse(record.to_dict(), headers={"Cache-Control": "no-store"})


async def _export_docx(request: Request) -> Response:
    payload = await _request_payload(request)
    raw_document = payload.get("document")
    document_payload = raw_document if isinstance(raw_document, Mapping) else payload
    document = ExportDocument.model_validate(document_payload)
    filename = unique_filename(document.filename or document.title, suffix=".docx")
    content = await asyncio.to_thread(build_docx, document)
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": _attachment_header(filename),
            "Cache-Control": "no-store",
        },
    )


async def _export_batch_docx(request: Request) -> Response:
    payload = await _request_payload(request)
    command = BatchExportRequest.model_validate(payload)
    archive, _ = await asyncio.to_thread(build_batch_zip, command)
    filename = unique_filename(command.filename, suffix=".zip")
    return Response(
        archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": _attachment_header(filename),
            "Cache-Control": "no-store",
        },
    )


async def _request_payload(request: Request) -> dict[str, Any]:
    max_request_bytes = _runtime(request).max_request_bytes
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_size = int(content_length)
        except ValueError:
            declared_size = 0
        if declared_size > max_request_bytes:
            raise ValueError(f"请求内容超过 {max_request_bytes} 字节上限")
    body = await request.body()
    if len(body) > max_request_bytes:
        raise ValueError(f"请求内容超过 {max_request_bytes} 字节上限")
    if not body:
        raise ValueError("请求内容为空")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("请求内容必须是 JSON 对象")
    return {str(key): item for key, item in value.items()}


def _model_response(model: BaseModel) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


def _attachment_header(filename: str) -> str:
    ascii_name = "download" + Path(filename).suffix.lower()
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _storage(request: Request) -> GongwenStorage:
    """Return the application-scoped local document repository."""

    value = request.app.state.gongwen_storage
    if not isinstance(value, GongwenStorage):
        raise RuntimeError("公文存储服务尚未初始化")
    return value


def _runtime(request: Request) -> RuntimeSettings:
    """Return validated deployment settings scoped to this application."""

    value = request.app.state.gongwen_runtime
    if not isinstance(value, RuntimeSettings):
        raise RuntimeError("运行配置尚未初始化")
    return value


def _articles_service(request: Request) -> ArticleLibrary:
    """Return the application-scoped article library."""

    value = request.app.state.article_library
    if not isinstance(value, ArticleLibrary):
        raise RuntimeError("文章来源库尚未初始化")
    return value


def _service(request: Request) -> GongwenService:
    """Return the application-scoped transport-neutral writing facade."""

    value = request.app.state.gongwen_service
    if not isinstance(value, GongwenService):
        raise RuntimeError("公文写作服务尚未初始化")
    return value


def _article_collection_service(request: Request) -> ArticleCollectionService:
    """Return the provider-neutral automatic collection service."""

    value = request.app.state.article_collection
    if not isinstance(value, ArticleCollectionService):
        raise RuntimeError("文章自动收集服务尚未初始化")
    return value


def _query_int(
    request: Request,
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """Parse and bound one integer query parameter."""

    raw = request.query_params.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"查询参数 {name} 必须是整数") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"查询参数 {name} 必须在 {minimum} 到 {maximum} 之间")
    return value


async def _validation_exception(_: Request, exc: Exception) -> Response:
    assert isinstance(exc, ValidationError)
    details = [
        {
            "field": ".".join(str(item) for item in error["loc"]),
            "message": error["msg"],
        }
        for error in exc.errors(include_url=False, include_input=False)
    ]
    return _error_response("invalid_request", "请检查必填项和输入格式", 422, details=details)


async def _json_exception(_: Request, exc: Exception) -> Response:
    del exc
    return _error_response("invalid_json", "请求不是有效的 JSON", 400)


async def _value_exception(_: Request, exc: Exception) -> Response:
    return _error_response("invalid_request", str(exc), 400)


async def _live_exception(_: Request, exc: Exception) -> Response:
    return _error_response("live_request_error", str(exc), 400)


async def _version_conflict_exception(_: Request, exc: Exception) -> Response:
    return _error_response("version_conflict", str(exc), 409)


async def _provider_exception(_: Request, exc: Exception) -> Response:
    # Deliberately do not echo vendor response bodies: they can contain submitted data.
    if isinstance(exc, ProviderAuthenticationError):
        return _error_response("provider_auth_error", "模型接口验证失败，请检查 API 密钥", 401)
    if isinstance(exc, ProviderRateLimitError):
        return _error_response("provider_rate_limit", "模型接口请求较多，请稍后再试", 429)
    if isinstance(exc, ProviderConfigurationError):
        return _error_response(
            "provider_configuration_error",
            "模型连接配置不完整，请检查服务商、接口地址、模型名称和密钥",
            400,
        )
    if isinstance(exc, ProviderTimeoutError):
        return _error_response("provider_timeout", "模型接口响应超时，请稍后再试", 504)
    if isinstance(exc, ProviderTransportError):
        return _error_response("provider_transport_error", "模型接口暂时连接失败", 502)
    return _error_response("provider_error", "模型接口返回异常，请重试或切换演示模式", 502)


def _error_response(
    code: str,
    message: str,
    status_code: int,
    *,
    details: list[dict[str, str]] | None = None,
) -> JSONResponse:
    error: dict[str, object] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return JSONResponse(
        {"error": error}, status_code=status_code, headers={"Cache-Control": "no-store"}
    )


def main() -> None:
    """Run the web service with environment-backed production settings."""

    settings = RuntimeSettings.from_env()
    parser = argparse.ArgumentParser(description="启动砚章个人公文写作 Web 服务")
    parser.add_argument("--host", default=settings.bind_host, help="监听地址")
    parser.add_argument("--port", type=int, default=settings.bind_port, help="监听端口")
    parser.add_argument("--workers", type=int, default=settings.workers, help="工作进程数")
    parser.add_argument("--reload", action="store_true", help="开发时自动重新加载")
    parser.add_argument(
        "--access-log",
        action=argparse.BooleanOptionalAction,
        default=settings.access_log,
        help="记录 HTTP 访问日志",
    )
    args = parser.parse_args()
    if args.reload and args.workers != 1:
        parser.error("--reload 与多工作进程不可同时使用")
    if settings.environment == "production" and args.workers != 1:
        parser.error("个人部署版本的 production 模式固定使用一个工作进程")
    uvicorn.run(
        "gongwen_web.app:create_app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
        access_log=args.access_log,
        proxy_headers=False,
        server_header=False,
        factory=True,
    )


if __name__ == "__main__":
    main()


__all__ = ["create_app", "main"]
