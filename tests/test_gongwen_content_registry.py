"""Composition-root coverage for registry-backed Gongwen content adapters."""

# Chinese fixture punctuation is intentional.
# ruff: noqa: RUF001

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from gongwen_mcp.tools import build_context
from gongwen_web.app import create_app
from gongwen_web.collection import ArticleCollectionScope
from gongwen_web.runtime import RuntimeSettings
from gongwen_web.storage import GongwenStorage
from yanzhang.providers.content import (
    ArticleDiscoveryQuery,
    DiscoveredArticle,
    HTTPFetchedPage,
)
from yanzhang.providers.registry import ProviderRegistry

_URL = "https://www.people.com.cn/n1/2026/0904/registry.html"


class _DiscoveryFixture:
    def __init__(self, items: Sequence[DiscoveredArticle] = ()) -> None:
        self.items = tuple(items)
        self.queries: list[ArticleDiscoveryQuery] = []

    async def discover(
        self,
        query: ArticleDiscoveryQuery,
    ) -> Sequence[DiscoveredArticle]:
        self.queries.append(query)
        return self.items


class _FetcherFixture:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def fetch(self, url: str) -> HTTPFetchedPage:
        self.urls.append(url)
        return HTTPFetchedPage(
            url=url,
            body=(
                "<html><head><meta property='og:title' content='以实干树牢正确政绩观'>"
                "</head><body><article><p>树牢正确政绩观，要坚持为民导向。</p>"
                "<p>各项工作都要经得起实践和群众检验。</p></article></body></html>"
            ).encode(),
        )


def _content_registry(
    discovery: _DiscoveryFixture,
    fetcher: _FetcherFixture,
) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register_article_discovery("official_search", lambda **_: discovery)
    registry.register_article_fetcher("official_http", lambda: fetcher)
    return registry


@pytest.mark.asyncio
async def test_web_app_resolves_default_discovery_through_injected_registry(
    tmp_path: Path,
) -> None:
    discovery = _DiscoveryFixture()
    fetcher = _FetcherFixture()
    registry = _content_registry(discovery, fetcher)
    application = create_app(
        storage=GongwenStorage(tmp_path / "documents.sqlite3"),
        settings=RuntimeSettings(environment="test"),
        provider_registry=registry,
    )
    try:
        record = await application.state.article_library.import_url(_URL, source_id="people")
        result = await application.state.article_collection.collect(
            ArticleCollectionScope.create(
                keywords=["政绩观"],
                source_ids=["people"],
            )
        )
    finally:
        application.state.gongwen_mcp_context.close()

    assert result.discovered_count == 0
    assert record.import_method == "url"
    assert fetcher.urls == [_URL]
    assert len(discovery.queries) == 1


@pytest.mark.asyncio
async def test_mcp_context_resolves_both_content_adapters_through_registry(
    tmp_path: Path,
) -> None:
    discovery = _DiscoveryFixture()
    fetcher = _FetcherFixture()
    context = build_context(
        settings=RuntimeSettings(environment="test"),
        data_dir=tmp_path,
        provider_registry=_content_registry(discovery, fetcher),
    )
    try:
        record = await context.article_library.import_url(_URL, source_id="people")
    finally:
        context.close()

    assert record.import_method == "url"
    assert fetcher.urls == [_URL]


@pytest.mark.asyncio
async def test_web_app_preserves_explicit_content_adapter_injection(tmp_path: Path) -> None:
    discovery = _DiscoveryFixture()
    fetcher = _FetcherFixture()
    application = create_app(
        storage=GongwenStorage(tmp_path / "explicit-web.sqlite3"),
        settings=RuntimeSettings(environment="test"),
        article_discovery=discovery,
        article_fetcher=fetcher,
        provider_registry=ProviderRegistry(),
    )
    try:
        record = await application.state.article_library.import_url(_URL, source_id="people")
    finally:
        application.state.gongwen_mcp_context.close()

    assert record.import_method == "url"
    assert fetcher.urls == [_URL]


@pytest.mark.asyncio
async def test_mcp_context_preserves_explicit_content_adapter_injection(tmp_path: Path) -> None:
    discovery = _DiscoveryFixture()
    fetcher = _FetcherFixture()
    context = build_context(
        settings=RuntimeSettings(environment="test"),
        data_dir=tmp_path,
        article_discovery=discovery,
        article_fetcher=fetcher,
        provider_registry=ProviderRegistry(),
    )
    try:
        result = await context.article_collection.collect(
            ArticleCollectionScope.create(
                keywords=["政绩观"],
                source_ids=["people"],
            )
        )
    finally:
        context.close()

    assert result.discovered_count == 0
    assert len(discovery.queries) == 1
