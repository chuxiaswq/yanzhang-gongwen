"""Deployment settings and lightweight ASGI protections for the web app.

The defaults intentionally keep the existing loopback development workflow
working.  Production installations opt into their public host names, reverse
proxy addresses, CORS origins, and single-user bearer token through
``YANZHANG_*`` environment variables.  The original ``GONGWEN_*`` names remain
accepted so existing personal deployments upgrade in place.
"""

# Chinese punctuation is intentional in user-facing configuration errors.
# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import math
import os
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from time import monotonic
from typing import Literal
from urllib.parse import unquote, urlsplit, urlunsplit

from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from gongwen_web.models import ProviderSettings
from yanzhang.providers.registry import get_default_registry

EnvironmentName = Literal["development", "test", "production"]
Clock = Callable[[], float]

_DEFAULT_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "testserver", "[::1]")
_PUBLIC_API_PATHS = frozenset({"/api/health", "/api/ready", "/api/bootstrap", "/api/v2/bootstrap"})
_MIN_BODY_BYTES = 1_024
_MAX_BODY_BYTES = 100 * 1024 * 1024
_ACCESS_LOGGER = logging.getLogger("yanzhang.access")


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Validated process configuration for one Gongwen web instance."""

    environment: EnvironmentName = "development"
    bind_host: str = "127.0.0.1"
    bind_port: int = 8787
    workers: int = 1
    access_log: bool = False
    allowed_hosts: tuple[str, ...] = _DEFAULT_ALLOWED_HOSTS
    cors_origins: tuple[str, ...] = ()
    trusted_proxy_ips: tuple[str, ...] = ()
    access_token: str | None = field(default=None, repr=False)
    mcp_access_token: str | None = field(default=None, repr=False)
    allow_unauthenticated: bool = False
    max_request_bytes: int = 8 * 1024 * 1024
    rate_limit_requests: int = 0
    rate_limit_window_seconds: int = 60
    hsts_seconds: int = 0
    enable_insecure_people_search: bool = False
    allow_insecure_local_model: bool = False
    server_provider: ProviderSettings | None = field(default=None, repr=False)
    client_provider_base_url_allowlist: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("GONGWEN_ENV 应为 development、test 或 production")
        if not self.bind_host.strip():
            raise ValueError("GONGWEN_HOST 需要填写监听地址")
        if self.bind_port < 1 or self.bind_port > 65_535:
            raise ValueError("GONGWEN_PORT 应在 1 到 65535 之间")
        if self.workers < 1 or self.workers > 32:
            raise ValueError("GONGWEN_WORKERS 应在 1 到 32 之间")
        if not self.allowed_hosts or any(not host.strip() for host in self.allowed_hosts):
            raise ValueError("GONGWEN_ALLOWED_HOSTS 至少需要一个主机名")
        if self.access_token is not None and not self.access_token.strip():
            raise ValueError("GONGWEN_ACCESS_TOKEN 不应为空")
        if self.mcp_access_token is not None and not self.mcp_access_token.strip():
            raise ValueError("GONGWEN_MCP_ACCESS_TOKEN 不应为空")
        self.validate_effective_bind_host(self.bind_host)
        if self.max_request_bytes < _MIN_BODY_BYTES or self.max_request_bytes > _MAX_BODY_BYTES:
            raise ValueError("GONGWEN_MAX_REQUEST_BYTES 应在 1024 到 104857600 之间")
        if self.rate_limit_requests < 0:
            raise ValueError("GONGWEN_RATE_LIMIT_REQUESTS 应大于或等于 0")
        if self.rate_limit_window_seconds < 1 or self.rate_limit_window_seconds > 86_400:
            raise ValueError("GONGWEN_RATE_LIMIT_WINDOW_SECONDS 应在 1 到 86400 之间")
        if self.hsts_seconds < 0 or self.hsts_seconds > 63_072_000:
            raise ValueError("GONGWEN_HSTS_SECONDS 应在 0 到 63072000 之间")
        if self.environment == "production":
            if self.access_token is None and not self.allow_unauthenticated:
                raise ValueError(
                    "production 模式需要配置 GONGWEN_ACCESS_TOKEN；"
                    "如需公开服务请显式设置 GONGWEN_ALLOW_UNAUTHENTICATED=true"
                )
            if self.access_token is not None and len(self.access_token.encode("utf-8")) < 32:
                raise ValueError("production 模式的 GONGWEN_ACCESS_TOKEN 至少需要 32 字节")
            if self.access_token is not None and self.access_token.strip().upper().startswith(
                ("CHANGE_ME", "CHANGEME")
            ):
                raise ValueError("production 模式的 GONGWEN_ACCESS_TOKEN 仍是示例占位值")
            if self.mcp_access_token is None:
                raise ValueError("production 模式需要配置 GONGWEN_MCP_ACCESS_TOKEN")
            if len(self.mcp_access_token.encode("utf-8")) < 32:
                raise ValueError("production 模式的 GONGWEN_MCP_ACCESS_TOKEN 至少需要 32 字节")
            if self.mcp_access_token.strip().upper().startswith(("CHANGE_ME", "CHANGEME")):
                raise ValueError("production 模式的 GONGWEN_MCP_ACCESS_TOKEN 仍是示例占位值")
            if self.access_token is not None and hmac.compare_digest(
                self.access_token.encode("utf-8"),
                self.mcp_access_token.encode("utf-8"),
            ):
                raise ValueError(
                    "production 模式的 GONGWEN_MCP_ACCESS_TOKEN 需要与 "
                    "GONGWEN_ACCESS_TOKEN 分开设置"
                )
            if self.workers != 1:
                raise ValueError("个人部署版本使用 SQLite，GONGWEN_WORKERS 请设置为 1")
            if any("*" in host for host in self.allowed_hosts):
                raise ValueError("production 模式的 GONGWEN_ALLOWED_HOSTS 需要精确配置")
            if "*" in self.cors_origins:
                raise ValueError("production 模式的 GONGWEN_CORS_ORIGINS 需要精确配置")
            if "*" in self.trusted_proxy_ips:
                raise ValueError("production 模式的 GONGWEN_TRUSTED_PROXY_IPS 需要精确配置")
        if self.server_provider is not None:
            provider_name = self.server_provider.name.strip().casefold()
            if provider_name not in get_default_registry().list_llm():
                raise ValueError(f"GONGWEN_LLM_PROVIDER 尚未注册：{provider_name}")
            if self.server_provider.base_url is not None:
                _validate_server_provider_base_url(
                    self.server_provider.base_url,
                    environment=self.environment,
                    allow_insecure_local_model=self.allow_insecure_local_model,
                )
        for base_url in self.client_provider_base_url_allowlist:
            _normalize_client_provider_base_url(base_url, setting=True)
        for origin in self.cors_origins:
            _validate_origin(origin)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> RuntimeSettings:
        """Build settings from an explicit mapping or the current environment."""

        raw_values = os.environ if environ is None else environ
        values = _with_yanzhang_aliases(raw_values)
        environment = _environment(values.get("GONGWEN_ENV", "development"))
        rate_default = 120 if environment == "production" else 0
        # Uvicorn's default access line includes the query string, which may
        # contain document searches or article-research terms. Keep it off
        # unless an operator explicitly opts in with a suitable log policy.
        access_log_default = False
        hsts_default = 31_536_000 if environment == "production" else 0
        provider = _server_provider_from_env(values)
        return cls(
            environment=environment,
            bind_host=_text(values, "GONGWEN_HOST", "127.0.0.1"),
            bind_port=_integer(values, "GONGWEN_PORT", 8787),
            workers=_integer(values, "GONGWEN_WORKERS", 1),
            access_log=_boolean(values, "GONGWEN_ACCESS_LOG", access_log_default),
            allowed_hosts=_csv(values.get("GONGWEN_ALLOWED_HOSTS")) or _DEFAULT_ALLOWED_HOSTS,
            cors_origins=_csv(values.get("GONGWEN_CORS_ORIGINS")),
            trusted_proxy_ips=_csv(values.get("GONGWEN_TRUSTED_PROXY_IPS")),
            access_token=_optional_text(values.get("GONGWEN_ACCESS_TOKEN")),
            mcp_access_token=_optional_text(values.get("GONGWEN_MCP_ACCESS_TOKEN")),
            allow_unauthenticated=_boolean(
                values,
                "GONGWEN_ALLOW_UNAUTHENTICATED",
                False,
            ),
            max_request_bytes=_integer(
                values,
                "GONGWEN_MAX_REQUEST_BYTES",
                8 * 1024 * 1024,
            ),
            rate_limit_requests=_integer(
                values,
                "GONGWEN_RATE_LIMIT_REQUESTS",
                rate_default,
            ),
            rate_limit_window_seconds=_integer(
                values,
                "GONGWEN_RATE_LIMIT_WINDOW_SECONDS",
                60,
            ),
            hsts_seconds=_integer(values, "GONGWEN_HSTS_SECONDS", hsts_default),
            enable_insecure_people_search=_explicit_true_flag(
                values,
                "GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH",
            ),
            allow_insecure_local_model=_explicit_true_flag(
                values,
                "GONGWEN_ALLOW_INSECURE_LOCAL_MODEL",
            ),
            server_provider=provider,
            client_provider_base_url_allowlist=_csv(
                values.get("GONGWEN_CLIENT_LLM_BASE_URL_ALLOWLIST")
            ),
        )

    @property
    def access_token_required(self) -> bool:
        """Whether API clients must send the configured bearer token."""

        return self.access_token is not None

    def validate_effective_bind_host(self, host: str) -> None:
        """Fail closed when the effective listener is reachable off-device.

        ``--host`` is applied after environment settings are constructed, so the
        CLI calls this method again with its final override.  A public Web API may
        be an explicit operator choice, but the MCP endpoint always retains its
        independent credential boundary.
        """

        candidate = host.strip()
        if not candidate:
            raise ValueError("GONGWEN_HOST 需要填写监听地址")
        if _is_loopback_host(candidate):
            return
        if self.access_token is None and not self.allow_unauthenticated:
            raise ValueError(
                "非回环监听需要配置 GONGWEN_ACCESS_TOKEN；"
                "公开 Web 服务需显式设置 GONGWEN_ALLOW_UNAUTHENTICATED=true"
            )
        if self.access_token is not None and len(self.access_token.encode("utf-8")) < 32:
            raise ValueError("非回环监听的 GONGWEN_ACCESS_TOKEN 至少需要 32 字节")
        if self.mcp_access_token is None:
            raise ValueError("非回环监听需要配置独立的 GONGWEN_MCP_ACCESS_TOKEN")
        if len(self.mcp_access_token.encode("utf-8")) < 32:
            raise ValueError("非回环监听的 GONGWEN_MCP_ACCESS_TOKEN 至少需要 32 字节")
        if self.access_token is not None and hmac.compare_digest(
            self.access_token.encode("utf-8"),
            self.mcp_access_token.encode("utf-8"),
        ):
            raise ValueError(
                "非回环监听的 GONGWEN_MCP_ACCESS_TOKEN 需要与 GONGWEN_ACCESS_TOKEN 分开设置"
            )

    @property
    def server_provider_configured(self) -> bool:
        """Whether a server-owned model credential is ready for live calls."""

        return self.server_provider is not None and bool(self.server_provider.api_key)

    def resolve_provider(self, client: ProviderSettings | None) -> ProviderSettings | None:
        """Merge browser settings with the server-owned provider configuration.

        A browser-supplied credential keeps the legacy fully explicit behavior.
        Otherwise the provider name, credential, and endpoint remain a single
        server-owned trust boundary; clients may choose a model and harmless
        generation options without redirecting the server credential.
        """

        server = self.server_provider
        if server is None:
            return self._validate_client_provider(client)
        if client is None:
            return server.model_copy(deep=True)
        if client.api_key:
            return self._validate_client_provider(client)
        return ProviderSettings(
            name=server.name,
            model=client.model or server.model,
            api_key=server.api_key,
            base_url=server.base_url,
            timeout_seconds=client.timeout_seconds or server.timeout_seconds,
            options=dict(server.options),
        )

    def _validate_client_provider(self, client: ProviderSettings | None) -> ProviderSettings | None:
        """Apply production-only egress rules to browser-owned model settings."""

        if client is None or self.environment != "production":
            return client
        endpoint = client.options.get("endpoint")
        if endpoint is not None and _is_unsafe_client_provider_endpoint(endpoint):
            raise ValueError("production 模式的页面模型 endpoint 只能填写相对路径")
        if client.base_url is None:
            return client
        normalized = _normalize_client_provider_base_url(client.base_url, setting=False)
        allowed = {
            _normalize_client_provider_base_url(value, setting=True)
            for value in self.client_provider_base_url_allowlist
        }
        if normalized not in allowed:
            raise ValueError(
                "production 模式的页面自定义模型地址未列入 GONGWEN_CLIENT_LLM_BASE_URL_ALLOWLIST"
            )
        return client.model_copy(update={"base_url": normalized}, deep=True)

    def public_model_configuration(self) -> dict[str, object]:
        """Return the non-secret server model fields suitable for bootstrap."""

        provider = self.server_provider
        return {
            "server_provider_configured": self.server_provider_configured,
            "provider_name": provider.name if provider is not None else None,
            "default_model": provider.model if provider is not None else None,
        }


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Outcome of one in-memory sliding-window rate-limit check."""

    allowed: bool
    remaining: int
    retry_after_seconds: int


class InMemoryRateLimiter:
    """Small per-client sliding-window limiter for a single application process."""

    def __init__(self, requests: int, window_seconds: int, *, clock: Clock = monotonic) -> None:
        if requests < 1:
            raise ValueError("requests 应大于 0")
        if window_seconds < 1:
            raise ValueError("window_seconds 应大于 0")
        self.requests = requests
        self.window_seconds = window_seconds
        self._clock = clock
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._checks = 0

    def check(self, key: str) -> RateLimitDecision:
        """Consume one request when capacity remains and return its status."""

        now = self._clock()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.requests:
                retry_after = max(1, math.ceil(bucket[0] + self.window_seconds - now))
                decision = RateLimitDecision(False, 0, retry_after)
            else:
                bucket.append(now)
                decision = RateLimitDecision(True, self.requests - len(bucket), 0)
            self._checks += 1
            if self._checks % 1_024 == 0:
                self._prune(cutoff)
            return decision

    def _prune(self, cutoff: float) -> None:
        stale = [key for key, bucket in self._buckets.items() if not bucket or bucket[-1] <= cutoff]
        for key in stale:
            self._buckets.pop(key, None)


class SecurityHeadersMiddleware:
    """Apply browser hardening headers consistently to every HTTP response."""

    def __init__(self, app: ASGIApp, *, hsts_seconds: int = 0) -> None:
        self.app = app
        self.hsts_seconds = hsts_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                _set_header(headers, b"x-content-type-options", b"nosniff")
                _set_header(headers, b"x-frame-options", b"DENY")
                _set_header(headers, b"referrer-policy", b"no-referrer")
                _set_header(
                    headers,
                    b"permissions-policy",
                    b"camera=(), microphone=(), geolocation=(), payment=()",
                )
                _set_header(headers, b"cross-origin-opener-policy", b"same-origin")
                _set_header(headers, b"cross-origin-resource-policy", b"same-origin")
                _set_header(
                    headers,
                    b"content-security-policy",
                    (
                        b"default-src 'self'; img-src 'self' data:; "
                        b"style-src 'self' 'unsafe-inline'; script-src 'self'; "
                        b"connect-src 'self'; font-src 'self' data:; object-src 'none'; "
                        b"base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
                    ),
                )
                if self.hsts_seconds and scope.get("scheme") == "https":
                    _set_header(
                        headers,
                        b"strict-transport-security",
                        f"max-age={self.hsts_seconds}".encode("ascii"),
                    )
                path = str(scope.get("path", ""))
                if path.startswith("/api/") or _is_mcp_path(path):
                    _set_header(headers, b"cache-control", b"no-store")
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RedactedAccessLogMiddleware:
    """Log route paths without query strings, bodies, headers, or client identifiers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = monotonic()
        status_code = 500

        async def tracked_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        finally:
            _ACCESS_LOGGER.info(
                "%s %s %d %.3fs",
                str(scope.get("method", "-")),
                str(scope.get("path", "/")),
                status_code,
                monotonic() - started,
            )


class RequestBodyLimitMiddleware:
    """Reject declared or streamed HTTP request bodies above a byte limit."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _content_length(scope)
        if declared is None:
            await _json_error(
                "invalid_content_length",
                "Content-Length 格式有误",
                400,
            )(scope, receive, send)
            return
        if declared > self.max_bytes:
            await _body_too_large(self.max_bytes)(scope, receive, send)
            return

        consumed = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_bytes:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await _body_too_large(self.max_bytes)(scope, receive, send)


class BearerTokenMiddleware:
    """Protect one route family with a fixed-length bearer-token digest."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        token: str,
        route_family: Literal["api", "mcp"] = "api",
    ) -> None:
        self.app = app
        self._token_digest = hashlib.sha256(token.encode("utf-8")).digest()
        self._route_family = route_family

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        protected = (
            _protected_api_request(scope)
            if self._route_family == "api"
            else _protected_mcp_request(scope)
        )
        if not protected:
            await self.app(scope, receive, send)
            return
        supplied = _bearer_token(scope)
        supplied_digest = hashlib.sha256(supplied.encode("utf-8")).digest()
        if hmac.compare_digest(self._token_digest, supplied_digest):
            await self.app(scope, receive, send)
            return
        response = _json_error(
            "authentication_required",
            "访问令牌缺失或不正确",
            401,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)


class RateLimitMiddleware:
    """Apply a bounded in-memory request rate per effective client address."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: InMemoryRateLimiter,
    ) -> None:
        self.app = app
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not _rate_limited_request(scope):
            await self.app(scope, receive, send)
            return
        decision = self.limiter.check(_client_key(scope))
        if decision.allowed:
            await self.app(scope, receive, send)
            return
        response = _json_error(
            "rate_limit_exceeded",
            "请求较为频繁，请稍后再试",
            429,
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )
        await response(scope, receive, send)


def runtime_middleware(
    settings: RuntimeSettings,
    *,
    rate_limiter: InMemoryRateLimiter | None = None,
) -> list[Middleware]:
    """Build middleware in outer-to-inner execution order."""

    middleware: list[Middleware] = []
    if settings.trusted_proxy_ips:
        middleware.append(
            Middleware(
                ProxyHeadersMiddleware,
                trusted_hosts=list(settings.trusted_proxy_ips),
            )
        )
    if settings.access_log:
        middleware.append(Middleware(RedactedAccessLogMiddleware))
    middleware.append(Middleware(SecurityHeadersMiddleware, hsts_seconds=settings.hsts_seconds))
    middleware.append(
        Middleware(
            TrustedHostMiddleware,
            allowed_hosts=list(settings.allowed_hosts),
            www_redirect=False,
        )
    )
    if settings.cors_origins:
        middleware.append(
            Middleware(
                CORSMiddleware,
                allow_origins=list(settings.cors_origins),
                allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                allow_headers=[
                    "Authorization",
                    "Content-Type",
                    "Accept",
                    "Mcp-Session-Id",
                    "MCP-Protocol-Version",
                    "Last-Event-ID",
                ],
                allow_credentials=False,
                expose_headers=["Content-Disposition", "Retry-After", "Mcp-Session-Id"],
                max_age=600,
            )
        )
    middleware.append(Middleware(RequestBodyLimitMiddleware, max_bytes=settings.max_request_bytes))
    if settings.rate_limit_requests:
        limiter = rate_limiter or InMemoryRateLimiter(
            settings.rate_limit_requests,
            settings.rate_limit_window_seconds,
        )
        middleware.append(Middleware(RateLimitMiddleware, limiter=limiter))
    if settings.access_token is not None:
        middleware.append(Middleware(BearerTokenMiddleware, token=settings.access_token))
    if settings.mcp_access_token is not None:
        middleware.append(
            Middleware(
                BearerTokenMiddleware,
                token=settings.mcp_access_token,
                route_family="mcp",
            )
        )
    return middleware


class _RequestBodyTooLarge(Exception):
    pass


def _body_too_large(max_bytes: int) -> JSONResponse:
    return _json_error(
        "request_too_large",
        f"请求内容超过 {max_bytes} 字节上限",
        413,
    )


def _json_error(
    code: str,
    message: str,
    status_code: int,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    response_headers = {"Cache-Control": "no-store", **dict(headers or {})}
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status_code,
        headers=response_headers,
    )


def _set_header(headers: list[tuple[bytes, bytes]], name: bytes, value: bytes) -> None:
    headers[:] = [(key, item) for key, item in headers if key.lower() != name]
    headers.append((name, value))


def _content_length(scope: Scope) -> int | None:
    values = [value for name, value in scope.get("headers", []) if name == b"content-length"]
    if not values:
        return 0
    if len(values) != 1:
        return None
    try:
        parsed = int(values[0].decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _protected_api_request(scope: Scope) -> bool:
    if scope["type"] != "http" or scope.get("method") == "OPTIONS":
        return False
    path = str(scope.get("path", ""))
    return path.startswith("/api/") and path not in _PUBLIC_API_PATHS


def _protected_mcp_request(scope: Scope) -> bool:
    if scope["type"] != "http" or scope.get("method") == "OPTIONS":
        return False
    return _is_mcp_path(str(scope.get("path", "")))


def _rate_limited_request(scope: Scope) -> bool:
    if scope["type"] != "http" or scope.get("method") == "OPTIONS":
        return False
    path = str(scope.get("path", ""))
    return (path.startswith("/api/") and path not in _PUBLIC_API_PATHS) or _is_mcp_path(path)


def _is_mcp_path(path: str) -> bool:
    return path == "/mcp" or path.startswith("/mcp/")


def _bearer_token(scope: Scope) -> str:
    values = [value for name, value in scope.get("headers", []) if name == b"authorization"]
    if len(values) != 1:
        return ""
    try:
        authorization: str = values[0].decode("latin1")
    except UnicodeDecodeError:
        return ""
    scheme, separator, credential = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer":
        return ""
    return credential.strip()


def _client_key(scope: Scope) -> str:
    client = scope.get("client")
    if client is None:
        return "unknown"
    return str(client[0])


def _environment(value: str) -> EnvironmentName:
    normalized = value.strip().casefold()
    aliases: dict[str, EnvironmentName] = {
        "dev": "development",
        "development": "development",
        "test": "test",
        "prod": "production",
        "production": "production",
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError("GONGWEN_ENV 应为 development、test 或 production") from exc


def _text(values: Mapping[str, str], name: str, default: str) -> str:
    return values.get(name, default).strip() or default


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _csv(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))


def _integer(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 应为整数") from exc


def _boolean(values: Mapping[str, str], name: str, default: bool) -> bool:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} 应为 true 或 false")


def _explicit_true_flag(values: Mapping[str, str], name: str) -> bool:
    """Enable a high-disclosure feature only for the literal value ``true``."""

    raw = values.get(name)
    if raw is None or not raw.strip() or raw.strip().casefold() == "false":
        return False
    if raw.strip().casefold() == "true":
        return True
    raise ValueError(f"{name} 应为 true 或 false")


def _validate_origin(origin: str) -> None:
    if origin == "*":
        return
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("GONGWEN_CORS_ORIGINS 仅接受完整的 http/https Origin")
    if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("GONGWEN_CORS_ORIGINS 应填写不含路径、参数或用户信息的 Origin")


def _is_loopback_host(host: str) -> bool:
    candidate = host.strip()
    if candidate.casefold().rstrip(".") == "localhost":
        return True
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    if "%" in candidate:
        return False
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def _normalize_client_provider_base_url(value: str, *, setting: bool) -> str:
    """Return the exact-comparison form for a browser-owned HTTPS base URL."""

    label = (
        "GONGWEN_CLIENT_LLM_BASE_URL_ALLOWLIST"
        if setting
        else ("production 模式的页面自定义模型地址（请配置 GONGWEN_CLIENT_LLM_BASE_URL_ALLOWLIST）")
    )
    candidate = value.strip()
    if not candidate or any(ord(character) < 32 for character in candidate):
        raise ValueError(f"{label} 含有无效地址")
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} 含有无效地址") from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{label} 仅接受不含参数或用户信息的 HTTPS 基础地址")
    path_segments = tuple(segment for segment in parsed.path.split("/") if segment)
    if any(segment in {".", ".."} for segment in path_segments):
        raise ValueError(f"{label} 不应包含相对路径段")
    hostname = parsed.hostname.casefold().rstrip(".")
    host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = host if port in {None, 443} else f"{host}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit(("https", netloc, path, "", ""))


def _validate_server_provider_base_url(
    value: str,
    *,
    environment: EnvironmentName,
    allow_insecure_local_model: bool,
) -> None:
    """Validate the operator-owned model endpoint without weakening local development."""

    label = "GONGWEN_LLM_BASE_URL"
    candidate = value.strip()
    if not candidate or any(ord(character) < 32 for character in candidate):
        raise ValueError(f"{label} 含有无效地址")
    try:
        parsed = urlsplit(candidate)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} 含有无效地址") from exc
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{label} 应为不含参数或用户信息的完整 HTTP(S) 基础地址")
    if environment != "production" or parsed.scheme.casefold() == "https":
        return
    if allow_insecure_local_model and _is_loopback_host(parsed.hostname):
        return
    raise ValueError(
        f"production 模式的 {label} 需要使用 HTTPS；"
        "仅回环本地模型可显式设置 GONGWEN_ALLOW_INSECURE_LOCAL_MODEL=true"
    )


def _is_unsafe_client_provider_endpoint(value: object) -> bool:
    """Detect endpoint overrides that can leave an approved base URL or path."""

    if not isinstance(value, str):
        return True
    candidate = value.strip()
    if not candidate:
        return False
    if any(ord(character) < 32 for character in candidate) or "\\" in candidate:
        return True
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return True
    decoded_segments = tuple(
        unquote(segment).casefold() for segment in parsed.path.split("/") if segment
    )
    return bool(
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or candidate.startswith("//")
        or any(segment in {".", ".."} for segment in decoded_segments)
    )


def _server_provider_from_env(values: Mapping[str, str]) -> ProviderSettings | None:
    api_key = _optional_text(values.get("GONGWEN_LLM_API_KEY"))
    model = _optional_text(values.get("GONGWEN_LLM_MODEL"))
    base_url = _optional_text(values.get("GONGWEN_LLM_BASE_URL"))
    provider_name = _optional_text(values.get("GONGWEN_LLM_PROVIDER"))
    timeout_raw = _optional_text(values.get("GONGWEN_LLM_TIMEOUT_SECONDS"))
    if not any((api_key, model, base_url, provider_name, timeout_raw)):
        return None
    timeout: float | None = None
    if timeout_raw is not None:
        try:
            timeout = float(timeout_raw)
        except ValueError as exc:
            raise ValueError("GONGWEN_LLM_TIMEOUT_SECONDS 应为数字") from exc
    normalized_name = (provider_name or "openai").casefold()
    compatibility_aliases = {"deepseek": "openai", "qwen": "openai", "custom": "openai"}
    if normalized_name in compatibility_aliases and base_url is None:
        raise ValueError(f"GONGWEN_LLM_PROVIDER={normalized_name} 时需要配置 GONGWEN_LLM_BASE_URL")
    return ProviderSettings(
        name=compatibility_aliases.get(normalized_name, normalized_name),
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout,
    )


def _with_yanzhang_aliases(values: Mapping[str, str]) -> Mapping[str, str]:
    """Map new product-wide names to legacy settings with new-name precedence.

    Keeping one normalized mapping lets validation and operational diagnostics
    retain their established field names while every deployment knob gains the
    broader ``YANZHANG_*`` spelling.
    """

    resolved = dict(values)
    for name, value in values.items():
        if name.startswith("YANZHANG_"):
            resolved[f"GONGWEN_{name.removeprefix('YANZHANG_')}"] = value
    return resolved


__all__ = [
    "BearerTokenMiddleware",
    "InMemoryRateLimiter",
    "RateLimitDecision",
    "RateLimitMiddleware",
    "RedactedAccessLogMiddleware",
    "RequestBodyLimitMiddleware",
    "RuntimeSettings",
    "SecurityHeadersMiddleware",
    "runtime_middleware",
]
