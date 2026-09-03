"""Offline scale and contract tests for article-library SQLite fast paths."""

# Chinese fixtures intentionally use full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import asyncio
import builtins
import threading
from collections.abc import Sequence
from pathlib import Path

import pytest

from gongwen_web.articles import (
    ArticleIdentity,
    ArticleLibrary,
    ArticleRecord,
    ArticleSummary,
    SQLiteArticleRepository,
)
from gongwen_web.collection import ArticleCollectionScope, ArticleCollectionService
from yanzhang.providers.content.article_discovery import (
    ArticleDiscoveryBatch,
    ArticleDiscoveryQuery,
    DiscoveredArticle,
)


class _ListOnlyRepository:
    """Repository fixture that intentionally exposes no SQLite fast-path methods."""

    def __init__(self, records: Sequence[ArticleRecord]) -> None:
        self.records = {record.id: record for record in records}

    def save(self, record: ArticleRecord) -> ArticleRecord:
        self.records[record.id] = record
        return record

    def get(self, article_id: str) -> ArticleRecord | None:
        return self.records.get(article_id)

    def list(self, *, source_id: str | None = None) -> list[ArticleRecord]:
        records = list(self.records.values())
        if source_id:
            records = [record for record in records if record.source_id == source_id]
        records.sort(key=lambda record: record.id)
        records.sort(key=lambda record: record.updated_at, reverse=True)
        records.sort(key=lambda record: record.published_date or "", reverse=True)
        return records

    def delete(self, article_id: str) -> bool:
        return self.records.pop(article_id, None) is not None


class _SpySQLiteArticleRepository(SQLiteArticleRepository):
    def __init__(self, path: str | Path) -> None:
        super().__init__(path)
        self.full_list_calls = 0
        self.summary_list_calls = 0
        self.summary_search_calls = 0
        self.identity_calls = 0

    def list(self, *, source_id: str | None = None) -> list[ArticleRecord]:
        self.full_list_calls += 1
        return super().list(source_id=source_id)

    def list_summaries(
        self,
        *,
        limit: int,
        offset: int,
        source_id: str | None = None,
    ) -> builtins.list[ArticleSummary]:
        self.summary_list_calls += 1
        return super().list_summaries(limit=limit, offset=offset, source_id=source_id)

    def search_summaries(
        self,
        terms: Sequence[str],
        *,
        limit: int,
        offset: int,
        source_id: str | None = None,
    ) -> tuple[builtins.list[ArticleSummary], int]:
        self.summary_search_calls += 1
        return super().search_summaries(
            terms,
            limit=limit,
            offset=offset,
            source_id=source_id,
        )

    def list_identities(self) -> builtins.list[ArticleIdentity]:
        self.identity_calls += 1
        return super().list_identities()


class _OneDuplicateDiscovery:
    async def discover(self, query: ArticleDiscoveryQuery) -> ArticleDiscoveryBatch:
        assert query.limit == 20
        return ArticleDiscoveryBatch(
            articles=(
                DiscoveredArticle(
                    url="https://www.people.com.cn/article-0000.html",
                    source_id="people",
                ),
            )
        )


class _NoGetArticleLibrary(ArticleLibrary):
    get_calls = 0

    def get_article(self, article_id: str) -> ArticleRecord | None:
        self.get_calls += 1
        return super().get_article(article_id)


def _seed(library: ArticleLibrary, count: int) -> None:
    for index in range(count):
        source_id = "people" if index % 2 == 0 else "gmw"
        keyword = "数字治理" if index % 7 == 0 else "基层服务"
        library.import_text(
            title=f"{keyword}工作观察 {index:04d}",
            content=(
                f"第{index:04d}篇文章围绕{keyword}展开分析。\n\n"
                f"要完善工作机制，提升协同效能。唯一编号{index:04d}。"
            ),
            source_id=source_id,
            url=(
                f"https://www.people.com.cn/article-{index:04d}.html"
                if source_id == "people"
                else f"https://news.gmw.cn/article-{index:04d}.html"
            ),
            published_date=f"2026-{index % 9 + 1:02d}-{index % 27 + 1:02d}",
            summary=f"{keyword}摘要 {index:04d}",
        )


def test_sql_fast_paths_match_fallback_order_scoring_excerpt_and_total(tmp_path: Path) -> None:
    with _SpySQLiteArticleRepository(tmp_path / "scaled.sqlite3") as repository:
        fast = ArticleLibrary(repository)
        _seed(fast, 2_000)
        records = repository.list()
        repository.full_list_calls = 0
        fallback = ArticleLibrary(_ListOnlyRepository(records))

        for source_id in (None, "people", "gmw"):
            assert [
                item.model_dump()
                for item in fast.list_articles(limit=37, offset=113, source_id=source_id)
            ] == [
                item.model_dump()
                for item in fallback.list_articles(limit=37, offset=113, source_id=source_id)
            ]
            for query in ("", "数字治理", "数字治理 机制", "不存在"):
                actual = fast.search_page(
                    query,
                    limit=31,
                    offset=9,
                    source_id=source_id,
                )
                expected = fallback.search_page(
                    query,
                    limit=31,
                    offset=9,
                    source_id=source_id,
                )
                assert actual.model_dump() == expected.model_dump()

        assert repository.full_list_calls == 0
        assert repository.summary_list_calls == 3
        assert repository.summary_search_calls == 12


@pytest.mark.asyncio
async def test_collection_identity_fast_path_avoids_full_list_and_per_article_get(
    tmp_path: Path,
) -> None:
    with _SpySQLiteArticleRepository(tmp_path / "identity.sqlite3") as repository:
        library = _NoGetArticleLibrary(repository)
        _seed(library, 1_500)
        repository.full_list_calls = 0
        service = ArticleCollectionService(library, _OneDuplicateDiscovery())

        result = await service.collect(
            ArticleCollectionScope.create(
                keywords=["数字治理"],
                source_ids=["people"],
            )
        )

        assert result.discovered_count == 1
        assert result.duplicate_count == 1
        assert repository.identity_calls == 1
        assert repository.full_list_calls == 0
        assert library.get_calls == 0
        identities = library.article_identity_index()
        assert repository.identity_calls == 2
        assert len(identities) == 1_500
        assert all(identity.content_hash and identity.id for identity in identities)


def test_empty_repository_fast_paths_preserve_zero_count(tmp_path: Path) -> None:
    with _SpySQLiteArticleRepository(tmp_path / "empty.sqlite3") as repository:
        library = ArticleLibrary(repository)

        assert library.list_articles() == []
        page = library.search_page("", limit=20, offset=400)
        assert page.items == []
        assert page.total == 0
        assert repository.full_list_calls == 0


@pytest.mark.asyncio
async def test_collection_index_lock_contention_does_not_freeze_event_loop(
    tmp_path: Path,
) -> None:
    with _SpySQLiteArticleRepository(tmp_path / "contended.sqlite3") as repository:
        library = ArticleLibrary(repository)
        service = ArticleCollectionService(library, _OneDuplicateDiscovery())
        lock_acquired = threading.Event()
        release_lock = threading.Event()

        def hold_repository_lock() -> None:
            with repository._lock:
                lock_acquired.set()
                release_lock.wait(timeout=1)

        holder = threading.Thread(target=hold_repository_lock, daemon=True)
        holder.start()
        assert lock_acquired.wait(timeout=0.5)

        loop = asyncio.get_running_loop()
        started_at = loop.time()
        collection = asyncio.create_task(
            service.collect(
                ArticleCollectionScope.create(
                    keywords=["数字治理"],
                    source_ids=["people"],
                )
            )
        )
        await asyncio.sleep(0.02)
        heartbeat_elapsed = loop.time() - started_at
        release_lock.set()
        result = await asyncio.wait_for(collection, timeout=1)
        holder.join(timeout=1)

        assert heartbeat_elapsed < 0.5
        assert result.discovered_count == 1
