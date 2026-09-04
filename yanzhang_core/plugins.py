"""Extension registry for installable Yanzhang capabilities.

The writing core deliberately knows only factories.  Concrete connectors,
parsers, workflow steps, packs, reviewers, exporters, and publishing targets
are loaded by the composition root through Python entry points.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from importlib import metadata
from threading import RLock
from typing import Any, TypedDict, cast

from yanzhang_core.workflow import StepHandler, WorkflowEngine

type ExtensionFactory = Callable[..., object]

_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class ExtensionKind(StrEnum):
    """Stable extension seams offered by the general writing platform."""

    SOURCE_CONNECTOR = "source_connector"
    PARSER = "parser"
    WORKFLOW_STEP = "workflow_step"
    TEMPLATE_PACK = "template_pack"
    REVIEWER = "reviewer"
    EXPORTER = "exporter"
    PUBLISH_TARGET = "publish_target"


ENTRY_POINT_GROUPS: Mapping[ExtensionKind, str] = {
    ExtensionKind.SOURCE_CONNECTOR: "yanzhang.source_connectors",
    ExtensionKind.PARSER: "yanzhang.parsers",
    ExtensionKind.WORKFLOW_STEP: "yanzhang.workflow_steps",
    ExtensionKind.TEMPLATE_PACK: "yanzhang.template_packs",
    ExtensionKind.REVIEWER: "yanzhang.reviewers",
    ExtensionKind.EXPORTER: "yanzhang.exporters",
    ExtensionKind.PUBLISH_TARGET: "yanzhang.publish_targets",
}


class ExtensionRegistryError(RuntimeError):
    """Base error for extension registration and discovery."""


class ExtensionNotFoundError(ExtensionRegistryError):
    """Raised when an extension identity has no registered factory."""


class ExtensionAlreadyRegisteredError(ExtensionRegistryError):
    """Raised when a registration would unexpectedly replace a factory."""


class ExtensionPluginError(ExtensionRegistryError):
    """Raised when a third-party entry point or factory fails."""


@dataclass(frozen=True, slots=True)
class ExtensionRegistration:
    """One named extension factory together with its provenance."""

    name: str
    kind: ExtensionKind
    factory: ExtensionFactory
    source: str = "runtime"


@dataclass(frozen=True, slots=True)
class ExtensionDiscoveryReport:
    """Non-fatal result of scanning every supported entry-point group."""

    loaded: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    errors: Mapping[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Whether all discovered entries loaded successfully."""

        return not self.errors


class WorkflowStepWiringReport(TypedDict):
    """JSON-serializable result of wiring workflow-step extensions."""

    kind: str
    registered: list[str]
    sources: dict[str, str]


class ExtensionRegistry:
    """Thread-safe registry for provider-neutral writing extensions."""

    def __init__(self) -> None:
        self._entries_by_kind: dict[ExtensionKind, dict[str, ExtensionRegistration]] = {
            kind: {} for kind in ExtensionKind
        }
        self._lock = RLock()

    def register(
        self,
        kind: ExtensionKind | str,
        name: str,
        factory: ExtensionFactory,
        *,
        replace: bool = False,
        source: str = "runtime",
    ) -> None:
        """Register one factory under a stable kind/name identity."""

        extension_kind = ExtensionKind(kind)
        normalized = _normalize_name(name)
        if not callable(factory):
            raise TypeError("extension factory must be callable")
        with self._lock:
            entries = self._entries_by_kind[extension_kind]
            if normalized in entries and not replace:
                raise ExtensionAlreadyRegisteredError(
                    f"{extension_kind.value} extension {normalized!r} is already registered"
                )
            entries[normalized] = ExtensionRegistration(
                name=normalized,
                kind=extension_kind,
                factory=factory,
                source=source,
            )

    def unregister(self, kind: ExtensionKind | str, name: str) -> None:
        """Remove one factory."""

        extension_kind = ExtensionKind(kind)
        normalized = _normalize_name(name)
        with self._lock:
            entries = self._entries_by_kind[extension_kind]
            if normalized not in entries:
                raise ExtensionNotFoundError(
                    f"unknown {extension_kind.value} extension {normalized!r}"
                )
            del entries[normalized]

    def registration(
        self,
        kind: ExtensionKind | str,
        name: str,
    ) -> ExtensionRegistration:
        """Return registration metadata without instantiating the extension."""

        extension_kind = ExtensionKind(kind)
        normalized = _normalize_name(name)
        with self._lock:
            try:
                return self._entries_by_kind[extension_kind][normalized]
            except KeyError as exc:
                available = ", ".join(self.list(extension_kind)) or "none"
                raise ExtensionNotFoundError(
                    f"unknown {extension_kind.value} extension {normalized!r}; "
                    f"available: {available}"
                ) from exc

    def create(
        self,
        kind: ExtensionKind | str,
        name: str,
        **config: Any,
    ) -> object:
        """Construct an extension with caller-supplied, non-secret configuration."""

        registration = self.registration(kind, name)
        try:
            return registration.factory(**config)
        except Exception as exc:
            raise ExtensionPluginError(
                f"failed to construct {registration.kind.value} extension "
                f"{registration.name!r}: {exc}"
            ) from exc

    def list(self, kind: ExtensionKind | str) -> tuple[str, ...]:
        """List registered names for one extension kind."""

        extension_kind = ExtensionKind(kind)
        with self._lock:
            return tuple(sorted(self._entries_by_kind[extension_kind]))

    def catalog(self) -> Mapping[str, tuple[str, ...]]:
        """Return a stable, JSON-friendly inventory for status surfaces."""

        return {kind.value: self.list(kind) for kind in ExtensionKind}

    def discover(
        self,
        *,
        strict: bool = False,
        replace: bool = False,
    ) -> ExtensionDiscoveryReport:
        """Discover all supported writing extension entry points."""

        loaded: list[str] = []
        skipped: list[str] = []
        errors: dict[str, str] = {}
        for kind, group in ENTRY_POINT_GROUPS.items():
            for entry_point in _entry_points_for(group):
                identity = f"{group}:{entry_point.name}"
                try:
                    normalized = _normalize_name(entry_point.name)
                    with self._lock:
                        exists = normalized in self._entries_by_kind[kind]
                    if exists and not replace:
                        skipped.append(identity)
                        continue
                    loaded_factory = entry_point.load()
                    if not callable(loaded_factory):
                        raise TypeError("entry point did not resolve to a callable factory")
                    self.register(
                        kind,
                        normalized,
                        loaded_factory,
                        replace=replace,
                        source=f"entry-point:{entry_point.value}",
                    )
                except Exception as exc:  # third-party extension boundary
                    if strict:
                        raise ExtensionPluginError(
                            f"failed to load extension {identity}: {exc}"
                        ) from exc
                    errors[identity] = f"{type(exc).__name__}: {exc}"
                else:
                    loaded.append(identity)
        return ExtensionDiscoveryReport(
            loaded=tuple(loaded),
            skipped=tuple(skipped),
            errors=errors,
        )

    load_plugins = discover


def create_extension_registry(*, discover_plugins: bool = True) -> ExtensionRegistry:
    """Create an isolated extension registry and optionally scan entry points."""

    registry = ExtensionRegistry()
    if discover_plugins:
        registry.discover()
    return registry


def wire_workflow_step_extensions(
    registry: ExtensionRegistry,
    workflow_engine: WorkflowEngine,
    *,
    factory_config: Mapping[str, Mapping[str, object]] | None = None,
    replace: bool = False,
) -> WorkflowStepWiringReport:
    """Construct and register every discovered workflow-step extension.

    Construction is completed for every step before the engine is mutated.  This
    keeps a broken third-party factory from leaving a partially wired set of
    handlers.  Configuration is keyed by the normalized extension name and is
    passed only to that extension's factory.
    """

    names = registry.list(ExtensionKind.WORKFLOW_STEP)
    configuration = _normalize_factory_config(factory_config, available=names)
    handlers: list[tuple[ExtensionRegistration, StepHandler]] = []
    for name in names:
        registration = registry.registration(ExtensionKind.WORKFLOW_STEP, name)
        instance = registry.create(
            ExtensionKind.WORKFLOW_STEP,
            name,
            **configuration.get(name, {}),
        )
        if not callable(instance):
            raise ExtensionPluginError(
                f"workflow_step extension {name!r} did not construct a callable handler"
            )
        handlers.append((registration, cast(StepHandler, instance)))

    registered: list[str] = []
    sources: dict[str, str] = {}
    for registration, handler in handlers:
        try:
            workflow_engine.register_step(registration.name, handler, replace=replace)
        except Exception as exc:
            raise ExtensionPluginError(
                f"failed to register workflow_step extension {registration.name!r}: {exc}"
            ) from exc
        registered.append(registration.name)
        sources[registration.name] = registration.source

    return {
        "kind": ExtensionKind.WORKFLOW_STEP.value,
        "registered": registered,
        "sources": sources,
    }


def _normalize_factory_config(
    factory_config: Mapping[str, Mapping[str, object]] | None,
    *,
    available: tuple[str, ...],
) -> dict[str, dict[str, object]]:
    if factory_config is None:
        return {}

    normalized: dict[str, dict[str, object]] = {}
    for raw_name, values in factory_config.items():
        name = _normalize_name(raw_name)
        if name in normalized:
            raise ValueError(f"duplicate workflow-step configuration: {name}")
        normalized[name] = dict(values)
    unknown = sorted(set(normalized).difference(available))
    if unknown:
        raise ExtensionNotFoundError(
            "workflow-step configuration references unknown extensions: " + ", ".join(unknown)
        )
    return normalized


def _normalize_name(name: str) -> str:
    normalized = name.strip().casefold()
    if not _NAME_PATTERN.fullmatch(normalized):
        raise ValueError(
            "extension name must start with an alphanumeric character and contain only "
            "letters, digits, '.', '_' or '-'"
        )
    return normalized


def _entry_points_for(group: str) -> tuple[metadata.EntryPoint, ...]:
    entry_points = metadata.entry_points()
    if hasattr(entry_points, "select"):
        return tuple(entry_points.select(group=group))
    return tuple(entry_points.get(group, ()))  # type: ignore[attr-defined]


__all__ = [
    "ENTRY_POINT_GROUPS",
    "ExtensionAlreadyRegisteredError",
    "ExtensionDiscoveryReport",
    "ExtensionFactory",
    "ExtensionKind",
    "ExtensionNotFoundError",
    "ExtensionPluginError",
    "ExtensionRegistration",
    "ExtensionRegistry",
    "ExtensionRegistryError",
    "WorkflowStepWiringReport",
    "create_extension_registry",
    "wire_workflow_step_extensions",
]
