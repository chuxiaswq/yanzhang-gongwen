"""Offline contract and API tests for scoped reference-article collection."""

# Chinese article fixtures intentionally use full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from gongwen_web.app import create_app
from gongwen_web.articles import (
    ArticleFetchError,
    ArticleLibrary,
    ArticleRecord,
    FetchedArticlePage,
    FetchedPage,
    SQLiteArticleRepository,
)
from gongwen_web.collection import ArticleCollectionScope, ArticleCollectionService
from gongwen_web.storage import GongwenStorage
from yanzhang.providers.content import ArticleDiscoveryQuery, DiscoveredArticle


class _FakeDiscovery:
    def __init__(self, items: Sequence[DiscoveredArticle]) -> None:
        self.items = tuple(items)
        self.queries: list[ArticleDiscoveryQuery] = []

    async def discover(
        self,
        query: ArticleDiscoveryQuery,
    ) -> Sequence[DiscoveredArticle]:
        self.queries.append(query)
        return self.items


class _ExplodingDiscovery:
    async def discover(self, query: ArticleDiscoveryQuery) -> Sequence[DiscoveredArticle]:
        del query
        raise RuntimeError(
            "provider failed api_key=fixture-private-value "
            "Bearer fixture-bearer-value /home/fixture/private/source.txt "
            "https://private.example.test/internal"
        )


class _FakeFetcher:
    def __init__(self, pages: dict[str, FetchedPage | ArticleFetchError]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    async def fetch(self, url: str) -> FetchedPage:
        self.calls.append(url)
        result = self.pages[url]
        if isinstance(result, ArticleFetchError):
            raise result
        return result


class _TimedFetcher:
    def __init__(
        self,
        pages: dict[str, FetchedPage | Exception],
        delays: dict[str, float],
    ) -> None:
        self.pages = pages
        self.delays = delays
        self.calls: list[str] = []
        self.completed: list[str] = []
        self.cancelled: list[str] = []
        self.active = 0
        self.max_active = 0

    async def fetch(self, url: str) -> FetchedPage:
        self.calls.append(url)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delays[url])
            result = self.pages[url]
            if isinstance(result, Exception):
                raise result
            self.completed.append(url)
            return result
        except asyncio.CancelledError:
            self.cancelled.append(url)
            raise
        finally:
            self.active -= 1


class _SlowPrepareLibrary(ArticleLibrary):
    def __init__(
        self,
        repository: SQLiteArticleRepository,
        *,
        fetcher: _FakeFetcher,
    ) -> None:
        super().__init__(repository, fetcher=fetcher)
        self.prepare_started = threading.Event()
        self.prepare_finished = threading.Event()

    def prepare_url_import(self, acquired: FetchedArticlePage) -> ArticleRecord:
        self.prepare_started.set()
        try:
            time.sleep(0.08)
            return super().prepare_url_import(acquired)
        finally:
            self.prepare_finished.set()


def _page(url: str, title: str, content: str, published_date: str = "2026-09-02") -> FetchedPage:
    paragraphs = "".join(f"<p>{paragraph}</p>" for paragraph in content.split("\n\n"))
    return FetchedPage(
        url=url,
        body=(
            "<html><head>"
            f"<meta property='og:title' content='{title}'>"
            f"<meta name='publishdate' content='{published_date}'>"
            "</head><body><article>"
            f"{paragraphs}"
            "</article></body></html>"
        ).encode(),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("discovery_timeout_seconds", float("nan")),
        ("discovery_timeout_seconds", float("inf")),
        ("discovery_timeout_seconds", 61.0),
        ("item_timeout_seconds", float("nan")),
        ("item_timeout_seconds", float("inf")),
        ("item_timeout_seconds", 121.0),
        ("batch_timeout_seconds", float("nan")),
        ("batch_timeout_seconds", float("inf")),
        ("batch_timeout_seconds", 601.0),
    ],
)
def test_collection_rejects_non_finite_and_excessive_timeouts(
    tmp_path: Path,
    field: str,
    value: float,
) -> None:
    with SQLiteArticleRepository(tmp_path / "timeout-validation.sqlite3") as repository:
        library = ArticleLibrary(repository, fetcher=_FakeFetcher({}))
        with pytest.raises(ValueError, match="有限数值"):
            ArticleCollectionService(
                library,
                _FakeDiscovery(()),
                **{field: value},
            )


@pytest.mark.asyncio
async def test_collection_redacts_untrusted_provider_error_details(tmp_path: Path) -> None:
    with SQLiteArticleRepository(tmp_path / "redaction.sqlite3") as repository:
        service = ArticleCollectionService(
            ArticleLibrary(repository, fetcher=_FakeFetcher({})),
            _ExplodingDiscovery(),
        )
        result = await service.collect(
            ArticleCollectionScope.create(
                keywords=["政绩观"],
                source_ids=["people"],
            )
        )

    response_text = result.source_errors[0].message
    assert "fixture-private-value" not in response_text
    assert "fixture-bearer-value" not in response_text
    assert "/home/fixture" not in response_text
    assert "private.example.test" not in response_text
    assert "[REDACTED]" in response_text
    assert "[PATH]" in response_text
    assert "[URL]" in response_text


@pytest.mark.asyncio
async def test_collection_filters_deduplicates_and_reports_every_candidate(
    tmp_path: Path,
) -> None:
    existing_url = "https://www.people.com.cn/existing.html"
    valid_url = "https://news.gmw.cn/2026-09/02/valid.htm"
    content_duplicate_url = "https://www.people.com.cn/duplicate-content.html"
    keyword_miss_url = "https://www.people.com.cn/keyword-miss.html"
    failed_url = "https://www.people.com.cn/fetch-failed.html"
    existing_content = "改革创新是推动高质量发展的重要动力。\n\n要完善工作机制，强化协同联动。"
    fetcher = _FakeFetcher(
        {
            valid_url: _page(
                valid_url,
                "以数字治理提升服务效能",
                "数字治理需要夯实数据基础。\n\n要以群众需求为导向，持续优化服务流程。",
            ),
            content_duplicate_url: _page(
                content_duplicate_url,
                "改革创新释放发展活力",
                existing_content,
            ),
            keyword_miss_url: _page(
                keyword_miss_url,
                "文化活动工作简报",
                "本次活动组织有序。\n\n各项现场服务保障工作顺利完成。",
            ),
            failed_url: ArticleFetchError("模拟页面获取失败"),
        }
    )
    candidates = (
        DiscoveredArticle(
            url=f"{existing_url}#fragment",
            source_id="people",
            title="已入库文章",
            published_date=date(2026, 9, 2),
        ),
        DiscoveredArticle(
            url=valid_url,
            source_id="gmw",
            title="以数字治理提升服务效能",
            published_date=date(2026, 9, 2),
        ),
        DiscoveredArticle(
            url=content_duplicate_url,
            source_id="people",
            title="改革创新释放发展活力",
            published_date=date(2026, 9, 2),
        ),
        DiscoveredArticle(
            url="https://www.people.com.cn/old.html",
            source_id="people",
            title="日期范围外文章",
            published_date=date(2026, 8, 31),
        ),
        DiscoveredArticle(
            url="https://www.qstheory.cn/dukan/out-of-source.htm",
            source_id="qiushi",
            title="来源范围外文章",
            published_date=date(2026, 9, 2),
        ),
        DiscoveredArticle(
            url=keyword_miss_url,
            source_id="people",
            title="文化活动工作简报",
            published_date=date(2026, 9, 2),
        ),
        DiscoveredArticle(
            url=failed_url,
            source_id="people",
            title="获取失败文章",
            published_date=date(2026, 9, 2),
        ),
        DiscoveredArticle(
            url="https://example.com/not-official.html",
            source_id="people",
            title="越界地址",
            published_date=date(2026, 9, 2),
        ),
    )
    discovery = _FakeDiscovery(candidates)

    with SQLiteArticleRepository(tmp_path / "collection.sqlite3") as repository:
        library = ArticleLibrary(repository, fetcher=fetcher)
        existing = library.import_text(
            title="以改革创新推动高质量发展",
            content=existing_content,
            source_id="people",
            url=existing_url,
            published_date="2026-09-02",
        )
        service = ArticleCollectionService(library, discovery)
        scope = ArticleCollectionScope.create(
            keywords=["数字治理", "改革"],
            source_ids=["people", "gmw"],
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 3),
            limit=10,
        )

        result = await service.collect(scope)

        assert discovery.queries == [
            ArticleDiscoveryQuery(
                keywords=("数字治理", "改革"),
                source_ids=("people", "gmw"),
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 3),
                limit=10,
            )
        ]
        assert result.discovered_count == 8
        assert result.imported_count == 1
        assert result.duplicate_count == 2
        assert result.skipped_count == 3
        assert result.failed_count == 2
        assert [item.reason_code for item in result.items] == [
            "duplicate_url",
            "imported",
            "duplicate_content",
            "date_out_of_scope",
            "source_out_of_scope",
            "keyword_out_of_scope",
            "import_failed",
            "invalid_url",
        ]
        assert result.items[0].article_id == existing.id
        assert result.items[2].article_id == existing.id
        assert result.items[6].message == "模拟页面获取失败"
        assert fetcher.calls == [
            valid_url,
            content_duplicate_url,
            keyword_miss_url,
            failed_url,
        ]
        stored = library.list_articles(limit=20)
        assert len(stored) == 2
        assert {item.title for item in stored} == {
            "以改革创新推动高质量发展",
            "以数字治理提升服务效能",
        }
        assert result.to_dict()["start_date"] == "2026-09-01"


def test_auto_collection_api_is_strict_bounded_and_uses_injected_fakes(
    tmp_path: Path,
) -> None:
    url = "https://news.gmw.cn/2026-09/03/content_123.htm"
    discovery = _FakeDiscovery(
        (
            DiscoveredArticle(
                url=url,
                source_id="gmw",
                title="数字治理要在协同上下功夫",
                published_date=date(2026, 9, 3),
            ),
            DiscoveredArticle(
                url="https://news.gmw.cn/2026-09/03/content_456.htm",
                source_id="gmw",
                title="超过数量上限的结果",
                published_date=date(2026, 9, 3),
            ),
        )
    )
    fetcher = _FakeFetcher(
        {
            url: _page(
                url,
                "数字治理要在协同上下功夫",
                "数字治理是一项系统工程。\n\n要强化部门协同，提升公共服务质效。",
                "2026-09-03",
            )
        }
    )
    storage = GongwenStorage(tmp_path / "documents.sqlite3")
    with SQLiteArticleRepository(tmp_path / "articles.sqlite3") as repository:
        library = ArticleLibrary(repository, fetcher=fetcher)
        application = create_app(
            storage=storage,
            article_library=library,
            article_discovery=discovery,
        )
        with TestClient(application) as client:
            payload = {
                "keywords": [" 数字治理 ", "数字治理"],
                "sources": ["gmw"],
                "date_from": "2026-09-01",
                "date_to": "2026-09-03",
                "limit": 1,
            }
            response = client.post("/api/articles/auto-collect", json=payload)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            result = response.json()
            assert result["keywords"] == ["数字治理"]
            assert result["source_ids"] == ["gmw"]
            assert result["discovered_count"] == 1
            assert result["imported_count"] == 1
            assert result["items"][0]["status"] == "imported"

            repeated = client.post("/api/articles/auto-collect", json=payload)
            assert repeated.status_code == 200
            assert repeated.json()["duplicate_count"] == 1
            assert fetcher.calls == [url]

            invalid_limit = client.post(
                "/api/articles/auto-collect",
                json={**payload, "limit": "1"},
            )
            assert invalid_limit.status_code == 422
            assert invalid_limit.json()["error"]["code"] == "invalid_request"

            reversed_dates = client.post(
                "/api/articles/auto-collect",
                json={**payload, "date_from": "2026-09-03", "date_to": "2026-09-01"},
            )
            assert reversed_dates.status_code == 422

            extra_field = client.post(
                "/api/articles/auto-collect",
                json={**payload, "unexpected": True},
            )
            assert extra_field.status_code == 422

            unknown_source = client.post(
                "/api/articles/auto-collect",
                json={**payload, "sources": ["unknown"]},
            )
            assert unknown_source.status_code == 400
            assert unknown_source.json()["error"]["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_collection_preserves_input_order_and_content_duplicate_winner(
    tmp_path: Path,
) -> None:
    urls = [f"https://www.people.com.cn/concurrent-{index}.html" for index in range(6)]
    contents = [
        f"政绩观建设要坚持为民导向。\n\n第{index}项工作要完善机制并务求实效。" for index in range(5)
    ]
    contents.append(contents[0])
    delays = dict(zip(urls, (0.08, 0.01, 0.05, 0.02, 0.03, 0.01), strict=True))
    fetcher = _TimedFetcher(
        {
            url: _page(url, f"政绩观建设专题文章{index}", contents[index])
            for index, url in enumerate(urls)
        },
        delays,
    )
    candidates = tuple(
        DiscoveredArticle(
            url=url,
            source_id="people",
            title=f"政绩观建设专题文章{index}",
            published_date=date(2026, 9, 2),
        )
        for index, url in enumerate(urls)
    )

    with SQLiteArticleRepository(tmp_path / "concurrent.sqlite3") as repository:
        library = ArticleLibrary(repository, fetcher=fetcher)
        service = ArticleCollectionService(
            library,
            _FakeDiscovery(candidates),
            item_timeout_seconds=1,
            batch_timeout_seconds=2,
        )

        result = await service.collect(
            ArticleCollectionScope.create(
                keywords=["政绩观"],
                source_ids=["people"],
                limit=10,
            )
        )

        assert fetcher.max_active == 1
        assert fetcher.completed == urls
        assert [item.index for item in result.items] == list(range(6))
        assert [item.url for item in result.items] == urls
        assert [item.status for item in result.items] == [
            "imported",
            "imported",
            "imported",
            "imported",
            "imported",
            "duplicate",
        ]
        assert result.items[-1].reason_code == "duplicate_content"
        assert len(library.list_articles(limit=20)) == 5


@pytest.mark.asyncio
async def test_hundred_candidate_scope_stays_within_total_runtime_boundary(
    tmp_path: Path,
) -> None:
    urls = [f"https://www.people.com.cn/bounded-{index}.html" for index in range(100)]
    fetcher = _TimedFetcher(
        {
            url: _page(
                url,
                f"政绩观建设第{index}篇",
                f"政绩观建设要坚持为民导向。\n\n这是第{index}项差异化工作举措。",
            )
            for index, url in enumerate(urls)
        },
        {url: 0.002 for url in urls},
    )
    candidates = tuple(
        DiscoveredArticle(
            url=url,
            source_id="people",
            title=f"政绩观建设第{index}篇",
            published_date=date(2026, 9, 2),
        )
        for index, url in enumerate(urls)
    )

    with SQLiteArticleRepository(tmp_path / "hundred.sqlite3") as repository:
        service = ArticleCollectionService(
            ArticleLibrary(repository, fetcher=fetcher),
            _FakeDiscovery(candidates),
            item_timeout_seconds=1,
            batch_timeout_seconds=3,
        )
        result = await service.collect(
            ArticleCollectionScope.create(
                keywords=["政绩观"],
                source_ids=["people"],
                limit=100,
            )
        )

        assert result.discovered_count == 100
        assert result.imported_count == 100
        assert fetcher.max_active == 1
        assert len(fetcher.calls) == 100


@pytest.mark.asyncio
async def test_collection_item_timeout_and_unexpected_error_do_not_abort_peers(
    tmp_path: Path,
) -> None:
    slow_url = "https://www.people.com.cn/slow.html"
    fast_url = "https://www.people.com.cn/fast.html"
    error_url = "https://www.people.com.cn/error.html"
    fetcher = _TimedFetcher(
        {
            slow_url: _page(slow_url, "政绩观慢文章", "政绩观建设要久久为功。"),
            fast_url: _page(fast_url, "政绩观快文章", "政绩观建设要务求实效。"),
            error_url: RuntimeError("模拟未分类获取异常"),
        },
        {slow_url: 0.2, fast_url: 0.001, error_url: 0.001},
    )
    candidates = tuple(
        DiscoveredArticle(
            url=url,
            source_id="people",
            title="政绩观建设",
            published_date=date(2026, 9, 2),
        )
        for url in (slow_url, fast_url, error_url)
    )

    with SQLiteArticleRepository(tmp_path / "item-timeout.sqlite3") as repository:
        service = ArticleCollectionService(
            ArticleLibrary(repository, fetcher=fetcher),
            _FakeDiscovery(candidates),
            item_timeout_seconds=0.03,
            batch_timeout_seconds=1,
        )

        result = await service.collect(
            ArticleCollectionScope.create(
                keywords=["政绩观"],
                source_ids=["people"],
            )
        )

        assert [item.reason_code for item in result.items] == [
            "import_timeout",
            "imported",
            "import_failed",
        ]
        assert result.imported_count == 1
        assert result.failed_count == 2
        assert fetcher.cancelled == [slow_url]
        assert fetcher.active == 0


@pytest.mark.asyncio
async def test_collection_parse_timeout_never_persists_after_worker_finishes(
    tmp_path: Path,
) -> None:
    url = "https://www.people.com.cn/slow-parse.html"
    fetcher = _FakeFetcher(
        {url: _page(url, "政绩观建设专题", "政绩观建设要坚持为民导向、务求实效。")}
    )
    discovery = _FakeDiscovery(
        (
            DiscoveredArticle(
                url=url,
                source_id="people",
                title="政绩观建设专题",
                published_date=date(2026, 9, 2),
            ),
        )
    )

    with SQLiteArticleRepository(tmp_path / "parse-timeout.sqlite3") as repository:
        library = _SlowPrepareLibrary(repository, fetcher=fetcher)
        service = ArticleCollectionService(
            library,
            discovery,
            item_timeout_seconds=0.02,
            batch_timeout_seconds=1,
        )

        result = await service.collect(
            ArticleCollectionScope.create(
                keywords=["政绩观"],
                source_ids=["people"],
            )
        )
        worker_finished = await asyncio.to_thread(library.prepare_finished.wait, 1)

        assert worker_finished
        assert result.items[0].reason_code == "import_timeout"
        assert library.list_articles() == []


@pytest.mark.asyncio
async def test_collection_batch_timeout_cancels_active_and_queued_acquisitions(
    tmp_path: Path,
) -> None:
    urls = [f"https://www.people.com.cn/batch-timeout-{index}.html" for index in range(5)]
    fetcher = _TimedFetcher(
        {
            url: _page(url, f"政绩观文章{index}", "政绩观建设要坚持实干担当。")
            for index, url in enumerate(urls)
        },
        {url: 0.3 for url in urls},
    )
    candidates = tuple(
        DiscoveredArticle(
            url=url,
            source_id="people",
            title=f"政绩观文章{index}",
            published_date=date(2026, 9, 2),
        )
        for index, url in enumerate(urls)
    )

    with SQLiteArticleRepository(tmp_path / "batch-timeout.sqlite3") as repository:
        service = ArticleCollectionService(
            ArticleLibrary(repository, fetcher=fetcher),
            _FakeDiscovery(candidates),
            item_timeout_seconds=1,
            batch_timeout_seconds=0.06,
        )

        result = await service.collect(
            ArticleCollectionScope.create(
                keywords=["政绩观"],
                source_ids=["people"],
            )
        )

        assert [item.index for item in result.items] == list(range(5))
        assert {item.reason_code for item in result.items} == {"collection_timeout"}
        assert result.failed_count == 5
        assert fetcher.max_active == 1
        assert len(fetcher.cancelled) == 1
        assert fetcher.active == 0


@pytest.mark.asyncio
async def test_repeated_url_is_single_flight_and_retries_after_earlier_skip(
    tmp_path: Path,
) -> None:
    url = "https://www.people.com.cn/repeated.html"
    page = _page(url, "普通工作文章", "工作推进要完善机制并狠抓落实。")
    fetcher = _TimedFetcher({url: page}, {url: 0.001})
    discovery = _FakeDiscovery(
        (
            DiscoveredArticle(
                url=url,
                source_id="people",
                title="普通工作文章",
                published_date=date(2026, 9, 2),
            ),
            DiscoveredArticle(
                url=url,
                source_id="people",
                title="政绩观建设专题",
                published_date=date(2026, 9, 2),
            ),
        )
    )

    with SQLiteArticleRepository(tmp_path / "single-flight.sqlite3") as repository:
        library = ArticleLibrary(repository, fetcher=fetcher)
        service = ArticleCollectionService(
            library,
            discovery,
            item_timeout_seconds=1,
            batch_timeout_seconds=2,
        )

        result = await service.collect(
            ArticleCollectionScope.create(
                keywords=["政绩观"],
                source_ids=["people"],
            )
        )

        assert [item.status for item in result.items] == ["skipped", "imported"]
        assert fetcher.calls == [url, url]
        assert len(library.list_articles(limit=20)) == 1


@pytest.mark.asyncio
async def test_invalid_original_url_is_isolated_from_other_candidates(tmp_path: Path) -> None:
    invalid_url = "https://www.people.com.cn/invalid-original.html"
    valid_url = "https://www.people.com.cn/valid-peer.html"
    fetcher = _FakeFetcher(
        {valid_url: _page(valid_url, "政绩观建设", "政绩观建设必须坚持为民导向。")}
    )
    discovery = _FakeDiscovery(
        (
            DiscoveredArticle(
                url=invalid_url,
                original_url="http://[::1",
                source_id="people",
                title="政绩观建设",
            ),
            DiscoveredArticle(
                url=valid_url,
                source_id="people",
                title="政绩观建设",
            ),
        )
    )

    with SQLiteArticleRepository(tmp_path / "invalid-original.sqlite3") as repository:
        service = ArticleCollectionService(
            ArticleLibrary(repository, fetcher=fetcher),
            discovery,
        )
        result = await service.collect(
            ArticleCollectionScope.create(
                keywords=["政绩观"],
                source_ids=["people"],
            )
        )

        assert [item.reason_code for item in result.items] == [
            "invalid_original_url",
            "imported",
        ]
        assert fetcher.calls == [valid_url]
