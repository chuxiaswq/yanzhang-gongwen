"""Deterministic in-memory LLM provider for local workflows and tests."""

from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from yanzhang.providers.llm.base import (
    LLMFinishReason,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMRole,
    LLMUsage,
    MessageLike,
    normalize_messages,
    validate_generation_options,
)


@dataclass(frozen=True, slots=True)
class FakeLLMCall:
    """Captured invocation for assertions and local diagnostics."""

    messages: tuple[LLMMessage, ...]
    model: str
    temperature: float | None
    max_tokens: int | None


class FakeLLMProvider(LLMProvider):
    """No-I/O LLM provider with optional scripted responses."""

    provider_name = "fake"

    def __init__(
        self,
        *,
        model: str = "fake-llm-v1",
        responses: Iterable[str | LLMResponse] = (),
        response_prefix: str = "Fake response",
    ) -> None:
        self.model = model
        self._responses = deque(responses)
        self.response_prefix = response_prefix
        self.calls: list[FakeLLMCall] = []

    async def chat(
        self,
        messages: Sequence[MessageLike],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop: Sequence[str] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        response_format: str | Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        del stop, tools, response_format, metadata
        validate_generation_options(temperature=temperature, max_tokens=max_tokens)
        normalized = normalize_messages(messages)
        selected_model = model or self.model
        self.calls.append(
            FakeLLMCall(
                messages=normalized,
                model=selected_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )
        if self._responses:
            scripted = self._responses.popleft()
            if isinstance(scripted, LLMResponse):
                return scripted
            content = scripted
        else:
            last_user = next(
                (message.text for message in reversed(normalized) if message.role is LLMRole.USER),
                normalized[-1].text,
            )
            digest = hashlib.sha256(last_user.encode("utf-8")).hexdigest()[:12]
            content = f"{self.response_prefix} [{digest}]: {last_user}"
        return LLMResponse(
            message=LLMMessage(role=LLMRole.ASSISTANT, content=content),
            provider=self.provider_name,
            model=selected_model,
            finish_reason=LLMFinishReason.STOP,
            usage=LLMUsage(),
            id=f"fake-{len(self.calls):08d}",
        )


MockLLMProvider = FakeLLMProvider
