"""Anthropic Messages API adapter implemented with ``httpx``."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from yanzhang.providers._http import DEFAULT_MAX_RESPONSE_BYTES, AsyncHTTPTransport
from yanzhang.providers.errors import ProviderConfigurationError, ProviderResponseError
from yanzhang.providers.llm.base import (
    LLMContentPart,
    LLMContentType,
    LLMFinishReason,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMRole,
    LLMToolCall,
    LLMUsage,
    MessageLike,
    normalize_messages,
    validate_generation_options,
)


class AnthropicProvider(AsyncHTTPTransport, LLMProvider):
    """Asynchronous adapter for Anthropic's Messages API."""

    provider_name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-5",
        base_url: str = "https://api.anthropic.com/v1",
        timeout: httpx.Timeout | float | None = None,
        client: httpx.AsyncClient | None = None,
        anthropic_version: str = "2023-06-01",
        endpoint: str = "/messages",
        default_max_tokens: int = 4_096,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderConfigurationError(
                "Anthropic API key is required", provider=self.provider_name
            )
        if not model:
            raise ProviderConfigurationError(
                "Anthropic model is required", provider=self.provider_name
            )
        if default_max_tokens <= 0:
            raise ProviderConfigurationError(
                "default_max_tokens must be positive", provider=self.provider_name
            )
        self.api_key = key
        self.model = model
        self.endpoint = endpoint
        self.default_max_tokens = default_max_tokens
        self._headers = {
            "x-api-key": key,
            "anthropic-version": anthropic_version,
            "content-type": "application/json",
        }
        self._init_transport(
            base_url=base_url,
            timeout=timeout,
            client=client,
            max_response_bytes=max_response_bytes,
        )

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
        del response_format  # JSON shape is requested in the portable prompt/schema.
        validate_generation_options(temperature=temperature, max_tokens=max_tokens)
        normalized = normalize_messages(messages)
        system_parts = [message.text for message in normalized if message.role in _SYSTEM_ROLES]
        chat_messages = [
            _message_payload(message) for message in normalized if message.role not in _SYSTEM_ROLES
        ]
        if not chat_messages:
            raise ValueError("Anthropic chat requires at least one user or assistant message")
        payload: dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": max_tokens or self.default_max_tokens,
            "messages": chat_messages,
        }
        if system_parts:
            payload["system"] = "\n\n".join(part for part in system_parts if part)
        if temperature is not None:
            payload["temperature"] = temperature
        if stop:
            payload["stop_sequences"] = list(stop)
        if tools:
            payload["tools"] = [_tool_definition(tool) for tool in tools]
        if metadata:
            user_id = metadata.get("user_id")
            if user_id is not None:
                payload["metadata"] = {"user_id": str(user_id)}
        data = await self._request_json(
            "POST", self.endpoint, headers=self._headers, json_body=payload
        )
        return _parse_response(data, self.provider_name)


_SYSTEM_ROLES = {LLMRole.SYSTEM, LLMRole.DEVELOPER}


def _message_payload(message: LLMMessage) -> dict[str, Any]:
    role = "assistant" if message.role is LLMRole.ASSISTANT else "user"
    if message.role is LLMRole.TOOL:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id or "",
                    "content": message.text,
                }
            ],
        }
    content = _content_payload(message)
    if message.tool_calls:
        if isinstance(content, str):
            blocks: list[dict[str, Any]] = [{"type": "text", "text": content}]
        else:
            blocks = list(content)
        blocks.extend(
            {
                "type": "tool_use",
                "id": call.id,
                "name": call.name,
                "input": _arguments_object(call.arguments),
            }
            for call in message.tool_calls
        )
        content = blocks
    return {"role": role, "content": content}


def _content_payload(message: LLMMessage) -> str | list[dict[str, Any]]:
    if isinstance(message.content, str) or message.content is None:
        return message.content or ""
    blocks: list[dict[str, Any]] = []
    for part in message.content:
        if part.type is LLMContentType.TEXT:
            blocks.append({"type": "text", "text": part.text or ""})
        elif part.type is LLMContentType.IMAGE_URL:
            blocks.append({"type": "image", "source": {"type": "url", "url": part.url or ""}})
        elif part.type is LLMContentType.FILE:
            blocks.append({"type": "document", "source": {"type": "url", "url": part.url or ""}})
    return blocks


def _tool_definition(tool: Mapping[str, Any]) -> dict[str, Any]:
    function = tool.get("function")
    source = function if isinstance(function, Mapping) else tool
    schema = source.get("parameters") or source.get("input_schema") or {"type": "object"}
    return {
        "name": str(source.get("name", "")),
        "description": str(source.get("description", "")),
        "input_schema": schema,
    }


def _parse_response(data: Mapping[str, Any], provider: str) -> LLMResponse:
    raw_content = data.get("content")
    if not isinstance(raw_content, Sequence) or isinstance(raw_content, (str, bytes)):
        raise ProviderResponseError("Anthropic response content is malformed", provider=provider)
    parts: list[LLMContentPart] = []
    calls: list[LLMToolCall] = []
    for block in raw_content:
        if not isinstance(block, Mapping):
            continue
        block_type = block.get("type")
        if block_type == "text":
            parts.append(LLMContentPart(type=LLMContentType.TEXT, text=str(block.get("text", ""))))
        elif block_type == "tool_use":
            raw_input = block.get("input")
            arguments: Mapping[str, Any] = raw_input if isinstance(raw_input, Mapping) else {}
            calls.append(
                LLMToolCall(
                    id=str(block.get("id", "")),
                    name=str(block.get("name", "")),
                    arguments=arguments,
                )
            )
    usage_data = data.get("usage")
    usage = usage_data if isinstance(usage_data, Mapping) else {}
    input_tokens = _integer(usage.get("input_tokens"))
    output_tokens = _integer(usage.get("output_tokens"))
    cached_tokens = _integer(usage.get("cache_read_input_tokens"))
    return LLMResponse(
        message=LLMMessage(
            role=LLMRole.ASSISTANT,
            content=tuple(parts),
            tool_calls=tuple(calls),
        ),
        provider=provider,
        model=_string_or_none(data.get("model")),
        finish_reason=_finish_reason(data.get("stop_reason")),
        usage=LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cached_input_tokens=cached_tokens,
        ),
        id=_string_or_none(data.get("id")),
        raw=data,
    )


def _arguments_object(arguments: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(arguments, Mapping):
        return arguments
    try:
        value = json.loads(arguments)
    except json.JSONDecodeError:
        return {"value": arguments}
    return value if isinstance(value, Mapping) else {"value": value}


def _finish_reason(value: Any) -> LLMFinishReason | None:
    if value is None:
        return None
    return {
        "end_turn": LLMFinishReason.STOP,
        "stop_sequence": LLMFinishReason.STOP,
        "max_tokens": LLMFinishReason.LENGTH,
        "tool_use": LLMFinishReason.TOOL_CALLS,
        "refusal": LLMFinishReason.CONTENT_FILTER,
    }.get(str(value), LLMFinishReason.OTHER)


def _integer(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def _string_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None
