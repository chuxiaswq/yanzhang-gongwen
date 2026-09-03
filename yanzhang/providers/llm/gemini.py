"""Google Gemini ``generateContent`` adapter implemented with ``httpx``."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

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


class GeminiProvider(AsyncHTTPTransport, LLMProvider):
    """Asynchronous adapter for Google's Gemini REST API."""

    provider_name = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gemini-2.5-pro",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: httpx.Timeout | float | None = None,
        client: httpx.AsyncClient | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise ProviderConfigurationError(
                "Gemini API key is required", provider=self.provider_name
            )
        if not model:
            raise ProviderConfigurationError(
                "Gemini model is required", provider=self.provider_name
            )
        self.api_key = key
        self.model = model
        self._headers = {"x-goog-api-key": key, "content-type": "application/json"}
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
        del metadata  # Gemini's generateContent endpoint has no request metadata field.
        validate_generation_options(temperature=temperature, max_tokens=max_tokens)
        normalized = normalize_messages(messages)
        selected_model = model or self.model
        system = [message.text for message in normalized if message.role in _SYSTEM_ROLES]
        contents = [
            _message_payload(message) for message in normalized if message.role not in _SYSTEM_ROLES
        ]
        if not contents:
            raise ValueError("Gemini chat requires at least one user or model message")
        payload: dict[str, Any] = {"contents": contents}
        if system:
            payload["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(text for text in system if text)}]
            }
        generation_config: dict[str, Any] = {}
        if temperature is not None:
            generation_config["temperature"] = temperature
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens
        if stop:
            generation_config["stopSequences"] = list(stop)
        if response_format is not None:
            if isinstance(response_format, str):
                generation_config["responseMimeType"] = (
                    "application/json"
                    if response_format in {"json", "json_object"}
                    else response_format
                )
            else:
                generation_config["responseMimeType"] = "application/json"
                schema = response_format.get("json_schema") or response_format.get("schema")
                if schema is not None:
                    generation_config["responseJsonSchema"] = schema
        if generation_config:
            payload["generationConfig"] = generation_config
        if tools:
            payload["tools"] = [
                {"functionDeclarations": [_tool_definition(tool) for tool in tools]}
            ]
        endpoint = f"/models/{quote(selected_model, safe='')}:generateContent"
        data = await self._request_json("POST", endpoint, headers=self._headers, json_body=payload)
        return _parse_response(data, self.provider_name, selected_model)


_SYSTEM_ROLES = {LLMRole.SYSTEM, LLMRole.DEVELOPER}


def _message_payload(message: LLMMessage) -> dict[str, Any]:
    role = "model" if message.role is LLMRole.ASSISTANT else "user"
    if message.role is LLMRole.TOOL:
        return {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": message.name or "tool",
                        "response": {"result": message.text},
                    }
                }
            ],
        }
    parts = _content_payload(message)
    parts.extend(
        {
            "functionCall": {
                "name": call.name,
                "args": _arguments_object(call.arguments),
            }
        }
        for call in message.tool_calls
    )
    return {"role": role, "parts": parts}


def _content_payload(message: LLMMessage) -> list[dict[str, Any]]:
    if isinstance(message.content, str) or message.content is None:
        return [{"text": message.content or ""}]
    parts: list[dict[str, Any]] = []
    for part in message.content:
        if part.type is LLMContentType.TEXT:
            parts.append({"text": part.text or ""})
        elif part.type in {LLMContentType.IMAGE_URL, LLMContentType.FILE}:
            parts.append(
                {
                    "fileData": {
                        "mimeType": part.mime_type or "application/octet-stream",
                        "fileUri": part.url or "",
                    }
                }
            )
        elif part.type is LLMContentType.AUDIO:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": part.mime_type or "audio/mpeg",
                        "data": encoded_content_data(part.data),
                    }
                }
            )
    return parts


def _tool_definition(tool: Mapping[str, Any]) -> dict[str, Any]:
    function = tool.get("function")
    source = function if isinstance(function, Mapping) else tool
    return {
        "name": str(source.get("name", "")),
        "description": str(source.get("description", "")),
        "parameters": source.get("parameters", {"type": "object"}),
    }


def _parse_response(data: Mapping[str, Any], provider: str, model: str) -> LLMResponse:
    candidates = data.get("candidates")
    if (
        not isinstance(candidates, Sequence)
        or isinstance(candidates, (str, bytes))
        or not candidates
    ):
        feedback = data.get("promptFeedback")
        raise ProviderResponseError(
            f"Gemini response has no candidates: {feedback!r}", provider=provider
        )
    candidate = candidates[0]
    if not isinstance(candidate, Mapping):
        raise ProviderResponseError("Gemini candidate is malformed", provider=provider)
    content = candidate.get("content")
    content_map = content if isinstance(content, Mapping) else {}
    raw_parts = content_map.get("parts", ())
    if not isinstance(raw_parts, Sequence) or isinstance(raw_parts, (str, bytes)):
        raise ProviderResponseError("Gemini response parts are malformed", provider=provider)
    parts: list[LLMContentPart] = []
    calls: list[LLMToolCall] = []
    for part in raw_parts:
        if not isinstance(part, Mapping):
            continue
        if "text" in part:
            parts.append(LLMContentPart(type=LLMContentType.TEXT, text=str(part.get("text", ""))))
        function_call = part.get("functionCall")
        if isinstance(function_call, Mapping):
            name = str(function_call.get("name", ""))
            raw_arguments = function_call.get("args")
            arguments: Mapping[str, Any] = (
                raw_arguments if isinstance(raw_arguments, Mapping) else {}
            )
            calls.append(
                LLMToolCall(
                    id=f"gemini-{len(calls)}-{name}",
                    name=name,
                    arguments=arguments,
                )
            )
    usage_data = data.get("usageMetadata")
    usage = usage_data if isinstance(usage_data, Mapping) else {}
    input_tokens = _integer(usage.get("promptTokenCount"))
    output_tokens = _integer(usage.get("candidatesTokenCount"))
    return LLMResponse(
        message=LLMMessage(
            role=LLMRole.ASSISTANT,
            content=tuple(parts),
            tool_calls=tuple(calls),
        ),
        provider=provider,
        model=model,
        finish_reason=_finish_reason(candidate.get("finishReason")),
        usage=LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=_integer(usage.get("totalTokenCount")) or input_tokens + output_tokens,
            cached_input_tokens=_integer(usage.get("cachedContentTokenCount")),
            reasoning_tokens=_integer(usage.get("thoughtsTokenCount")),
        ),
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
    normalized = str(value).upper()
    return {
        "STOP": LLMFinishReason.STOP,
        "MAX_TOKENS": LLMFinishReason.LENGTH,
        "SAFETY": LLMFinishReason.CONTENT_FILTER,
        "BLOCKLIST": LLMFinishReason.CONTENT_FILTER,
        "PROHIBITED_CONTENT": LLMFinishReason.CONTENT_FILTER,
    }.get(normalized, LLMFinishReason.OTHER)


def _integer(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) else 0
