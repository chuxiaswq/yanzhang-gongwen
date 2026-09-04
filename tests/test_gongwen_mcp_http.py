"""Protocol-level tests for the embedded Streamable HTTP MCP endpoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from gongwen_web.app import create_app
from gongwen_web.articles import ArticleLibraryError
from gongwen_web.runtime import RuntimeSettings
from gongwen_web.storage import GongwenStorage

_MCP_TOKEN = "mcp-fixture-token"
_WEB_TOKEN = "web-fixture-token"
_BASE_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _settings() -> RuntimeSettings:
    return RuntimeSettings(
        environment="test",
        access_token=_WEB_TOKEN,
        mcp_access_token=_MCP_TOKEN,
        allowed_hosts=("testserver", "docs.example.test"),
        cors_origins=("https://client.example",),
    )


def _rpc(
    client: TestClient,
    request_id: int,
    method: str,
    params: dict[str, object],
    *,
    token: str | None = _MCP_TOKEN,
    headers: dict[str, str] | None = None,
) -> Any:
    request_headers = {**_BASE_HEADERS, **(headers or {})}
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    return client.post(
        "/mcp",
        headers=request_headers,
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        follow_redirects=False,
    )


def _initialize(client: TestClient, *, token: str | None = _MCP_TOKEN) -> Any:
    return _rpc(
        client,
        1,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "gongwen-test", "version": "1.0"},
        },
        token=token,
    )


def test_streamable_http_initializes_at_exact_path_and_keeps_tokens_separate(
    tmp_path: Path,
) -> None:
    application = create_app(
        storage=GongwenStorage(tmp_path / "gongwen.sqlite3"),
        settings=_settings(),
    )
    assert (
        application.state.gongwen_mcp_context.yanzhang_platform
        is application.state.yanzhang_platform
    )
    assert application.state.yanzhang_platform.artifact_store is (
        application.state.gongwen_artifact_store
    )
    assert application.state.yanzhang_platform.runtime is application.state.gongwen_runtime

    with TestClient(application) as client:
        assert _initialize(client, token=None).status_code == 401
        assert _initialize(client, token=_WEB_TOKEN).status_code == 401

        response = _initialize(client)
        assert response.status_code == 200
        assert response.history == []
        assert response.headers["cache-control"] == "no-store"
        payload = response.json()
        assert payload["result"]["protocolVersion"] == "2025-06-18"
        assert payload["result"]["serverInfo"]["name"] == "砚章公文写作"

        tools = _rpc(client, 2, "tools/list", {}).json()["result"]["tools"]
        assert len(tools) == 71
        assert len([tool for tool in tools if tool["name"].startswith("gongwen_")]) == 26
        assert len([tool for tool in tools if tool["name"].startswith("yanzhang_")]) == 45
        status = _rpc(
            client,
            3,
            "tools/call",
            {"name": "gongwen_get_status", "arguments": {}},
        ).json()["result"]
        assert status["isError"] is False
        assert status["structuredContent"]["service"] == "gongwen-mcp"

        yanzhang_status = _rpc(
            client,
            4,
            "tools/call",
            {"name": "yanzhang_get_status", "arguments": {}},
        ).json()["result"]
        assert yanzhang_status["isError"] is False
        assert yanzhang_status["structuredContent"]["service"] == "yanzhang-platform"

        resource = _rpc(
            client,
            5,
            "resources/read",
            {"uri": "gongwen://status"},
        ).json()["result"]
        assert resource["contents"][0]["mimeType"] == "application/json"
        prompt = _rpc(
            client,
            6,
            "prompts/get",
            {"name": "gongwen_title_workbench", "arguments": {"topic": "政绩观"}},
        ).json()["result"]
        assert "gongwen_generate_titles" in prompt["messages"][0]["content"]["text"]


def test_streamable_http_enforces_host_and_origin(tmp_path: Path) -> None:
    application = create_app(
        storage=GongwenStorage(tmp_path / "gongwen.sqlite3"),
        settings=_settings(),
    )

    with TestClient(application) as client:
        bad_host = _rpc(
            client,
            1,
            "initialize",
            {},
            headers={"Host": "unexpected.example"},
        )
        assert bad_host.status_code in {400, 421}

        bad_origin = _rpc(
            client,
            2,
            "initialize",
            {},
            headers={"Origin": "https://unexpected.example"},
        )
        assert bad_origin.status_code == 403

        allowed_origin = _initialize(client)
        assert allowed_origin.status_code == 200
        allowed_origin = _rpc(
            client,
            3,
            "tools/list",
            {},
            headers={"Origin": "https://client.example"},
        )
        assert allowed_origin.status_code == 200
        assert allowed_origin.headers["access-control-allow-origin"] == "https://client.example"


def test_stateless_calls_share_repository_until_application_shutdown(tmp_path: Path) -> None:
    application = create_app(
        storage=GongwenStorage(tmp_path / "gongwen.sqlite3"),
        settings=_settings(),
    )

    with TestClient(application) as client:
        for request_id in (1, 2):
            response = _rpc(
                client,
                request_id,
                "tools/call",
                {
                    "name": "gongwen_search_articles",
                    "arguments": {"query": "政绩观"},
                },
            )
            assert response.status_code == 200
            assert response.json()["result"]["isError"] is False

    with pytest.raises(ArticleLibraryError, match="已经关闭"):
        application.state.article_library.search_page("政绩观")


def test_tool_validation_errors_do_not_reflect_submitted_material(tmp_path: Path) -> None:
    application = create_app(
        storage=GongwenStorage(tmp_path / "gongwen.sqlite3"),
        settings=_settings(),
    )
    secret = "SECRET-MATERIAL token-fixture-value"

    with TestClient(application) as client:
        wrong_type = _rpc(
            client,
            1,
            "tools/call",
            {
                "name": "gongwen_review_document",
                "arguments": {"content": [secret]},
            },
        )
        too_long = _rpc(
            client,
            2,
            "tools/call",
            {
                "name": "gongwen_review_document",
                "arguments": {"content": secret + "甲" * 200_000},
            },
        )
        extra_field = _rpc(
            client,
            3,
            "tools/call",
            {
                "name": "gongwen_save_document",
                "arguments": {
                    "title": "不应写入",
                    "content": "正文",
                    "api_key": secret,
                },
            },
        )
        assert application.state.gongwen_storage.list_documents() == []

    for response in (wrong_type, too_long, extra_field):
        assert response.status_code == 200
        assert response.json()["result"]["isError"] is True
        assert "invalid_request" in response.text
        assert "SECRET-MATERIAL" not in response.text
        assert "token-fixture-value" not in response.text
