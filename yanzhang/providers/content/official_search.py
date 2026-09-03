"""Bounded live discovery adapter for People's Daily, GMW, and Qiushi.

Only this provider opens discovery-network connections.  It uses the publications'
public search interfaces, keeps each source failure isolated, validates every fixed
destination before connecting, and returns metadata for application-side validation
and import.  Article bodies are still fetched by the separate article HTTP adapter.
"""

# Chinese publication names and messages intentionally use full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import asyncio
import base64
import html
import ipaddress
import json
import re
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from datetime import time as datetime_time
from typing import Literal, cast
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from yanzhang.providers.content.article_discovery import (
    ArticleDiscoveryBatch,
    ArticleDiscoveryError,
    ArticleDiscoveryFailure,
    ArticleDiscoveryQuery,
    DiscoveredArticle,
)
from yanzhang.providers.content.article_http import HostResolver, SystemHostResolver

_PEOPLE_SEARCH_URL = "http://search.people.cn/search-platform/front/search"
_QIUSHI_SEARCH_URL = "https://search.qstheory.cn/api/search"
_GMW_TOKEN_URL = "https://zhonghua.gmw.cn/service/getToken.do"
_GMW_SEARCH_URL = "https://zhonghua.gmw.cn/service/search.do"
_GMW_KEY_SUFFIX = "*!!asd!@(8e*dfd!(edk"
_GMW_NONCE_ALPHABET = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HIGHLIGHT_TAG_RE = re.compile(r"</?em\b[^>]*>", re.IGNORECASE)
_DATE_RE = re.compile(r"(?P<year>20\d{2})[-年/](?P<month>\d{1,2})[-月/](?P<day>\d{1,2})")
_PUBLICATION_TIMEZONE = ZoneInfo("Asia/Shanghai")
_PEOPLE_SEARCH_DISABLED_MESSAGE = (
    "人民网自动检索默认关闭；如确需使用，请显式设置 "
    "GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH=true。该检索接口使用 HTTP，"
    "检索关键词与日期范围会以明文传输。"
)


class OfficialSearchDiscoveryProvider:
    """Discover official articles with source-isolated, bounded search requests."""

    strategies: Mapping[str, str] = {
        "people": "人民网公开检索接口；检索结果仅定位 HTTPS 文章页",
        "gmw": "光明网公开搜索前端协议；结果按发布日期在本地复核",
        "qiushi": "求是网公开检索接口；起止日期直接传给官方检索",
    }

    def __init__(
        self,
        *,
        timeout_seconds: float = 12.0,
        max_response_bytes: int = 2 * 1024 * 1024,
        max_results: int = 100,
        max_queries_per_source: int = 3,
        max_pages_per_source: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: HostResolver | None = None,
        clock_ms: Callable[[], int] | None = None,
        nonce_factory: Callable[[], str] | None = None,
        enable_insecure_people_search: bool = False,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise ValueError("timeout_seconds 必须在 0 到 60 秒之间")
        if max_response_bytes < 1024 or max_response_bytes > 10 * 1024 * 1024:
            raise ValueError("max_response_bytes 必须在 1 KB 到 10 MB 之间")
        if max_results < 1 or max_results > 100:
            raise ValueError("max_results 必须在 1 到 100 之间")
        if max_queries_per_source < 1 or max_queries_per_source > 5:
            raise ValueError("max_queries_per_source 必须在 1 到 5 之间")
        if max_pages_per_source < 1 or max_pages_per_source > 5:
            raise ValueError("max_pages_per_source 必须在 1 到 5 之间")
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._max_results = max_results
        self._max_queries_per_source = max_queries_per_source
        self._max_pages_per_source = max_pages_per_source
        self._transport = transport
        self._resolver = resolver or SystemHostResolver()
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._nonce_factory = nonce_factory or _gmw_nonce
        self._enable_insecure_people_search = enable_insecure_people_search

    @property
    def people_search_enabled(self) -> bool:
        """Whether the plaintext People search endpoint was explicitly enabled."""

        return self._enable_insecure_people_search

    async def discover(self, query: ArticleDiscoveryQuery) -> ArticleDiscoveryBatch:
        """Search selected sources concurrently and merge them in source order."""

        _validate_query(query)
        source_ids = tuple(dict.fromkeys(query.source_ids))
        tasks = [self._discover_source(source_id, query) for source_id in source_ids]
        outcomes = await asyncio.gather(*tasks)
        by_source: list[list[DiscoveredArticle]] = []
        failures: list[ArticleDiscoveryFailure] = []
        for _source_id, outcome in zip(source_ids, outcomes, strict=True):
            if isinstance(outcome, ArticleDiscoveryFailure):
                failures.append(outcome)
            else:
                by_source.append(outcome)
        limit = min(query.limit, self._max_results)
        merged = _round_robin(by_source, limit)
        return ArticleDiscoveryBatch(articles=tuple(merged), failures=tuple(failures))

    async def _discover_source(
        self,
        source_id: str,
        query: ArticleDiscoveryQuery,
    ) -> list[DiscoveredArticle] | ArticleDiscoveryFailure:
        if source_id == "people" and not self._enable_insecure_people_search:
            return ArticleDiscoveryFailure(
                source_id=source_id,
                message=_PEOPLE_SEARCH_DISABLED_MESSAGE,
                code="insecure_transport_disabled",
            )
        try:
            if source_id == "people":
                return await self._discover_people(query)
            if source_id == "gmw":
                return await self._discover_gmw(query)
            if source_id == "qiushi":
                return await self._discover_qiushi(query)
            raise ArticleDiscoveryError("文章来源标识未登记")
        except (ArticleDiscoveryError, ValueError) as exc:
            return ArticleDiscoveryFailure(
                source_id=source_id,
                message=_message(exc),
            )

    async def _discover_people(self, query: ArticleDiscoveryQuery) -> list[DiscoveredArticle]:
        if not self._enable_insecure_people_search:
            raise ArticleDiscoveryError(_PEOPLE_SEARCH_DISABLED_MESSAGE)
        # One combined request respects the official site's deliberately slow crawl policy.
        keyword = " ".join(query.keywords[: self._max_queries_per_source])
        payload: dict[str, object] = {
            "key": keyword,
            "page": 1,
            "limit": min(query.limit, self._max_results),
            "hasTitle": True,
            "hasContent": True,
            "isFuzzy": True,
            "type": 0,
            "sortType": 2,
            "startTime": _epoch_millis(query.start_date, end_of_day=False),
            "endTime": _epoch_millis(query.end_date, end_of_day=True),
            "belongsId": [],
        }
        body = await self._request("POST", _PEOPLE_SEARCH_URL, json_body=payload)
        response = _json_object(body)
        if str(response.get("code", "")) != "0":
            raise ArticleDiscoveryError("人民网检索接口返回异常")
        data = response.get("data")
        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, list):
            raise ArticleDiscoveryError("人民网检索接口缺少结果列表")
        result: list[DiscoveredArticle] = []
        for raw in records:
            if not isinstance(raw, dict):
                continue
            original_url = _string(raw.get("url")) or _string(raw.get("originUrl"))
            url = _official_candidate_url(original_url, "people")
            if url is None:
                continue
            published = _epoch_date(raw.get("displayTime")) or _epoch_date(raw.get("inputTime"))
            if not _date_allowed(published, query):
                continue
            title = _plain_text(_string(raw.get("title"))) or None
            full_content = _plain_text(
                _string(raw.get("contentOriginal")) or _string(raw.get("content"))
            )
            result.append(
                DiscoveredArticle(
                    url=url,
                    source_id="people",
                    title=title,
                    published_date=published,
                    summary=full_content[:240] or None,
                    channel="people_search_api",
                    # The official endpoint currently redirects HTTPS requests
                    # to HTTP. Its response is candidate metadata only; article
                    # content must be acquired again from the validated HTTPS
                    # publication URL before it can be stored.
                    content=None,
                    original_url=original_url if original_url != url else None,
                )
            )
        return _deduplicate(result, self._max_results)

    async def _discover_qiushi(self, query: ArticleDiscoveryQuery) -> list[DiscoveredArticle]:
        result: list[DiscoveredArticle] = []
        for keyword in query.keywords[: self._max_queries_per_source]:
            payload: dict[str, object] = {
                "pageNum": 1,
                "pageSize": min(query.limit, self._max_results),
                "sortField": "-release_date",
                "highlight": True,
                "highlightPreTag": "<em>",
                "highlightPostTag": "</em>",
                "keyword": keyword,
                "searchFields": ["title"],
                "startTime": query.start_date.isoformat() if query.start_date else "",
                "endTime": query.end_date.isoformat() if query.end_date else "",
                "inFilters": {"origin": ["《求是》", "求是网"]},
                "author": "",
            }
            body = await self._request("POST", _QIUSHI_SEARCH_URL, json_body=payload)
            response = _json_object(body)
            data = response.get("data")
            records = data.get("list") if isinstance(data, dict) else None
            if not isinstance(records, list):
                raise ArticleDiscoveryError("求是网检索接口缺少结果列表")
            for raw in records:
                if not isinstance(raw, dict):
                    continue
                original_url = _string(raw.get("origin_url"))
                url = _official_candidate_url(original_url, "qiushi")
                if url is None:
                    continue
                published = _parse_date(raw.get("release_date"))
                if not _date_allowed(published, query):
                    continue
                result.append(
                    DiscoveredArticle(
                        url=url,
                        source_id="qiushi",
                        title=_plain_text(_string(raw.get("title"))) or None,
                        published_date=published,
                        summary=_plain_text(_string(raw.get("description")))[:500] or None,
                        channel="qiushi_search_api",
                        original_url=original_url if original_url != url else None,
                    )
                )
            if len(result) >= self._max_results:
                break
        return _deduplicate(result, self._max_results)

    async def _discover_gmw(self, query: ArticleDiscoveryQuery) -> list[DiscoveredArticle]:
        now = self._clock_ms()
        callback = f"jQuery{now}_1"
        token_body = await self._request(
            "GET",
            _GMW_TOKEN_URL,
            params={"callback": callback, "_": str(now)},
        )
        token_payload = _jsonp_value(token_body)
        token = _string(token_payload.get("token")) if isinstance(token_payload, dict) else ""
        if len(token) < 12 or token.lower() == "wait":
            raise ArticleDiscoveryError("光明网检索令牌暂不可用")

        result: list[DiscoveredArticle] = []
        for keyword in query.keywords[: self._max_queries_per_source]:
            for page in range(1, self._max_pages_per_source + 1):
                stamp = self._clock_ms()
                request_callback = f"jQuery{stamp}_{page + 1}"
                signature = _gmw_signature(
                    keyword=keyword,
                    page=page,
                    timestamp_ms=stamp,
                    nonce=self._nonce_factory(),
                    token=token,
                )
                params: dict[str, str] = {
                    "q": keyword,
                    "c": "n",
                    "cp": str(page),
                    # Title-first discovery keeps collected examples relevant to
                    # the writing workbench; the article body is verified later.
                    "tt": "true",
                    "dateType": "default",
                    "callback": request_callback,
                    "hd": signature,
                    "tk": token,
                    "_": str(stamp),
                }
                if query.start_date is not None or query.end_date is not None:
                    params.update(
                        {
                            "adv": "true",
                            "limitTime": "0",
                            "beginTime": _range_datetime(query.start_date, end=False),
                            "endTime": _range_datetime(query.end_date, end=True),
                            "fm": "false",
                            "editor": "",
                            "sourceName": "",
                            "siteflag": "1",
                            "sitestr": "",
                        }
                    )
                body = await self._request("GET", _GMW_SEARCH_URL, params=params)
                response = _jsonp_value(body)
                if not isinstance(response, dict):
                    raise ArticleDiscoveryError("光明网检索接口返回格式异常")
                if response.get("isBlock") is True:
                    raise ArticleDiscoveryError("光明网检索接口要求稍后重试")
                payload = response.get("result")
                records = payload.get("list") if isinstance(payload, dict) else None
                if not isinstance(records, list):
                    raise ArticleDiscoveryError("光明网检索接口缺少结果列表")
                for raw in records:
                    if not isinstance(raw, dict):
                        continue
                    original_url = _string(raw.get("url"))
                    url = _official_candidate_url(original_url, "gmw")
                    if url is None:
                        continue
                    published = _parse_date(raw.get("pubtime"))
                    if not _date_allowed(published, query):
                        continue
                    result.append(
                        DiscoveredArticle(
                            url=url,
                            source_id="gmw",
                            title=_plain_text(_string(raw.get("title"))) or None,
                            published_date=published,
                            summary=_plain_text(_string(raw.get("synopsis")))[:500] or None,
                            channel="gmw_signed_search",
                            original_url=original_url if original_url != url else None,
                        )
                    )
                if len(records) < 10 or len(result) >= self._max_results:
                    break
            if len(result) >= self._max_results:
                break
        return _deduplicate(result, self._max_results)

    async def _request(
        self,
        method: Literal["GET", "POST"],
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, object] | None = None,
    ) -> bytes:
        await self._validate_destination(url)
        headers = {
            "Accept": "application/json,text/javascript,*/*;q=0.8",
            "User-Agent": "YanzhangOfficialArticleDiscovery/1.0",
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_seconds),
                follow_redirects=False,
                transport=self._transport,
                trust_env=False,
                headers=headers,
            ) as client:
                async with client.stream(
                    method,
                    url,
                    params=params,
                    json=json_body,
                ) as response:
                    if response.status_code < 200 or response.status_code >= 300:
                        raise ArticleDiscoveryError(
                            f"官方检索接口返回状态码 {response.status_code}"
                        )
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self._max_response_bytes:
                            raise ArticleDiscoveryError("官方检索响应超过允许大小")
                        chunks.append(chunk)
                    return b"".join(chunks)
        except ArticleDiscoveryError:
            raise
        except httpx.TimeoutException as exc:
            raise ArticleDiscoveryError("官方检索请求超时") from exc
        except httpx.HTTPError as exc:
            raise ArticleDiscoveryError("官方检索连接失败") from exc

    async def _validate_destination(self, url: str) -> None:
        parts = urlsplit(url)
        hostname = parts.hostname
        allowed = {
            "search.people.cn": {"http", "https"},
            "search.qstheory.cn": {"https"},
            "zhonghua.gmw.cn": {"https"},
        }
        if hostname not in allowed or parts.scheme not in allowed[hostname]:
            raise ArticleDiscoveryError("官方检索目标未登记")
        try:
            addresses = await asyncio.wait_for(
                self._resolver.resolve(hostname), timeout=min(self._timeout_seconds, 5.0)
            )
        except (TimeoutError, OSError) as exc:
            raise ArticleDiscoveryError("官方检索域名解析失败") from exc
        if not addresses:
            raise ArticleDiscoveryError("官方检索域名没有可用地址")
        for address in addresses:
            try:
                resolved = ipaddress.ip_address(address.split("%", 1)[0])
            except ValueError as exc:
                raise ArticleDiscoveryError("官方检索域名返回了无效地址") from exc
            if not resolved.is_global:
                raise ArticleDiscoveryError("官方检索域名解析到了非公网地址")


def _validate_query(query: ArticleDiscoveryQuery) -> None:
    if not query.keywords or not query.source_ids:
        raise ArticleDiscoveryError("检索关键词和文章来源不能为空")
    if query.limit < 1 or query.limit > 100:
        raise ArticleDiscoveryError("检索数量上限必须在 1 到 100 之间")
    if query.start_date and query.end_date and query.start_date > query.end_date:
        raise ArticleDiscoveryError("检索起始日期不能晚于结束日期")


def _round_robin(
    groups: Sequence[Sequence[DiscoveredArticle]], limit: int
) -> list[DiscoveredArticle]:
    result: list[DiscoveredArticle] = []
    seen: set[str] = set()
    position = 0
    while len(result) < limit:
        changed = False
        for group in groups:
            if position >= len(group):
                continue
            changed = True
            item = group[position]
            if item.url not in seen:
                seen.add(item.url)
                result.append(item)
                if len(result) >= limit:
                    break
        if not changed:
            break
        position += 1
    return result


def _deduplicate(items: Sequence[DiscoveredArticle], limit: int) -> list[DiscoveredArticle]:
    result: list[DiscoveredArticle] = []
    seen: set[str] = set()
    for item in items:
        if item.url in seen:
            continue
        seen.add(item.url)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _official_candidate_url(value: str, source_id: str) -> str | None:
    if not value:
        return None
    joined = urljoin(
        {
            "people": "https://www.people.com.cn/",
            "gmw": "https://www.gmw.cn/",
            "qiushi": "https://www.qstheory.cn/",
        }[source_id],
        html.unescape(value.strip()),
    )
    try:
        parts = urlsplit(joined)
        hostname = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    domains = {
        "people": ("people.com.cn", "people.cn"),
        "gmw": ("gmw.cn",),
        "qiushi": ("qstheory.cn",),
    }[source_id]
    if not hostname or not any(
        hostname == item or hostname.endswith(f".{item}") for item in domains
    ):
        return None
    if parts.username or parts.password or parts.port not in {None, 80, 443}:
        return None
    return urlunsplit(("https", hostname, parts.path or "/", parts.query, ""))


def _gmw_signature(
    *,
    keyword: str,
    page: int,
    timestamp_ms: int,
    nonce: str,
    token: str,
) -> str:
    if len(token) < 12:
        raise ArticleDiscoveryError("光明网检索令牌长度异常")
    message = (
        json.dumps(
            {"q": keyword, "c": "n", "pg": page, "rdom": nonce, "tmp": timestamp_ms},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "_gmwseach"
    )
    key = (token[:12] + _GMW_KEY_SUFFIX).encode()
    padder = padding.PKCS7(128).padder()
    padded = padder.update(message.encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(encrypted).decode("ascii")


def _gmw_nonce() -> str:
    raw = "".join(secrets.choice(_GMW_NONCE_ALPHABET) for _ in range(7))
    return f"{raw[:4]}@{raw[4:]}"


def _json_object(body: bytes) -> dict[str, object]:
    try:
        value = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArticleDiscoveryError("官方检索接口返回的 JSON 无效") from exc
    if not isinstance(value, dict):
        raise ArticleDiscoveryError("官方检索接口返回格式异常")
    return cast(dict[str, object], value)


def _jsonp_value(body: bytes) -> object:
    try:
        text = body.decode("utf-8-sig").strip()
    except UnicodeDecodeError as exc:
        raise ArticleDiscoveryError("官方检索接口返回编码异常") from exc
    opening = text.find("(")
    closing = text.rfind(")")
    payload = text[opening + 1 : closing] if opening >= 0 and closing > opening else text
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ArticleDiscoveryError("官方检索接口返回的 JSONP 无效") from exc


def _epoch_date(value: object) -> date | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
    elif isinstance(value, str):
        try:
            raw = float(value.strip())
        except ValueError:
            return _parse_date(value)
    else:
        return None
    if raw > 10_000_000_000:
        raw /= 1000
    try:
        return datetime.fromtimestamp(raw, tz=_PUBLICATION_TIMEZONE).date()
    except (OverflowError, OSError, ValueError):
        return None


def _parse_date(value: object) -> date | None:
    text = _string(value)
    match = _DATE_RE.search(text)
    if not match:
        return None
    try:
        return date(int(match["year"]), int(match["month"]), int(match["day"]))
    except ValueError:
        return None


def _date_allowed(value: date | None, query: ArticleDiscoveryQuery) -> bool:
    if value is None:
        return True
    if query.start_date and value < query.start_date:
        return False
    return not query.end_date or value <= query.end_date


def _epoch_millis(value: date | None, *, end_of_day: bool) -> int:
    if value is None:
        return 0
    wall_time = datetime_time.max if end_of_day else datetime_time.min
    return int(datetime.combine(value, wall_time, tzinfo=_PUBLICATION_TIMEZONE).timestamp() * 1000)


def _range_datetime(value: date | None, *, end: bool) -> str:
    if value is None:
        return ""
    suffix = "23:59:59" if end else "00:00:00"
    return f"{value.isoformat()} {suffix}"


def _plain_text(value: str) -> str:
    # The search services wrap matching text in inline ``<em>`` tags. Removing
    # those tags without adding spaces keeps Chinese titles intact; other tags
    # still become boundaries so adjacent paragraphs do not run together.
    without_highlights = _HIGHLIGHT_TAG_RE.sub("", value)
    return " ".join(html.unescape(_HTML_TAG_RE.sub(" ", without_highlights)).split())


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _message(error: Exception) -> str:
    return " ".join(str(error).split())[:300] or "官方文章来源发现失败"


__all__ = ["OfficialSearchDiscoveryProvider"]
