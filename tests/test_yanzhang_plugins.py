"""Tests for the general writing extension registry."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

import yanzhang_core.plugins as plugin_module
from yanzhang_core.plugins import (
    ENTRY_POINT_GROUPS,
    ExtensionAlreadyRegisteredError,
    ExtensionKind,
    ExtensionNotFoundError,
    ExtensionPluginError,
    ExtensionRegistry,
    wire_workflow_step_extensions,
)
from yanzhang_core.storage import WritingStorage
from yanzhang_core.workflow import (
    StepContext,
    StepResult,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowStepDefinition,
)


@dataclass(frozen=True)
class _FixtureExtension:
    label: str


@dataclass(frozen=True)
class _FixtureEntryPoint:
    name: str
    value: str
    factory: Callable[..., object]

    def load(self) -> object:
        return self.factory


def test_registry_constructs_each_extension_kind() -> None:
    registry = ExtensionRegistry()
    for kind in ExtensionKind:
        registry.register(kind, "fixture", lambda label=kind.value: _FixtureExtension(label))

    assert set(registry.catalog()) == {kind.value for kind in ExtensionKind}
    assert set(ENTRY_POINT_GROUPS) == set(ExtensionKind)
    for kind in ExtensionKind:
        created = registry.create(kind, "fixture")
        assert isinstance(created, _FixtureExtension)
        assert created.label == kind.value


def test_registry_replacement_and_missing_contract() -> None:
    registry = ExtensionRegistry()
    registry.register(ExtensionKind.PARSER, "markdown", lambda: "v1")
    with pytest.raises(ExtensionAlreadyRegisteredError):
        registry.register(ExtensionKind.PARSER, "markdown", lambda: "v2")

    registry.register(
        ExtensionKind.PARSER,
        "markdown",
        lambda: "v2",
        replace=True,
    )
    assert registry.create(ExtensionKind.PARSER, "MARKDOWN") == "v2"
    registry.unregister(ExtensionKind.PARSER, "markdown")
    with pytest.raises(ExtensionNotFoundError):
        registry.create(ExtensionKind.PARSER, "markdown")


def test_registry_wraps_factory_failures() -> None:
    registry = ExtensionRegistry()

    def broken() -> object:
        raise RuntimeError("fixture failure")

    registry.register(ExtensionKind.EXPORTER, "broken", broken)
    with pytest.raises(ExtensionPluginError, match="fixture failure"):
        registry.create(ExtensionKind.EXPORTER, "broken")


def test_registry_rejects_ambiguous_names() -> None:
    registry = ExtensionRegistry()
    with pytest.raises(ValueError):
        registry.register(ExtensionKind.REVIEWER, "bad/name", lambda: object())


def test_discovered_workflow_step_is_wired_and_executed_without_catalog_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries_by_group: dict[str, tuple[_FixtureEntryPoint, ...]] = {}
    factory: Callable[..., object]
    for kind, group in ENTRY_POINT_GROUPS.items():
        if kind is ExtensionKind.WORKFLOW_STEP:

            def step_factory(*, prefix: object = "wired") -> object:
                def handler(context: StepContext) -> StepResult:
                    return StepResult(
                        state_updates={"plugin_result": f"{prefix}:{context.input['topic']}"}
                    )

                return handler

            factory = step_factory
        else:

            def fixture_factory(label: object = kind.value) -> object:
                return _FixtureExtension(str(label))

            factory = fixture_factory
        entries_by_group[group] = (
            _FixtureEntryPoint(
                name=f"fixture-{kind.value}",
                value=f"fixture:{kind.value}",
                factory=factory,
            ),
        )

    monkeypatch.setattr(
        plugin_module,
        "_entry_points_for",
        lambda group: entries_by_group.get(group, ()),
    )
    registry = ExtensionRegistry()
    discovery = registry.discover(strict=True)
    assert discovery.ok is True
    assert len(discovery.loaded) == len(ExtensionKind)
    catalog_before = registry.catalog()

    engine = WorkflowEngine(WritingStorage(tmp_path / "plugins.sqlite3"))
    try:
        report = wire_workflow_step_extensions(
            registry,
            engine,
            factory_config={"FIXTURE-WORKFLOW_STEP": {"prefix": "扩展"}},
        )
        assert json.loads(json.dumps(report, ensure_ascii=False)) == {
            "kind": "workflow_step",
            "registered": ["fixture-workflow_step"],
            "sources": {"fixture-workflow_step": "entry-point:fixture:workflow_step"},
        }
        catalog_after = registry.catalog()
        for kind in ExtensionKind:
            if kind is not ExtensionKind.WORKFLOW_STEP:
                assert catalog_after[kind.value] == catalog_before[kind.value]

        definition = WorkflowDefinition(
            id="plugin-workflow",
            version="1",
            steps=(
                WorkflowStepDefinition(
                    id="plugin-step",
                    handler="fixture-workflow_step",
                ),
            ),
        )
        run = engine.create_run(definition, {"topic": "绿色发展"})
        completed = engine.run_sync(run["id"])
        assert completed["status"] == "succeeded"
        assert completed["state"] == {"plugin_result": "扩展:绿色发展"}
    finally:
        engine.close()


def test_workflow_step_wiring_wraps_constructor_type_errors(tmp_path: Path) -> None:
    registry = ExtensionRegistry()

    def broken_factory() -> object:
        raise TypeError("fixture constructor rejected its configuration")

    registry.register(ExtensionKind.WORKFLOW_STEP, "broken", broken_factory)
    engine = WorkflowEngine(WritingStorage(tmp_path / "broken.sqlite3"))
    try:
        with pytest.raises(
            ExtensionPluginError,
            match=r"failed to construct workflow_step extension 'broken'",
        ):
            wire_workflow_step_extensions(registry, engine)
    finally:
        engine.close()


def test_workflow_step_wiring_rejects_non_callable_instances(tmp_path: Path) -> None:
    registry = ExtensionRegistry()
    registry.register(ExtensionKind.WORKFLOW_STEP, "invalid", lambda: object())
    engine = WorkflowEngine(WritingStorage(tmp_path / "invalid.sqlite3"))
    try:
        with pytest.raises(
            ExtensionPluginError,
            match=r"workflow_step extension 'invalid' did not construct a callable handler",
        ):
            wire_workflow_step_extensions(registry, engine)
    finally:
        engine.close()
