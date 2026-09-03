"""Offline contracts for the three official publication search adapters."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import httpx
import pytest

from yanzhang.providers.content import ArticleDiscoveryQuery
from yanzhang.providers.content.official_search import OfficialSearchDiscoveryProvider


class _PublicResolver:
    async def resolve(self, hostname: str) -> tuple[str, ...]:
        del hostname
        return ("8.8.8.8",)


def _query(*sources: str, limit: int = 6) -> ArticleDiscoveryQuery:
    return ArticleDiscoveryQuery(
        keywords=("乡村振兴",),
        source_ids=tuple(sources),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        limit=limit,
    )


def _epoch(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp() * 1_000)


@pytest.mark.asyncio
async def test_official_search_parses_all_sources_and_cleans_highlights() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "search.people.cn":
            payload = json.loads(request.content)
            assert payload["key"] == "乡村振兴"
            assert payload["limit"] == 6
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "records": [
                            {
                                "url": "http://politics.people.com.cn/n1/example.html",
                                "title": "推进<em>乡村振兴</em>取得新成效",
                                "displayTime": _epoch("2026-09-02T08:00:00"),
                                "contentOriginal": "乡村振兴工作取得阶段性成效。" * 8,
                            }
                        ]
                    },
                },
            )
        if request.url.host == "search.qstheory.cn":
            payload = json.loads(request.content)
            assert payload["searchFields"] == ["title"]
            assert payload["startTime"] == "2026-09-01"
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {
                        "list": [
                            {
                                "origin_url": "http://www.qstheory.cn/example/c.html",
                                "release_date": "2026-09-02 10:00:00",
                                "title": "把握推进<em>乡村振兴</em>的方法",
                                "description": "坚持因地制宜、分类施策。",
                            }
                        ]
                    },
                },
            )
        if request.url.path.endswith("getToken.do"):
            return httpx.Response(200, text='callback({"token":"123456789012TOKEN"})')
        if request.url.host == "zhonghua.gmw.cn":
            assert request.url.params["tk"] == "123456789012TOKEN"
            assert request.url.params["hd"]
            return httpx.Response(
                200,
                text=(
                    'callback({"result":{"list":[{'
                    '"url":"https://theory.gmw.cn/2026-09/02/content_1.htm",'
                    '"title":"为<em>乡村振兴</em>注入新动能",'
                    '"pubtime":"2026-09-02 09:30:00",'
                    '"synopsis":"不断增强发展内生动力。"}]}})'
                ),
            )
        raise AssertionError(f"unexpected request: {request.url}")

    provider = OfficialSearchDiscoveryProvider(
        transport=httpx.MockTransport(handler),
        resolver=_PublicResolver(),
        clock_ms=lambda: 1_780_000_000_000,
        nonce_factory=lambda: "ABCD@EFG",
        enable_insecure_people_search=True,
    )

    result = await provider.discover(_query("people", "gmw", "qiushi"))

    assert not result.failures
    assert [item.source_id for item in result.articles] == ["people", "gmw", "qiushi"]
    assert [item.title for item in result.articles] == [
        "推进乡村振兴取得新成效",
        "为乡村振兴注入新动能",
        "把握推进乡村振兴的方法",
    ]
    assert result.articles[0].url.startswith("https://politics.people.com.cn/")
    assert result.articles[0].content is None
    assert result.articles[0].summary
    assert result.articles[1].channel == "gmw_signed_search"
    assert len(seen) == 4


@pytest.mark.asyncio
async def test_one_source_failure_does_not_discard_other_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "search.people.cn":
            return httpx.Response(503, text="temporary")
        if request.url.host == "search.qstheory.cn":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "list": [
                            {
                                "origin_url": "https://www.qstheory.cn/example/c.html",
                                "release_date": "2026-09-02",
                                "title": "乡村振兴重在实干",
                                "description": "以实干推动工作落实。",
                            }
                        ]
                    }
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    provider = OfficialSearchDiscoveryProvider(
        transport=httpx.MockTransport(handler),
        resolver=_PublicResolver(),
        enable_insecure_people_search=True,
    )

    result = await provider.discover(_query("people", "qiushi"))

    assert [item.source_id for item in result.articles] == ["qiushi"]
    assert [(item.source_id, item.code) for item in result.failures] == [
        ("people", "discovery_failed")
    ]
    assert "503" in result.failures[0].message


@pytest.mark.asyncio
async def test_response_size_and_query_bounds_are_enforced() -> None:
    provider = OfficialSearchDiscoveryProvider(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 1_025)),
        resolver=_PublicResolver(),
        max_response_bytes=1_024,
        enable_insecure_people_search=True,
    )

    oversized = await provider.discover(_query("people"))

    assert not oversized.articles
    assert oversized.failures[0].source_id == "people"
    assert "超过允许大小" in oversized.failures[0].message

    with pytest.raises(ValueError, match="1 到 100"):
        await provider.discover(
            ArticleDiscoveryQuery(
                keywords=("主题",),
                source_ids=("people",),
                start_date=None,
                end_date=None,
                limit=101,
            )
        )


@pytest.mark.asyncio
async def test_people_search_is_disabled_by_default_without_sending_the_query() -> None:
    keyword = "仅用于确认不会进入错误信息的敏感检索词"
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"code": 0, "data": {"records": []}})

    provider = OfficialSearchDiscoveryProvider(
        transport=httpx.MockTransport(handler),
        resolver=_PublicResolver(),
    )
    result = await provider.discover(
        ArticleDiscoveryQuery(
            keywords=(keyword,),
            source_ids=("people",),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 3),
            limit=6,
        )
    )

    assert provider.people_search_enabled is False
    assert calls == 0
    assert not result.articles
    assert len(result.failures) == 1
    assert result.failures[0].code == "insecure_transport_disabled"
    message = result.failures[0].message
    assert "GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH=true" in message
    assert "HTTP" in message
    assert "明文传输" in message
    assert keyword not in message
