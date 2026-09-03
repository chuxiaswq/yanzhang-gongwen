"""OpenAI Chat Completions adapter implemented with ``httpx``."""

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
    encoded_content_data,
    normalize_messages,
    validate_generation_options,
)


class OpenAIProvider(AsyncHTTPTransport, LLMProvider):
    """Asynchronous adapter for an OpenAI-compatible chat endpoint."""

    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-5",
        base_url: str = "https://api.openai.com/v1",
        timeout: httpx.Timeout | float | None = None,
        client: httpx.AsyncClient | None = None,
        organization: str | None = None,
        project: str | None = None,
        endpoint: str = "/chat/completions",
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise ProviderConfigurationError(
                "OpenAI API key is required", provider=self.provider_name
            )
        if not model:
            raise ProviderConfigurationError(
                "OpenAI model is required", provider=self.provider_name
            )
        self.api_key = key
        self.model = model
        self.endpoint = endpoint
        self._headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        if organization:
            self._headers["OpenAI-Organization"] = organization
        if project:
            self._headers["OpenAI-Project"] = project
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
        validate_generation_options(temperature=temperature, max_tokens=max_tokens)
        normalized = normalize_messages(messages)
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": [_message_payload(message) for message in normalized],
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_completion_tokens"] = max_tokens
        if stop:
            payload["stop"] = list(stop)
        if tools:
            payload["tools"] = list(tools)
        if response_format is not None:
            payload["response_format"] = (
                {"type": response_format}
                if isinstance(response_format, str)
                else dict(response_format)
            )
        if metadata:
            payload["metadata"] = dict(metadata)

        data = await self._request_json(
            "POST", self.endpoint, headers=self._headers, json_body=payload
        )
        return _parse_response(data, self.provider_name)


def _message_payload(message: LLMMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": message.role.value,
        "content": _content_payload(message),
    }
    if message.name:
        payload["name"] = message.name
    if message.tool_call_id:
        payload["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": tool_call.type,
                "function": {
                    "name": tool_call.name,
                    "arguments": _arguments_text(tool_call.arguments),
                },
            }
            for tool_call in message.tool_calls
        ]
    return payload


def _content_payload(message: LLMMessage) -> str | list[dict[str, Any]] | None:
    if isinstance(message.content, str) or message.content is None:
        return message.content
    content: list[dict[str, Any]] = []
    for part in message.content:
        if part.type is LLMContentType.TEXT:
            content.append({"type": "text", "text": part.text or ""})
        elif part.type is LLMContentType.IMAGE_URL:
            image: dict[str, Any] = {"url": part.url}
            if part.detail:
                image["detail"] = part.detail
            content.append({"type": "image_url", "image_url": image})
        elif part.type is LLMContentType.AUDIO:
            audio: dict[str, Any] = {"data": encoded_content_data(part.data)}
            if part.mime_type:
                audio["format"] = part.mime_type.rsplit("/", 1)[-1]
            content.append({"type": "input_audio", "input_audio": audio})
        elif part.type is LLMContentType.FILE:
            file_data: dict[str, Any] = {}
            if part.url:
                file_data["file_url"] = part.url
            if part.data:
                file_data["file_data"] = encoded_content_data(part.data)
            content.append({"type": "file", "file": file_data})
    return content


def _parse_response(data: Mapping[str, Any], provider: str) -> LLMResponse:
    choices = data.get("choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        raise ProviderResponseError("OpenAI response has no choices", provider=provider)
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise ProviderResponseError("OpenAI choice is malformed", provider=provider)
    message_data = choice.get("message")
    if not isinstance(message_data, Mapping):
        raise ProviderResponseError("OpenAI response message is malformed", provider=provider)

    content = _parse_content(message_data.get("content"))
    raw_tool_calls = message_data.get("tool_calls", ())
    tool_calls = (
        tuple(
            LLMToolCall.from_value(value) for value in raw_tool_calls if isinstance(value, Mapping)
        )
        if isinstance(raw_tool_calls, Sequence) and not isinstance(raw_tool_calls, (str, bytes))
        else ()
    )
    usage_data = data.get("usage")
    usage_map = usage_data if isinstance(usage_data, Mapping) else {}
    prompt_details = usage_map.get("prompt_tokens_details")
    completion_details = usage_map.get("completion_tokens_details")
    prompt_map = prompt_details if isinstance(prompt_details, Mapping) else {}
    completion_map = completion_details if isinstance(completion_details, Mapping) else {}
    finish_reason = _finish_reason(choice.get("finish_reason"))
    return LLMResponse(
        message=LLMMessage(
            role=LLMRole.ASSISTANT,
            content=content,
            tool_calls=tool_calls,
        ),
        provider=provider,
        model=_string_or_none(data.get("model")),
        finish_reason=finish_reason,
        usage=LLMUsage(
            input_tokens=_integer(usage_map.get("prompt_tokens")),
            output_tokens=_integer(usage_map.get("completion_tokens")),
            total_tokens=_integer(usage_map.get("total_tokens")),
            cached_input_tokens=_integer(prompt_map.get("cached_tokens")),
            reasoning_tokens=_integer(completion_map.get("reasoning_tokens")),
        ),
        id=_string_or_none(data.get("id")),
        raw=data,
    )


def _parse_content(value: Any) -> str | tuple[LLMContentPart, ...] | None:
    if value is None or isinstance(value, str):
        return value
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return str(value)
    parts: list[LLMContentPart] = []
    for raw_part in value:
        if not isinstance(raw_part, Mapping):
            continue
        text = raw_part.get("text") or raw_part.get("refusal")
        if text is not None:
            parts.append(LLMContentPart(type=LLMContentType.TEXT, text=str(text)))
    return tuple(parts)


def _arguments_text(arguments: str | Mapping[str, Any]) -> str:
    return arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)


def _finish_reason(value: Any) -> LLMFinishReason | None:
    if value is None:
        return None
    return {
        "stop": LLMFinishReason.STOP,
        "length": LLMFinishReason.LENGTH,
        "tool_calls": LLMFinishReason.TOOL_CALLS,
        "function_call": LLMFinishReason.TOOL_CALLS,
        "content_filter": LLMFinishReason.CONTENT_FILTER,
    }.get(str(value), LLMFinishReason.OTHER)


def _integer(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def _string_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None
