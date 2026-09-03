"""Offline tests for the persistent reference-article library."""

# ruff: noqa: RUF001 -- Chinese article fixtures intentionally use full-width punctuation.

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from gongwen_web.articles import (
    OFFICIAL_SOURCES,
    ArticleFetchError,
    ArticleLibrary,
    ArticleLibraryError,
    ArticleURLValidationError,
    FetchedPage,
    HTTPArticleFetcher,
    SQLiteArticleRepository,
    extract_article_html,
    normalize_url,
    recognize_source,
    validate_official_url,
)
from gongwen_web.models import StyleReference


def _clock() -> datetime:
    return datetime(2026, 9, 3, 8, 30, tzinfo=UTC)


class _FakeFetcher:
    def __init__(self, page: FetchedPage) -> None:
        self.page = page
        self.calls: list[str] = []

    async def fetch(self, url: str) -> FetchedPage:
        self.calls.append(url)
        return self.page


class _PublicResolver:
    async def resolve(self, hostname: str) -> tuple[str, ...]:
        del hostname
        return ("8.8.8.8",)


def test_official_sources_and_url_boundary_are_traceable() -> None:
    assert set(OFFICIAL_SOURCES) == {"people", "gmw", "qiushi"}
    assert recognize_source("https://paper.people.com.cn/rmrb/example.html").id == "people"  # type: ignore[union-attr]
    assert recognize_source("https://news.gmw.cn/2026/example.htm").id == "gmw"  # type: ignore[union-attr]
    assert recognize_source("https://www.qstheory.cn/dukan/example.htm").id == "qiushi"  # type: ignore[union-attr]
    assert recognize_source("https://people.com.cn.example.test/article") is None

    normalized = normalize_url("HTTPS://WWW.PEOPLE.COM.CN:443/a/../article?id=1#fragment")
    assert normalized == "https://www.people.com.cn/a/../article?id=1"
    assert validate_official_url(normalized) == normalized

    fixture_username = "fixture-user"
    fixture_password = "fixture-password"
    credentialed_url = (
        "https:" + "//" + fixture_username + ":" + fixture_password + "@people.com.cn/article"
    )
    for rejected in (
        "file:///etc/passwd",
        "http://127.0.0.1/article",
        "http://[::1]/article",
        credentialed_url,
        "https://people.com.cn:8443/article",
        "https://people.com.cn.example.test/article",
    ):
        with pytest.raises(ArticleURLValidationError):
            validate_official_url(rejected)


def test_article_repository_rejects_partial_existing_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "partial-articles.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE reference_articles (id TEXT PRIMARY KEY)")

    with pytest.raises(ArticleLibraryError, match="schema 缺少字段"):
        SQLiteArticleRepository(database_path)


def test_manual_import_is_persistent_searchable_and_json_ready(tmp_path: Path) -> None:
    database_path = tmp_path / "articles.sqlite3"
    with SQLiteArticleRepository(database_path) as repository:
        library = ArticleLibrary(repository, clock=_clock)
        assert library.list_sources()[0]["homepage"] == "https://www.people.com.cn/"
        first = library.import_text(
            title="以数字化转型提升基层治理效能",
            content=(
                "截至2026年6月30日，统一事项平台已接入18个处室。\n\n"
                "一、坚持问题导向。数据显示，平均办理时长同比下降31%。\n\n"
                "二、强化协同联动。下一步将统一数据标准，减少重复填报。"
            ),
            source_id="people",
            url="https://opinion.people.com.cn/n1/2026/0903/example.html#share",
            published_date="2026年9月3日 08:00",
        )
        second = library.import_text(
            title="以扎实调研推动文化服务提质增效",
            content="首先摸清群众需求，其次完善服务清单，再次健全长效机制。",
            source_id="gmw",
            published_date="2026-08-30",
        )

        assert first.id.startswith("article_")
        assert first.url == "https://opinion.people.com.cn/n1/2026/0903/example.html"
        assert first.published_date == "2026-09-03"
        assert first.created_at == "2026-09-03T08:30:00+00:00"
        assert "数据支撑" in first.style_features
        assert first.to_dict()["content"] == first.content
        assert "content" not in first.to_dict(include_content=False)

        hits = library.search_articles("数字化 治理")
        assert [item.id for item in hits] == [first.id]
        assert hits[0].score > 0
        assert "统一事项平台" in hits[0].excerpt
        assert library.search_articles("调研", source_id="gmw")[0].id == second.id
        assert library.search_articles("调研", source_id="people") == []

        page = library.search_page("", limit=1)
        assert page.total == 2
        assert page.limit == 1
        assert page.items[0].id == first.id
        assert isinstance(page.to_dict()["items"], list)

    # A new repository instance proves that records were persisted on disk.
    with SQLiteArticleRepository(database_path) as reopened:
        library = ArticleLibrary(reopened, clock=_clock)
        stored = library.get_article(first.id)
        assert stored is not None
        assert stored.content_hash == first.content_hash
        assert library.delete_article(first.id) is True
        assert library.delete_article(first.id) is False
        assert library.get_article(first.id) is None


def test_same_manual_content_is_idempotent_and_pagination_is_validated(tmp_path: Path) -> None:
    database_path = tmp_path / "articles.sqlite3"
    with SQLiteArticleRepository(database_path) as repository:
        library = ArticleLibrary(repository, clock=_clock)
        first = library.import_text(title="标题", content="这是一段用于本地检索的完整正文内容。")
        repeated = library.import_text(title="标题", content="这是一段用于本地检索的完整正文内容。")
        assert repeated.id == first.id
        assert len(library.list_articles()) == 1
        assert library.search_articles("不存在的关键词") == []
        with pytest.raises(ValueError, match="limit"):
            library.list_articles(limit=0)
        with pytest.raises(ValueError, match="offset"):
            library.search_articles("标题", offset=-1)


def test_html_extraction_uses_metadata_and_excludes_page_chrome() -> None:
    document = """
    <!doctype html><html><head>
      <title>备用页面标题 - 人民网</title>
      <meta property="og:title" content="让数字化成果更好服务基层治理">
      <meta property="article:published_time" content="2026-09-02T09:10:00+08:00">
      <meta name="description" content="文章围绕基层治理中的数字化实践展开分析。">
      <link rel="canonical" href="/n1/2026/0902/c1001-123.html">
      <script type="application/ld+json">{"@type":"WebSite","name":"人民网"}</script>
      <script type="application/ld+json">
        {"@type":"NewsArticle","headline":"JSON标题","datePublished":"2026-09-01"}
      </script>
      <script>window.secret = "不应进入正文";</script>
    </head><body>
      <nav><p>首页 新闻 理论</p><img src="logo.png"></nav>
      <main class="article-content">
        <h1>正文中的标题</h1>
        <p>数字化转型不是简单增加工具，而是推动治理流程系统重塑。</p>
        <p>一、坚持需求导向，把群众感受作为检验工作成效的重要标准。</p>
        <p>二、完善协同机制，进一步打通数据壁垒、优化服务流程。</p>
      </main>
      <footer><p>联系我们 网站地图</p></footer>
    </body></html>
    """
    extracted = extract_article_html(
        document,
        url="https://www.people.com.cn/original.html",
        source=OFFICIAL_SOURCES["people"],
    )

    assert extracted.title == "让数字化成果更好服务基层治理"
    assert extracted.url == "https://www.people.com.cn/n1/2026/0902/c1001-123.html"
    assert extracted.published_date == "2026-09-02"
    assert extracted.source_name == "人民日报 / 人民网"
    assert extracted.summary == "文章围绕基层治理中的数字化实践展开分析。"
    assert "治理流程系统重塑" in extracted.content
    assert "首页 新闻" not in extracted.content
    assert "不应进入正文" not in extracted.content
    assert "联系我们" not in extracted.content
    assert "分层论述" in extracted.style_features


def test_html_extraction_handles_implicit_paragraph_closes_and_ignores_related_blocks() -> None:
    extracted = extract_article_html(
        """
        <html><head><title>隐式闭合测试</title></head><body>
        <nav><p>菜单内容没有显式闭合</nav>
        <div class="related-articles"><p>
        推荐内容足够长但不属于文章正文，不能覆盖真正正文段落。</div>
        <article><p>第一段正文没有显式闭合
        <p>第二段正文继续说明重点任务和具体落实要求。</article>
        </body></html>
        """,
        url="https://www.people.com.cn/example.html",
        source=OFFICIAL_SOURCES["people"],
    )
    assert "第一段正文" in extracted.content
    assert "第二段正文" in extracted.content
    assert "菜单内容" not in extracted.content
    assert "推荐内容" not in extracted.content


def test_html_extraction_selects_article_h1_instead_of_joining_navigation_h1() -> None:
    extracted = extract_article_html(
        """
        <html><head><title>甘肃：以正确政绩观引领高质量发展 _光明网</title></head>
        <body>
          <h1>全部导航</h1>
          <main class="article-content">
            <h1>甘肃：以正确政绩观引领高质量发展</h1>
            <p>以正确政绩观引领高质量发展，关键是把群众感受作为工作标尺。</p>
          </main>
        </body></html>
        """,
        url="https://news.gmw.cn/2026-09/03/content_123.htm",
        source=OFFICIAL_SOURCES["gmw"],
    )

    assert extracted.title == "甘肃：以正确政绩观引领高质量发展"


@pytest.mark.asyncio
async def test_url_import_uses_only_injected_fetcher_and_returns_style_reference(
    tmp_path: Path,
) -> None:
    url = "https://news.gmw.cn/2026-09/03/content_123.htm"
    page = FetchedPage(
        url=url,
        body=(
            "<html><head><meta property='og:title' content='以改革创新释放发展活力'>"
            "<meta name='publishdate' content='2026年09月03日'></head>"
            "<body><article><p>改革创新是推动高质量发展的重要动力。</p>"
            "<p>一方面，要完善工作机制；另一方面，要强化协同联动。</p>"
            "</article></body></html>"
        ).encode(),
    )
    fetcher = _FakeFetcher(page)
    database_path = tmp_path / "articles.sqlite3"
    with SQLiteArticleRepository(database_path) as repository:
        library = ArticleLibrary(repository, fetcher=fetcher, clock=_clock)
        assert fetcher.calls == []
        record = await library.import_url(url)

        assert fetcher.calls == [url]
        assert record.import_method == "url"
        assert record.source_id == "gmw"
        assert record.title == "以改革创新释放发展活力"
        assert record.published_date == "2026-09-03"
        assert library.get_article(record.id) == record
        cards = library.references([record.id, record.id])
        assert len(cards) == 1
        assert cards[0]["usage"] == "style_only"
        assert cards[0]["provenance_status"] == "fetched_verified"
        assert "content" not in cards[0]
        assert cards[0]["summary"]
        assert StyleReference.model_validate(cards[0]).excerpt


@pytest.mark.asyncio
async def test_url_import_rejects_missing_adapter_and_cross_source_redirect(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "articles.sqlite3"
    with SQLiteArticleRepository(database_path) as repository:
        library = ArticleLibrary(repository, clock=_clock)
        with pytest.raises(ArticleFetchError, match="适配器"):
            await library.import_url("https://www.people.com.cn/article.html")

        cross_source = _FakeFetcher(
            FetchedPage(
                url="https://www.gmw.cn/article.html",
                body=(
                    b"<html><h1>title</h1><article><p>long enough article content."
                    b"</p></article></html>"
                ),
            )
        )
        library = ArticleLibrary(repository, fetcher=cross_source, clock=_clock)
        with pytest.raises(ArticleURLValidationError, match="其他来源"):
            await library.import_url("https://www.people.com.cn/article.html")


@pytest.mark.asyncio
async def test_http_fetch_adapter_validates_redirects_and_size_without_public_network() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/article"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content="<html><article><p>官方来源文章正文。</p></article></html>".encode(),
        )

    fetcher = HTTPArticleFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_PublicResolver(),
        max_bytes=2048,
    )
    page = await fetcher.fetch("https://www.people.com.cn/start")
    assert requests == [
        "https://www.people.com.cn/start",
        "https://www.people.com.cn/article",
    ]
    assert page.status_code == 200
    assert "文章正文" in page.body.decode()

    oversized = HTTPArticleFetcher(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"x" * 2049,
            )
        ),
        resolver=_PublicResolver(),
        max_bytes=2048,
    )
    with pytest.raises(ArticleFetchError, match="超过允许"):
        await oversized.fetch("https://www.people.com.cn/large")
