"""Content acquisition adapters."""

from yanzhang.providers.content.article_discovery import (
    ArticleDiscoveryBatch,
    ArticleDiscoveryError,
    ArticleDiscoveryFailure,
    ArticleDiscoveryProvider,
    ArticleDiscoveryQuery,
    DiscoveredArticle,
    EmptyArticleDiscoveryProvider,
)
from yanzhang.providers.content.article_http import (
    ArticleFetcherProvider,
    HostResolver,
    HTTPArticleFetcher,
    HTTPFetchedPage,
    SourceDomains,
    SystemHostResolver,
)
from yanzhang.providers.content.official_search import OfficialSearchDiscoveryProvider

__all__ = [
    "ArticleDiscoveryBatch",
    "ArticleDiscoveryError",
    "ArticleDiscoveryFailure",
    "ArticleDiscoveryProvider",
    "ArticleDiscoveryQuery",
    "ArticleFetcherProvider",
    "DiscoveredArticle",
    "EmptyArticleDiscoveryProvider",
    "HTTPArticleFetcher",
    "HTTPFetchedPage",
    "HostResolver",
    "OfficialSearchDiscoveryProvider",
    "SourceDomains",
    "SystemHostResolver",
]
