"""Registration and in-process resource tests for the Gongwen MCP server."""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from gongwen_mcp.server import close_server, create_server
from gongwen_mcp.tools import GongwenMCPContext, build_context
from gongwen_web.articles import ArticleLibraryError
from gongwen_web.runtime import RuntimeSettings

TOOL_NAMES = [
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
]
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def mcp_context(tmp_path: Path) -> Iterator[GongwenMCPContext]:
    context = build_context(
        settings=RuntimeSettings(environment="test"),
        data_dir=tmp_path,
    )
    try:
        yield context
    finally:
        context.close()


@pytest.mark.asyncio
async def test_server_registers_exact_tools_with_client_safe_schemas(
    mcp_context: GongwenMCPContext,
) -> None:
    server = create_server(mcp_context)
    tools = await server.list_tools()

    assert [tool.name for tool in tools] == TOOL_NAMES
    assert all(tool.name.isascii() and tool.name.replace("_", "").isalnum() for tool in tools)
    assert all(tool.inputSchema["additionalProperties"] is False for tool in tools)

    title_tool = next(tool for tool in tools if tool.name == "gongwen_generate_titles")
    title_properties = cast(dict[str, object], title_tool.inputSchema["properties"])
    engine = cast(dict[str, object], title_properties["engine"])
    title_defs = cast(dict[str, dict[str, object]], title_tool.inputSchema["$defs"])
    assert title_tool.inputSchema["required"] == ["topic"]
    assert engine["default"] == "auto"
    assert title_defs["TitleCount"]["minimum"] == 1
    assert title_defs["TitleCount"]["maximum"] == 20
    assert "provider" not in title_properties
    assert "api_key" not in title_properties
    assert "base_url" not in title_properties

    read_tool = next(tool for tool in tools if tool.name == "gongwen_read_document")
    read_defs = cast(dict[str, dict[str, object]], read_tool.inputSchema["$defs"])
    assert read_defs["DocumentChunkOffset"]["minimum"] == 0
    assert read_defs["ChunkSize"]["minimum"] == 500
    assert read_defs["ChunkSize"]["maximum"] == 20_000

    review_tool = next(tool for tool in tools if tool.name == "gongwen_review_document")
    review_defs = cast(dict[str, dict[str, object]], review_tool.inputSchema["$defs"])
    assert review_defs["ReviewContent"]["maxLength"] == 200_000

    collect_tool = next(tool for tool in tools if tool.name == "gongwen_collect_articles")
    collect_defs = cast(dict[str, dict[str, object]], collect_tool.inputSchema["$defs"])
    assert collect_defs["KeywordList"]["minItems"] == 1
    assert collect_defs["KeywordList"]["maxItems"] == 20
    assert collect_defs["PageLimit"]["maximum"] == 100

    delete_tool = next(tool for tool in tools if tool.name == "gongwen_delete_document")
    assert delete_tool.annotations is not None
    assert delete_tool.annotations.destructiveHint is True
    assert delete_tool.annotations.readOnlyHint is False


@pytest.mark.asyncio
async def test_server_registers_resources_prompts_and_calls_core_tools(
    mcp_context: GongwenMCPContext,
) -> None:
    server = create_server(mcp_context)

    resources = await server.list_resources()
    templates = await server.list_resource_templates()
    prompts = await server.list_prompts()
    assert [str(item.uri) for item in resources] == ["gongwen://status"]
    assert [item.uriTemplate for item in templates] == [
        "gongwen://methods/{document_type}",
        "gongwen://documents/{id}",
        "gongwen://documents/{id}/versions/{version}",
        "gongwen://articles/{id}",
        "gongwen://exports/{id}",
    ]
    assert [item.name for item in prompts] == [
        "gongwen_title_workbench",
        "gongwen_draft_from_materials",
        "gongwen_revise_document",
        "gongwen_official_article_research",
    ]

    _, status = await server.call_tool("gongwen_get_status", {})
    assert status["ok"] is True
    _, saved = await server.call_tool(
        "gongwen_save_document",
        {"title": "MCP 测试稿", "content": "一、突出实干实效\n把工作做到群众心坎上。"},
    )
    document_id = cast(str, saved["id"])
    document_contents = await server.read_resource(f"gongwen://documents/{document_id}")
    document = json.loads(cast(str, document_contents[0].content))
    assert document["document"]["title"] == "MCP 测试稿"
    assert document["content"]["text"].startswith("一、突出实干实效")

    prompt = await server.get_prompt(
        "gongwen_title_workbench",
        {"topic": "树立正确政绩观", "document_type": "交流发言"},
    )
    assert prompt.messages
    assert "gongwen_generate_titles" in cast(str, prompt.messages[0].content.text)

    draft_prompt = await server.get_prompt(
        "gongwen_draft_from_materials",
        {"topic": "政绩观", "materials": "材料一"},
    )
    draft_text = cast(str, draft_prompt.messages[0].content.text)
    assert "gongwen_read_document" in draft_text
    assert "完整正文" in draft_text


@pytest.mark.asyncio
async def test_export_resource_reads_artifact_off_the_event_loop(
    mcp_context: GongwenMCPContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller_thread = threading.current_thread()

    def read(artifact_id: str) -> bytes:
        assert artifact_id == "a" * 32
        assert threading.current_thread() is not caller_thread
        return b"PK\x03\x04fixture"

    monkeypatch.setattr(mcp_context.artifact_store, "read", read)
    contents = await create_server(mcp_context).read_resource(f"gongwen://exports/{'a' * 32}")

    assert contents[0].content == b"PK\x03\x04fixture"
    assert contents[0].mime_type == "application/octet-stream"


@pytest.mark.asyncio
async def test_close_server_releases_only_a_lazily_owned_context(tmp_path: Path) -> None:
    created: list[GongwenMCPContext] = []

    def factory() -> GongwenMCPContext:
        context = build_context(
            settings=RuntimeSettings(environment="test"),
            data_dir=tmp_path,
        )
        created.append(context)
        return context

    server = create_server(
        context_factory=factory,
        settings=RuntimeSettings(environment="test"),
    )
    _, status = await server.call_tool("gongwen_get_status", {})
    assert status["ok"] is True
    assert len(created) == 1

    close_server(server)
    with pytest.raises(ArticleLibraryError, match="已经关闭"):
        created[0].article_library.search_page("")


@pytest.mark.asyncio
async def test_stdio_entrypoint_initializes_lists_and_calls(tmp_path: Path) -> None:
    environment = {
        "GONGWEN_ENV": "test",
        "GONGWEN_DATA_DIR": str(tmp_path / "stdio-data"),
        "PATH": os.environ.get("PATH", ""),
    }
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "gongwen_mcp.server", "--transport", "stdio"],
        env=environment,
        cwd=_PROJECT_ROOT,
    )

    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            status = await session.call_tool("gongwen_get_status", {})

    assert initialized.protocolVersion == "2025-11-25"
    assert [tool.name for tool in listed.tools] == TOOL_NAMES
    assert status.isError is False
    assert status.structuredContent is not None
    assert status.structuredContent["service"] == "gongwen-mcp"
