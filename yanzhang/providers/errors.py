"""Provider-neutral exception hierarchy.

Adapters translate transport and vendor errors into these exceptions so callers do
not need to import a vendor SDK (or understand its error model).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ProviderError(RuntimeError):
    """Base class for all provider-layer failures."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class ProviderConfigurationError(ProviderError, ValueError):
    """A provider was constructed with incomplete or invalid configuration."""


class ProviderNotFoundError(ProviderConfigurationError, LookupError):
    """No provider with the requested registry name exists."""


class ProviderAlreadyRegisteredError(ProviderConfigurationError):
    """A registry name was registered twice without explicit replacement."""


class ProviderPluginError(ProviderConfigurationError):
    """A provider plugin could not be discovered or loaded."""


class ProviderTransportError(ProviderError):
    """The remote service could not be reached or the connection failed."""


class ProviderTimeoutError(ProviderTransportError, TimeoutError):
    """The request exceeded the configured timeout."""


class ProviderAPIError(ProviderError):
    """A provider returned an unsuccessful HTTP response."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        status_code: int | None = None,
        error_code: str | None = None,
        request_id: str | None = None,
        retry_after_seconds: float | None = None,
        details: Mapping[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message, provider=provider, retryable=retryable)
        self.status_code = status_code
        self.error_code = error_code
        self.request_id = request_id
        self.retry_after_seconds = retry_after_seconds
        self.details = dict(details or {})


class ProviderAuthenticationError(ProviderAPIError):
    """Credentials were absent, invalid, or rejected by the provider."""


class ProviderRateLimitError(ProviderAPIError):
    """The remote provider throttled the request."""


class ProviderResponseError(ProviderError):
    """A successful response did not match the provider's documented schema."""


class ProviderTaskFailedError(ProviderError):
    """An asynchronous provider task reached a failed terminal state."""
