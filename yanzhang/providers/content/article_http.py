"""Bounded HTTP adapter for explicitly requested official-article imports."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx


class SourceDomains(Protocol):
    """Minimal source policy consumed by the HTTP adapter."""

    @property
    def domains(self) -> tuple[str, ...]:
        """Return exact registrable domains accepted for this source."""


class HostResolver(Protocol):
    """DNS boundary used before opening an HTTP connection."""

    async def resolve(self, hostname: str) -> Sequence[str]:
        """Return all resolved numeric addresses for one hostname."""


class SystemHostResolver:
    """Asynchronous system resolver used by live article imports."""

    async def resolve(self, hostname: str) -> Sequence[str]:
        loop = asyncio.get_running_loop()
        results = await loop.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        addresses: list[str] = []
        for result in results:
            sockaddr = result[4]
            if sockaddr and isinstance(sockaddr[0], str) and sockaddr[0] not in addresses:
                addresses.append(sockaddr[0])
        return addresses


@dataclass(frozen=True, slots=True)
class HTTPFetchedPage:
    """Bounded response consumed structurally by the article library."""

    url: str
    body: bytes
    content_type: str = "text/html; charset=utf-8"
    status_code: int = 200


@runtime_checkable
class ArticleFetcherProvider(Protocol):
    """Structural contract for bounded article acquisition adapters."""

    async def fetch(self, url: str) -> HTTPFetchedPage:
        """Fetch one validated article URL without leaking transport details."""


class HTTPArticleFetcher:
    """HTTPS adapter with domain, redirect, DNS, timeout and size controls."""

    _DEFAULT_DOMAINS = ("people.com.cn", "people.cn", "gmw.cn", "qstheory.cn")

    def __init__(
        self,
        *,
        sources: Mapping[str, SourceDomains] | None = None,
        timeout_seconds: float = 12.0,
        max_bytes: int = 2 * 1024 * 1024,
        max_redirects: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: HostResolver | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise ValueError("timeout_seconds 必须在 0 到 60 秒之间")
        if max_bytes < 1024 or max_bytes > 10 * 1024 * 1024:
            raise ValueError("max_bytes 必须在 1 KB 到 10 MB 之间")
        if max_redirects < 0 or max_redirects > 5:
            raise ValueError("max_redirects 必须在 0 到 5 之间")
        domains: tuple[str, ...]
        if sources is None:
            domains = self._DEFAULT_DOMAINS
        else:
            domains = tuple(domain for source in sources.values() for domain in source.domains)
        self._domains = tuple(domain.lower().rstrip(".") for domain in domains)
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._transport = transport
        self._resolver = resolver or SystemHostResolver()

    async def fetch(self, url: str) -> HTTPFetchedPage:
        """Fetch one official HTTPS page after a caller explicitly requests it."""

        current_url = self._validate_url(url)
        timeout = httpx.Timeout(self._timeout_seconds)
        headers = {
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "YanzhangLocalArticleImporter/1.0",
        }
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            transport=self._transport,
            headers=headers,
            trust_env=False,
        ) as client:
            for redirect_count in range(self._max_redirects + 1):
                try:
                    await self._validate_destination(current_url)
                    async with client.stream("GET", current_url) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location or redirect_count >= self._max_redirects:
                                raise ValueError("文章来源页面跳转次数过多或缺少跳转地址")
                            current_url = self._validate_url(urljoin(current_url, location))
                            continue
                        if response.status_code < 200 or response.status_code >= 300:
                            raise ValueError(f"文章来源页面返回状态码 {response.status_code}")
                        content_type = response.headers.get("content-type", "")
                        if not _is_html_content_type(content_type):
                            raise ValueError("文章来源地址返回的不是 HTML 页面")
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > self._max_bytes:
                                raise ValueError("文章来源页面超过允许的大小")
                            chunks.append(chunk)
                        return HTTPFetchedPage(
                            url=str(response.url),
                            body=b"".join(chunks),
                            content_type=content_type,
                            status_code=response.status_code,
                        )
                except ValueError:
                    raise
                except httpx.TimeoutException as exc:
                    raise ValueError("文章来源页面获取超时") from exc
                except httpx.HTTPError as exc:
                    raise ValueError("文章来源页面连接失败") from exc
        raise ValueError("文章来源页面跳转次数过多")

    def _validate_url(self, url: str) -> str:
        value = " ".join(url.split())
        try:
            parts = urlsplit(value)
            port = parts.port
        except ValueError as exc:
            raise ValueError("文章来源地址格式无效") from exc
        if parts.scheme.lower() != "https":
            raise ValueError("联网导入文章来源时必须使用 HTTPS")
        if not parts.hostname or parts.username or parts.password:
            raise ValueError("文章来源地址格式无效")
        hostname = parts.hostname.lower().rstrip(".")
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise ValueError("文章来源地址必须使用已登记的域名")
        if port is not None and port != 443:
            raise ValueError("文章来源地址使用了与协议不匹配的端口")
        if not any(
            hostname == domain or hostname.endswith(f".{domain}") for domain in self._domains
        ):
            raise ValueError("文章来源地址不属于已登记的官方来源")
        return urlunsplit(("https", hostname, parts.path or "/", parts.query, ""))

    async def _validate_destination(self, url: str) -> None:
        hostname = urlsplit(url).hostname
        if not hostname:
            raise ValueError("文章来源地址格式无效")
        try:
            addresses = await asyncio.wait_for(
                self._resolver.resolve(hostname), timeout=min(self._timeout_seconds, 5.0)
            )
        except TimeoutError as exc:
            raise ValueError("文章来源域名解析超时") from exc
        except OSError as exc:
            raise ValueError("文章来源域名解析失败") from exc
        if not addresses:
            raise ValueError("文章来源域名没有可用地址")
        for address in addresses:
            try:
                resolved = ipaddress.ip_address(address.split("%", 1)[0])
            except ValueError as exc:
                raise ValueError("文章来源域名返回了无效地址") from exc
            if not resolved.is_global:
                raise ValueError("文章来源域名解析到了非公网地址")


def _is_html_content_type(value: str) -> bool:
    media_type = value.lower().split(";", 1)[0].strip()
    return media_type in {"text/html", "application/xhtml+xml"}


__all__ = [
    "ArticleFetcherProvider",
    "HTTPArticleFetcher",
    "HTTPFetchedPage",
    "HostResolver",
    "SourceDomains",
    "SystemHostResolver",
]
