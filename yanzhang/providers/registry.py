"""Provider registry and Python entry-point discovery for Yanzhang."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from importlib import metadata
from threading import RLock
from typing import Any, cast

from yanzhang.providers.content.article_discovery import ArticleDiscoveryProvider
from yanzhang.providers.content.article_http import ArticleFetcherProvider
from yanzhang.providers.errors import (
    ProviderAlreadyRegisteredError,
    ProviderNotFoundError,
    ProviderPluginError,
)
from yanzhang.providers.llm.base import LLMProvider

LLM_ENTRY_POINT_GROUP = "yanzhang.llm_providers"
ARTICLE_DISCOVERY_ENTRY_POINT_GROUP = "yanzhang.article_discovery_providers"
ARTICLE_FETCHER_ENTRY_POINT_GROUP = "yanzhang.article_fetcher_providers"

type LLMFactory = Callable[..., LLMProvider]
type ArticleDiscoveryFactory = Callable[..., ArticleDiscoveryProvider]
type ArticleFetcherFactory = Callable[..., ArticleFetcherProvider]
type ProviderFactory = LLMFactory | ArticleDiscoveryFactory | ArticleFetcherFactory

_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class ProviderKind(StrEnum):
    """Provider categories used by the standalone writing service."""

    LLM = "llm"
    ARTICLE_DISCOVERY = "article_discovery"
    ARTICLE_FETCHER = "article_fetcher"


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    """A registry entry and its provenance."""

    name: str
    kind: ProviderKind
    factory: ProviderFactory
    source: str = "runtime"


@dataclass(frozen=True, slots=True)
class PluginDiscoveryReport:
    """Non-fatal outcome of entry-point discovery."""

    loaded: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    errors: Mapping[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


class ProviderRegistry:
    """Name-to-factory registry for writing-model and article adapters."""

    def __init__(self) -> None:
        self._llm: dict[str, ProviderRegistration] = {}
        self._article_discovery: dict[str, ProviderRegistration] = {}
        self._article_fetcher: dict[str, ProviderRegistration] = {}
        self._lock = RLock()

    def register_llm(
        self,
        name: str,
        factory: LLMFactory,
        *,
        replace: bool = False,
        source: str = "runtime",
    ) -> None:
        self._register(ProviderKind.LLM, name, factory, replace=replace, source=source)

    def register_article_discovery(
        self,
        name: str,
        factory: ArticleDiscoveryFactory,
        *,
        replace: bool = False,
        source: str = "runtime",
    ) -> None:
        self._register(
            ProviderKind.ARTICLE_DISCOVERY,
            name,
            factory,
            replace=replace,
            source=source,
        )

    def register_article_fetcher(
        self,
        name: str,
        factory: ArticleFetcherFactory,
        *,
        replace: bool = False,
        source: str = "runtime",
    ) -> None:
        self._register(
            ProviderKind.ARTICLE_FETCHER,
            name,
            factory,
            replace=replace,
            source=source,
        )

    def unregister_llm(self, name: str) -> None:
        self._unregister(ProviderKind.LLM, name)

    def unregister_article_discovery(self, name: str) -> None:
        self._unregister(ProviderKind.ARTICLE_DISCOVERY, name)

    def unregister_article_fetcher(self, name: str) -> None:
        self._unregister(ProviderKind.ARTICLE_FETCHER, name)

    def create_llm(self, name: str, **config: Any) -> LLMProvider:
        """Construct a registered LLM adapter."""

        registration = self._lookup(ProviderKind.LLM, name)
        try:
            provider = registration.factory(**config)
        except TypeError as exc:
            raise ProviderPluginError(
                f"failed to construct LLM provider {name!r}: {exc}", provider=name
            ) from exc
        if not isinstance(provider, LLMProvider):
            raise ProviderPluginError(
                f"LLM factory {name!r} returned {type(provider).__name__}, not LLMProvider",
                provider=name,
            )
        return provider

    def create_article_discovery(
        self,
        name: str,
        **config: Any,
    ) -> ArticleDiscoveryProvider:
        """Construct a registered article-discovery adapter."""

        registration = self._lookup(ProviderKind.ARTICLE_DISCOVERY, name)
        try:
            provider = registration.factory(**config)
        except TypeError as exc:
            raise ProviderPluginError(
                f"failed to construct article discovery provider {name!r}: {exc}",
                provider=name,
            ) from exc
        if not isinstance(provider, ArticleDiscoveryProvider):
            raise ProviderPluginError(
                f"article discovery factory {name!r} returned "
                f"{type(provider).__name__}, not ArticleDiscoveryProvider",
                provider=name,
            )
        return provider

    def create_article_fetcher(
        self,
        name: str,
        **config: Any,
    ) -> ArticleFetcherProvider:
        """Construct a registered article-fetcher adapter."""

        registration = self._lookup(ProviderKind.ARTICLE_FETCHER, name)
        try:
            provider = registration.factory(**config)
        except TypeError as exc:
            raise ProviderPluginError(
                f"failed to construct article fetcher provider {name!r}: {exc}",
                provider=name,
            ) from exc
        if not isinstance(provider, ArticleFetcherProvider):
            raise ProviderPluginError(
                f"article fetcher factory {name!r} returned "
                f"{type(provider).__name__}, not ArticleFetcherProvider",
                provider=name,
            )
        return provider

    def list_llm(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._llm))

    def list_article_discovery(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._article_discovery))

    def list_article_fetcher(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._article_fetcher))

    def registration(self, kind: ProviderKind | str, name: str) -> ProviderRegistration:
        return self._lookup(ProviderKind(kind), name)

    def discover(
        self,
        *,
        strict: bool = False,
        replace: bool = False,
    ) -> PluginDiscoveryReport:
        """Load external provider factories from Yanzhang entry-point groups."""

        loaded: list[str] = []
        skipped: list[str] = []
        errors: dict[str, str] = {}
        with self._lock:
            groups = (
                (ProviderKind.LLM, LLM_ENTRY_POINT_GROUP),
                (ProviderKind.ARTICLE_DISCOVERY, ARTICLE_DISCOVERY_ENTRY_POINT_GROUP),
                (ProviderKind.ARTICLE_FETCHER, ARTICLE_FETCHER_ENTRY_POINT_GROUP),
            )
            for kind, group in groups:
                for entry_point in _entry_points_for(group):
                    identity = f"{group}:{entry_point.name}"
                    normalized_name = _normalize_name(entry_point.name)
                    target = self._entries(kind)
                    if normalized_name in target and not replace:
                        skipped.append(identity)
                        continue
                    try:
                        loaded_factory = entry_point.load()
                        if not callable(loaded_factory):
                            raise TypeError("entry point did not resolve to a callable factory")
                        self._register(
                            kind,
                            normalized_name,
                            cast(ProviderFactory, loaded_factory),
                            replace=replace,
                            source=f"entry-point:{entry_point.value}",
                        )
                    except Exception as exc:  # third-party extension boundary
                        if strict:
                            raise ProviderPluginError(
                                f"failed to load provider plugin {identity}: {exc}",
                                provider=normalized_name,
                            ) from exc
                        errors[identity] = f"{type(exc).__name__}: {exc}"
                    else:
                        loaded.append(identity)
        return PluginDiscoveryReport(
            loaded=tuple(loaded),
            skipped=tuple(skipped),
            errors=errors,
        )

    load_plugins = discover

    def _register(
        self,
        kind: ProviderKind,
        name: str,
        factory: ProviderFactory,
        *,
        replace: bool,
        source: str,
    ) -> None:
        normalized = _normalize_name(name)
        if not callable(factory):
            raise TypeError("provider factory must be callable")
        with self._lock:
            entries = self._entries(kind)
            if normalized in entries and not replace:
                raise ProviderAlreadyRegisteredError(
                    f"{kind.value} provider {normalized!r} is already registered",
                    provider=normalized,
                )
            entries[normalized] = ProviderRegistration(
                name=normalized,
                kind=kind,
                factory=factory,
                source=source,
            )

    def _unregister(self, kind: ProviderKind, name: str) -> None:
        normalized = _normalize_name(name)
        with self._lock:
            entries = self._entries(kind)
            if normalized not in entries:
                raise ProviderNotFoundError(
                    f"unknown {kind.value} provider {normalized!r}", provider=normalized
                )
            del entries[normalized]

    def _lookup(self, kind: ProviderKind, name: str) -> ProviderRegistration:
        normalized = _normalize_name(name)
        with self._lock:
            entries = self._entries(kind)
            try:
                return entries[normalized]
            except KeyError as exc:
                available = ", ".join(sorted(entries)) or "none"
                raise ProviderNotFoundError(
                    f"unknown {kind.value} provider {normalized!r}; available: {available}",
                    provider=normalized,
                ) from exc

    def _entries(self, kind: ProviderKind) -> dict[str, ProviderRegistration]:
        if kind is ProviderKind.LLM:
            return self._llm
        if kind is ProviderKind.ARTICLE_DISCOVERY:
            return self._article_discovery
        return self._article_fetcher


def register_builtin_providers(registry: ProviderRegistry) -> ProviderRegistry:
    """Register bundled adapters without making network requests."""

    from yanzhang.providers.content import HTTPArticleFetcher, OfficialSearchDiscoveryProvider
    from yanzhang.providers.llm import (
        AnthropicProvider,
        FakeLLMProvider,
        GeminiProvider,
        OpenAIProvider,
    )

    for name, factory in {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "gemini": GeminiProvider,
        "fake": FakeLLMProvider,
        "mock": FakeLLMProvider,
    }.items():
        registry.register_llm(name, factory, source="builtin")
    registry.register_article_discovery(
        "official_search",
        OfficialSearchDiscoveryProvider,
        source="builtin",
    )
    registry.register_article_fetcher(
        "official_http",
        HTTPArticleFetcher,
        source="builtin",
    )
    return registry


def create_default_registry(
    *,
    discover_plugins: bool = True,
    strict_plugins: bool = False,
) -> ProviderRegistry:
    """Create an isolated registry containing built-ins and optional plugins."""

    registry = register_builtin_providers(ProviderRegistry())
    if discover_plugins:
        registry.discover(strict=strict_plugins)
    return registry


_default_registry: ProviderRegistry | None = None
_default_registry_lock = RLock()


def get_default_registry() -> ProviderRegistry:
    """Return the process-wide lazily initialized provider registry."""

    global _default_registry
    if _default_registry is None:
        with _default_registry_lock:
            if _default_registry is None:
                _default_registry = create_default_registry()
    return _default_registry


def _normalize_name(name: str) -> str:
    normalized = name.strip().casefold()
    if not _NAME_PATTERN.fullmatch(normalized):
        raise ValueError(
            "provider name must start with an alphanumeric character and contain only "
            "letters, digits, '.', '_' or '-'"
        )
    return normalized


def _entry_points_for(group: str) -> tuple[metadata.EntryPoint, ...]:
    entry_points = metadata.entry_points()
    if hasattr(entry_points, "select"):
        return tuple(entry_points.select(group=group))
    return tuple(entry_points.get(group, ()))  # type: ignore[attr-defined]


__all__ = [
    "ARTICLE_DISCOVERY_ENTRY_POINT_GROUP",
    "ARTICLE_FETCHER_ENTRY_POINT_GROUP",
    "LLM_ENTRY_POINT_GROUP",
    "PluginDiscoveryReport",
    "ProviderKind",
    "ProviderRegistration",
    "ProviderRegistry",
    "create_default_registry",
    "get_default_registry",
    "register_builtin_providers",
]
