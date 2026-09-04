"""Composition-root adapter from runtime settings to a writing-model callback.

The general writing core accepts a tiny text callback and remains independent
of concrete model vendors.  This module owns provider construction, the remote
request lifetime, normalized response checks, and prompt-size boundaries.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from gongwen_web.models import ProviderSettings
from gongwen_web.runtime import RuntimeSettings
from yanzhang.providers.llm.base import LLMProvider
from yanzhang.providers.registry import ProviderKind, ProviderRegistry, get_default_registry

_MAX_PROMPT_CHARS = 500_000
_MAX_RESPONSE_CHARS = 1_000_000
_RESERVED_OPTIONS = frozenset({"api_key", "base_url", "model", "timeout"})


class ModelGatewayError(ValueError):
    """Stable configuration or response error for the general writing path."""


class RuntimeModelCallback:
    """Callable that performs exactly one provider-neutral model exchange."""

    def __init__(
        self,
        settings: RuntimeSettings,
        *,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._registry = registry or get_default_registry()

    async def __call__(self, system_prompt: str, user_prompt: str, /) -> str:
        """Generate text while keeping credentials inside the server boundary."""

        system_text = system_prompt.strip()
        user_text = user_prompt.strip()
        if not system_text or not user_text:
            raise ModelGatewayError("模型提示词需要包含系统要求和用户任务")
        if len(system_text) + len(user_text) > _MAX_PROMPT_CHARS:
            raise ModelGatewayError("模型提示词超过 500000 字符上限")

        provider_settings = self._settings.resolve_provider(None)
        if provider_settings is None:
            raise ModelGatewayError("实时写作模式尚未配置服务端模型")
        provider = self._create_provider(provider_settings)
        try:
            response = await provider.chat(
                (
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_text},
                ),
                model=provider_settings.model,
                temperature=0.2,
                max_tokens=8_192,
                metadata={"operation": "yanzhang_writing"},
            )
        finally:
            await provider.aclose()
        content = response.content.strip()
        if not content:
            raise ModelGatewayError("模型返回了空文本")
        if len(content) > _MAX_RESPONSE_CHARS:
            raise ModelGatewayError("模型返回文本超过 1000000 字符上限")
        return content

    def _create_provider(self, settings: ProviderSettings) -> LLMProvider:
        name = settings.name.strip().casefold()
        if not name:
            raise ModelGatewayError("模型服务商名称为空")
        registration = self._registry.registration(ProviderKind.LLM, name)
        candidates: dict[str, object | None] = {
            **{
                key: value
                for key, value in settings.options.items()
                if key not in _RESERVED_OPTIONS
            },
            "model": settings.model,
            "api_key": settings.api_key,
            "base_url": settings.base_url,
            "timeout": settings.timeout_seconds,
        }
        return self._registry.create_llm(
            name,
            **_supported_options(registration.factory, candidates),
        )


def build_model_callback(
    settings: RuntimeSettings,
    *,
    registry: ProviderRegistry | None = None,
) -> RuntimeModelCallback | None:
    """Return a live callback only when the server model is fully configured."""

    if not settings.server_provider_configured:
        return None
    return RuntimeModelCallback(settings, registry=registry)


def _supported_options(
    factory: Callable[..., Any],
    candidates: Mapping[str, object | None],
) -> dict[str, object]:
    values = {key: value for key, value in candidates.items() if value is not None}
    try:
        signature = inspect.signature(factory)
    except (TypeError, ValueError):
        return values
    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return values
    return {key: value for key, value in values.items() if key in signature.parameters}


__all__ = ["ModelGatewayError", "RuntimeModelCallback", "build_model_callback"]
