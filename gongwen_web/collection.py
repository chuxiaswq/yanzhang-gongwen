"""Scoped orchestration for discovering and importing reference articles.

The service deliberately owns no HTTP client.  Candidate discovery goes through an
injected provider and page acquisition remains inside ``ArticleLibrary``'s injected
fetch adapter, so tests can exercise the complete state machine without public
network access.
"""

# Chinese user-facing messages intentionally use full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from gongwen_web.articles import (
    OFFICIAL_SOURCES,
    ArticleIdentity,
    ArticleLibraryError,
    ArticleRecord,
    ArticleSummary,
    ArticleURLValidationError,
    FetchedArticlePage,
    OfficialSource,
    normalize_url,
    recognize_source,
    validate_official_url,
)
from gongwen_web.resource_limits import (
    ARTICLE_COLLECTION_BATCH_TIMEOUT_SECONDS,
    ARTICLE_COLLECTION_DISCOVERY_TIMEOUT_SECONDS,
    ARTICLE_COLLECTION_ITEM_TIMEOUT_SECONDS,
    ARTICLE_COLLECTION_MAX_BATCH_TIMEOUT_SECONDS,
    ARTICLE_COLLECTION_MAX_DISCOVERY_TIMEOUT_SECONDS,
    ARTICLE_COLLECTION_MAX_ITEM_TIMEOUT_SECONDS,
)
from yanzhang.providers.content.article_discovery import (
    ArticleDiscoveryBatch,
    ArticleDiscoveryFailure,
    ArticleDiscoveryProvider,
    ArticleDiscoveryQuery,
    DiscoveredArticle,
)

_BEARER_PATTERN = re.compile(r"(?i)bearer\s+[^\s,;]+")
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|authorization|secret)\s*[:=]\s*[^\s,;]+"
)
_KEY_PATTERN = re.compile(r"\b(?:sk|key|token)-[A-Za-z0-9._-]{8,}\b", re.IGNORECASE)
_URL_PATTERN = re.compile(r"https?://[^\s\]\[(){}<>]+", re.IGNORECASE)
_PATH_PATTERN = re.compile(
    r"(?:(?<![A-Za-z0-9])/(?:[^/\s:;,]+/)+[^/\s:;,]+|"
    r"[A-Za-z]:\\(?:[^\\\s:;,]+\\)+[^\\\s:;,]+)"
)
_PEOPLE_INSECURE_DISABLED_MESSAGE = (
    "人民网自动检索默认关闭；如确需使用，请显式设置 "
    "GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH=true。该检索接口使用 HTTP，"
    "检索关键词与日期范围会以明文传输。"
)


class ArticleCollectionError(ValueError):
    """Raised when an automatic collection scope is invalid."""


@dataclass(frozen=True, slots=True)
class ArticleCollectionScope:
    """Normalized, inclusive search range for one bounded collection run."""

    keywords: tuple[str, ...]
    source_ids: tuple[str, ...]
    start_date: date | None = None
    end_date: date | None = None
    limit: int = 20

    @classmethod
    def create(
        cls,
        *,
        keywords: Sequence[str],
        source_ids: Sequence[str],
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 20,
        registered_sources: Mapping[str, OfficialSource] = OFFICIAL_SOURCES,
    ) -> ArticleCollectionScope:
        """Validate and normalize API or programmatic scope values."""

        normalized_keywords = _unique_nonempty(keywords)
        normalized_sources = _unique_nonempty(source_ids)
        if not normalized_keywords:
            raise ArticleCollectionError("至少需要提供一个检索关键词")
        if len(normalized_keywords) > 20:
            raise ArticleCollectionError("检索关键词最多为 20 个")
        if any(len(keyword) > 100 for keyword in normalized_keywords):
            raise ArticleCollectionError("单个检索关键词不能超过 100 个字符")
        if not normalized_sources:
            raise ArticleCollectionError("至少需要选择一个文章来源")
        unknown_sources = [item for item in normalized_sources if item not in registered_sources]
        if unknown_sources:
            raise ArticleCollectionError(f"文章来源标识未登记：{', '.join(unknown_sources)}")
        if limit < 1 or limit > 100:
            raise ArticleCollectionError("limit 必须在 1 到 100 之间")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ArticleCollectionError("start_date 不能晚于 end_date")
        return cls(
            keywords=normalized_keywords,
            source_ids=normalized_sources,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )


class _CollectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


type CollectionItemStatus = Literal["imported", "duplicate", "skipped", "failed"]


class ArticleCollectionItem(_CollectionModel):
    """Machine-readable status for one discovered candidate."""

    index: int = Field(ge=0)
    status: CollectionItemStatus
    reason_code: str
    url: str
    source_id: str
    article_id: str | None = None
    title: str | None = None
    published_date: str | None = None
    discovery_channel: str | None = None
    message: str


class ArticleCollectionSourceError(_CollectionModel):
    """A source-specific discovery failure reported without aborting the batch."""

    source_id: str
    status: Literal["failed"] = "failed"
    reason_code: str
    message: str


class ArticleCollectionResult(_CollectionModel):
    """Aggregate and per-item outcome of one automatic collection run."""

    keywords: list[str]
    source_ids: list[str]
    start_date: str | None
    end_date: str | None
    limit: int
    discovered_count: int = Field(ge=0)
    imported_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    source_error_count: int = Field(ge=0)
    items: list[ArticleCollectionItem]
    source_errors: list[ArticleCollectionSourceError]

    def to_dict(self) -> dict[str, object]:
        """Serialize the batch result for an API response."""

        return dict(self.model_dump(mode="json"))


class ArticleImportLibrary(Protocol):
    """Minimal local-library surface needed by the collector."""

    async def fetch_url_import(
        self,
        url: str,
        *,
        source_id: str | None = None,
        style_features: Sequence[str] = (),
    ) -> FetchedArticlePage:
        """Acquire one validated official URL without parsing or persistence."""

    def prepare_url_import(self, acquired: FetchedArticlePage) -> ArticleRecord:
        """Parse a fetched page without touching persistence."""

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
        """Normalize provider-returned text without touching persistence."""

    def persist_prepared_import(self, record: ArticleRecord) -> ArticleRecord:
        """Persist one prepared record."""

    def get_article(self, article_id: str) -> ArticleRecord | None:
        """Return one locally stored record."""

    def list_articles(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        source_id: str | None = None,
    ) -> list[ArticleSummary]:
        """Return a bounded page of local records."""

    def delete_article(self, article_id: str) -> bool:
        """Delete a newly imported out-of-scope or duplicate record."""


@runtime_checkable
class ArticleIdentityLibrary(Protocol):
    """Optional lightweight collection de-duplication fast path."""

    def article_identity_index(self) -> list[ArticleIdentity]:
        """Return IDs, URLs, and content hashes without article bodies."""


@dataclass(frozen=True, slots=True)
class _PreparedCandidate:
    index: int
    candidate: DiscoveredArticle
    source_id: str
    url: str
    original_url: str | None


@dataclass(frozen=True, slots=True)
class _CandidateAcquisition:
    prepared: _PreparedCandidate
    record: ArticleRecord | None = None
    used_discovery_content: bool = False
    failure: ArticleCollectionItem | None = None


class ArticleCollectionService:
    """Discover, validate, de-duplicate and import a bounded article batch."""

    def __init__(
        self,
        library: ArticleImportLibrary,
        discovery: ArticleDiscoveryProvider,
        *,
        sources: Mapping[str, OfficialSource] = OFFICIAL_SOURCES,
        discovery_timeout_seconds: float = ARTICLE_COLLECTION_DISCOVERY_TIMEOUT_SECONDS,
        item_timeout_seconds: float = ARTICLE_COLLECTION_ITEM_TIMEOUT_SECONDS,
        batch_timeout_seconds: float = ARTICLE_COLLECTION_BATCH_TIMEOUT_SECONDS,
    ) -> None:
        _validate_timeout(
            "discovery_timeout_seconds",
            discovery_timeout_seconds,
            maximum=ARTICLE_COLLECTION_MAX_DISCOVERY_TIMEOUT_SECONDS,
        )
        _validate_timeout(
            "item_timeout_seconds",
            item_timeout_seconds,
            maximum=ARTICLE_COLLECTION_MAX_ITEM_TIMEOUT_SECONDS,
        )
        _validate_timeout(
            "batch_timeout_seconds",
            batch_timeout_seconds,
            maximum=ARTICLE_COLLECTION_MAX_BATCH_TIMEOUT_SECONDS,
        )
        self._library = library
        self._discovery = discovery
        self._sources = dict(sources)
        self._discovery_timeout_seconds = discovery_timeout_seconds
        self._item_timeout_seconds = item_timeout_seconds
        self._batch_timeout_seconds = batch_timeout_seconds
        # One service instance owns one local article repository. Serializing
        # batches and candidates keeps the identity snapshot coherent because
        # ArticleLibrary.import_url combines acquisition with persistence.
        self._collection_lock = asyncio.Lock()

    async def collect(self, scope: ArticleCollectionScope) -> ArticleCollectionResult:
        """Run one provider-neutral collection operation with per-item outcomes."""

        normalized_scope = ArticleCollectionScope.create(
            keywords=scope.keywords,
            source_ids=scope.source_ids,
            start_date=scope.start_date,
            end_date=scope.end_date,
            limit=scope.limit,
            registered_sources=self._sources,
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._batch_timeout_seconds
        try:
            await asyncio.wait_for(
                self._collection_lock.acquire(),
                timeout=self._remaining(deadline),
            )
        except TimeoutError:
            return _collection_result(
                normalized_scope,
                (),
                _scope_errors(
                    normalized_scope,
                    reason_code="collection_timeout",
                    message="本次文章收集在等待本地资料库时超过整批时限",
                ),
            )
        try:
            return await self._collect_locked(normalized_scope, deadline=deadline)
        finally:
            self._collection_lock.release()

    async def _collect_locked(
        self,
        scope: ArticleCollectionScope,
        *,
        deadline: float,
    ) -> ArticleCollectionResult:
        query = ArticleDiscoveryQuery(
            keywords=scope.keywords,
            source_ids=scope.source_ids,
            start_date=scope.start_date,
            end_date=scope.end_date,
            limit=scope.limit,
        )
        discovery_timeout = min(
            self._discovery_timeout_seconds,
            self._remaining(deadline),
        )
        try:
            discovered = await asyncio.wait_for(
                self._discovery.discover(query),
                timeout=discovery_timeout,
            )
        except TimeoutError:
            return _collection_result(
                scope,
                (),
                _scope_errors(
                    scope,
                    reason_code="discovery_timeout",
                    message="文章来源检索超过本次运行时限",
                ),
            )
        except Exception as exc:
            return _collection_result(
                scope,
                (),
                _scope_errors(
                    scope,
                    reason_code="discovery_failed",
                    message=_bounded_message(exc),
                ),
            )

        candidates: Sequence[DiscoveredArticle]
        if isinstance(discovered, ArticleDiscoveryBatch):
            candidates = discovered.articles
            source_errors = [_source_error(item) for item in discovered.failures]
        else:
            candidates = discovered
            source_errors = []
        bounded_candidates = tuple(candidates[: scope.limit])
        if not bounded_candidates:
            return _collection_result(scope, (), source_errors)
        try:
            existing = await asyncio.to_thread(self._existing_index)
        except Exception as exc:
            index_failure_items = [
                _item(
                    index,
                    "failed",
                    "local_index_failed",
                    candidate.url.strip(),
                    candidate.source_id.strip(),
                    candidate,
                    message=_bounded_message(exc),
                )
                for index, candidate in enumerate(bounded_candidates)
            ]
            return _collection_result(scope, index_failure_items, source_errors)
        if asyncio.get_running_loop().time() >= deadline:
            index_timeout_items = [
                _item(
                    index,
                    "failed",
                    "collection_timeout",
                    candidate.url.strip(),
                    candidate.source_id.strip(),
                    candidate,
                    message="读取本地资料库索引超过整批时限",
                )
                for index, candidate in enumerate(bounded_candidates)
            ]
            return _collection_result(scope, index_timeout_items, source_errors)

        items: list[ArticleCollectionItem] = []
        for index, candidate in enumerate(bounded_candidates):
            prepared_or_item = self._prepare_candidate(
                index=index,
                candidate=candidate,
                scope=scope,
                existing=existing,
            )
            if isinstance(prepared_or_item, ArticleCollectionItem):
                items.append(prepared_or_item)
                continue
            outcome = await self._acquire_bounded_candidate(
                prepared_or_item,
                deadline=deadline,
            )
            try:
                finalized = await asyncio.to_thread(
                    self._finalize_candidate,
                    outcome,
                    scope=scope,
                    existing=existing,
                )
            except Exception as exc:
                finalized = _failure_item(
                    outcome.prepared,
                    reason_code="finalize_failed",
                    message=_bounded_message(exc),
                )
            items.append(finalized)
        return _collection_result(scope, items, source_errors)

    def _prepare_candidate(
        self,
        *,
        index: int,
        candidate: DiscoveredArticle,
        scope: ArticleCollectionScope,
        existing: _ExistingArticleIndex,
    ) -> ArticleCollectionItem | _PreparedCandidate:
        source_id = candidate.source_id.strip()
        raw_url = candidate.url.strip()
        try:
            url = validate_official_url(raw_url, self._sources)
            recognized = recognize_source(url, self._sources)
        except ArticleURLValidationError as exc:
            return _item(
                index,
                "failed",
                "invalid_url",
                raw_url,
                source_id,
                candidate,
                message=str(exc),
            )
        if recognized is None or source_id != recognized.id:
            return _item(
                index,
                "failed",
                "source_mismatch",
                url,
                source_id,
                candidate,
                message="发现结果的来源标识与文章地址不一致",
            )
        if source_id not in scope.source_ids:
            return _item(
                index,
                "skipped",
                "source_out_of_scope",
                url,
                source_id,
                candidate,
                message="文章来源不在本次选择范围内",
            )
        if candidate.published_date is not None and not _date_in_scope(
            candidate.published_date, scope
        ):
            return _item(
                index,
                "skipped",
                "date_out_of_scope",
                url,
                source_id,
                candidate,
                message="文章日期不在本次起止日期范围内",
            )
        try:
            original_url = normalize_url(candidate.original_url) if candidate.original_url else None
        except ArticleURLValidationError as exc:
            return _item(
                index,
                "failed",
                "invalid_original_url",
                url,
                source_id,
                candidate,
                message=_bounded_message(exc),
            )
        duplicate_id = existing.by_url.get(url)
        if duplicate_id is None and original_url is not None:
            duplicate_id = existing.by_url.get(original_url)
        if duplicate_id is not None:
            return _item(
                index,
                "duplicate",
                "duplicate_url",
                url,
                source_id,
                candidate,
                article_id=duplicate_id,
                message="文章地址已存在于本地资料库",
            )

        return _PreparedCandidate(
            index=index,
            candidate=candidate,
            source_id=source_id,
            url=url,
            original_url=original_url,
        )

    async def _acquire_bounded_candidate(
        self,
        prepared: _PreparedCandidate,
        *,
        deadline: float,
    ) -> _CandidateAcquisition:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return _acquisition_failure(
                prepared,
                reason_code="collection_timeout",
                message="文章获取超过本次整批运行时限",
            )
        try:
            acquisition = await asyncio.wait_for(
                self._acquire_candidate(prepared),
                timeout=min(self._item_timeout_seconds, remaining),
            )
        except TimeoutError:
            batch_expired = asyncio.get_running_loop().time() >= deadline
            return _acquisition_failure(
                prepared,
                reason_code="collection_timeout" if batch_expired else "import_timeout",
                message=(
                    "文章获取超过本次整批运行时限" if batch_expired else "单篇文章获取超过运行时限"
                ),
            )
        except Exception as exc:
            return _acquisition_failure(
                prepared,
                reason_code="import_failed",
                message=_bounded_message(exc),
            )
        if acquisition.failure is not None:
            return acquisition
        if asyncio.get_running_loop().time() >= deadline:
            return _acquisition_failure(
                prepared,
                reason_code="collection_timeout",
                message="文章解析超过本次整批运行时限",
            )
        record = acquisition.record
        if record is None:
            return _acquisition_failure(
                prepared,
                reason_code="import_failed",
                message="文章导入准备阶段未返回可用结果",
            )
        try:
            persisted = await asyncio.to_thread(self._library.persist_prepared_import, record)
        except Exception as exc:
            return _acquisition_failure(
                prepared,
                reason_code="import_failed",
                message=_bounded_message(exc),
            )
        return _CandidateAcquisition(
            prepared=prepared,
            record=persisted,
            used_discovery_content=acquisition.used_discovery_content,
        )

    async def _acquire_candidate(
        self,
        prepared: _PreparedCandidate,
    ) -> _CandidateAcquisition:
        candidate = prepared.candidate

        used_discovery_content = False
        try:
            acquired = await self._library.fetch_url_import(
                prepared.url,
                source_id=prepared.source_id,
            )
            record = await asyncio.to_thread(self._library.prepare_url_import, acquired)
        except ArticleLibraryError as exc:
            if not candidate.title or not candidate.content:
                return _acquisition_failure(
                    prepared,
                    reason_code="import_failed",
                    message=_bounded_message(exc),
                )
            try:
                record = await asyncio.to_thread(
                    self._library.prepare_text_import,
                    title=candidate.title,
                    content=candidate.content,
                    source_id=prepared.source_id,
                    url=prepared.original_url or prepared.url,
                    published_date=_date_text(candidate.published_date),
                    summary=candidate.summary,
                )
            except ArticleLibraryError as fallback_exc:
                return _acquisition_failure(
                    prepared,
                    reason_code="import_failed",
                    message=_bounded_message(fallback_exc),
                )
            used_discovery_content = True

        return _CandidateAcquisition(
            prepared=prepared,
            record=record,
            used_discovery_content=used_discovery_content,
        )

    def _finalize_candidate(
        self,
        acquisition: _CandidateAcquisition,
        *,
        scope: ArticleCollectionScope,
        existing: _ExistingArticleIndex,
    ) -> ArticleCollectionItem:
        prepared = acquisition.prepared
        candidate = prepared.candidate
        if acquisition.failure is not None:
            return acquisition.failure
        record = acquisition.record
        if record is None:
            return _failure_item(
                prepared,
                reason_code="import_failed",
                message="文章导入过程未返回可用结果",
            )

        if record.id in existing.ids:
            existing.by_url[prepared.url] = record.id
            return _item_from_record(
                prepared.index,
                "duplicate",
                "duplicate_url",
                record,
                discovery_channel=candidate.channel,
                message="文章已通过规范地址存在于本地资料库",
            )
        content_duplicate_id = existing.by_hash.get(record.content_hash)
        if content_duplicate_id is not None and content_duplicate_id != record.id:
            self._library.delete_article(record.id)
            existing.by_url[prepared.url] = content_duplicate_id
            return _item_from_record(
                prepared.index,
                "duplicate",
                "duplicate_content",
                record,
                article_id=content_duplicate_id,
                discovery_channel=candidate.channel,
                message="文章正文与本地资料库中的内容重复",
            )

        effective_date = _record_date(record) or candidate.published_date
        if (scope.start_date is not None or scope.end_date is not None) and effective_date is None:
            self._library.delete_article(record.id)
            return _item_from_record(
                prepared.index,
                "skipped",
                "date_missing",
                record,
                discovery_channel=candidate.channel,
                message="文章缺少可核验的发布日期，未纳入指定日期范围",
            )
        if effective_date is not None and not _date_in_scope(effective_date, scope):
            self._library.delete_article(record.id)
            return _item_from_record(
                prepared.index,
                "skipped",
                "date_out_of_scope",
                record,
                discovery_channel=candidate.channel,
                message="文章发布日期不在本次起止日期范围内",
            )
        if not _matches_keywords(record, candidate, scope.keywords):
            self._library.delete_article(record.id)
            return _item_from_record(
                prepared.index,
                "skipped",
                "keyword_out_of_scope",
                record,
                discovery_channel=candidate.channel,
                message="文章内容未命中本次检索关键词",
            )

        existing.add(record, requested_url=prepared.url)
        return _item_from_record(
            prepared.index,
            "imported",
            "imported_from_discovery" if acquisition.used_discovery_content else "imported",
            record,
            discovery_channel=candidate.channel,
            message=(
                "文章已使用官方检索返回的正文导入本地资料库"
                if acquisition.used_discovery_content
                else "文章已导入本地资料库"
            ),
        )

    @staticmethod
    def _remaining(deadline: float) -> float:
        return max(0.000_001, deadline - asyncio.get_running_loop().time())

    def _existing_index(self) -> _ExistingArticleIndex:
        index = _ExistingArticleIndex()
        if isinstance(self._library, ArticleIdentityLibrary):
            for identity in self._library.article_identity_index():
                index.add_identity(identity)
            return index
        offset = 0
        page_size = 200
        while True:
            summaries = self._library.list_articles(limit=page_size, offset=offset)
            for summary in summaries:
                record = self._library.get_article(summary.id)
                if record is not None:
                    index.add(record)
            if len(summaries) < page_size:
                return index
            offset += page_size


@dataclass(slots=True)
class _ExistingArticleIndex:
    by_url: dict[str, str]
    by_hash: dict[str, str]
    ids: set[str]

    def __init__(self) -> None:
        self.by_url = {}
        self.by_hash = {}
        self.ids = set()

    def add(self, record: ArticleRecord, *, requested_url: str | None = None) -> None:
        self.add_identity(
            ArticleIdentity(
                id=record.id,
                url=record.url,
                content_hash=record.content_hash,
            )
        )
        if requested_url:
            self.by_url[requested_url] = record.id

    def add_identity(self, identity: ArticleIdentity) -> None:
        """Index one lightweight identity without retaining article text."""

        self.ids.add(identity.id)
        self.by_hash.setdefault(identity.content_hash, identity.id)
        if identity.url:
            self.by_url[normalize_url(identity.url)] = identity.id


def _acquisition_failure(
    prepared: _PreparedCandidate,
    *,
    reason_code: str,
    message: str,
) -> _CandidateAcquisition:
    return _CandidateAcquisition(
        prepared=prepared,
        failure=_failure_item(
            prepared,
            reason_code=reason_code,
            message=message,
        ),
    )


def _failure_item(
    prepared: _PreparedCandidate,
    *,
    reason_code: str,
    message: str,
) -> ArticleCollectionItem:
    return _item(
        prepared.index,
        "failed",
        reason_code,
        prepared.url,
        prepared.source_id,
        prepared.candidate,
        message=message,
    )


def _scope_errors(
    scope: ArticleCollectionScope,
    *,
    reason_code: str,
    message: str,
) -> list[ArticleCollectionSourceError]:
    return [
        ArticleCollectionSourceError(
            source_id=source_id,
            reason_code=reason_code,
            message=message,
        )
        for source_id in scope.source_ids
    ]


def _collection_result(
    scope: ArticleCollectionScope,
    items: Sequence[ArticleCollectionItem],
    source_errors: Sequence[ArticleCollectionSourceError],
) -> ArticleCollectionResult:
    counts = {status: 0 for status in ("imported", "duplicate", "skipped", "failed")}
    for item in items:
        counts[item.status] += 1
    return ArticleCollectionResult(
        keywords=list(scope.keywords),
        source_ids=list(scope.source_ids),
        start_date=_date_text(scope.start_date),
        end_date=_date_text(scope.end_date),
        limit=scope.limit,
        discovered_count=len(items),
        imported_count=counts["imported"],
        duplicate_count=counts["duplicate"],
        skipped_count=counts["skipped"],
        failed_count=counts["failed"] + len(source_errors),
        source_error_count=len(source_errors),
        items=list(items),
        source_errors=list(source_errors),
    )


def _item(
    index: int,
    status: CollectionItemStatus,
    reason_code: str,
    url: str,
    source_id: str,
    candidate: DiscoveredArticle,
    *,
    article_id: str | None = None,
    message: str,
) -> ArticleCollectionItem:
    return ArticleCollectionItem(
        index=index,
        status=status,
        reason_code=reason_code,
        url=url,
        source_id=source_id,
        article_id=article_id,
        title=candidate.title,
        published_date=_date_text(candidate.published_date),
        discovery_channel=candidate.channel,
        message=message,
    )


def _item_from_record(
    index: int,
    status: CollectionItemStatus,
    reason_code: str,
    record: ArticleRecord,
    *,
    article_id: str | None = None,
    discovery_channel: str | None = None,
    message: str,
) -> ArticleCollectionItem:
    return ArticleCollectionItem(
        index=index,
        status=status,
        reason_code=reason_code,
        url=record.url or "",
        source_id=record.source_id,
        article_id=article_id or record.id,
        title=record.title,
        published_date=record.published_date,
        discovery_channel=discovery_channel,
        message=message,
    )


def _source_error(failure: ArticleDiscoveryFailure) -> ArticleCollectionSourceError:
    message = (
        _PEOPLE_INSECURE_DISABLED_MESSAGE
        if failure.code == "insecure_transport_disabled"
        else _bounded_message(ArticleCollectionError(failure.message))
    )
    return ArticleCollectionSourceError(
        source_id=failure.source_id,
        reason_code=failure.code,
        message=message,
    )


def _unique_nonempty(values: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return tuple(result)


def _validate_timeout(name: str, value: float, *, maximum: float) -> None:
    if not math.isfinite(value) or value <= 0 or value > maximum:
        raise ValueError(f"{name} 必须是大于 0 且不超过 {maximum:g} 的有限数值")


def _matches_keywords(
    record: ArticleRecord,
    candidate: DiscoveredArticle,
    keywords: Sequence[str],
) -> bool:
    text = "\n".join(
        (
            record.title,
            record.summary,
            record.content,
            candidate.title or "",
            candidate.summary or "",
        )
    ).casefold()
    return any(keyword.casefold() in text for keyword in keywords)


def _record_date(record: ArticleRecord) -> date | None:
    if not record.published_date:
        return None
    try:
        return date.fromisoformat(record.published_date)
    except ValueError:
        return None


def _date_in_scope(value: date, scope: ArticleCollectionScope) -> bool:
    if scope.start_date is not None and value < scope.start_date:
        return False
    return scope.end_date is None or value <= scope.end_date


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _bounded_message(error: Exception) -> str:
    message = " ".join(str(error).split())
    message = _BEARER_PATTERN.sub("Bearer [REDACTED]", message)
    message = _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", message)
    message = _KEY_PATTERN.sub("[REDACTED]", message)
    message = _URL_PATTERN.sub("[URL]", message)
    message = _PATH_PATTERN.sub("[PATH]", message)
    return message[:300] or "文章导入过程未返回可用结果"


__all__ = [
    "ArticleCollectionError",
    "ArticleCollectionItem",
    "ArticleCollectionResult",
    "ArticleCollectionScope",
    "ArticleCollectionService",
    "ArticleCollectionSourceError",
    "ArticleIdentityLibrary",
    "ArticleImportLibrary",
    "CollectionItemStatus",
]
