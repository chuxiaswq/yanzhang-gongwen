"""Persistent reference article library for the personal writing service.

The module deliberately separates content acquisition from storage and parsing.
``ArticleLibrary`` never opens a network connection itself: URL imports go through
an injected :class:`ArticleFetcher`.  The bundled HTTP implementation is an explicit
adapter with an official-domain allowlist, redirect validation, timeouts and a byte
limit.  Merely constructing the library never downloads anything.

Full article text is retained only in the user's local SQLite database.  Search and
generation-facing reference methods return short excerpts or abstract style features
instead of copying full source text into a generated document.
"""

# Chinese punctuation is intentional in extracted article text and user-facing errors.
# ruff: noqa: RUF001

from __future__ import annotations

import asyncio
import builtins
import hashlib
import html
import ipaddress
import json
import re
import sqlite3
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, Literal, Protocol, Self, runtime_checkable
from urllib.parse import urljoin, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

from yanzhang.providers.content import (
    HostResolver,
    HTTPFetchedPage,
    SystemHostResolver,
)
from yanzhang.providers.content import (
    HTTPArticleFetcher as _ProviderHTTPArticleFetcher,
)


class ArticleLibraryError(ValueError):
    """Base error for an invalid article-library operation."""


class ArticleURLValidationError(ArticleLibraryError):
    """Raised when a URL is outside the configured official-source boundary."""


class ArticleFetchError(ArticleLibraryError):
    """Raised when an explicit URL import cannot retrieve a usable HTML page."""


@dataclass(frozen=True, slots=True)
class OfficialSource:
    """Metadata and domain policy for one registered official publication."""

    id: str
    name: str
    homepage: str
    domains: tuple[str, ...]
    description: str
    style_features: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return browser-ready source metadata."""

        return {
            "id": self.id,
            "name": self.name,
            "homepage": self.homepage,
            "domains": list(self.domains),
            "description": self.description,
            "style_features": list(self.style_features),
        }


OFFICIAL_SOURCES: Mapping[str, OfficialSource] = MappingProxyType(
    {
        "people": OfficialSource(
            id="people",
            name="人民日报 / 人民网",
            homepage="https://www.people.com.cn/",
            domains=("people.com.cn", "people.cn"),
            description="人民日报及人民网公开页面，适合观察权威报道和评论文章的结构表达。",
            style_features=("主题鲜明", "事实先行", "层次清楚", "表述凝练"),
        ),
        "gmw": OfficialSource(
            id="gmw",
            name="光明日报 / 光明网",
            homepage="https://www.gmw.cn/",
            domains=("gmw.cn",),
            description="光明日报及光明网公开页面，适合观察理论、文化类文章的阐释方式。",
            style_features=("理论阐释", "文化视角", "论据充分", "语气稳健"),
        ),
        "qiushi": OfficialSource(
            id="qiushi",
            name="求是 / 求是网",
            homepage="https://www.qstheory.cn/",
            domains=("qstheory.cn",),
            description="求是杂志及求是网公开页面，适合观察理论文章的论证层次。",
            style_features=("论点先行", "层层递进", "逻辑严密", "政策表达"),
        ),
    }
)

_REQUIRED_ARTICLE_COLUMNS = frozenset(
    {
        "id",
        "title",
        "content",
        "source_id",
        "source_name",
        "url",
        "published_date",
        "summary",
        "style_features_json",
        "content_hash",
        "import_method",
        "created_at",
        "updated_at",
    }
)


class _ArticleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ArticleRecord(_ArticleModel):
    """A complete locally stored article and its traceable metadata."""

    id: str
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1)
    source_id: str
    source_name: str
    url: str | None = None
    published_date: str | None = None
    summary: str
    style_features: list[str] = Field(default_factory=list)
    content_hash: str
    import_method: Literal["manual", "url"]
    created_at: str
    updated_at: str

    def to_dict(self, *, include_content: bool = True) -> dict[str, object]:
        """Serialize the record, optionally omitting locally retained full text."""

        data: dict[str, object] = dict(self.model_dump(mode="json"))
        if not include_content:
            data.pop("content", None)
        return data


class ArticleSummary(_ArticleModel):
    """Compact article metadata returned by list and full-text search."""

    id: str
    title: str
    source_id: str
    source_name: str
    url: str | None
    published_date: str | None
    summary: str
    excerpt: str
    style_features: list[str]
    import_method: Literal["manual", "url"]
    updated_at: str
    score: int = 0

    def to_dict(self) -> dict[str, object]:
        """Serialize the search summary for a JSON response."""

        return dict(self.model_dump(mode="json"))


class ArticleSearchPage(_ArticleModel):
    """A stable, pageable full-text search result."""

    items: list[ArticleSummary]
    total: int
    offset: int
    limit: int
    query: str

    def to_dict(self) -> dict[str, object]:
        """Serialize the page for a JSON response."""

        return dict(self.model_dump(mode="json"))


@dataclass(frozen=True, slots=True)
class ArticleIdentity:
    """Lightweight fields used for URL and content-hash de-duplication."""

    id: str
    url: str | None
    content_hash: str


@dataclass(frozen=True, slots=True)
class FetchedPage:
    """Bounded response returned by an article acquisition adapter."""

    url: str
    body: bytes
    content_type: str = "text/html; charset=utf-8"
    status_code: int = 200


class ArticleFetcher(Protocol):
    """Network boundary used only for a user-triggered URL import."""

    async def fetch(self, url: str) -> FetchedPageLike:
        """Fetch one already validated official article URL."""


class FetchedPageLike(Protocol):
    """Structural response contract implemented by acquisition adapters."""

    @property
    def url(self) -> str: ...

    @property
    def body(self) -> bytes: ...

    @property
    def content_type(self) -> str: ...

    @property
    def status_code(self) -> int: ...


@dataclass(frozen=True, slots=True)
class FetchedArticlePage:
    """Validated network result awaiting CPU parsing and local persistence."""

    requested_url: str
    source: OfficialSource
    page: FetchedPageLike
    style_features: tuple[str, ...] = ()


class HTTPArticleFetcher(_ProviderHTTPArticleFetcher):
    """Compatibility facade translating adapter failures to library errors."""

    async def fetch(self, url: str) -> HTTPFetchedPage:
        try:
            return await super().fetch(url)
        except ValueError as exc:
            raise ArticleFetchError(str(exc)) from exc


class ArticleRepository(Protocol):
    """Persistence contract used by :class:`ArticleLibrary`."""

    def save(self, record: ArticleRecord) -> ArticleRecord:
        """Insert or replace one article and return the persisted record."""

    def get(self, article_id: str) -> ArticleRecord | None:
        """Read an article by id."""

    def list(self, *, source_id: str | None = None) -> list[ArticleRecord]:
        """List records in a stable order."""

    def delete(self, article_id: str) -> bool:
        """Delete a record, returning whether a row changed."""


@runtime_checkable
class ArticleSummaryRepository(Protocol):
    """Optional SQL-backed fast path for lightweight listing and search."""

    def list_summaries(
        self,
        *,
        limit: int,
        offset: int,
        source_id: str | None = None,
    ) -> builtins.list[ArticleSummary]:
        """Return one already ordered page without loading article bodies."""

    def search_summaries(
        self,
        terms: Sequence[str],
        *,
        limit: int,
        offset: int,
        source_id: str | None = None,
    ) -> tuple[list[ArticleSummary], int]:
        """Return a ranked page and the pre-pagination match count."""


@runtime_checkable
class ArticleIdentityRepository(Protocol):
    """Optional fast path exposing only fields required by collection de-duplication."""

    def list_identities(self) -> list[ArticleIdentity]:
        """Return all local article identities without loading full text."""


class SQLiteArticleRepository:
    """Small, thread-safe SQLite repository dedicated to local article content."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser() if str(path) != ":memory:" else Path(":memory:")
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.create_function(
            "article_search_score",
            6,
            _sqlite_search_score,
            deterministic=True,
        )
        self._connection.create_function(
            "article_search_excerpt",
            2,
            _sqlite_search_excerpt,
            deterministic=True,
        )
        self._lock = threading.RLock()
        self._closed = False
        try:
            self._initialize()
        except BaseException:
            self._connection.close()
            self._closed = True
            raise

    def _initialize(self) -> None:
        with self._lock, self._connection:
            if str(self.path) != ":memory:":
                self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            exists = self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'reference_articles'"
            ).fetchone()
            if exists is not None:
                columns = frozenset(
                    str(row[1])
                    for row in self._connection.execute(
                        "PRAGMA table_info(reference_articles)"
                    ).fetchall()
                )
                missing = sorted(_REQUIRED_ARTICLE_COLUMNS - columns)
                if missing:
                    raise ArticleLibraryError("文章来源库 schema 缺少字段：" + ",".join(missing))
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS reference_articles (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    url TEXT,
                    published_date TEXT,
                    summary TEXT NOT NULL,
                    style_features_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    import_method TEXT NOT NULL CHECK (import_method IN ('manual', 'url')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS reference_articles_url_unique
                    ON reference_articles(url) WHERE url IS NOT NULL AND url != '';
                CREATE INDEX IF NOT EXISTS reference_articles_source_idx
                    ON reference_articles(source_id);
                CREATE INDEX IF NOT EXISTS reference_articles_updated_idx
                    ON reference_articles(updated_at DESC);
                CREATE INDEX IF NOT EXISTS reference_articles_list_order_idx
                    ON reference_articles(
                        COALESCE(published_date, '') DESC, updated_at DESC, id ASC
                    );
                CREATE INDEX IF NOT EXISTS reference_articles_source_list_order_idx
                    ON reference_articles(
                        source_id, COALESCE(published_date, '') DESC, updated_at DESC, id ASC
                    );
                CREATE INDEX IF NOT EXISTS reference_articles_content_hash_idx
                    ON reference_articles(content_hash);
                """
            )

    def save(self, record: ArticleRecord) -> ArticleRecord:
        self._ensure_open()
        with self._lock, self._connection:
            existing: sqlite3.Row | None = None
            if record.url:
                existing = self._connection.execute(
                    "SELECT id, created_at FROM reference_articles WHERE url = ?",
                    (record.url,),
                ).fetchone()
            if existing is None:
                existing = self._connection.execute(
                    "SELECT id, created_at FROM reference_articles WHERE id = ?",
                    (record.id,),
                ).fetchone()
            persisted = record
            if existing is not None:
                persisted = record.model_copy(
                    update={"id": str(existing["id"]), "created_at": str(existing["created_at"])}
                )
            self._connection.execute(
                """
                INSERT INTO reference_articles (
                    id, title, content, source_id, source_name, url, published_date,
                    summary, style_features_json, content_hash, import_method,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    source_id = excluded.source_id,
                    source_name = excluded.source_name,
                    url = excluded.url,
                    published_date = excluded.published_date,
                    summary = excluded.summary,
                    style_features_json = excluded.style_features_json,
                    content_hash = excluded.content_hash,
                    import_method = excluded.import_method,
                    updated_at = excluded.updated_at
                """,
                (
                    persisted.id,
                    persisted.title,
                    persisted.content,
                    persisted.source_id,
                    persisted.source_name,
                    persisted.url,
                    persisted.published_date,
                    persisted.summary,
                    json.dumps(persisted.style_features, ensure_ascii=False),
                    persisted.content_hash,
                    persisted.import_method,
                    persisted.created_at,
                    persisted.updated_at,
                ),
            )
        return persisted

    def get(self, article_id: str) -> ArticleRecord | None:
        self._ensure_open()
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM reference_articles WHERE id = ?", (article_id,)
            ).fetchone()
        return _record_from_row(row) if row is not None else None

    def list(self, *, source_id: str | None = None) -> list[ArticleRecord]:
        self._ensure_open()
        query = "SELECT * FROM reference_articles"
        parameters: tuple[str, ...] = ()
        if source_id:
            query += " WHERE source_id = ?"
            parameters = (source_id,)
        query += " ORDER BY COALESCE(published_date, '') DESC, updated_at DESC, id ASC"
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return [_record_from_row(row) for row in rows]

    def list_summaries(
        self,
        *,
        limit: int,
        offset: int,
        source_id: str | None = None,
    ) -> builtins.list[ArticleSummary]:
        """Return one SQL-paginated metadata page without selecting article bodies."""

        self._ensure_open()
        query = """
            SELECT id, title, source_id, source_name, url, published_date, summary,
                   summary AS excerpt, style_features_json, import_method, updated_at,
                   0 AS score
            FROM reference_articles
        """
        parameters: builtins.list[object] = []
        if source_id:
            query += " WHERE source_id = ?"
            parameters.append(source_id)
        query += (
            " ORDER BY COALESCE(published_date, '') DESC, updated_at DESC, id ASC LIMIT ? OFFSET ?"
        )
        parameters.extend((limit, offset))
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return [_summary_from_row(row) for row in rows]

    def search_summaries(
        self,
        terms: Sequence[str],
        *,
        limit: int,
        offset: int,
        source_id: str | None = None,
    ) -> tuple[builtins.list[ArticleSummary], int]:
        """Rank and paginate in SQLite while returning only one lightweight page."""

        self._ensure_open()
        encoded_terms = json.dumps(list(terms), ensure_ascii=False, separators=(",", ":"))
        source_clause = " WHERE source_id = :source_id" if source_id else ""
        if not terms:
            return self._unranked_search_summaries(
                encoded_terms=encoded_terms,
                source_clause=source_clause,
                limit=limit,
                offset=offset,
                source_id=source_id,
            )
        common_parameters: dict[str, object] = {
            "terms": encoded_terms,
        }
        if source_id:
            common_parameters["source_id"] = source_id
        count_query = f"""
            SELECT COUNT(*)
            FROM reference_articles
            {source_clause}
            {"AND" if source_id else "WHERE"}
                article_search_score(
                    title, summary, source_name, style_features_json, content, :terms
                ) > 0
        """
        page_query = f"""
            WITH scored AS MATERIALIZED (
                SELECT id, title, source_id, source_name, url, published_date, summary,
                       style_features_json, import_method, updated_at,
                       article_search_score(
                           title, summary, source_name, style_features_json, content, :terms
                       ) AS score
                FROM reference_articles
                {source_clause}
            ),
            page AS MATERIALIZED (
                SELECT id, title, source_id, source_name, url, published_date, summary,
                       style_features_json, import_method, updated_at, score
                FROM scored
                WHERE score > 0
                ORDER BY score DESC, COALESCE(published_date, '') DESC, id ASC
                LIMIT :limit OFFSET :offset
            )
            SELECT page.id, page.title, page.source_id, page.source_name, page.url,
                   page.published_date, page.summary,
                   article_search_excerpt(article.content, :terms) AS excerpt,
                   page.style_features_json, page.import_method, page.updated_at, page.score
            FROM page
            JOIN reference_articles AS article ON article.id = page.id
            ORDER BY page.score DESC, COALESCE(page.published_date, '') DESC, page.id ASC
        """
        page_parameters = {**common_parameters, "limit": limit, "offset": offset}
        with self._lock:
            count_row = self._connection.execute(count_query, common_parameters).fetchone()
            rows = self._connection.execute(page_query, page_parameters).fetchall()
        total = int(count_row[0]) if count_row is not None else 0
        return [_summary_from_row(row) for row in rows], total

    def _unranked_search_summaries(
        self,
        *,
        encoded_terms: str,
        source_clause: str,
        limit: int,
        offset: int,
        source_id: str | None,
    ) -> tuple[builtins.list[ArticleSummary], int]:
        """Handle an empty query with metadata-first SQL pagination and COUNT."""

        common_parameters: dict[str, object] = {}
        if source_id:
            common_parameters["source_id"] = source_id
        count_query = f"SELECT COUNT(*) FROM reference_articles{source_clause}"
        page_query = f"""
            WITH page AS MATERIALIZED (
                SELECT id, title, source_id, source_name, url, published_date, summary,
                       style_features_json, import_method, updated_at
                FROM reference_articles
                {source_clause}
                ORDER BY COALESCE(published_date, '') DESC, id ASC
                LIMIT :limit OFFSET :offset
            )
            SELECT page.id, page.title, page.source_id, page.source_name, page.url,
                   page.published_date, page.summary, page.style_features_json,
                   page.import_method, page.updated_at,
                   article_search_excerpt(article.content, :terms) AS excerpt,
                   0 AS score
            FROM page
            JOIN reference_articles AS article ON article.id = page.id
            ORDER BY COALESCE(page.published_date, '') DESC, page.id ASC
        """
        page_parameters = {
            **common_parameters,
            "terms": encoded_terms,
            "limit": limit,
            "offset": offset,
        }
        with self._lock:
            count_row = self._connection.execute(count_query, common_parameters).fetchone()
            rows = self._connection.execute(page_query, page_parameters).fetchall()
        total = int(count_row[0]) if count_row is not None else 0
        return [_summary_from_row(row) for row in rows], total

    def list_identities(self) -> builtins.list[ArticleIdentity]:
        """Return de-duplication keys without loading title, summary, or full text."""

        self._ensure_open()
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, url, content_hash FROM reference_articles ORDER BY id ASC"
            ).fetchall()
        return [
            ArticleIdentity(
                id=str(row["id"]),
                url=str(row["url"]) if row["url"] is not None else None,
                content_hash=str(row["content_hash"]),
            )
            for row in rows
        ]

    def delete(self, article_id: str) -> bool:
        self._ensure_open()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM reference_articles WHERE id = ?", (article_id,)
            )
        return cursor.rowcount > 0

    def close(self) -> None:
        """Close the owned SQLite connection."""

        if self._closed:
            return
        with self._lock:
            self._connection.close()
            self._closed = True

    def __enter__(self) -> Self:
        self._ensure_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise ArticleLibraryError("文章来源库已经关闭")


class ArticleLibrary:
    """Application service for explicit imports, metadata and local search."""

    def __init__(
        self,
        repository: ArticleRepository,
        *,
        fetcher: ArticleFetcher | None = None,
        sources: Mapping[str, OfficialSource] = OFFICIAL_SOURCES,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._fetcher = fetcher
        self._sources = dict(sources)
        self._clock = clock or (lambda: datetime.now(UTC))

    def list_sources(self) -> list[dict[str, object]]:
        """List source metadata without downloading any article."""

        return [source.to_dict() for source in self._sources.values()]

    def import_text(
        self,
        *,
        title: str,
        content: str,
        source_id: str = "manual",
        source_name: str = "用户导入",
        url: str | None = None,
        published_date: str | None = None,
        summary: str | None = None,
        style_features: Sequence[str] = (),
    ) -> ArticleRecord:
        """Store text the user has explicitly supplied."""

        record = self.prepare_text_import(
            title=title,
            content=content,
            source_id=source_id,
            source_name=source_name,
            url=url,
            published_date=published_date,
            summary=summary,
            style_features=style_features,
        )
        return self.persist_prepared_import(record)

    def prepare_text_import(
        self,
        *,
        title: str,
        content: str,
        source_id: str = "manual",
        source_name: str = "用户导入",
        url: str | None = None,
        published_date: str | None = None,
        summary: str | None = None,
        style_features: Sequence[str] = (),
        import_method: Literal["manual", "url"] = "manual",
    ) -> ArticleRecord:
        """Normalize an article into a record without touching persistence."""

        normalized_title = _clean_inline(title)
        normalized_content = normalize_article_text(content)
        if not normalized_title:
            raise ArticleLibraryError("文章标题不能为空")
        if not normalized_content:
            raise ArticleLibraryError("文章正文不能为空")
        if len(normalized_content) > 2_000_000:
            raise ArticleLibraryError("文章正文超过 200 万字的本地限制")

        normalized_url = normalize_url(url) if url else None
        official_source = self._sources.get(source_id)
        if official_source is not None:
            resolved_source_name = official_source.name
            if normalized_url:
                recognized = recognize_source(normalized_url, self._sources)
                if recognized is None or recognized.id != official_source.id:
                    raise ArticleURLValidationError("文章地址与所选官方来源不一致")
        else:
            resolved_source_name = _clean_inline(source_name) or "用户导入"
            if source_id != "manual":
                raise ArticleLibraryError("文章来源标识未登记")

        features = _merge_style_features(
            official_source.style_features if official_source else (),
            infer_style_features(normalized_content),
            style_features,
        )
        now = self._clock().astimezone(UTC).isoformat()
        content_hash = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
        identity = normalized_url or f"{source_id}:{normalized_title}:{content_hash}"
        article_id = "article_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        record = ArticleRecord(
            id=article_id,
            title=normalized_title,
            content=normalized_content,
            source_id=source_id,
            source_name=resolved_source_name,
            url=normalized_url,
            published_date=normalize_date(published_date),
            summary=_clean_inline(summary)[:240]
            if summary and _clean_inline(summary)
            else summarize_text(normalized_content),
            style_features=list(features),
            content_hash=content_hash,
            import_method=import_method,
            created_at=now,
            updated_at=now,
        )
        return record

    def persist_prepared_import(self, record: ArticleRecord) -> ArticleRecord:
        """Persist a previously normalized record at the explicit SQLite boundary."""

        return self._repository.save(record)

    async def fetch_url_import(
        self,
        url: str,
        *,
        source_id: str | None = None,
        style_features: Sequence[str] = (),
    ) -> FetchedArticlePage:
        """Perform only the network stage of an official URL import."""

        normalized_url = validate_official_url(url, self._sources)
        recognized = recognize_source(normalized_url, self._sources)
        if recognized is None:
            raise ArticleURLValidationError("文章来源地址不属于已登记的官方来源")
        if source_id is not None and source_id != recognized.id:
            raise ArticleURLValidationError("文章地址与所选官方来源不一致")
        if self._fetcher is None:
            raise ArticleFetchError("尚未配置文章来源获取适配器")
        try:
            fetched = await self._fetcher.fetch(normalized_url)
        except ArticleLibraryError:
            raise
        except ValueError as exc:
            raise ArticleFetchError(str(exc)) from exc
        return FetchedArticlePage(
            requested_url=normalized_url,
            source=recognized,
            page=fetched,
            style_features=tuple(style_features),
        )

    def prepare_url_import(self, acquired: FetchedArticlePage) -> ArticleRecord:
        """Parse a fetched page into a record without writing to SQLite."""

        fetched = acquired.page
        recognized = acquired.source
        normalized_url = acquired.requested_url
        if fetched.status_code < 200 or fetched.status_code >= 300:
            raise ArticleFetchError(f"文章来源页面返回状态码 {fetched.status_code}")
        if len(fetched.body) > 10 * 1024 * 1024:
            raise ArticleFetchError("文章来源页面超过解析上限")
        if not _is_html_content_type(fetched.content_type):
            raise ArticleFetchError("文章来源地址返回的不是 HTML 页面")

        final_url = validate_official_url(fetched.url or normalized_url, self._sources)
        final_source = recognize_source(final_url, self._sources)
        if final_source is None or final_source.id != recognized.id:
            raise ArticleURLValidationError("文章来源页面跳转到了其他来源")
        parsed = extract_article_html(
            _decode_html(fetched.body, fetched.content_type),
            url=final_url,
            source=final_source,
        )
        if not parsed.content:
            raise ArticleFetchError("页面中没有提取到可用的文章正文")
        if not parsed.title:
            raise ArticleFetchError("页面中没有提取到文章标题")

        return self.prepare_text_import(
            title=parsed.title,
            content=parsed.content,
            source_id=final_source.id,
            url=parsed.url,
            published_date=parsed.published_date,
            summary=parsed.summary,
            style_features=(*parsed.style_features, *acquired.style_features),
            import_method="url",
        )

    async def import_url(
        self,
        url: str,
        *,
        source_id: str | None = None,
        style_features: Sequence[str] = (),
    ) -> ArticleRecord:
        """Fetch and store one user-selected official URL through the injected adapter."""

        acquired = await self.fetch_url_import(
            url,
            source_id=source_id,
            style_features=style_features,
        )
        record = await asyncio.to_thread(self.prepare_url_import, acquired)
        return await asyncio.to_thread(self.persist_prepared_import, record)

    def get_article(self, article_id: str) -> ArticleRecord | None:
        """Read one complete local article."""

        return self._repository.get(article_id.strip())

    def list_articles(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        source_id: str | None = None,
    ) -> list[ArticleSummary]:
        """List locally imported articles without returning full text."""

        _validate_pagination(limit, offset)
        if isinstance(self._repository, ArticleSummaryRepository):
            return self._repository.list_summaries(
                limit=limit,
                offset=offset,
                source_id=source_id,
            )
        records = self._repository.list(source_id=source_id)
        return [
            _summary_from_record(record, excerpt=record.summary)
            for record in records[offset : offset + limit]
        ]

    def search_articles(
        self,
        query: str,
        *,
        limit: int = 20,
        offset: int = 0,
        source_id: str | None = None,
    ) -> list[ArticleSummary]:
        """Search title, metadata and locally stored full text with stable ranking."""

        return self.search_page(query, limit=limit, offset=offset, source_id=source_id).items

    def search_page(
        self,
        query: str,
        *,
        limit: int = 20,
        offset: int = 0,
        source_id: str | None = None,
    ) -> ArticleSearchPage:
        """Return a pageable search result including the pre-pagination total."""

        _validate_pagination(limit, offset)
        normalized_query = _clean_inline(query)[:200]
        terms = _query_terms(normalized_query)
        if isinstance(self._repository, ArticleSummaryRepository):
            items, total = self._repository.search_summaries(
                terms,
                limit=limit,
                offset=offset,
                source_id=source_id,
            )
            return ArticleSearchPage(
                items=items,
                total=total,
                offset=offset,
                limit=limit,
                query=normalized_query,
            )
        candidates = self._repository.list(source_id=source_id)
        ranked: list[tuple[int, ArticleRecord]] = []
        for record in candidates:
            score = _search_score(record, terms)
            if not terms or score > 0:
                ranked.append((score, record))
        ranked.sort(key=lambda item: item[1].id)
        ranked.sort(key=lambda item: item[1].published_date or "", reverse=True)
        ranked.sort(key=lambda item: item[0], reverse=True)
        page = ranked[offset : offset + limit]
        items = [
            _summary_from_record(
                record,
                excerpt=_search_excerpt(record.content, terms),
                score=score,
            )
            for score, record in page
        ]
        return ArticleSearchPage(
            items=items,
            total=len(ranked),
            offset=offset,
            limit=limit,
            query=normalized_query,
        )

    def article_identity_index(self) -> list[ArticleIdentity]:
        """Return lightweight URL/hash keys used by automatic collection de-duplication."""

        if isinstance(self._repository, ArticleIdentityRepository):
            return self._repository.list_identities()
        return [
            ArticleIdentity(id=record.id, url=record.url, content_hash=record.content_hash)
            for record in self._repository.list()
        ]

    def delete_article(self, article_id: str) -> bool:
        """Delete one local article."""

        return self._repository.delete(article_id.strip())

    def references(
        self, article_ids: Iterable[str], *, max_excerpt_chars: int = 360
    ) -> list[dict[str, object]]:
        """Build up to eight style-only cards without exposing stored full text."""

        if max_excerpt_chars < 80 or max_excerpt_chars > 1000:
            raise ArticleLibraryError("参考摘录长度必须在 80 到 1000 字之间")
        cards: list[dict[str, object]] = []
        seen: set[str] = set()
        for article_id in article_ids:
            if len(cards) >= 8:
                break
            normalized_id = article_id.strip()
            if not normalized_id or normalized_id in seen:
                continue
            seen.add(normalized_id)
            record = self._repository.get(normalized_id)
            if record is None:
                raise ArticleLibraryError(f"未找到参考文章：{normalized_id}")
            cards.append(
                {
                    "id": record.id,
                    "title": record.title,
                    "source_id": record.source_id,
                    "source_name": record.source_name,
                    "published_at": record.published_date or "",
                    "published_date": record.published_date,
                    "url": record.url or "",
                    "excerpt": record.summary[:max_excerpt_chars],
                    "summary": record.summary[:max_excerpt_chars],
                    "style_features": list(record.style_features),
                    "usage": "style_only",
                    "import_method": record.import_method,
                    "provenance_status": (
                        "fetched_verified" if record.import_method == "url" else "manual_claim"
                    ),
                }
            )
        return cards


@dataclass(frozen=True, slots=True)
class ExtractedArticle:
    """Structured result of deterministic HTML extraction."""

    title: str
    content: str
    published_date: str | None
    source_name: str
    url: str
    summary: str
    style_features: tuple[str, ...]


class _ArticleHTMLParser(HTMLParser):
    _IGNORED_TAGS: ClassVar[set[str]] = {
        "aside",
        "canvas",
        "footer",
        "form",
        "nav",
        "noscript",
        "style",
        "svg",
    }
    _CONTENT_HINTS: ClassVar[tuple[str, ...]] = (
        "article",
        "content",
        "detail",
        "正文",
        "main",
        "text",
    )
    _VOID_TAGS: ClassVar[set[str]] = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
    _BLOCK_TAGS: ClassVar[set[str]] = {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "dl",
        "fieldset",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "ul",
    }
    _NEGATIVE_HINTS: ClassVar[tuple[str, ...]] = (
        "comment",
        "footer",
        "header",
        "nav",
        "recommend",
        "related",
        "share",
        "sidebar",
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.canonical_url: str | None = None
        self.title_parts: list[str] = []
        self.h1_candidates: list[str] = []
        self.visible_parts: list[str] = []
        self.paragraphs: list[tuple[int, str]] = []
        self.json_ld_documents: list[str] = []
        self._ignored_depth = 0
        self._article_depth = 0
        self._main_depth = 0
        self._hint_depth = 0
        self._negative_depth = 0
        self._container_hints: list[tuple[str, bool, bool]] = []
        self._title_depth = 0
        self._h1_depth = 0
        self._h1_parts: list[str] = []
        self._ignored_tags: list[str] = []
        self._paragraph_depth = 0
        self._paragraph_parts: list[str] = []
        self._paragraph_score = 0
        self._json_ld_depth = 0
        self._json_ld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {key.lower(): value or "" for key, value in attrs}
        if self._ignored_depth:
            if tag not in self._VOID_TAGS:
                self._ignored_tags.append(tag)
                self._ignored_depth = len(self._ignored_tags)
            return
        if self._paragraph_depth and tag in self._BLOCK_TAGS:
            self._finish_paragraph()
        if tag in self._IGNORED_TAGS or (tag == "script" and not _is_json_ld(values)):
            self._ignored_tags = [tag]
            self._ignored_depth = 1
            return
        if tag == "script" and _is_json_ld(values):
            self._json_ld_depth = 1
            self._json_ld_parts = []
            return
        if tag == "meta":
            key = (
                values.get("property") or values.get("name") or values.get("itemprop") or ""
            ).lower()
            content = _clean_inline(values.get("content", ""))
            if key and content and key not in self.meta:
                self.meta[key] = content
        elif tag == "link" and "canonical" in values.get("rel", "").lower().split():
            href = values.get("href", "").strip()
            if href:
                self.canonical_url = href
        elif tag == "title":
            self._title_depth += 1
        elif tag == "h1":
            if self._h1_depth == 0:
                self._h1_parts = []
            self._h1_depth += 1
        if tag == "article":
            self._article_depth += 1
        if tag == "main":
            self._main_depth += 1
        if tag in {"article", "div", "main", "section"}:
            class_and_id = f"{values.get('class', '')} {values.get('id', '')}".lower()
            has_negative = any(hint in class_and_id for hint in self._NEGATIVE_HINTS)
            has_hint = (
                any(hint in class_and_id for hint in self._CONTENT_HINTS) and not has_negative
            )
            self._container_hints.append((tag, has_hint, has_negative))
            if has_hint:
                self._hint_depth += 1
            if has_negative:
                self._negative_depth += 1
        if tag == "p":
            self._paragraph_depth = 1
            self._paragraph_parts = []
            self._paragraph_score = (
                self._article_depth * 4
                + self._main_depth * 3
                + self._hint_depth * 2
                - self._negative_depth * 20
            )
        elif tag == "br" and self._paragraph_depth:
            self._paragraph_parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        was_ignored = bool(self._ignored_depth)
        self.handle_starttag(tag, attrs)
        if was_ignored and tag.lower() in self._VOID_TAGS:
            return
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._ignored_depth:
            if tag in self._ignored_tags:
                reverse_index = self._ignored_tags[::-1].index(tag)
                del self._ignored_tags[len(self._ignored_tags) - reverse_index - 1 :]
                self._ignored_depth = len(self._ignored_tags)
            return
        if self._json_ld_depth:
            self._json_ld_depth -= 1
            if self._json_ld_depth == 0:
                document = "".join(self._json_ld_parts).strip()
                if document:
                    self.json_ld_documents.append(document)
            return
        if self._paragraph_depth and (
            tag == "p" or tag in {"article", "body", "div", "html", "main", "section"}
        ):
            self._finish_paragraph()
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        elif tag == "h1" and self._h1_depth:
            self._h1_depth -= 1
            if self._h1_depth == 0:
                heading = _clean_inline("".join(self._h1_parts))
                if heading:
                    self.h1_candidates.append(heading)
                self._h1_parts = []
        if tag == "article" and self._article_depth:
            self._article_depth -= 1
        if tag == "main" and self._main_depth:
            self._main_depth -= 1
        if (
            tag in {"article", "div", "main", "section"}
            and self._container_hints
            and self._container_hints[-1][0] == tag
        ):
            _, had_hint, had_negative = self._container_hints.pop()
            if had_hint:
                self._hint_depth -= 1
            if had_negative:
                self._negative_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._json_ld_depth:
            self._json_ld_parts.append(data)
            return
        if self._title_depth:
            self.title_parts.append(data)
        if self._h1_depth:
            self._h1_parts.append(data)
        cleaned = _clean_inline(data)
        if cleaned:
            self.visible_parts.append(cleaned)
        if self._paragraph_depth:
            self._paragraph_parts.append(data)

    def _finish_paragraph(self) -> None:
        paragraph = _clean_inline("".join(self._paragraph_parts))
        if len(paragraph) >= 8 and not _is_boilerplate(paragraph):
            self.paragraphs.append((self._paragraph_score, paragraph))
        self._paragraph_depth = 0
        self._paragraph_parts = []
        self._paragraph_score = 0


def extract_article_html(
    document: str,
    *,
    url: str,
    source: OfficialSource | None = None,
) -> ExtractedArticle:
    """Extract article metadata and readable paragraphs from an HTML document."""

    parser = _ArticleHTMLParser()
    parser.feed(document)
    parser.close()
    json_ld = _extract_json_ld(parser.json_ld_documents)

    title = _first_nonempty(
        parser.meta.get("og:title"),
        parser.meta.get("twitter:title"),
        _string_value(json_ld.get("headline")),
        _best_article_heading(parser.h1_candidates),
        _clean_page_title("".join(parser.title_parts)),
    )
    paragraphs = _choose_paragraphs(parser.paragraphs)
    content = normalize_article_text("\n\n".join(paragraphs))
    if not content:
        content = normalize_article_text(_string_value(json_ld.get("articleBody")))

    published_date = normalize_date(
        _first_nonempty(
            parser.meta.get("article:published_time"),
            parser.meta.get("pubdate"),
            parser.meta.get("publishdate"),
            parser.meta.get("date"),
            parser.meta.get("datepublished"),
            _string_value(json_ld.get("datePublished")),
            _find_date(" ".join(parser.visible_parts[:300])),
            _find_date(url),
        )
    )
    description = _first_nonempty(
        parser.meta.get("description"),
        parser.meta.get("og:description"),
        _string_value(json_ld.get("description")),
    )
    canonical = urljoin(url, parser.canonical_url) if parser.canonical_url else url
    try:
        canonical = normalize_url(canonical)
    except ArticleURLValidationError:
        canonical = normalize_url(url)
    if source:
        canonical_source = recognize_source(canonical, {source.id: source})
        if canonical_source is None:
            canonical = normalize_url(url)
    source_name = (
        source.name
        if source
        else _first_nonempty(
            parser.meta.get("source"),
            parser.meta.get("og:site_name"),
            _publisher_name(json_ld),
            "用户导入",
        )
    )
    base_features = source.style_features if source else ()
    features = _merge_style_features(base_features, infer_style_features(content))
    return ExtractedArticle(
        title=title,
        content=content,
        published_date=published_date,
        source_name=source_name,
        url=canonical,
        summary=_clean_inline(description)[:240] if description else summarize_text(content),
        style_features=features,
    )


def recognize_source(
    url: str, sources: Mapping[str, OfficialSource] = OFFICIAL_SOURCES
) -> OfficialSource | None:
    """Resolve a registered source from an exact or subdomain hostname match."""

    try:
        hostname = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    for source in sources.values():
        if any(hostname == domain or hostname.endswith(f".{domain}") for domain in source.domains):
            return source
    return None


def normalize_url(url: str) -> str:
    """Normalize a non-secret HTTP URL while rejecting local-address forms."""

    value = _clean_inline(url)
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise ArticleURLValidationError("文章来源地址格式无效") from exc
    if parts.scheme.lower() not in {"http", "https"}:
        raise ArticleURLValidationError("文章来源地址仅支持 HTTP 或 HTTPS")
    if not parts.hostname or parts.username or parts.password:
        raise ArticleURLValidationError("文章来源地址格式无效")
    hostname = parts.hostname.lower().rstrip(".")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ArticleURLValidationError("文章来源地址必须使用已登记的域名")
    expected_port = 80 if parts.scheme.lower() == "http" else 443
    if port is not None and port != expected_port:
        raise ArticleURLValidationError("文章来源地址使用了与协议不匹配的端口")
    netloc = hostname
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))


def validate_official_url(
    url: str, sources: Mapping[str, OfficialSource] = OFFICIAL_SOURCES
) -> str:
    """Validate and normalize an article URL against registered domains."""

    normalized = normalize_url(url)
    if recognize_source(normalized, sources) is None:
        raise ArticleURLValidationError("文章来源地址不属于已登记的官方来源")
    return normalized


def normalize_article_text(value: str) -> str:
    """Normalize pasted or extracted text without changing its wording."""

    value = html.unescape(value).replace("\u3000", " ").replace("\xa0", " ")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_clean_inline(line) for line in value.split("\n")]
    normalized: list[str] = []
    previous_blank = True
    for line in lines:
        if not line:
            if not previous_blank:
                normalized.append("")
            previous_blank = True
            continue
        if normalized and normalized[-1] == line:
            continue
        normalized.append(line)
        previous_blank = False
    return "\n".join(normalized).strip()


def summarize_text(content: str, *, max_chars: int = 180) -> str:
    """Create a short local extractive summary with a strict character cap."""

    normalized = _clean_inline(content)
    if len(normalized) <= max_chars:
        return normalized
    sentences = re.split(r"(?<=[。！？!?；;])\s*", normalized)
    selected = ""
    for sentence in sentences:
        if not sentence:
            continue
        if selected and len(selected) + len(sentence) > max_chars:
            break
        selected += sentence
        if len(selected) >= max_chars * 2 // 3:
            break
    if not selected:
        selected = normalized[:max_chars]
    visible = selected[:max_chars]
    suffix = "…" if len(normalized) > len(visible) else ""
    return visible.rstrip("，、；;：:") + suffix


def infer_style_features(content: str) -> tuple[str, ...]:
    """Infer abstract structural traits; never reproduce source sentences."""

    normalized = normalize_article_text(content)
    paragraphs = [item for item in normalized.split("\n") if item]
    features: list[str] = []
    if re.search(r"(?:^|\n)[一二三四五六七八九十]+[、，.]", normalized):
        features.append("分层论述")
    if any(marker in normalized for marker in ("首先", "其次", "再次", "一方面", "另一方面")):
        features.append("递进展开")
    if any(marker in normalized for marker in ("数据显示", "截至", "%", "同比", "增长", "下降")):
        features.append("数据支撑")
    if any(marker in normalized for marker in ("指出", "强调", "要求", "部署")):
        features.append("政策表述")
    if paragraphs:
        average_length = sum(len(item) for item in paragraphs) / len(paragraphs)
        features.append("短段凝练" if average_length <= 90 else "长段论证")
    if len(paragraphs) >= 5:
        features.append("多层结构")
    return tuple(features[:6])


def normalize_date(value: str | None) -> str | None:
    """Normalize common publication-date representations to ``YYYY-MM-DD``."""

    if not value:
        return None
    cleaned = _clean_inline(value)
    match = re.search(r"(?<!\d)(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?", cleaned)
    if match:
        year, month, day = (int(part) for part in match.groups())
        try:
            return datetime(year, month, day, tzinfo=UTC).date().isoformat()
        except ValueError:
            return None
    return None


def _record_from_row(row: sqlite3.Row) -> ArticleRecord:
    try:
        raw_features = json.loads(str(row["style_features_json"]))
    except json.JSONDecodeError:
        raw_features = []
    features = [str(item) for item in raw_features] if isinstance(raw_features, list) else []
    return ArticleRecord(
        id=str(row["id"]),
        title=str(row["title"]),
        content=str(row["content"]),
        source_id=str(row["source_id"]),
        source_name=str(row["source_name"]),
        url=str(row["url"]) if row["url"] is not None else None,
        published_date=(str(row["published_date"]) if row["published_date"] is not None else None),
        summary=str(row["summary"]),
        style_features=features,
        content_hash=str(row["content_hash"]),
        import_method="url" if str(row["import_method"]) == "url" else "manual",
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _summary_from_row(row: sqlite3.Row) -> ArticleSummary:
    try:
        raw_features = json.loads(str(row["style_features_json"]))
    except json.JSONDecodeError:
        raw_features = []
    features = [str(item) for item in raw_features] if isinstance(raw_features, list) else []
    return ArticleSummary(
        id=str(row["id"]),
        title=str(row["title"]),
        source_id=str(row["source_id"]),
        source_name=str(row["source_name"]),
        url=str(row["url"]) if row["url"] is not None else None,
        published_date=(str(row["published_date"]) if row["published_date"] is not None else None),
        summary=str(row["summary"]),
        excerpt=_clean_inline(str(row["excerpt"]))[:220],
        style_features=features,
        import_method="url" if str(row["import_method"]) == "url" else "manual",
        updated_at=str(row["updated_at"]),
        score=int(row["score"]),
    )


def _summary_from_record(record: ArticleRecord, *, excerpt: str, score: int = 0) -> ArticleSummary:
    return ArticleSummary(
        id=record.id,
        title=record.title,
        source_id=record.source_id,
        source_name=record.source_name,
        url=record.url,
        published_date=record.published_date,
        summary=record.summary,
        excerpt=_clean_inline(excerpt)[:220],
        style_features=list(record.style_features),
        import_method=record.import_method,
        updated_at=record.updated_at,
        score=score,
    )


def _query_terms(query: str) -> tuple[str, ...]:
    terms = [
        item.casefold() for item in re.split(r"[\s,，。；;、：:!?！？/]+", query) if item.strip()
    ]
    return tuple(dict.fromkeys(terms))


def _search_score(record: ArticleRecord, terms: Sequence[str]) -> int:
    return _search_score_fields(
        title=record.title,
        summary=record.summary,
        source_name=record.source_name,
        style_features=record.style_features,
        content=record.content,
        terms=terms,
    )


def _search_score_fields(
    *,
    title: str,
    summary: str,
    source_name: str,
    style_features: Sequence[str],
    content: str,
    terms: Sequence[str],
) -> int:
    if not terms:
        return 0
    title = title.casefold()
    summary = summary.casefold()
    metadata = " ".join((source_name, *style_features)).casefold()
    content = content.casefold()
    if not all(
        term in title or term in summary or term in metadata or term in content for term in terms
    ):
        return 0
    return sum(
        title.count(term) * 12
        + summary.count(term) * 5
        + metadata.count(term) * 3
        + min(content.count(term), 8)
        for term in terms
    )


def _sqlite_search_score(
    title: object,
    summary: object,
    source_name: object,
    style_features_json: object,
    content: object,
    terms_json: object,
) -> int:
    return _search_score_fields(
        title=_sqlite_text(title),
        summary=_sqlite_text(summary),
        source_name=_sqlite_text(source_name),
        style_features=_sqlite_string_list(style_features_json),
        content=_sqlite_text(content),
        terms=_sqlite_string_list(terms_json),
    )


def _sqlite_search_excerpt(content: object, terms_json: object) -> str:
    return _search_excerpt(_sqlite_text(content), _sqlite_string_list(terms_json))


def _sqlite_string_list(value: object) -> tuple[str, ...]:
    try:
        decoded = json.loads(_sqlite_text(value))
    except json.JSONDecodeError:
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(str(item) for item in decoded)


def _sqlite_text(value: object) -> str:
    return value if isinstance(value, str) else "" if value is None else str(value)


def _search_excerpt(content: str, terms: Sequence[str], *, max_chars: int = 180) -> str:
    inline = _clean_inline(content)
    if not inline:
        return ""
    positions = [inline.casefold().find(term) for term in terms]
    positions = [position for position in positions if position >= 0]
    if not positions or len(inline) <= max_chars:
        return inline[:max_chars]
    start = max(0, min(positions) - max_chars // 3)
    end = min(len(inline), start + max_chars)
    prefix = "…" if start else ""
    suffix = "…" if end < len(inline) else ""
    return prefix + inline[start:end].strip() + suffix


def _validate_pagination(limit: int, offset: int) -> None:
    if limit < 1 or limit > 200:
        raise ArticleLibraryError("limit 必须在 1 到 200 之间")
    if offset < 0:
        raise ArticleLibraryError("offset 不能小于 0")


def _choose_paragraphs(paragraphs: Sequence[tuple[int, str]]) -> list[str]:
    if not paragraphs:
        return []
    preferred = [text for score, text in paragraphs if score > 0]
    if sum(len(item) for item in preferred) < 80:
        preferred = [text for score, text in paragraphs if score >= 0]
    result: list[str] = []
    seen: set[str] = set()
    for paragraph in preferred:
        fingerprint = re.sub(r"\s+", "", paragraph)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append(paragraph)
    return result


def _extract_json_ld(documents: Sequence[str]) -> dict[str, object]:
    for raw in documents:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidates: list[object] = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            graph = candidate.get("@graph")
            nested = graph if isinstance(graph, list) else [candidate]
            for item in nested:
                if not isinstance(item, dict):
                    continue
                kind = item.get("@type")
                kinds = kind if isinstance(kind, list) else [kind]
                if any(
                    str(entry).lower() in {"article", "newsarticle", "reportagearticle"}
                    for entry in kinds
                ):
                    return {str(key): val for key, val in item.items()}
    return {}


def _publisher_name(value: Mapping[str, object]) -> str:
    publisher = value.get("publisher")
    if isinstance(publisher, dict):
        return _string_value(publisher.get("name"))
    return ""


def _string_value(value: object) -> str:
    return value if isinstance(value, str) else ""


def _is_json_ld(attrs: Mapping[str, str]) -> bool:
    return attrs.get("type", "").lower().split(";", 1)[0].strip() == "application/ld+json"


def _is_html_content_type(value: str) -> bool:
    media_type = value.lower().split(";", 1)[0].strip()
    return media_type in {"text/html", "application/xhtml+xml"}


def _decode_html(body: bytes, content_type: str) -> str:
    match = re.search(r"charset\s*=\s*[\"']?([^\s;\"']+)", content_type, re.IGNORECASE)
    encodings = [match.group(1)] if match else []
    prefix = body[:2048].decode("ascii", errors="ignore")
    meta_match = re.search(r"charset\s*=\s*[\"']?([^\s;\"'>]+)", prefix, re.IGNORECASE)
    if meta_match:
        encodings.append(meta_match.group(1))
    encodings.extend(("utf-8", "gb18030"))
    for encoding in dict.fromkeys(encodings):
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def _find_date(value: str) -> str:
    match = re.search(r"20\d{2}[年./-]\d{1,2}[月./-]\d{1,2}日?", value)
    return match.group(0) if match else ""


def _clean_page_title(value: str) -> str:
    cleaned = _clean_inline(value)
    return re.split(r"\s*[-_|—]\s*(?:人民网|光明网|求是网).*$", cleaned)[0].strip()


def _best_article_heading(candidates: Sequence[str]) -> str:
    """Choose one real article heading instead of concatenating every page H1."""

    return next(
        (
            cleaned
            for value in candidates
            if (cleaned := _clean_inline(value)) and not _is_boilerplate(cleaned)
        ),
        "",
    )


def _clean_inline(value: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _first_nonempty(*values: str | None) -> str:
    return next((_clean_inline(value) for value in values if _clean_inline(value)), "")


def _merge_style_features(*groups: Sequence[str]) -> tuple[str, ...]:
    merged: list[str] = []
    for value in (item for group in groups for item in group):
        cleaned = _clean_inline(value)
        if cleaned and cleaned not in merged:
            merged.append(cleaned[:40])
    return tuple(merged[:10])


def _is_boilerplate(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    return len(compact) < 8 or any(
        marker in compact
        for marker in (
            "责任编辑：",
            "版权声明",
            "未经许可",
            "分享到",
            "客户端下载",
            "网站地图",
            "联系我们",
        )
    )


__all__ = [
    "OFFICIAL_SOURCES",
    "ArticleFetchError",
    "ArticleFetcher",
    "ArticleIdentity",
    "ArticleIdentityRepository",
    "ArticleLibrary",
    "ArticleLibraryError",
    "ArticleRecord",
    "ArticleRepository",
    "ArticleSearchPage",
    "ArticleSummary",
    "ArticleSummaryRepository",
    "ArticleURLValidationError",
    "ExtractedArticle",
    "FetchedArticlePage",
    "FetchedPage",
    "FetchedPageLike",
    "HTTPArticleFetcher",
    "HostResolver",
    "OfficialSource",
    "SQLiteArticleRepository",
    "SystemHostResolver",
    "extract_article_html",
    "infer_style_features",
    "normalize_article_text",
    "normalize_date",
    "normalize_url",
    "recognize_source",
    "summarize_text",
    "validate_official_url",
]
