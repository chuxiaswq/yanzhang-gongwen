"""Internal asynchronous HTTP transport shared by provider adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx

from yanzhang.providers.errors import (
    ProviderAPIError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderTransportError,
)

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
DEFAULT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MIN_MAX_RESPONSE_BYTES = 1024
MAX_MAX_RESPONSE_BYTES = 2 * 1024 * 1024 * 1024


class AsyncHTTPTransport:
    """Small ownership-aware wrapper around :class:`httpx.AsyncClient`.

    An injected client remains owned by its caller. A client created by this
    transport is closed by :meth:`aclose` and async context-manager exit.
    """

    provider_name = "provider"

    def _init_transport(
        self,
        *,
        base_url: str,
        timeout: httpx.Timeout | float | None = None,
        client: httpx.AsyncClient | None = None,
        default_headers: Mapping[str, str] | None = None,
        trust_env: bool = True,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        if not base_url or not base_url.strip():
            raise ValueError("base_url must be a non-empty URL")
        _validate_max_response_bytes(max_response_bytes)
        self._base_url = base_url.rstrip("/")
        self._max_response_bytes = max_response_bytes
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
            headers=dict(default_headers or {}),
            trust_env=trust_env,
        )

    @property
    def base_url(self) -> str:
        """The normalized API base URL."""

        return self._base_url

    @property
    def is_closed(self) -> bool:
        """Whether the underlying HTTP client has been closed."""

        return self._client.is_closed

    @property
    def max_response_bytes(self) -> int:
        """Maximum decoded JSON response size."""

        return self._max_response_bytes

    def _url(self, path: str) -> str:
        if path.startswith(("https://", "http://")):
            return path
        return f"{self._base_url}/{path.lstrip('/')}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        max_response_bytes: int | None = None,
    ) -> httpx.Response:
        try:
            if max_response_bytes is None:
                response = await self._client.request(
                    method,
                    self._url(path),
                    headers=dict(headers or {}),
                    params=params,
                    json=json_body,
                    data=data,
                )
            else:
                async with self._client.stream(
                    method,
                    self._url(path),
                    headers=dict(headers or {}),
                    params=params,
                    json=json_body,
                    data=data,
                ) as streamed_response:
                    response = await self._read_bounded_response(
                        streamed_response,
                        max_response_bytes=max_response_bytes,
                    )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"{self.provider_name} request timed out",
                provider=self.provider_name,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderTransportError(
                f"{self.provider_name} transport failed: {exc}",
                provider=self.provider_name,
                retryable=True,
            ) from exc

        if response.is_error:
            self._raise_api_error(response)
        return response

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        response = await self._request(
            method,
            path,
            headers=headers,
            params=params,
            json_body=json_body,
            data=data,
            max_response_bytes=self._max_response_bytes,
        )
        try:
            payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise ProviderResponseError(
                f"{self.provider_name} returned invalid JSON",
                provider=self.provider_name,
            ) from exc
        if not isinstance(payload, Mapping):
            raise ProviderResponseError(
                f"{self.provider_name} returned a non-object JSON response",
                provider=self.provider_name,
            )
        return payload

    async def _read_bounded_response(
        self,
        response: httpx.Response,
        *,
        max_response_bytes: int,
    ) -> httpx.Response:
        declared_size = _content_length(response.headers.get("content-length"))
        if declared_size is not None and declared_size > max_response_bytes:
            raise self._response_too_large(max_response_bytes)

        content = bytearray()
        async for chunk in response.aiter_bytes():
            if len(content) + len(chunk) > max_response_bytes:
                raise self._response_too_large(max_response_bytes)
            content.extend(chunk)

        return httpx.Response(
            status_code=response.status_code,
            headers=_decoded_response_headers(response.headers),
            content=bytes(content),
            request=response.request,
            extensions=dict(response.extensions),
            history=list(response.history),
            default_encoding=response.default_encoding,
        )

    def _response_too_large(self, max_response_bytes: int) -> ProviderResponseError:
        return ProviderResponseError(
            f"{self.provider_name} response exceeded the {max_response_bytes}-byte size limit",
            provider=self.provider_name,
        )

    def _raise_api_error(self, response: httpx.Response) -> None:
        payload: Mapping[str, Any] = {}
        try:
            decoded = response.json()
            if isinstance(decoded, Mapping):
                payload = decoded
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            pass

        error = payload.get("error")
        details = error if isinstance(error, Mapping) else payload
        message = _error_message(details) or _trimmed(response.text)
        if not message:
            message = f"HTTP {response.status_code}"
        code_value = details.get("code") if isinstance(details, Mapping) else None
        error_code = str(code_value) if code_value is not None else None
        request_id = (
            response.headers.get("x-request-id")
            or response.headers.get("request-id")
            or response.headers.get("x-amzn-requestid")
        )
        retry_after = _retry_after(response.headers.get("retry-after"))
        retryable = response.status_code in {408, 409, 425, 429} or response.status_code >= 500
        exception_type: type[ProviderAPIError]
        if response.status_code in {401, 403}:
            exception_type = ProviderAuthenticationError
        elif response.status_code == 429:
            exception_type = ProviderRateLimitError
        else:
            exception_type = ProviderAPIError
        raise exception_type(
            f"{self.provider_name} API error: {message}",
            provider=self.provider_name,
            status_code=response.status_code,
            error_code=error_code,
            request_id=request_id,
            retry_after_seconds=retry_after,
            details=details if isinstance(details, Mapping) else None,
            retryable=retryable,
        )

    async def aclose(self) -> None:
        """Close a client created by this adapter."""

        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()


def _error_message(details: Mapping[str, Any]) -> str | None:
    for key in ("message", "error", "detail", "msg"):
        value = details.get(key)
        if isinstance(value, str) and value:
            return _trimmed(value)
    return None


def _trimmed(value: str, limit: int = 1_000) -> str:
    clean = " ".join(value.split())
    return clean if len(clean) <= limit else f"{clean[:limit]}…"


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _validate_max_response_bytes(value: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not MIN_MAX_RESPONSE_BYTES <= value <= MAX_MAX_RESPONSE_BYTES
    ):
        raise ValueError(
            "max_response_bytes must be an integer between "
            f"{MIN_MAX_RESPONSE_BYTES} and {MAX_MAX_RESPONSE_BYTES}"
        )


def _content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _decoded_response_headers(headers: httpx.Headers) -> list[tuple[str, str]]:
    removed = {"content-encoding", "content-length", "transfer-encoding"}
    return [(name, value) for name, value in headers.multi_items() if name.lower() not in removed]
