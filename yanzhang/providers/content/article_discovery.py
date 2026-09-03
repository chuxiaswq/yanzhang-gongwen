"""Provider-neutral contracts for discovering official publication articles.

Discovery implementations may use search pages, feeds, or a separately configured
search service.  The application layer sees only these immutable value objects and
never performs network I/O itself.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable


class ArticleDiscoveryError(ValueError):
    """Raised when a discovery adapter cannot complete a scoped lookup."""


@dataclass(frozen=True, slots=True)
class ArticleDiscoveryQuery:
    """Normalized search scope passed to an article-discovery adapter."""

    keywords: tuple[str, ...]
    source_ids: tuple[str, ...]
    start_date: date | None
    end_date: date | None
    limit: int


@dataclass(frozen=True, slots=True)
class DiscoveredArticle:
    """One traceable candidate returned by a discovery adapter."""

    url: str
    source_id: str
    title: str | None = None
    published_date: date | None = None
    summary: str | None = None
    channel: str | None = None
    content: str | None = None
    original_url: str | None = None


@dataclass(frozen=True, slots=True)
class ArticleDiscoveryFailure:
    """One source-scoped failure that did not stop the remaining sources."""

    source_id: str
    message: str
    code: str = "discovery_failed"


@dataclass(frozen=True, slots=True)
class ArticleDiscoveryBatch:
    """Candidates plus isolated source failures from one discovery call."""

    articles: tuple[DiscoveredArticle, ...] = ()
    failures: tuple[ArticleDiscoveryFailure, ...] = ()


@runtime_checkable
class ArticleDiscoveryProvider(Protocol):
    """Boundary implemented by live and deterministic article discoverers."""

    async def discover(
        self,
        query: ArticleDiscoveryQuery,
    ) -> ArticleDiscoveryBatch | Sequence[DiscoveredArticle]:
        """Return candidates for a fully normalized, bounded query."""


class EmptyArticleDiscoveryProvider:
    """Offline-safe default that discovers no remote candidates."""

    async def discover(
        self,
        query: ArticleDiscoveryQuery,
    ) -> ArticleDiscoveryBatch | Sequence[DiscoveredArticle]:
        del query
        return ()


__all__ = [
    "ArticleDiscoveryBatch",
    "ArticleDiscoveryError",
    "ArticleDiscoveryFailure",
    "ArticleDiscoveryProvider",
    "ArticleDiscoveryQuery",
    "DiscoveredArticle",
    "EmptyArticleDiscoveryProvider",
]
