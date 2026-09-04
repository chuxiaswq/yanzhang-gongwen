"""Provider-neutral academic metadata connectors with bounded HTTP adapters."""

# ruff: noqa: RUF001 -- Chinese user-facing messages use full-width punctuation.

from __future__ import annotations

import asyncio
import json
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, cast, runtime_checkable
from urllib.parse import quote

import httpx

from yanzhang_academic.models import Author, BibliographicRecord, RecordType, normalize_doi

_MAX_METADATA_RESPONSE_BYTES = 2 * 1024 * 1024
_RESPONSE_CHUNK_BYTES = 64 * 1024
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_RETRY_BACKOFF_SECONDS = 0.25
_DEFAULT_MAX_RETRY_DELAY_SECONDS = 10.0


class MetadataConnectorError(RuntimeError):
    """Base error for a bounded metadata lookup."""


class MetadataTimeoutError(MetadataConnectorError):
    """Raised when a provider exceeds the configured timeout."""


class MetadataRateLimitError(MetadataConnectorError):
    """Raised when the remote provider asks the client to slow down."""

    def __init__(self, provider: str, retry_after_seconds: float | None = None) -> None:
        self.provider = provider
        self.retry_after_seconds = retry_after_seconds
        suffix = (
            f"，建议 {retry_after_seconds:g} 秒后重试" if retry_after_seconds is not None else ""
        )
        super().__init__(f"{provider} 元数据服务触发频率限制{suffix}")


@runtime_checkable
class MetadataConnector(Protocol):
    """Structural connector contract used by Web, MCP and service layers."""

    @property
    def name(self) -> str:
        """Stable provider name."""

    async def search(self, query: str, *, limit: int = 10) -> list[BibliographicRecord]:
        """Search verified provider metadata."""

    async def lookup(self, identifier: str) -> BibliographicRecord | None:
        """Resolve one provider identifier, DOI or arXiv identifier."""


class AsyncRateLimiter:
    """Small lock-based request pacer shared by one connector instance."""

    def __init__(
        self,
        min_interval_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if min_interval_seconds < 0 or min_interval_seconds > 60:
            raise ValueError("min_interval_seconds 必须在 0 到 60 之间")
        self._interval = min_interval_seconds
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: float | None = None
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        """Wait until the next request is permitted."""

        async with self._lock:
            now = self._clock()
            if self._last_request_at is not None:
                delay = self._last_request_at + self._interval - now
                if delay > 0:
                    await self._sleeper(delay)
            self._last_request_at = self._clock()


class _HTTPMetadataConnector:
    """Shared timeout, response-size and error handling for metadata APIs."""

    name = "metadata"
    base_url = "https://example.invalid"

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        min_interval_seconds: float = 0.1,
        max_response_bytes: int = _MAX_METADATA_RESPONSE_BYTES,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        retry_backoff_seconds: float = _DEFAULT_RETRY_BACKOFF_SECONDS,
        max_retry_delay_seconds: float = _DEFAULT_MAX_RETRY_DELAY_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
        user_agent: str = "YanzhangAcademic/0.2",
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise ValueError("timeout_seconds 必须在 0 到 60 秒之间")
        if max_response_bytes < 1_024 or max_response_bytes > _MAX_METADATA_RESPONSE_BYTES:
            raise ValueError("max_response_bytes 必须在 1 KB 到 2 MB 之间")
        if max_attempts < 1 or max_attempts > 5:
            raise ValueError("max_attempts 必须在 1 到 5 之间")
        if retry_backoff_seconds < 0 or retry_backoff_seconds > 60:
            raise ValueError("retry_backoff_seconds 必须在 0 到 60 秒之间")
        if max_retry_delay_seconds < 0 or max_retry_delay_seconds > 60:
            raise ValueError("max_retry_delay_seconds 必须在 0 到 60 秒之间")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_response_bytes = max_response_bytes
        self._max_attempts = max_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._max_retry_delay_seconds = max_retry_delay_seconds
        self._transport = transport
        self._headers = {"Accept": "application/json", "User-Agent": user_agent}
        self._sleeper = sleeper
        self._limiter = AsyncRateLimiter(min_interval_seconds, sleeper=sleeper)

    @staticmethod
    def _validate_query(query: str, *, limit: int) -> str:
        normalized = " ".join(query.split())
        if not normalized or len(normalized) > 1_000:
            raise ValueError("检索词长度必须在 1 到 1000 个字符之间")
        if limit < 1 or limit > 50:
            raise ValueError("limit 必须在 1 到 50 之间")
        return normalized

    async def _get(self, path: str, *, params: Mapping[str, str | int]) -> bytes:
        for attempt in range(1, self._max_attempts + 1):
            await self._limiter.wait()
            retry_error: MetadataConnectorError | None = None
            retry_after: float | None = None
            try:
                async with httpx.AsyncClient(
                    base_url=self.base_url,
                    timeout=self._timeout,
                    transport=self._transport,
                    follow_redirects=False,
                    trust_env=False,
                    headers=self._headers,
                ) as client:
                    async with client.stream("GET", path, params=params) as response:
                        if response.status_code == 429:
                            retry_after = _retry_after(response.headers.get("retry-after"))
                            retry_error = MetadataRateLimitError(self.name, retry_after)
                        elif 500 <= response.status_code <= 599:
                            retry_error = MetadataConnectorError(
                                f"{self.name} 元数据服务返回状态码 {response.status_code}"
                            )
                        elif response.status_code == 404:
                            return b""
                        elif response.status_code < 200 or response.status_code >= 300:
                            raise MetadataConnectorError(
                                f"{self.name} 元数据服务返回状态码 {response.status_code}"
                            )
                        else:
                            declared_size = _content_length(response.headers.get("content-length"))
                            if (
                                declared_size is not None
                                and declared_size > self._max_response_bytes
                            ):
                                raise MetadataConnectorError(f"{self.name} 元数据响应超过大小上限")
                            body = bytearray()
                            async for chunk in response.aiter_bytes(
                                chunk_size=_RESPONSE_CHUNK_BYTES
                            ):
                                if len(body) + len(chunk) > self._max_response_bytes:
                                    raise MetadataConnectorError(
                                        f"{self.name} 元数据响应超过大小上限"
                                    )
                                body.extend(chunk)
                            return bytes(body)
            except httpx.TimeoutException as exc:
                timeout_error = MetadataTimeoutError(f"{self.name} 元数据请求超时")
                if attempt >= self._max_attempts:
                    raise timeout_error from exc
                await self._wait_before_retry(attempt)
                continue
            except httpx.TransportError as exc:
                transport_error = MetadataConnectorError(f"{self.name} 元数据连接失败")
                if attempt >= self._max_attempts:
                    raise transport_error from exc
                await self._wait_before_retry(attempt)
                continue
            except httpx.HTTPError as exc:
                raise MetadataConnectorError(f"{self.name} 元数据连接失败") from exc

            if retry_error is None:
                raise RuntimeError("元数据连接器重试状态无效")
            if attempt >= self._max_attempts:
                raise retry_error
            await self._wait_before_retry(attempt, retry_after=retry_after)

        raise RuntimeError("元数据连接器重试次数无效")

    async def _wait_before_retry(
        self,
        attempt: int,
        *,
        retry_after: float | None = None,
    ) -> None:
        delay = (
            retry_after
            if retry_after is not None
            else self._retry_backoff_seconds * (2 ** (attempt - 1))
        )
        bounded_delay = min(delay, self._max_retry_delay_seconds)
        if bounded_delay > 0:
            await self._sleeper(bounded_delay)

    async def _get_json(self, path: str, *, params: Mapping[str, str | int]) -> object:
        body = await self._get(path, params=params)
        if not body:
            return None
        try:
            return cast(object, json.loads(body))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise MetadataConnectorError(f"{self.name} 元数据响应不是有效 JSON") from exc


class CrossrefConnector(_HTTPMetadataConnector):
    """Crossref works API adapter."""

    name = "crossref"
    base_url = "https://api.crossref.org"

    async def search(self, query: str, *, limit: int = 10) -> list[BibliographicRecord]:
        normalized = self._validate_query(query, limit=limit)
        payload = await self._get_json(
            "/works", params={"query.bibliographic": normalized, "rows": limit}
        )
        message = _mapping(payload).get("message")
        items = _mapping(message).get("items")
        if not isinstance(items, list):
            return []
        return [record for item in items if (record := _crossref_record(item)) is not None]

    async def lookup(self, identifier: str) -> BibliographicRecord | None:
        doi = normalize_doi(identifier)
        if not doi or not doi.startswith("10.") or "/" not in doi:
            raise ValueError("Crossref lookup 需要有效 DOI")
        payload = await self._get_json(f"/works/{quote(doi, safe='')}", params={})
        return _crossref_record(_mapping(payload).get("message"))


class OpenAlexConnector(_HTTPMetadataConnector):
    """OpenAlex works API adapter."""

    name = "openalex"
    base_url = "https://api.openalex.org"

    async def search(self, query: str, *, limit: int = 10) -> list[BibliographicRecord]:
        normalized = self._validate_query(query, limit=limit)
        payload = await self._get_json("/works", params={"search": normalized, "per-page": limit})
        items = _mapping(payload).get("results")
        if not isinstance(items, list):
            return []
        return [record for item in items if (record := _openalex_record(item)) is not None]

    async def lookup(self, identifier: str) -> BibliographicRecord | None:
        normalized = " ".join(identifier.split())
        if not normalized or len(normalized) > 500:
            raise ValueError("OpenAlex lookup 标识长度无效")
        doi = normalize_doi(normalized)
        if doi and doi.startswith("10.") and "/" in doi:
            payload = await self._get_json("/works", params={"filter": f"doi:{doi}", "per-page": 1})
            results = _mapping(payload).get("results")
            if not isinstance(results, list) or not results:
                return None
            return _openalex_record(results[0])
        openalex_id = normalized.rsplit("/", 1)[-1]
        if not re.fullmatch(r"W[0-9]+", openalex_id, flags=re.I):
            raise ValueError("OpenAlex lookup 需要 DOI 或 W 开头的作品标识")
        payload = await self._get_json(f"/works/{openalex_id.upper()}", params={})
        return _openalex_record(payload)


class ArxivConnector(_HTTPMetadataConnector):
    """arXiv Atom API adapter."""

    name = "arxiv"
    base_url = "https://export.arxiv.org"

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        min_interval_seconds: float = 0.34,
        max_response_bytes: int = 2 * 1024 * 1024,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        retry_backoff_seconds: float = _DEFAULT_RETRY_BACKOFF_SECONDS,
        max_retry_delay_seconds: float = _DEFAULT_MAX_RETRY_DELAY_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
        user_agent: str = "YanzhangAcademic/0.2",
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__(
            timeout_seconds=timeout_seconds,
            min_interval_seconds=min_interval_seconds,
            max_response_bytes=max_response_bytes,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            max_retry_delay_seconds=max_retry_delay_seconds,
            transport=transport,
            user_agent=user_agent,
            sleeper=sleeper,
        )
        self._headers["Accept"] = "application/atom+xml"

    async def search(self, query: str, *, limit: int = 10) -> list[BibliographicRecord]:
        normalized = self._validate_query(query, limit=limit)
        body = await self._get(
            "/api/query",
            params={"search_query": f'all:"{normalized}"', "start": 0, "max_results": limit},
        )
        return _parse_arxiv_feed(body)

    async def lookup(self, identifier: str) -> BibliographicRecord | None:
        normalized = _normalize_arxiv_id(identifier)
        body = await self._get("/api/query", params={"id_list": normalized, "max_results": 1})
        records = _parse_arxiv_feed(body)
        return records[0] if records else None


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if 0 <= parsed <= 86_400 else None


def _content_length(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized.isascii() or not normalized.isdigit():
        raise MetadataConnectorError("元数据响应的 Content-Length 无效")
    return int(normalized)


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    if isinstance(value, str):
        return " ".join(value.split())
    return ""


def _integer(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _list_text(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _date_parts(value: object) -> tuple[int | None, int | None, int | None]:
    parts = _mapping(value).get("date-parts")
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], list):
        return None, None, None
    date = parts[0]
    parsed = [_integer(date[index]) if index < len(date) else None for index in range(3)]
    return parsed[0], parsed[1], parsed[2]


def _provider_people(value: object, *, crossref: bool = False) -> list[Author]:
    if not isinstance(value, list):
        return []
    result: list[Author] = []
    for index, item in enumerate(value):
        data = _mapping(item)
        if crossref:
            family = _text(data.get("family"))
            given = _text(data.get("given"))
            literal = _text(data.get("name"))
        else:
            author = _mapping(data.get("author"))
            display = _text(author.get("display_name"))
            family, given, literal = "", "", display
        if family or given or literal:
            result.append(
                Author(
                    family=family,
                    given=given,
                    literal=literal,
                    sequence="first" if index == 0 else "additional",
                )
            )
    return result


def _crossref_record(value: object) -> BibliographicRecord | None:
    item = _mapping(value)
    titles = _list_text(item.get("title"))
    if not titles:
        return None
    year, month, day = _date_parts(
        item.get("published-print") or item.get("published-online") or item.get("issued")
    )
    raw_type = _text(item.get("type"))
    type_map: dict[str, RecordType] = {
        "journal-article": "article-journal",
        "book": "book",
        "book-chapter": "chapter",
        "proceedings-article": "paper-conference",
        "report": "report",
        "dissertation": "thesis",
        "posted-content": "preprint",
    }
    doi = normalize_doi(_text(item.get("DOI")))
    source_key = doi or _text(item.get("URL"))
    return BibliographicRecord(
        type=type_map.get(raw_type, "document"),
        title=titles[0],
        authors=_provider_people(item.get("author"), crossref=True),
        editors=_provider_people(item.get("editor"), crossref=True),
        issued_year=year,
        issued_month=month,
        issued_day=day,
        container_title=(_list_text(item.get("container-title")) or [""])[0],
        publisher=_text(item.get("publisher")),
        volume=_text(item.get("volume")),
        issue=_text(item.get("issue")),
        pages=_text(item.get("page")),
        doi=doi,
        url=_text(item.get("URL")) or None,
        abstract=_text(item.get("abstract")),
        language=_text(item.get("language")),
        import_source="crossref",
        source_key=source_key,
        metadata_verified=True,
    )


def _openalex_record(value: object) -> BibliographicRecord | None:
    item = _mapping(value)
    title = _text(item.get("title") or item.get("display_name"))
    if not title:
        return None
    raw_type = _text(item.get("type"))
    type_map: dict[str, RecordType] = {
        "article": "article-journal",
        "book": "book",
        "book-chapter": "chapter",
        "proceedings-article": "paper-conference",
        "report": "report",
        "dissertation": "thesis",
        "preprint": "preprint",
    }
    primary_location = _mapping(item.get("primary_location"))
    source = _mapping(primary_location.get("source"))
    biblio = _mapping(item.get("biblio"))
    doi = normalize_doi(_text(item.get("doi")))
    openalex_id = _text(item.get("id"))
    return BibliographicRecord(
        type=type_map.get(raw_type, "document"),
        title=title,
        authors=_provider_people(item.get("authorships")),
        issued_year=_integer(item.get("publication_year")),
        container_title=_text(source.get("display_name")),
        volume=_text(biblio.get("volume")),
        issue=_text(biblio.get("issue")),
        pages=_openalex_pages(biblio),
        doi=doi,
        url=_text(primary_location.get("landing_page_url")) or openalex_id or None,
        abstract=_openalex_abstract(item.get("abstract_inverted_index")),
        keywords=_openalex_topics(item.get("keywords")),
        language=_text(item.get("language")),
        import_source="openalex",
        source_key=openalex_id.rsplit("/", 1)[-1] if openalex_id else doi or "",
        metadata_verified=True,
    )


def _openalex_pages(biblio: Mapping[str, object]) -> str:
    first = _text(biblio.get("first_page"))
    last = _text(biblio.get("last_page"))
    return f"{first}-{last}" if first and last and first != last else first


def _openalex_abstract(value: object) -> str:
    inverted = _mapping(value)
    positions: list[tuple[int, str]] = []
    for word, raw_positions in inverted.items():
        if not isinstance(word, str) or not isinstance(raw_positions, list):
            continue
        for position in raw_positions:
            if isinstance(position, int) and not isinstance(position, bool):
                positions.append((position, word))
    return " ".join(word for _, word in sorted(positions))


def _openalex_topics(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        keyword = _text(_mapping(item).get("display_name"))
        if keyword and keyword not in result:
            result.append(keyword)
    return result


def _normalize_arxiv_id(value: str) -> str:
    normalized = value.strip()
    normalized = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", normalized, flags=re.I)
    normalized = re.sub(r"^arxiv:\s*", "", normalized, flags=re.I)
    normalized = normalized.removesuffix(".pdf")
    pattern = r"(?:[a-z-]+(?:\.[A-Z]{2})?/[0-9]{7}|[0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?"
    if not re.fullmatch(pattern, normalized, flags=re.I):
        raise ValueError("arXiv lookup 需要有效的论文标识")
    return normalized


def _parse_arxiv_feed(payload: bytes) -> list[BibliographicRecord]:
    if not payload:
        return []
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise MetadataConnectorError("arxiv 元数据响应不是有效 Atom XML") from exc
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    records: list[BibliographicRecord] = []
    for entry in root.findall("atom:entry", namespace):
        title = _xml_text(entry, "atom:title", namespace)
        identifier_url = _xml_text(entry, "atom:id", namespace)
        if not title or not identifier_url:
            continue
        authors = [
            Author(
                literal=" ".join(
                    author.findtext("atom:name", default="", namespaces=namespace).split()
                ),
                sequence="first" if index == 0 else "additional",
            )
            for index, author in enumerate(entry.findall("atom:author", namespace))
            if author.findtext("atom:name", default="", namespaces=namespace).strip()
        ]
        published = _xml_text(entry, "atom:published", namespace)
        year = int(published[:4]) if re.match(r"^[0-9]{4}", published) else None
        arxiv_id = identifier_url.rstrip("/").rsplit("/", 1)[-1]
        categories = [
            term
            for category in entry.findall("atom:category", namespace)
            if (term := category.attrib.get("term", ""))
        ]
        records.append(
            BibliographicRecord(
                type="preprint",
                title=title,
                authors=authors,
                issued_year=year,
                container_title="arXiv",
                url=identifier_url,
                abstract=_xml_text(entry, "atom:summary", namespace),
                keywords=categories,
                import_source="arxiv",
                source_key=arxiv_id,
                metadata_verified=True,
            )
        )
    return records


def _xml_text(element: ET.Element, path: str, namespace: dict[str, str]) -> str:
    return " ".join((element.findtext(path, default="", namespaces=namespace)).split())


__all__ = [
    "ArxivConnector",
    "AsyncRateLimiter",
    "CrossrefConnector",
    "MetadataConnector",
    "MetadataConnectorError",
    "MetadataRateLimitError",
    "MetadataTimeoutError",
    "OpenAlexConnector",
]
