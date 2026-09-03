"""Model-neutral contracts for large-language-model providers."""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import TracebackType
from typing import Any, Self


class LLMRole(StrEnum):
    """Portable chat roles understood by the provider adapters."""

    SYSTEM = "system"
    DEVELOPER = "developer"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class LLMContentType(StrEnum):
    """Supported model-neutral message content types."""

    TEXT = "text"
    IMAGE_URL = "image_url"
    AUDIO = "audio"
    FILE = "file"


class LLMFinishReason(StrEnum):
    """Normalized reason why a provider stopped generating."""

    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class LLMContentPart:
    """One text or media component within a chat message."""

    type: LLMContentType
    text: str | None = None
    url: str | None = None
    data: str | bytes | None = None
    mime_type: str | None = None
    detail: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", LLMContentType(self.type))
        if self.type is LLMContentType.TEXT and self.text is None:
            raise ValueError("text content requires text")
        if self.type is LLMContentType.IMAGE_URL and not self.url:
            raise ValueError("image_url content requires url")
        if self.type is LLMContentType.AUDIO and self.data is None:
            raise ValueError("audio content requires data")
        if self.type is LLMContentType.FILE and self.data is None and not self.url:
            raise ValueError("file content requires data or url")

    @classmethod
    def from_value(cls, value: LLMContentPart | Mapping[str, Any]) -> LLMContentPart:
        """Coerce a portable mapping into a typed content part."""

        if isinstance(value, LLMContentPart):
            return value
        part_type = value.get("type", LLMContentType.TEXT)
        image_value = value.get("image_url")
        url = value.get("url")
        detail = value.get("detail")
        if isinstance(image_value, str):
            url = image_value
        elif isinstance(image_value, Mapping):
            url = image_value.get("url", url)
            detail = image_value.get("detail", detail)
        return cls(
            type=LLMContentType(str(part_type)),
            text=_optional_str(value.get("text")),
            url=_optional_str(url),
            data=value.get("data") if isinstance(value.get("data"), (str, bytes)) else None,
            mime_type=_optional_str(value.get("mime_type")),
            detail=_optional_str(detail),
            metadata=_mapping(value.get("metadata")),
        )


@dataclass(frozen=True, slots=True)
class LLMToolCall:
    """A provider-neutral function/tool invocation emitted by an LLM."""

    id: str
    name: str
    arguments: str | Mapping[str, Any]
    type: str = "function"

    @classmethod
    def from_value(cls, value: LLMToolCall | Mapping[str, Any]) -> LLMToolCall:
        if isinstance(value, LLMToolCall):
            return value
        function = value.get("function")
        function_data = function if isinstance(function, Mapping) else value
        raw_arguments = function_data.get("arguments", "{}")
        arguments: str | Mapping[str, Any] = (
            raw_arguments if isinstance(raw_arguments, (str, Mapping)) else str(raw_arguments)
        )
        return cls(
            id=str(value.get("id", "")),
            name=str(function_data.get("name", "")),
            arguments=arguments,
            type=str(value.get("type", "function")),
        )


MessageContent = str | tuple[LLMContentPart, ...] | None


def encoded_content_data(data: str | bytes | None) -> str:
    """Return JSON-safe media data, base64-encoding raw bytes exactly once."""

    if data is None:
        return ""
    if isinstance(data, bytes):
        return base64.b64encode(data).decode("ascii")
    return data


@dataclass(frozen=True, slots=True)
class LLMMessage:
    """A model-neutral chat message.

    ``content`` accepts plain text or a tuple of typed multimodal parts. Use
    :meth:`from_value` when accepting JSON-like input from a CLI or MCP tool.
    """

    role: LLMRole
    content: MessageContent
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[LLMToolCall, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", LLMRole(self.role))
        if isinstance(self.content, Sequence) and not isinstance(self.content, (str, tuple)):
            object.__setattr__(
                self,
                "content",
                tuple(LLMContentPart.from_value(item) for item in self.content),
            )
        if isinstance(self.content, tuple):
            object.__setattr__(
                self,
                "content",
                tuple(LLMContentPart.from_value(item) for item in self.content),
            )
        object.__setattr__(
            self,
            "tool_calls",
            tuple(LLMToolCall.from_value(item) for item in self.tool_calls),
        )

    @property
    def text(self) -> str:
        """Return the concatenated textual content, ignoring media parts."""

        if isinstance(self.content, str):
            return self.content
        if self.content is None:
            return ""
        return "".join(part.text or "" for part in self.content if part.type is LLMContentType.TEXT)

    @classmethod
    def from_value(cls, value: LLMMessage | Mapping[str, Any]) -> LLMMessage:
        """Coerce the common ``{"role": ..., "content": ...}`` shape."""

        if isinstance(value, LLMMessage):
            return value
        content_value = value.get("content")
        content: MessageContent
        if content_value is None or isinstance(content_value, str):
            content = content_value
        elif isinstance(content_value, Sequence) and not isinstance(content_value, (str, bytes)):
            content = tuple(
                LLMContentPart.from_value(item)
                for item in content_value
                if isinstance(item, (LLMContentPart, Mapping))
            )
        else:
            content = str(content_value)
        raw_tool_calls = value.get("tool_calls", ())
        tool_calls = (
            tuple(
                LLMToolCall.from_value(item)
                for item in raw_tool_calls
                if isinstance(item, (LLMToolCall, Mapping))
            )
            if isinstance(raw_tool_calls, Sequence) and not isinstance(raw_tool_calls, (str, bytes))
            else ()
        )
        return cls(
            role=LLMRole(str(value.get("role", LLMRole.USER))),
            content=content,
            name=_optional_str(value.get("name")),
            tool_call_id=_optional_str(value.get("tool_call_id")),
            tool_calls=tool_calls,
            metadata=_mapping(value.get("metadata")),
        )


@dataclass(frozen=True, slots=True)
class LLMUsage:
    """Normalized token accounting returned by a provider."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0

    def __post_init__(self) -> None:
        if (
            min(
                self.input_tokens,
                self.output_tokens,
                self.total_tokens,
                self.cached_input_tokens,
                self.reasoning_tokens,
            )
            < 0
        ):
            raise ValueError("token counts cannot be negative")
        if self.total_tokens == 0 and (self.input_tokens or self.output_tokens):
            object.__setattr__(self, "total_tokens", self.input_tokens + self.output_tokens)


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Normalized response returned by every LLM provider."""

    message: LLMMessage
    provider: str
    model: str | None = None
    finish_reason: LLMFinishReason | None = None
    usage: LLMUsage = field(default_factory=LLMUsage)
    id: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.message.role is not LLMRole.ASSISTANT:
            raise ValueError("an LLM response message must have the assistant role")
        if self.finish_reason is not None:
            object.__setattr__(self, "finish_reason", LLMFinishReason(self.finish_reason))

    @property
    def content(self) -> str:
        """Convenient text-only view used by agents and simple integrations."""

        return self.message.text

    @property
    def tool_calls(self) -> tuple[LLMToolCall, ...]:
        return self.message.tool_calls


MessageLike = LLMMessage | Mapping[str, Any]


class LLMProvider(ABC):
    """Abstract asynchronous LLM provider."""

    provider_name: str
    model: str

    @abstractmethod
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
        """Generate one assistant response for a sequence of messages."""

    async def aclose(self) -> None:
        """Release resources owned by the provider."""

        return None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()


def normalize_messages(messages: Sequence[MessageLike]) -> tuple[LLMMessage, ...]:
    """Validate and normalize externally supplied messages."""

    if not messages:
        raise ValueError("messages must contain at least one message")
    return tuple(LLMMessage.from_value(message) for message in messages)


def validate_generation_options(
    *,
    temperature: float | None,
    max_tokens: int | None,
) -> None:
    """Apply portable validation before making a billable request."""

    if temperature is not None and not 0 <= temperature <= 2:
        raise ValueError("temperature must be between 0 and 2")
    if max_tokens is not None and max_tokens <= 0:
        raise ValueError("max_tokens must be positive")


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
