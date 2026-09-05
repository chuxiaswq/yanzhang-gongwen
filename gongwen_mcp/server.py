"""FastMCP transports for the Gongwen writing service.

The same registration is used by the local stdio executable and by the
Streamable HTTP endpoint embedded in :mod:`gongwen_web.app`.  Importing this
module has no filesystem or network side effects; the application context is
created lazily unless a caller explicitly supplies a shared context.
"""

# Chinese punctuation is intentional in tool and prompt descriptions.
# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import date
from threading import RLock
from typing import Annotated, Any, cast
from urllib.parse import unquote

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ContentBlock, ToolAnnotations
from mcp.types import Tool as MCPTool
from pydantic import BaseModel, Field, JsonValue, ValidationError

from gongwen_mcp.schemas import (
    AuditDocumentRequest,
    CollectArticlesRequest,
    DeleteArticleRequest,
    DeleteDocumentRequest,
    EngineMode,
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
from gongwen_mcp.tools import (
    GongwenMCPContext,
    GongwenToolError,
    GongwenTools,
    build_context,
)
from gongwen_mcp.writing_schemas import (
    GetCitationLinkRequest,
    GetEvidenceRequest,
    GetLiteratureMatrixRequest,
    GetLiteratureRequest,
    GetResearchClaimRequest,
    ListCitationLinksRequest,
    ListEvidenceRequest,
    ListLiteratureMatricesRequest,
    ListLiteratureRequest,
    ListResearchClaimsRequest,
)
from gongwen_mcp.writing_server import register_writing_tools
from gongwen_mcp.writing_tools import (
    YanzhangMCPContext,
    YanzhangPlatform,
    YanzhangToolError,
    YanzhangWritingTools,
)
from gongwen_web.methodologies import CustomContentMethodology, CustomTitleFormula
from gongwen_web.runtime import RuntimeSettings

ContextFactory = Callable[[], GongwenMCPContext]

type TopicText = Annotated[str, Field(min_length=1, max_length=300)]
type RewriteContent = Annotated[str, Field(min_length=1, max_length=100_000)]
type ReviewContent = Annotated[str, Field(min_length=1, max_length=200_000)]
type AuditContent = Annotated[str, Field(min_length=1, max_length=30_000)]
type DocumentContent = Annotated[str, Field(min_length=1, max_length=500_000)]
type ArticleContent = Annotated[str, Field(min_length=1, max_length=2_000_000)]
type TitleCount = Annotated[int, Field(ge=1, le=20)]
type PageLimit = Annotated[int, Field(ge=1, le=100)]
type PageOffset = Annotated[int, Field(ge=0, le=1_000_000)]
type DocumentChunkOffset = Annotated[int, Field(ge=0, le=500_000)]
type ArticleChunkOffset = Annotated[int, Field(ge=0, le=2_000_000)]
type ChunkSize = Annotated[int, Field(ge=500, le=20_000)]
type KeywordList = Annotated[list[str], Field(min_length=1, max_length=20)]
type SourceIdList = Annotated[list[str], Field(min_length=1, max_length=10)]
type ExportReferences = Annotated[list[ExportDocumentRef], Field(min_length=1, max_length=50)]
type MergeRows = Annotated[list[dict[str, JsonValue]], Field(min_length=1, max_length=200)]

_SERVER_INSTRUCTIONS = """\
砚章·AI文字工作台，同时提供兼容的公文工具与通用写作工具。新项目优先使用 yanzhang_ 工具，
按“项目—资料—标题—工作流—资产—审校—导出”推进；学术任务使用文献、证据和引用核验工具。
历史公文任务继续使用 gongwen_ 工具。正文事实以用户材料为准；v0.2 项目导出通过项目作用域的
yanzhang:// 资源读取，v0.1 兼容导出继续使用 gongwen:// 资源。
"""


class _SanitizedFastMCP(FastMCP):
    """Keep tool errors useful without reflecting submitted arguments."""

    async def list_tools(self) -> list[MCPTool]:
        tools = await super().list_tools()
        return [
            tool.model_copy(
                update={
                    "inputSchema": {
                        **tool.inputSchema,
                        "additionalProperties": False,
                    }
                }
            )
            for tool in tools
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        registered = self._tool_manager.get_tool(name)
        if registered is not None:
            properties = registered.parameters.get("properties", {})
            allowed = set(properties) if isinstance(properties, dict) else set()
            extra_count = len(set(arguments).difference(allowed))
            if extra_count:
                raise ToolError(f"invalid_request: 请求包含 {extra_count} 个未定义字段") from None
        try:
            return await super().call_tool(name, arguments)
        except ToolError as exc:
            cause = exc.__cause__
            if isinstance(cause, (GongwenToolError, YanzhangToolError)):
                raise ToolError(f"{cause.code}: {cause.message}") from None
            if isinstance(cause, ValidationError):
                raise ToolError(_validation_error_message(cause)) from None
            raise ToolError("internal_error: 工具调用异常，请检查工具名和参数类型") from None


class _LazyRuntime:
    """Build one shared context on first use and close it at transport shutdown."""

    def __init__(self, context: GongwenMCPContext | None, factory: ContextFactory) -> None:
        self._owns_context = context is None
        self._context = context
        self._factory = factory
        self._tools = GongwenTools(context) if context is not None else None
        self._lock = RLock()

    def context(self) -> GongwenMCPContext:
        if self._context is not None:
            return self._context
        with self._lock:
            if self._context is None:
                self._context = self._factory()
        return self._context

    def tools(self) -> GongwenTools:
        if self._tools is not None:
            return self._tools
        with self._lock:
            if self._tools is None:
                self._tools = GongwenTools(self.context())
        return self._tools

    def close(self) -> None:
        if self._owns_context and self._context is not None:
            self._context.close()


class _LazyYanzhangPlatform:
    """Resolve the v2 platform only when a Yanzhang tool is first called."""

    def __init__(self, runtime: _LazyRuntime) -> None:
        self._runtime = runtime

    def __getattr__(
        self,
        name: str,
    ) -> Callable[[object], Awaitable[Mapping[str, object]]]:
        if not name.startswith("yanzhang_"):
            raise AttributeError(name)

        async def invoke(request: object) -> Mapping[str, object]:
            platform = self._runtime.context().yanzhang_platform
            if platform is None:
                raise YanzhangToolError("service_unavailable", "通用写作平台尚未初始化")
            action = cast(
                Callable[[object], Awaitable[Mapping[str, object]]],
                getattr(platform, name),
            )
            return await action(request)

        return invoke


def create_server(
    context: GongwenMCPContext | None = None,
    *,
    context_factory: ContextFactory | None = None,
    settings: RuntimeSettings | None = None,
) -> FastMCP:
    """Create a fully registered Gongwen MCP server.

    A supplied ``context`` lets the Web application share its SQLite-backed
    repositories and service facade with MCP.  The default stdio path creates a
    context lazily from environment-backed settings.
    """

    if context is not None and context_factory is not None:
        raise ValueError("context 和 context_factory 只能提供一个")
    runtime_settings = settings or (
        context.settings if context is not None else RuntimeSettings.from_env()
    )
    factory = context_factory or (lambda: build_context(settings=runtime_settings))
    runtime = _LazyRuntime(context, factory)
    yanzhang_context = YanzhangMCPContext(
        platform=cast(YanzhangPlatform, _LazyYanzhangPlatform(runtime))
    )
    yanzhang_tools = YanzhangWritingTools(yanzhang_context)

    server = _SanitizedFastMCP(
        "砚章公文写作",
        instructions=_SERVER_INSTRUCTIONS,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        max_request_body_size=runtime_settings.max_request_bytes,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=_mcp_allowed_hosts(runtime_settings.allowed_hosts),
            allowed_origins=_mcp_allowed_origins(runtime_settings),
        ),
    )

    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    model_operation = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
    local_generation = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    mutate = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
    mutate_network = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
    destructive = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    )

    @server.tool(
        name="gongwen_get_status",
        title="查看砚章状态",
        description="查看服务、持久化、模型模式和 MCP 能力状态，不返回密钥。",
        annotations=read_only,
    )
    async def gongwen_get_status() -> dict[str, object]:
        return await runtime.tools().gongwen_get_status(_request(StatusRequest))

    @server.tool(
        name="gongwen_get_methods",
        title="获取公文写作方法",
        description="按文种获取标题公式、正文方法论和推荐默认值。",
        annotations=read_only,
    )
    async def gongwen_get_methods(document_type: str | None = None) -> dict[str, object]:
        return await runtime.tools().gongwen_get_methods(
            _request(MethodsRequest, document_type=document_type)
        )

    @server.tool(
        name="gongwen_generate_titles",
        title="批量生成并评分标题",
        description="按文种、主题、材料与标题公式生成候选标题，完成九维评分和排序。",
        annotations=model_operation,
    )
    async def gongwen_generate_titles(
        topic: TopicText,
        document_type: str = "工作总结",
        purpose: str = "",
        audience: str = "",
        materials: str | list[str] = "",
        tone: str = "稳健规范",
        reference_style: str = "权威媒体综合写法",
        style_reference_ids: list[str] | None = None,
        engine: EngineMode = "auto",
        count: TitleCount = 5,
        formula_ids: list[str] | None = None,
        custom_title_formula: CustomTitleFormula | str | None = None,
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_generate_titles(
            _request(
                GenerateTitlesRequest,
                topic=topic,
                document_type=document_type,
                purpose=purpose,
                audience=audience,
                materials=materials,
                tone=tone,
                reference_style=reference_style,
                style_reference_ids=style_reference_ids or [],
                engine=engine,
                count=count,
                formula_ids=formula_ids or [],
                custom_title_formula=custom_title_formula,
            )
        )

    @server.tool(
        name="gongwen_generate_document",
        title="生成并保存公文",
        description=(
            "按选定标题、材料与方法论生成完整文稿并保存；更新 document_id 时必须携带"
            " expected_version，新建指定 id 时使用 0。"
        ),
        annotations=mutate_network,
    )
    async def gongwen_generate_document(
        topic: TopicText,
        document_type: str = "工作总结",
        purpose: str = "",
        audience: str = "",
        materials: str | list[str] = "",
        tone: str = "稳健规范",
        reference_style: str = "权威媒体综合写法",
        style_reference_ids: list[str] | None = None,
        engine: EngineMode = "auto",
        requirements: str = "",
        fact_lock: bool = True,
        length: str = "标准",
        title_count: TitleCount = 5,
        title_formula_ids: list[str] | None = None,
        custom_title_formula: CustomTitleFormula | str | None = None,
        selected_title: str | None = None,
        content_methodology_id: str | None = None,
        custom_methodology: CustomContentMethodology | None = None,
        document_id: str | None = None,
        expected_version: int | None = None,
        version_note: str = "MCP 自动生成",
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_generate_document(
            _request(
                GenerateDocumentRequest,
                topic=topic,
                document_type=document_type,
                purpose=purpose,
                audience=audience,
                materials=materials,
                tone=tone,
                reference_style=reference_style,
                style_reference_ids=style_reference_ids or [],
                engine=engine,
                requirements=requirements,
                fact_lock=fact_lock,
                length=length,
                title_count=title_count,
                title_formula_ids=title_formula_ids or [],
                custom_title_formula=custom_title_formula,
                selected_title=selected_title,
                content_methodology_id=content_methodology_id,
                custom_methodology=custom_methodology,
                document_id=document_id,
                expected_version=expected_version,
                version_note=version_note,
            )
        )

    @server.tool(
        name="gongwen_rewrite_text",
        title="按场景改写文本",
        description="按文种对应的公文、职场、传播或学术语域润色、压缩或扩写文本。",
        annotations=model_operation,
    )
    async def gongwen_rewrite_text(
        text: RewriteContent,
        instruction: str = "提升表达的规范性、准确性和凝练度",
        mode: str = "polish",
        tone: str = "稳健规范",
        engine: EngineMode = "auto",
        document_type: str = "",
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_rewrite_text(
            _request(
                RewriteTextRequest,
                text=text,
                document_type=document_type,
                instruction=instruction,
                mode=mode,
                tone=tone,
                engine=engine,
            )
        )

    @server.tool(
        name="gongwen_review_document",
        title="审校公文",
        description="检查结构、语言、篇幅、占位符和可读性，并给出修改建议。",
        annotations=model_operation,
    )
    async def gongwen_review_document(
        content: ReviewContent,
        title: str = "",
        document_type: str = "",
        materials: str = "",
        engine: EngineMode = "auto",
        compact: bool = True,
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_review_document(
            _request(
                ReviewDocumentRequest,
                title=title,
                content=content,
                document_type=document_type,
                materials=materials,
                engine=engine,
                compact=compact,
            )
        )

    @server.tool(
        name="gongwen_audit_document",
        title="高级事实审校",
        description="把正文中的事实主张与用户材料建立证据映射，标出待核实项。",
        annotations=local_generation,
    )
    async def gongwen_audit_document(
        content: AuditContent,
        title: str = "",
        materials: str | list[str] = "",
        compact: bool = True,
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_audit_document(
            _request(
                AuditDocumentRequest,
                title=title,
                content=content,
                materials=materials,
                compact=compact,
            )
        )

    @server.tool(
        name="gongwen_save_document",
        title="保存公文版本",
        description=(
            "新建文稿；指定 document_id 时必须携带 expected_version，首次创建使用 0，"
            "更新使用刚读取的当前版本号。"
        ),
        annotations=mutate,
    )
    async def gongwen_save_document(
        title: str,
        content: DocumentContent,
        document_id: str | None = None,
        document_type: str = "",
        metadata: dict[str, JsonValue] | None = None,
        version_note: str = "",
        expected_version: int | None = None,
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_save_document(
            _request(
                SaveDocumentRequest,
                document_id=document_id,
                title=title,
                content=content,
                document_type=document_type,
                metadata=metadata or {},
                version_note=version_note,
                expected_version=expected_version,
            )
        )

    @server.tool(
        name="gongwen_list_documents",
        title="检索文稿",
        description="分页列出或按标题和内容检索服务端文稿。",
        annotations=read_only,
    )
    async def gongwen_list_documents(
        limit: PageLimit = 20,
        offset: PageOffset = 0,
        search: str | None = None,
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_list_documents(
            _request(ListDocumentsRequest, limit=limit, offset=offset, search=search)
        )

    @server.tool(
        name="gongwen_read_document",
        title="读取文稿",
        description="读取当前文稿元数据与指定范围的正文。",
        annotations=read_only,
    )
    async def gongwen_read_document(
        document_id: str,
        chunk_offset: DocumentChunkOffset = 0,
        chunk_size: ChunkSize = 8_000,
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_read_document(
            _request(
                ReadDocumentRequest,
                document_id=document_id,
                chunk_offset=chunk_offset,
                chunk_size=chunk_size,
            )
        )

    @server.tool(
        name="gongwen_list_versions",
        title="列出文稿版本",
        description="分页读取指定文稿的不可变版本列表。",
        annotations=read_only,
    )
    async def gongwen_list_versions(
        document_id: str,
        limit: PageLimit = 20,
        offset: PageOffset = 0,
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_list_versions(
            _request(
                ListVersionsRequest,
                document_id=document_id,
                limit=limit,
                offset=offset,
            )
        )

    @server.tool(
        name="gongwen_read_version",
        title="读取历史版本",
        description="读取指定文稿版本的元数据与分块正文。",
        annotations=read_only,
    )
    async def gongwen_read_version(
        document_id: str,
        version: int,
        chunk_offset: DocumentChunkOffset = 0,
        chunk_size: ChunkSize = 8_000,
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_read_version(
            _request(
                ReadVersionRequest,
                document_id=document_id,
                version=version,
                chunk_offset=chunk_offset,
                chunk_size=chunk_size,
            )
        )

    @server.tool(
        name="gongwen_delete_document",
        title="删除文稿",
        description="删除一个明确指定的服务端文稿及其版本。",
        annotations=destructive,
    )
    async def gongwen_delete_document(document_id: str) -> dict[str, object]:
        return await runtime.tools().gongwen_delete_document(
            _request(DeleteDocumentRequest, document_id=document_id)
        )

    @server.tool(
        name="gongwen_list_article_sources",
        title="列出文章来源",
        description="列出当前支持的权威媒体和用户导入来源。",
        annotations=read_only,
    )
    async def gongwen_list_article_sources() -> dict[str, object]:
        return await runtime.tools().gongwen_list_article_sources(
            _request(ListArticleSourcesRequest)
        )

    @server.tool(
        name="gongwen_search_articles",
        title="检索文章来源库",
        description="按关键词、来源和分页条件检索文章来源元数据。",
        annotations=read_only,
    )
    async def gongwen_search_articles(
        query: str = "",
        source_id: str | None = None,
        limit: PageLimit = 20,
        offset: PageOffset = 0,
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_search_articles(
            _request(
                SearchArticlesRequest,
                query=query,
                source_id=source_id,
                limit=limit,
                offset=offset,
            )
        )

    @server.tool(
        name="gongwen_read_article",
        title="读取参考文章",
        description="读取一篇来源文章的元数据和指定范围正文。",
        annotations=read_only,
    )
    async def gongwen_read_article(
        article_id: str,
        chunk_offset: ArticleChunkOffset = 0,
        chunk_size: ChunkSize = 8_000,
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_read_article(
            _request(
                ReadArticleRequest,
                article_id=article_id,
                chunk_offset=chunk_offset,
                chunk_size=chunk_size,
            )
        )

    @server.tool(
        name="gongwen_get_style_references",
        title="获取风格参考",
        description="从已选文章来源提取标题、结构和表达特征，不迁移文章事实。",
        annotations=read_only,
    )
    async def gongwen_get_style_references(
        article_ids: list[str],
        max_excerpt_chars: int = 360,
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_get_style_references(
            _request(
                GetStyleReferencesRequest,
                article_ids=article_ids,
                max_excerpt_chars=max_excerpt_chars,
            )
        )

    @server.tool(
        name="gongwen_import_article_text",
        title="导入文章文本",
        description="把用户提供并注明来源的文章文本写入文章来源库。",
        annotations=mutate,
    )
    async def gongwen_import_article_text(
        title: str,
        content: ArticleContent,
        source_id: str = "manual",
        source_name: str = "用户导入",
        url: str | None = None,
        published_date: str | None = None,
        summary: str | None = None,
        style_features: list[str] | None = None,
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_import_article_text(
            _request(
                ImportArticleTextRequest,
                title=title,
                content=content,
                source_id=source_id,
                source_name=source_name,
                url=url,
                published_date=published_date,
                summary=summary,
                style_features=style_features or [],
            )
        )

    @server.tool(
        name="gongwen_import_article_url",
        title="导入文章链接",
        description="抓取用户指定的官方文章链接并写入文章来源库。",
        annotations=mutate_network,
    )
    async def gongwen_import_article_url(
        url: str,
        source_id: str | None = None,
        style_features: list[str] | None = None,
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_import_article_url(
            _request(
                ImportArticleURLRequest,
                url=url,
                source_id=source_id,
                style_features=style_features or [],
            )
        )

    @server.tool(
        name="gongwen_collect_articles",
        title="按范围自动采集文章",
        description="按关键词、来源、日期和数量上限自动发现并导入文章来源。",
        annotations=mutate_network,
    )
    async def gongwen_collect_articles(
        keywords: KeywordList,
        source_ids: SourceIdList,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: PageLimit = 20,
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_collect_articles(
            _request(
                CollectArticlesRequest,
                keywords=keywords,
                source_ids=source_ids,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
        )

    @server.tool(
        name="gongwen_delete_article",
        title="删除参考文章",
        description="删除一篇明确指定的文章来源。",
        annotations=destructive,
    )
    async def gongwen_delete_article(article_id: str) -> dict[str, object]:
        return await runtime.tools().gongwen_delete_article(
            _request(DeleteArticleRequest, article_id=article_id)
        )

    @server.tool(
        name="gongwen_export_docx",
        title="导出 Word 文稿",
        description="把一个当前或历史文稿版本生成 DOCX，并返回可读取的资源 URI。",
        annotations=mutate,
    )
    async def gongwen_export_docx(
        document_id: str,
        version: int | None = None,
        template_style: TemplateStyle = "standard",
        filename: str | None = None,
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_export_docx(
            _request(
                ExportDocxRequest,
                document_id=document_id,
                version=version,
                template_style=template_style,
                filename=filename,
            )
        )

    @server.tool(
        name="gongwen_export_documents_zip",
        title="批量导出 Word 压缩包",
        description="把多篇当前或历史文稿版本打包为 ZIP，并返回可读取的资源 URI。",
        annotations=mutate,
    )
    async def gongwen_export_documents_zip(
        documents: ExportReferences,
        filename: str = "批量公文.zip",
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_export_documents_zip(
            _request(ExportDocumentsZipRequest, documents=documents, filename=filename)
        )

    @server.tool(
        name="gongwen_mail_merge_docx",
        title="生成 Word 域批量文稿",
        description="将文稿中的 Word 字段与多行数据合并，生成批量 DOCX 压缩包。",
        annotations=mutate,
    )
    async def gongwen_mail_merge_docx(
        document_id: str,
        rows: MergeRows,
        version: int | None = None,
        template_style: TemplateStyle = "standard",
        filename: str = "批量公文.zip",
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_mail_merge_docx(
            _request(
                MailMergeDocxRequest,
                document_id=document_id,
                rows=rows,
                version=version,
                template_style=template_style,
                filename=filename,
            )
        )

    @server.tool(
        name="gongwen_test_model",
        title="测试真实模型连接",
        description="测试服务端配置的模型连接与最小响应，不接收或返回模型密钥。",
        annotations=model_operation,
    )
    async def gongwen_test_model(engine: EngineMode = "auto") -> dict[str, object]:
        return await runtime.tools().gongwen_test_model(_request(TestModelRequest, engine=engine))

    @server.tool(
        name="gongwen_get_model_usage",
        title="查看模型用量",
        description="分页读取模型调用记录和 Token 用量汇总。",
        annotations=read_only,
    )
    async def gongwen_get_model_usage(
        limit: PageLimit = 20,
        offset: PageOffset = 0,
    ) -> dict[str, object]:
        return await runtime.tools().gongwen_get_model_usage(
            _request(
                GetModelUsageRequest,
                limit=limit,
                offset=offset,
            )
        )

    @server.resource(
        "gongwen://status",
        name="gongwen_status",
        title="砚章服务状态",
        description="当前服务、存储、模型和 MCP 能力状态。",
        mime_type="application/json",
    )
    async def gongwen_status_resource() -> str:
        return _json_resource(await runtime.tools().gongwen_get_status(_request(StatusRequest)))

    @server.resource(
        "gongwen://methods/{document_type}",
        name="gongwen_methods",
        title="公文写作方法",
        description="指定文种可用的标题公式和正文方法论。",
        mime_type="application/json",
    )
    async def gongwen_methods_resource(document_type: str) -> str:
        result = await runtime.tools().gongwen_get_methods(
            _request(MethodsRequest, document_type=unquote(document_type))
        )
        return _json_resource(result)

    @server.resource(
        "gongwen://documents/{id}",
        name="gongwen_document",
        title="砚章当前文稿",
        description="指定文稿的当前版本与分块正文。",
        mime_type="application/json",
    )
    async def gongwen_document_resource(id: str) -> str:
        result = await runtime.tools().gongwen_read_document(
            _request(
                ReadDocumentRequest,
                document_id=unquote(id),
                chunk_offset=0,
                chunk_size=20_000,
            )
        )
        return _json_resource(result)

    @server.resource(
        "gongwen://documents/{id}/versions/{version}",
        name="gongwen_document_version",
        title="砚章历史文稿版本",
        description="指定文稿的一个不可变历史版本与分块正文。",
        mime_type="application/json",
    )
    async def gongwen_document_version_resource(id: str, version: int) -> str:
        result = await runtime.tools().gongwen_read_version(
            _request(
                ReadVersionRequest,
                document_id=unquote(id),
                version=version,
                chunk_offset=0,
                chunk_size=20_000,
            )
        )
        return _json_resource(result)

    @server.resource(
        "gongwen://articles/{id}",
        name="gongwen_article",
        title="砚章参考文章",
        description="指定文章来源及其分块正文。",
        mime_type="application/json",
    )
    async def gongwen_article_resource(id: str) -> str:
        result = await runtime.tools().gongwen_read_article(
            _request(
                ReadArticleRequest,
                article_id=unquote(id),
                chunk_offset=0,
                chunk_size=20_000,
            )
        )
        return _json_resource(result)

    @server.resource(
        "gongwen://exports/{id}",
        name="gongwen_export",
        title="砚章导出文件",
        description="读取导出工具生成且仍在有效期内的 Word、PDF、文本或压缩工件。",
        mime_type="application/octet-stream",
    )
    async def gongwen_export_resource(id: str) -> bytes:
        return await asyncio.to_thread(
            runtime.context().artifact_store.read,
            unquote(id),
            legacy_only=True,
        )

    @server.resource(
        "yanzhang://projects/{project_id}/exports/{artifact_id}",
        name="yanzhang_project_export",
        title="砚章项目导出文件",
        description="按项目归属读取 v0.2 写作资产生成且仍在有效期内的导出工件。",
        mime_type="application/octet-stream",
    )
    async def yanzhang_project_export_resource(project_id: str, artifact_id: str) -> bytes:
        return await asyncio.to_thread(
            runtime.context().artifact_store.read,
            unquote(artifact_id),
            project_id=unquote(project_id),
        )

    @server.resource(
        "yanzhang://projects/{project_id}/academic/literature",
        name="yanzhang_academic_literature",
        title="砚章项目文献库",
        description="读取项目已保存的前 100 条标准化文献记录。",
        mime_type="application/json",
    )
    async def yanzhang_academic_literature_resource(project_id: str) -> str:
        result = await yanzhang_tools.yanzhang_list_literature(
            _request(
                ListLiteratureRequest,
                project_id=unquote(project_id),
                include_abstract=True,
                limit=100,
                offset=0,
            )
        )
        return _json_resource(result)

    @server.resource(
        "yanzhang://projects/{project_id}/academic/literature/{record_id}",
        name="yanzhang_academic_literature_record",
        title="砚章项目文献记录",
        description="按项目与记录标识读取文献元数据与来源追踪。",
        mime_type="application/json",
    )
    async def yanzhang_academic_literature_record_resource(project_id: str, record_id: str) -> str:
        result = await yanzhang_tools.yanzhang_get_literature(
            _request(
                GetLiteratureRequest,
                project_id=unquote(project_id),
                record_id=unquote(record_id),
                include_abstract=True,
            )
        )
        return _json_resource(result)

    @server.resource(
        "yanzhang://projects/{project_id}/academic/evidence",
        name="yanzhang_academic_evidence",
        title="砚章项目证据片段",
        description="读取项目已保存的前 100 条证据片段。",
        mime_type="application/json",
    )
    async def yanzhang_academic_evidence_resource(project_id: str) -> str:
        result = await yanzhang_tools.yanzhang_list_evidence(
            _request(
                ListEvidenceRequest,
                project_id=unquote(project_id),
                limit=100,
                offset=0,
            )
        )
        return _json_resource(result)

    @server.resource(
        "yanzhang://projects/{project_id}/academic/evidence/{evidence_id}",
        name="yanzhang_academic_evidence_item",
        title="砚章项目证据记录",
        description="按项目与证据标识读取来源谱系和精确片段。",
        mime_type="application/json",
    )
    async def yanzhang_academic_evidence_item_resource(project_id: str, evidence_id: str) -> str:
        result = await yanzhang_tools.yanzhang_get_evidence(
            _request(
                GetEvidenceRequest,
                project_id=unquote(project_id),
                evidence_id=unquote(evidence_id),
            )
        )
        return _json_resource(result)

    @server.resource(
        "yanzhang://projects/{project_id}/academic/matrices",
        name="yanzhang_academic_matrices",
        title="砚章项目文献矩阵",
        description="读取项目已保存的前 100 个文献比较矩阵。",
        mime_type="application/json",
    )
    async def yanzhang_academic_matrices_resource(project_id: str) -> str:
        result = await yanzhang_tools.yanzhang_list_literature_matrices(
            _request(
                ListLiteratureMatricesRequest,
                project_id=unquote(project_id),
                limit=100,
                offset=0,
            )
        )
        return _json_resource(result)

    @server.resource(
        "yanzhang://projects/{project_id}/academic/matrices/{matrix_id}",
        name="yanzhang_academic_matrix",
        title="砚章项目文献矩阵记录",
        description="按项目与矩阵标识读取完整文献矩阵。",
        mime_type="application/json",
    )
    async def yanzhang_academic_matrix_resource(project_id: str, matrix_id: str) -> str:
        result = await yanzhang_tools.yanzhang_get_literature_matrix(
            _request(
                GetLiteratureMatrixRequest,
                project_id=unquote(project_id),
                matrix_id=unquote(matrix_id),
            )
        )
        return _json_resource(result)

    @server.resource(
        "yanzhang://projects/{project_id}/academic/claims",
        name="yanzhang_academic_claims",
        title="砚章项目研究主张",
        description="读取项目已保存的前 100 条研究主张。",
        mime_type="application/json",
    )
    async def yanzhang_academic_claims_resource(project_id: str) -> str:
        result = await yanzhang_tools.yanzhang_list_research_claims(
            _request(
                ListResearchClaimsRequest,
                project_id=unquote(project_id),
                limit=100,
                offset=0,
            )
        )
        return _json_resource(result)

    @server.resource(
        "yanzhang://projects/{project_id}/academic/claims/{claim_id}",
        name="yanzhang_academic_claim",
        title="砚章项目研究主张记录",
        description="按项目与主张标识读取一条研究主张。",
        mime_type="application/json",
    )
    async def yanzhang_academic_claim_resource(project_id: str, claim_id: str) -> str:
        result = await yanzhang_tools.yanzhang_get_research_claim(
            _request(
                GetResearchClaimRequest,
                project_id=unquote(project_id),
                claim_id=unquote(claim_id),
            )
        )
        return _json_resource(result)

    @server.resource(
        "yanzhang://projects/{project_id}/academic/citation-links",
        name="yanzhang_academic_citation_links",
        title="砚章项目引用链",
        description="读取项目已保存的前 100 条主张—文献—证据关系。",
        mime_type="application/json",
    )
    async def yanzhang_academic_citation_links_resource(project_id: str) -> str:
        result = await yanzhang_tools.yanzhang_list_citation_links(
            _request(
                ListCitationLinksRequest,
                project_id=unquote(project_id),
                limit=100,
                offset=0,
            )
        )
        return _json_resource(result)

    @server.resource(
        "yanzhang://projects/{project_id}/academic/citation-links/{link_id}",
        name="yanzhang_academic_citation_link",
        title="砚章项目引用链记录",
        description="按项目与引用链标识读取完整来源关系。",
        mime_type="application/json",
    )
    async def yanzhang_academic_citation_link_resource(project_id: str, link_id: str) -> str:
        result = await yanzhang_tools.yanzhang_get_citation_link(
            _request(
                GetCitationLinkRequest,
                project_id=unquote(project_id),
                link_id=unquote(link_id),
            )
        )
        return _json_resource(result)

    @server.prompt(
        name="gongwen_title_workbench",
        title="公文标题工作台",
        description="从方法选择、参考检索到批量拟题和比较的完整步骤。",
    )
    def gongwen_title_workbench(
        topic: str,
        document_type: str = "讲话稿",
        audience: str = "",
    ) -> str:
        return (
            f"围绕“{topic}”完成{document_type}拟题，受众为“{audience or '待明确'}”。\n"
            "依次调用 gongwen_get_methods、gongwen_search_articles、"
            "gongwen_get_style_references、gongwen_generate_titles。\n"
            "至少比较排比式、对仗式、问题导向式标题，展示总分、公式、推荐理由和事实风险；"
            "选定标题前先向用户呈现前三名。"
        )

    @server.prompt(
        name="gongwen_draft_from_materials",
        title="从材料生成完整公文",
        description="从材料、标题、正文到审校和保存的完整流程。",
    )
    def gongwen_draft_from_materials(
        topic: str,
        materials: str,
        document_type: str = "工作总结",
        requirements: str = "",
    ) -> str:
        return (
            f"以“{topic}”为主题撰写{document_type}。用户材料如下：\n{materials}\n"
            f"补充要求：{requirements or '采用稳健规范表达'}。\n"
            "先调用 gongwen_get_methods 和 gongwen_generate_titles，确认标题后调用 "
            "gongwen_generate_document；使用返回的文稿 id 调用 gongwen_read_document，"
            "按分块读取完整正文后，再调用 gongwen_review_document 与 "
            "gongwen_audit_document。正文中的数据、时间、主体和因果关系只以用户材料为"
            "依据，待核实信息保留清晰占位。"
        )

    @server.prompt(
        name="gongwen_revise_document",
        title="修订已有公文",
        description="读取现稿、分段修改、复核并保存新版本。",
    )
    def gongwen_revise_document(document_id: str, requirements: str = "") -> str:
        return (
            f"读取文稿 {document_id} 的当前内容和版本，按以下要求修订："
            f"{requirements or '提升标题、小标题和每段首句的力度与连贯性'}。\n"
            "长文按分块读取，使用 gongwen_rewrite_text 分段处理，再调用 "
            "gongwen_review_document 与 gongwen_audit_document；确认整体一致后，以读取到的"
            "最新版本号调用 gongwen_save_document 保存新版本。"
        )

    @server.prompt(
        name="gongwen_official_article_research",
        title="权威文章来源研究",
        description="按主题范围采集文章并形成可追溯的写作风格参考。",
    )
    def gongwen_official_article_research(
        keywords: str,
        source_ids: str = "gmw,qiushi",
        date_range: str = "",
    ) -> str:
        return (
            f"围绕关键词“{keywords}”，从来源 {source_ids} 开展有界文章来源研究，"
            f"日期范围为“{date_range or '用户指定范围'}”。\n"
            "先调用 gongwen_list_article_sources，再调用 gongwen_collect_articles；"
            "用 gongwen_search_articles 核对入库结果，选择少量相关文章调用 "
            "gongwen_get_style_references。输出标题、来源、发布日期、原始链接和可借鉴的"
            "标题/结构特点，不把参考文章事实移入新稿。"
            "人民网自动检索只在部署者显式开启后按需加入；其当前检索入口会明文传输"
            "关键词与日期范围。"
        )

    register_writing_tools(server, yanzhang_context)

    server.__dict__["_gongwen_runtime"] = runtime
    return server


def _mcp_allowed_hosts(hosts: tuple[str, ...]) -> list[str]:
    """Expand trusted host names to the SDK's exact and wildcard-port forms."""

    expanded: list[str] = []
    for raw in hosts:
        host = raw.strip()
        if not host or host == "*":
            continue
        expanded.append(host)
        if not _has_explicit_port(host):
            expanded.append(f"{host}:*")
    return list(dict.fromkeys(expanded))


def _mcp_allowed_origins(settings: RuntimeSettings) -> list[str]:
    """Keep browser origins explicit while supporting local desktop clients."""

    origins = list(settings.cors_origins)
    if settings.environment != "production":
        origins.extend(
            [
                "http://127.0.0.1:*",
                "http://localhost:*",
                "http://[::1]:*",
                "https://127.0.0.1:*",
                "https://localhost:*",
                "https://[::1]:*",
            ]
        )
    return list(dict.fromkeys(origins))


def _has_explicit_port(host: str) -> bool:
    if host.startswith("["):
        closing = host.find("]")
        return closing >= 0 and len(host) > closing + 1 and host[closing + 1] == ":"
    return host.count(":") == 1


def _json_resource(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _request[RequestT: BaseModel](model: type[RequestT], **payload: object) -> RequestT:
    """Validate a tool request without echoing submitted material on errors."""

    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise GongwenToolError("invalid_request", _validation_details(exc)) from None


def _validation_error_message(exc: ValidationError) -> str:
    return f"invalid_request: {_validation_details(exc)}"


def _validation_details(exc: ValidationError) -> str:
    details = [
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors(include_url=False, include_input=False)[:20]
    ]
    return "；".join(details)[:500] or "请求参数有误"


def close_server(server: Any) -> None:
    """Close a context lazily created by :func:`create_server`."""

    runtime = getattr(server, "_gongwen_runtime", None)
    if isinstance(runtime, _LazyRuntime):
        runtime.close()


def main() -> None:
    """Run the local Gongwen MCP transport."""

    parser = argparse.ArgumentParser(description="启动砚章公文写作 MCP 服务")
    parser.add_argument(
        "--transport",
        choices=("stdio",),
        default="stdio",
        help="MCP 传输方式（本地客户端使用 stdio）",
    )
    args = parser.parse_args()
    settings = RuntimeSettings.from_env()
    context = build_context(settings=settings)
    try:
        create_server(context, settings=settings).run(transport=args.transport)
    finally:
        context.close()


if __name__ == "__main__":
    main()


__all__ = ["ContextFactory", "close_server", "create_server", "main"]
