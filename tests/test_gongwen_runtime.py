"""Offline tests for deployable Gongwen web runtime controls."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from gongwen_web.app import create_app
from gongwen_web.demo import generate_demo
from gongwen_web.models import GeneratedDocument, GenerateRequest, ProviderSettings
from gongwen_web.runtime import InMemoryRateLimiter, RuntimeSettings, runtime_middleware
from gongwen_web.storage import GongwenStorage


@pytest.fixture
def storage(tmp_path: Path) -> GongwenStorage:
    return GongwenStorage(tmp_path / "runtime.sqlite3")


def test_runtime_settings_parse_production_environment_without_exposing_secrets() -> None:
    secret = "a-strong-single-user-token-value-123456"
    mcp_secret = "a-separate-strong-mcp-token-value-123456"
    settings = RuntimeSettings.from_env(
        {
            "GONGWEN_ENV": "production",
            "GONGWEN_HOST": "0.0.0.0",
            "GONGWEN_PORT": "8080",
            "GONGWEN_ALLOWED_HOSTS": "docs.example.test,localhost",
            "GONGWEN_CORS_ORIGINS": "https://ui.example.test",
            "GONGWEN_TRUSTED_PROXY_IPS": "10.0.0.0/8,127.0.0.1",
            "GONGWEN_ACCESS_TOKEN": secret,
            "GONGWEN_MCP_ACCESS_TOKEN": mcp_secret,
            "GONGWEN_LLM_PROVIDER": "openai",
            "GONGWEN_LLM_MODEL": "fixture-model",
            "GONGWEN_LLM_API_KEY": "server-model-secret",
            "GONGWEN_LLM_BASE_URL": "https://models.example.test/v1",
            "GONGWEN_CLIENT_LLM_BASE_URL_ALLOWLIST": (
                "https://gateway.example.test/v1,https://second.example.test/api"
            ),
            "GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH": "true",
        }
    )

    assert settings.environment == "production"
    assert settings.bind_host == "0.0.0.0"
    assert settings.bind_port == 8080
    assert settings.allowed_hosts == ("docs.example.test", "localhost")
    assert settings.rate_limit_requests == 120
    assert settings.access_log is False
    assert settings.hsts_seconds == 31_536_000
    assert settings.mcp_access_token == mcp_secret
    assert settings.server_provider_configured is True
    assert settings.client_provider_base_url_allowlist == (
        "https://gateway.example.test/v1",
        "https://second.example.test/api",
    )
    assert settings.enable_insecure_people_search is True
    assert settings.public_model_configuration() == {
        "server_provider_configured": True,
        "provider_name": "openai",
        "default_model": "fixture-model",
    }
    assert secret not in repr(settings)
    assert mcp_secret not in repr(settings)
    assert "server-model-secret" not in repr(settings)

    with pytest.raises(ValueError, match="GONGWEN_ACCESS_TOKEN"):
        RuntimeSettings.from_env(
            {
                "GONGWEN_ENV": "production",
                "GONGWEN_ALLOWED_HOSTS": "docs.example.test",
                "GONGWEN_MCP_ACCESS_TOKEN": mcp_secret,
            }
        )
    public_settings = RuntimeSettings.from_env(
        {
            "GONGWEN_ENV": "production",
            "GONGWEN_ALLOWED_HOSTS": "docs.example.test",
            "GONGWEN_MCP_ACCESS_TOKEN": mcp_secret,
            "GONGWEN_ALLOW_UNAUTHENTICATED": "true",
        }
    )
    assert public_settings.access_token_required is False
    with pytest.raises(ValueError, match="精确配置"):
        RuntimeSettings.from_env(
            {
                "GONGWEN_ENV": "production",
                "GONGWEN_ACCESS_TOKEN": secret,
                "GONGWEN_MCP_ACCESS_TOKEN": mcp_secret,
                "GONGWEN_ALLOWED_HOSTS": "*",
            }
        )
    with pytest.raises(ValueError, match="精确配置"):
        RuntimeSettings.from_env(
            {
                "GONGWEN_ENV": "production",
                "GONGWEN_ACCESS_TOKEN": secret,
                "GONGWEN_MCP_ACCESS_TOKEN": mcp_secret,
                "GONGWEN_ALLOWED_HOSTS": "*.example.test",
            }
        )
    with pytest.raises(ValueError, match="示例占位值"):
        RuntimeSettings.from_env(
            {
                "GONGWEN_ENV": "production",
                "GONGWEN_ACCESS_TOKEN": "CHANGE_ME_WITH_AT_LEAST_32_RANDOM_CHARACTERS",
                "GONGWEN_MCP_ACCESS_TOKEN": mcp_secret,
                "GONGWEN_ALLOWED_HOSTS": "docs.example.test",
            }
        )
    with pytest.raises(ValueError, match="GONGWEN_MCP_ACCESS_TOKEN"):
        RuntimeSettings.from_env(
            {
                "GONGWEN_ENV": "production",
                "GONGWEN_ACCESS_TOKEN": secret,
                "GONGWEN_ALLOWED_HOSTS": "docs.example.test",
            }
        )
    with pytest.raises(ValueError, match="32 字节"):
        RuntimeSettings.from_env(
            {
                "GONGWEN_ENV": "production",
                "GONGWEN_ACCESS_TOKEN": secret,
                "GONGWEN_MCP_ACCESS_TOKEN": "short-mcp-token",
                "GONGWEN_ALLOWED_HOSTS": "docs.example.test",
            }
        )
    with pytest.raises(ValueError, match="示例占位值"):
        RuntimeSettings.from_env(
            {
                "GONGWEN_ENV": "production",
                "GONGWEN_ACCESS_TOKEN": secret,
                "GONGWEN_MCP_ACCESS_TOKEN": "CHANGE_ME_WITH_AT_LEAST_32_RANDOM_CHARACTERS",
                "GONGWEN_ALLOWED_HOSTS": "docs.example.test",
            }
        )
    with pytest.raises(ValueError, match="分开设置"):
        RuntimeSettings.from_env(
            {
                "GONGWEN_ENV": "production",
                "GONGWEN_ACCESS_TOKEN": secret,
                "GONGWEN_MCP_ACCESS_TOKEN": secret,
                "GONGWEN_ALLOWED_HOSTS": "docs.example.test",
            }
        )

    development = RuntimeSettings.from_env({"GONGWEN_MCP_ACCESS_TOKEN": ""})
    assert development.mcp_access_token is None
    assert development.enable_insecure_people_search is False

    explicit_access_log = RuntimeSettings.from_env({"GONGWEN_ACCESS_LOG": "true"})
    assert explicit_access_log.access_log is True

    with pytest.raises(ValueError, match="GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH"):
        RuntimeSettings.from_env({"GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH": "sometimes"})
    with pytest.raises(ValueError, match="GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH"):
        RuntimeSettings.from_env({"GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH": "1"})


def test_server_provider_aliases_are_normalized_and_unknown_names_fail_fast() -> None:
    settings = RuntimeSettings.from_env(
        {
            "GONGWEN_LLM_PROVIDER": "deepseek",
            "GONGWEN_LLM_MODEL": "fixture-model",
            "GONGWEN_LLM_API_KEY": "fixture-secret",
            "GONGWEN_LLM_BASE_URL": "https://models.example.test/v1",
        }
    )
    assert settings.server_provider is not None
    assert settings.server_provider.name == "openai"

    with pytest.raises(ValueError, match="GONGWEN_LLM_BASE_URL"):
        RuntimeSettings.from_env(
            {
                "GONGWEN_LLM_PROVIDER": "qwen",
                "GONGWEN_LLM_API_KEY": "fixture-secret",
            }
        )
    with pytest.raises(ValueError, match="尚未注册"):
        RuntimeSettings.from_env(
            {
                "GONGWEN_LLM_PROVIDER": "not-a-provider",
                "GONGWEN_LLM_API_KEY": "fixture-secret",
            }
        )


def test_bootstrap_reports_explicit_people_search_opt_in(storage: GongwenStorage) -> None:
    application = create_app(
        storage=storage,
        settings=RuntimeSettings(
            environment="test",
            enable_insecure_people_search=True,
        ),
    )

    with TestClient(application) as client:
        bootstrap = client.get("/api/bootstrap")

    assert bootstrap.status_code == 200
    assert bootstrap.json()["capabilities"]["people_auto_discovery"] is True


def test_production_browser_provider_requires_exact_https_base_url_allowlist() -> None:
    settings = RuntimeSettings(
        environment="production",
        allowed_hosts=("docs.example.test",),
        access_token="a-strong-single-user-token-value-123456",
        mcp_access_token="a-separate-strong-mcp-token-value-123456",
        client_provider_base_url_allowlist=("https://models.example.test/v1",),
    )
    allowed = ProviderSettings(
        name="openai",
        model="fixture-model",
        api_key="browser-model-secret",
        base_url="https://MODELS.example.test:443/v1/",
        options={"endpoint": "/chat/completions"},
    )

    resolved = settings.resolve_provider(allowed)

    assert resolved is not None
    assert resolved.base_url == "https://models.example.test/v1"
    assert resolved.options == {"endpoint": "/chat/completions"}

    for denied_url in (
        "https://models.example.test/v2",
        "https://other.example.test/v1",
        "http://models.example.test/v1",
    ):
        with pytest.raises(ValueError, match="GONGWEN_CLIENT_LLM_BASE_URL_ALLOWLIST"):
            settings.resolve_provider(allowed.model_copy(update={"base_url": denied_url}))

    for endpoint in (
        "https://other.example.test/chat",
        "../admin",
        "/chat/completions?target=other",
    ):
        with pytest.raises(ValueError, match=r"endpoint.*相对路径"):
            settings.resolve_provider(
                allowed.model_copy(update={"options": {"endpoint": endpoint}})
            )


def test_client_provider_allowlist_does_not_restrict_server_owned_endpoint() -> None:
    server = ProviderSettings(
        name="openai",
        model="server-model",
        api_key="server-model-secret",
        base_url="https://private-model.example.test/v1",
    )
    settings = RuntimeSettings(
        environment="production",
        allowed_hosts=("docs.example.test",),
        access_token="a-strong-single-user-token-value-123456",
        mcp_access_token="a-separate-strong-mcp-token-value-123456",
        server_provider=server,
    )

    default = settings.resolve_provider(None)
    selected = settings.resolve_provider(ProviderSettings(model="browser-selected-model"))

    assert default is not None
    assert default.base_url == "https://private-model.example.test/v1"
    assert selected is not None
    assert selected.base_url == "https://private-model.example.test/v1"
    assert selected.model == "browser-selected-model"


def test_development_browser_provider_keeps_custom_base_url_behavior() -> None:
    settings = RuntimeSettings()
    client = ProviderSettings(
        name="openai",
        api_key="browser-model-secret",
        base_url="http://127.0.0.1:11434/v1",
        options={"endpoint": "/chat/completions"},
    )

    assert settings.resolve_provider(client) is client


def test_auth_host_cors_and_security_headers(storage: GongwenStorage) -> None:
    settings = RuntimeSettings(
        allowed_hosts=("testserver", "docs.example.test"),
        cors_origins=("https://ui.example.test",),
        access_token="fixture-access-token",
    )
    with TestClient(create_app(storage=storage, settings=settings)) as client:
        for public_path in ("/", "/static/styles.css", "/api/health", "/api/ready"):
            response = client.get(public_path)
            assert response.status_code == 200
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["x-frame-options"] == "DENY"
            assert response.headers["referrer-policy"] == "no-referrer"
            assert "camera=()" in response.headers["permissions-policy"]
            assert "frame-ancestors 'none'" in response.headers["content-security-policy"]

        bootstrap = client.get("/api/bootstrap")
        assert bootstrap.status_code == 200
        assert bootstrap.json()["security"] == {"access_token_required": True}

        missing = client.get("/api/methodologies")
        assert missing.status_code == 401
        assert missing.json()["error"]["code"] == "authentication_required"
        assert missing.headers["www-authenticate"] == "Bearer"
        assert missing.headers["cache-control"] == "no-store"
        assert missing.headers["x-frame-options"] == "DENY"

        query_token = client.get(
            "/api/methodologies",
            params={"access_token": "fixture-access-token"},
        )
        assert query_token.status_code == 401
        wrong = client.get(
            "/api/methodologies",
            headers={"Authorization": "Bearer wrong"},
        )
        assert wrong.status_code == 401
        accepted = client.get(
            "/api/methodologies",
            headers={"Authorization": "Bearer fixture-access-token"},
        )
        assert accepted.status_code == 200

        allowed_origin = client.get(
            "/api/methodologies",
            headers={"Origin": "https://ui.example.test"},
        )
        assert allowed_origin.status_code == 401
        assert allowed_origin.headers["access-control-allow-origin"] == "https://ui.example.test"
        blocked_origin = client.get(
            "/api/methodologies",
            headers={"Origin": "https://other.example.test"},
        )
        assert "access-control-allow-origin" not in blocked_origin.headers
        preflight = client.options(
            "/api/methodologies",
            headers={
                "Origin": "https://ui.example.test",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "https://ui.example.test"
        mcp_preflight = client.options(
            "/mcp",
            headers={
                "Origin": "https://ui.example.test",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": (
                    "Authorization, Content-Type, Mcp-Session-Id, "
                    "MCP-Protocol-Version, Last-Event-ID"
                ),
            },
        )
        assert mcp_preflight.status_code == 200
        allowed_headers = mcp_preflight.headers["access-control-allow-headers"].casefold()
        for header in (
            "authorization",
            "content-type",
            "mcp-session-id",
            "mcp-protocol-version",
            "last-event-id",
        ):
            assert header in allowed_headers
        mcp_cors = client.get("/mcp", headers={"Origin": "https://ui.example.test"})
        assert "Mcp-Session-Id" in mcp_cors.headers["access-control-expose-headers"]

        invalid_host = client.get("/api/health", headers={"Host": "evil.example.test"})
        assert invalid_host.status_code == 400
        assert invalid_host.headers["x-frame-options"] == "DENY"


def test_mcp_and_web_api_use_independent_bearer_tokens() -> None:
    async def accepted(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True}, headers={"Mcp-Session-Id": "fixture-session"})

    settings = RuntimeSettings(
        access_token="fixture-web-token",
        mcp_access_token="fixture-mcp-token",
    )
    application = Starlette(
        routes=[
            Route("/api/private", accepted, methods=["GET"]),
            Route("/mcp", accepted, methods=["GET", "POST"]),
            Route("/mcp/", accepted, methods=["GET", "POST"]),
        ],
        middleware=runtime_middleware(settings),
    )

    with TestClient(application) as client:
        for path in ("/mcp", "/mcp/"):
            missing = client.post(path)
            assert missing.status_code == 401
            assert missing.headers["www-authenticate"] == "Bearer"
            assert missing.headers["cache-control"] == "no-store"

            wrong = client.post(path, headers={"Authorization": "Bearer wrong"})
            assert wrong.status_code == 401
            web_token = client.post(
                path,
                headers={"Authorization": "Bearer fixture-web-token"},
            )
            assert web_token.status_code == 401
            query_token = client.post(path, params={"access_token": "fixture-mcp-token"})
            assert query_token.status_code == 401
            duplicate = client.post(
                path,
                headers=[
                    ("Authorization", "Bearer fixture-mcp-token"),
                    ("Authorization", "Bearer fixture-mcp-token"),
                ],
            )
            assert duplicate.status_code == 401

            response = client.post(
                path,
                headers={"Authorization": "Bearer fixture-mcp-token"},
            )
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"

        web_response = client.get(
            "/api/private",
            headers={"Authorization": "Bearer fixture-web-token"},
        )
        assert web_response.status_code == 200
        assert (
            client.get(
                "/api/private",
                headers={"Authorization": "Bearer fixture-mcp-token"},
            ).status_code
            == 401
        )
        assert client.options("/mcp").status_code != 401
        assert client.get("/mcp-other").status_code == 404


def test_body_limit_rejects_declared_and_streamed_payloads(storage: GongwenStorage) -> None:
    settings = RuntimeSettings(max_request_bytes=1_024)
    with TestClient(create_app(storage=storage, settings=settings)) as client:
        declared = client.post(
            "/api/fact-audit",
            content=b"{}",
            headers={"Content-Length": "1025", "Content-Type": "application/json"},
        )
        assert declared.status_code == 413
        assert declared.json()["error"]["code"] == "request_too_large"
        assert declared.headers["x-content-type-options"] == "nosniff"

        streamed = client.post(
            "/api/fact-audit",
            content=iter((b'{"content":"', b"x" * 1_100, b'"}')),
            headers={"Content-Type": "application/json"},
        )
        assert streamed.status_code == 413
        assert streamed.json()["error"]["code"] == "request_too_large"

        malformed = client.post(
            "/api/fact-audit",
            content=b"{}",
            headers={"Content-Length": "NaN", "Content-Type": "application/json"},
        )
        assert malformed.status_code == 400
        assert malformed.json()["error"]["code"] == "invalid_content_length"

        base = {"content": "事实材料。", "padding": ""}
        encoded = json.dumps(base, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        base["padding"] = "x" * (1_024 - len(encoded))
        boundary = json.dumps(base, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        assert len(boundary) == 1_024
        accepted = client.post(
            "/api/fact-audit",
            content=boundary,
            headers={"Content-Type": "application/json"},
        )
        assert accepted.status_code == 200


def test_forwarded_scheme_is_used_only_for_a_trusted_proxy(storage: GongwenStorage) -> None:
    forwarded_headers = {"X-Forwarded-Proto": "https"}
    untrusted_settings = RuntimeSettings(hsts_seconds=300)
    with TestClient(create_app(storage=storage, settings=untrusted_settings)) as client:
        untrusted = client.get("/api/health", headers=forwarded_headers)
    assert "strict-transport-security" not in untrusted.headers

    trusted_settings = RuntimeSettings(
        trusted_proxy_ips=("testclient",),
        hsts_seconds=300,
    )
    with TestClient(create_app(storage=storage, settings=trusted_settings)) as client:
        trusted = client.get("/api/health", headers=forwarded_headers)
    assert trusted.headers["strict-transport-security"] == "max-age=300"


def test_rate_limit_is_deterministic_and_public_probes_are_exempt(
    storage: GongwenStorage,
) -> None:
    now = [100.0]
    limiter = InMemoryRateLimiter(2, 60, clock=lambda: now[0])
    settings = RuntimeSettings(rate_limit_requests=2, rate_limit_window_seconds=60)
    with TestClient(create_app(storage=storage, settings=settings, rate_limiter=limiter)) as client:
        assert client.get("/api/methodologies").status_code == 200
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/ready").status_code == 200
        mcp_response = client.post("/mcp")
        assert mcp_response.status_code != 429
        assert mcp_response.headers["cache-control"] == "no-store"
        limited = client.get("/api/methodologies")
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "rate_limit_exceeded"
        assert limited.headers["retry-after"] == "60"
        assert limited.headers["x-frame-options"] == "DENY"

        now[0] += 61
        assert client.get("/api/methodologies").status_code == 200


def test_readiness_failure_is_public_and_sanitized(
    storage: GongwenStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_readiness() -> None:
        raise OSError(f"database unavailable at {storage.path}")

    monkeypatch.setattr(storage, "check_ready", fail_readiness)
    settings = RuntimeSettings(access_token="fixture-access-token")
    with TestClient(create_app(storage=storage, settings=settings)) as client:
        response = client.get("/api/ready")
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "service_not_ready",
            "message": "文稿存储服务尚未就绪",
        }
    }
    assert str(storage.path) not in response.text


def test_live_request_can_use_server_provider_without_browser_secret(
    storage: GongwenStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_module = importlib.import_module("gongwen_web.app")
    captured: list[ProviderSettings | None] = []

    async def fake_generate_live(command: GenerateRequest) -> GeneratedDocument:
        captured.append(command.provider)
        return generate_demo(command.model_copy(update={"live": False}))

    monkeypatch.setattr(app_module, "generate_live", fake_generate_live)
    settings = RuntimeSettings(
        server_provider=ProviderSettings(
            name="openai",
            model="server-default-model",
            api_key="server-model-secret",
            base_url="https://models.example.test/v1",
            timeout_seconds=30,
        )
    )
    with TestClient(create_app(storage=storage, settings=settings)) as client:
        bootstrap = client.get("/api/bootstrap").json()
        default_response = client.post(
            "/api/generate",
            json={
                "topic": "服务端默认模型",
                "document_type": "报告",
                "materials": "已形成工作方案。",
                "live": True,
            },
        )
        response = client.post(
            "/api/generate",
            json={
                "topic": "服务端模型配置",
                "document_type": "报告",
                "materials": "已形成工作方案。",
                "live": True,
                "provider": {
                    "name": "browser-name-is-not-used-with-server-secret",
                    "model": "browser-selected-model",
                    "base_url": "https://browser.example.test/v1",
                    "timeout_seconds": 12,
                },
            },
        )

    assert default_response.status_code == 200
    assert response.status_code == 200
    assert bootstrap["model"] == {
        "server_provider_configured": True,
        "provider_name": "openai",
        "default_model": "server-default-model",
    }
    assert "server-model-secret" not in json.dumps(bootstrap)
    assert len(captured) == 2
    default_provider = captured[0]
    assert default_provider is not None
    assert default_provider.model == "server-default-model"
    assert default_provider.api_key == "server-model-secret"
    provider = captured[1]
    assert provider is not None
    assert provider.name == "openai"
    assert provider.model == "browser-selected-model"
    assert provider.api_key == "server-model-secret"
    assert provider.base_url == "https://models.example.test/v1"
    assert provider.timeout_seconds == 12
