"""A small persistent workflow engine for local and single-server deployments.

The engine persists every state transition and step checkpoint in SQLite.  A
handler executes after the transaction that marks its step as running has
closed, so slow model or connector calls never hold a database transaction.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
import uuid
from collections.abc import Awaitable, Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, cast

from yanzhang_core.storage import (
    ProjectScopeError,
    RecordNotFoundError,
    StepRunRecord,
    WorkflowRunRecord,
    WritingStorage,
)


class WorkflowStatus(StrEnum):
    """Persisted states for one complete run."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    """Persisted states for one workflow step."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class WorkflowStepDefinition:
    """One ordered, versioned handler reference."""

    id: str
    handler: str
    settings: Mapping[str, object] = field(default_factory=dict)
    max_attempts: int = 1
    pause_after: bool = False

    def __post_init__(self) -> None:
        if not self.id.strip() or len(self.id) > 128:
            raise ValueError("step id must contain between 1 and 128 characters")
        if not self.handler.strip() or len(self.handler) > 128:
            raise ValueError("step handler must contain between 1 and 128 characters")
        if not 1 <= self.max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        _json_object(self.settings)


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    """A deterministic sequence stored with every run for recovery."""

    id: str
    version: str
    steps: tuple[WorkflowStepDefinition, ...]

    def __post_init__(self) -> None:
        if not self.id.strip() or len(self.id) > 128:
            raise ValueError("workflow id must contain between 1 and 128 characters")
        if not self.version.strip() or len(self.version) > 64:
            raise ValueError("workflow version must contain between 1 and 64 characters")
        if not self.steps:
            raise ValueError("workflow must contain at least one step")
        ids = tuple(step.id for step in self.steps)
        if len(ids) != len(set(ids)):
            raise ValueError("workflow step ids must be unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "version": self.version,
            "steps": [
                {
                    "id": step.id,
                    "handler": step.handler,
                    "settings": dict(step.settings),
                    "max_attempts": step.max_attempts,
                    "pause_after": step.pause_after,
                }
                for step in self.steps
            ],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> WorkflowDefinition:
        raw_steps = value.get("steps")
        if not isinstance(raw_steps, list):
            raise ValueError("workflow steps must be a list")
        steps: list[WorkflowStepDefinition] = []
        for raw in raw_steps:
            if not isinstance(raw, Mapping):
                raise ValueError("workflow step must be an object")
            raw_settings = raw.get("settings", {})
            if not isinstance(raw_settings, Mapping):
                raise ValueError("workflow step settings must be an object")
            steps.append(
                WorkflowStepDefinition(
                    id=str(raw.get("id", "")),
                    handler=str(raw.get("handler", "")),
                    settings={str(key): item for key, item in raw_settings.items()},
                    max_attempts=_strict_int(raw.get("max_attempts", 1), "max_attempts"),
                    pause_after=_strict_bool(raw.get("pause_after", False), "pause_after"),
                )
            )
        return cls(
            id=str(value.get("id", "")), version=str(value.get("version", "")), steps=tuple(steps)
        )


@dataclass(frozen=True, slots=True)
class StepResult:
    """Serializable output, run-state updates, and resumable checkpoint."""

    output: Mapping[str, object] = field(default_factory=dict)
    state_updates: Mapping[str, object] = field(default_factory=dict)
    checkpoint: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _json_object(self.output)
        _json_object(self.state_updates)
        _json_object(self.checkpoint)


@dataclass(frozen=True, slots=True)
class StepContext:
    """Immutable input plus safe callbacks exposed to a step handler."""

    run_id: str
    step_id: str
    input: Mapping[str, object]
    state: Mapping[str, object]
    settings: Mapping[str, object]
    checkpoint: Mapping[str, object]
    attempt: int
    _checkpoint_writer: Callable[[Mapping[str, object]], None] = field(repr=False)
    _cancel_reader: Callable[[], bool] = field(repr=False)

    def save_checkpoint(self, checkpoint: Mapping[str, object]) -> None:
        """Persist progress while a long handler runs."""

        validated = _json_object(checkpoint)
        self._checkpoint_writer(validated)

    def cancel_requested(self) -> bool:
        """Let cooperative handlers stop promptly between bounded units."""

        return self._cancel_reader()


class StepHandlerProtocol(Protocol):
    def __call__(
        self,
        context: StepContext,
    ) -> StepResult | Mapping[str, object] | Awaitable[StepResult | Mapping[str, object]]: ...


type StepHandler = StepHandlerProtocol


class WorkflowEngineError(RuntimeError):
    """Stable base exception for orchestration errors."""


class StepHandlerNotFoundError(WorkflowEngineError, LookupError):
    """Raised when a persisted workflow references an unregistered handler."""


class WorkflowStateError(WorkflowEngineError, ValueError):
    """Raised when an operation does not apply to the run's current state."""


class WorkflowEngine:
    """Execute persisted workflows synchronously, asynchronously, or in a pool."""

    def __init__(self, storage: WritingStorage, *, max_workers: int = 2) -> None:
        if not 1 <= max_workers <= 16:
            raise ValueError("max_workers must be between 1 and 16")
        self.storage = storage
        self._handlers: dict[str, StepHandler] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="yanzhang")
        self._futures: dict[str, Future[WorkflowRunRecord]] = {}
        self._active_runs: set[str] = set()
        self._lock = threading.RLock()

    def register_step(self, name: str, handler: StepHandler, *, replace: bool = False) -> None:
        normalized = name.strip()
        if not normalized or len(normalized) > 128:
            raise ValueError("step handler name must contain between 1 and 128 characters")
        if not callable(handler):
            raise TypeError("step handler must be callable")
        with self._lock:
            if normalized in self._handlers and not replace:
                raise ValueError(f"step handler is already registered: {normalized}")
            self._handlers[normalized] = handler

    def unregister_step(self, name: str) -> None:
        with self._lock:
            self._handlers.pop(name.strip(), None)

    def create_run(
        self,
        definition: WorkflowDefinition,
        input: Mapping[str, object],
        *,
        project_id: str | None = None,
        run_id: str | None = None,
    ) -> WorkflowRunRecord:
        """Persist a queued run and all pending step rows atomically."""

        payload = _json_object(input)
        project_key = _normalize_project_id(project_id)
        input_project_id = payload.get("project_id")
        if project_key is None and input_project_id is not None:
            raise ProjectScopeError("workflow project scope must be supplied explicitly")
        if project_key is not None:
            if input_project_id is not None and input_project_id != project_key:
                raise ProjectScopeError("workflow input project does not match its scope")
            payload["project_id"] = project_key
        run_key = run_id or uuid.uuid4().hex
        now = _utc_now()
        definition_payload = definition.to_dict()
        with self.storage.write_transaction() as connection:
            if project_key is not None:
                project = connection.execute(
                    "SELECT 1 FROM projects WHERE id=?",
                    (project_key,),
                ).fetchone()
                if project is None:
                    raise RecordNotFoundError("workflow project not found")
            connection.execute(
                """
                INSERT INTO workflow_runs(
                    id, workflow_id, workflow_version, project_id, status,
                    current_step_id, cancel_requested, input_json, state_json,
                    definition_json, output_asset_id, error_code, error_message,
                    created_at, started_at, updated_at, finished_at
                ) VALUES (
                    ?, ?, ?, ?, 'queued', ?, 0, ?, '{}', ?,
                    NULL, NULL, NULL, ?, NULL, ?, NULL
                )
                """,
                (
                    run_key,
                    definition.id,
                    definition.version,
                    project_key,
                    definition.steps[0].id,
                    _dump_json(payload),
                    _dump_json(definition_payload),
                    now,
                    now,
                ),
            )
            for position, step in enumerate(definition.steps):
                connection.execute(
                    """
                    INSERT INTO step_runs(
                        id, run_id, step_id, position, handler, status,
                        attempt_count, input_json, output_json, checkpoint_json,
                        error_code, error_message, started_at, updated_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, '{}', '{}', NULL, NULL, NULL, ?, NULL)
                    """,
                    (
                        uuid.uuid4().hex,
                        run_key,
                        step.id,
                        position,
                        step.handler,
                        _dump_json({"settings": dict(step.settings)}),
                        now,
                    ),
                )
        return self.get_run(run_key, project_id=project_key)

    def get_run(
        self,
        run_id: str,
        *,
        project_id: str | None = None,
    ) -> WorkflowRunRecord:
        project_key = _normalize_project_id(project_id)
        where = "id=? AND project_id=?" if project_key is not None else "id=?"
        values: tuple[object, ...] = (run_id, project_key) if project_key is not None else (run_id,)
        with self.storage.read_connection() as connection:
            row = connection.execute(
                f"SELECT * FROM workflow_runs WHERE {where}",
                values,
            ).fetchone()
        if row is None:
            raise RecordNotFoundError("workflow run not found")
        return _workflow_run_from_row(row)

    def list_runs(
        self,
        *,
        project_id: str | None = None,
        status: WorkflowStatus | str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WorkflowRunRecord]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("invalid pagination")
        clauses: list[str] = []
        values: list[object] = []
        if project_id is not None:
            clauses.append("project_id=?")
            values.append(project_id)
        if status is not None:
            clauses.append("status=?")
            values.append(str(WorkflowStatus(status)))
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        values.extend((limit, offset))
        with self.storage.read_connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM workflow_runs {where} "
                "ORDER BY updated_at DESC, id ASC LIMIT ? OFFSET ?",
                tuple(values),
            ).fetchall()
        return [_workflow_run_from_row(row) for row in rows]

    def list_step_runs(
        self,
        run_id: str,
        *,
        project_id: str | None = None,
    ) -> list[StepRunRecord]:
        if project_id is not None:
            self.get_run(run_id, project_id=project_id)
        with self.storage.read_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM step_runs WHERE run_id=? ORDER BY position", (run_id,)
            ).fetchall()
        return [_step_run_from_row(row) for row in rows]

    async def run(
        self,
        run_id: str,
        *,
        project_id: str | None = None,
    ) -> WorkflowRunRecord:
        """Run or continue from the first incomplete persisted step."""

        with self._lock:
            if run_id in self._active_runs:
                raise WorkflowStateError("workflow run is already active")
            self._active_runs.add(run_id)
        try:
            return await self._run_active(run_id, project_id=project_id)
        finally:
            with self._lock:
                self._active_runs.discard(run_id)

    async def _run_active(
        self,
        run_id: str,
        *,
        project_id: str | None = None,
    ) -> WorkflowRunRecord:
        """Execute a run after the in-process ownership check."""

        definition, run = self._prepare_run(run_id, project_id=project_id)
        if run["status"] in {
            WorkflowStatus.SUCCEEDED.value,
            WorkflowStatus.CANCELLED.value,
        }:
            return run

        for step in definition.steps:
            row = self._get_step(run_id, step.id)
            if row["status"] == StepStatus.SUCCEEDED.value:
                continue
            if self._cancel_requested(run_id):
                return self._mark_cancelled(run_id, step.id)

            while row["attempt_count"] < step.max_attempts:
                context = self._start_step(run_id, step, row)
                try:
                    handler = self._handler(step.handler)
                    result_value = handler(context)
                    if inspect.isawaitable(result_value):
                        result_value = await result_value
                    result = _coerce_result(result_value)
                except asyncio.CancelledError:
                    self.request_cancel(run_id)
                    return self._mark_cancelled(run_id, step.id)
                except Exception as exc:
                    row = self._fail_step(run_id, step.id, exc)
                    if row["attempt_count"] >= step.max_attempts:
                        return self._mark_failed(run_id, step.id, exc)
                    continue

                if self._cancel_requested(run_id):
                    return self._mark_cancelled(run_id, step.id)
                run = self._complete_step(run_id, step, result)
                if step.pause_after:
                    return self._mark_waiting_review(run_id, step.id)
                break
            else:
                return self._mark_failed(
                    run_id,
                    step.id,
                    WorkflowEngineError("step attempts exhausted"),
                )

        return self._mark_succeeded(run_id)

    def run_sync(
        self,
        run_id: str,
        *,
        project_id: str | None = None,
    ) -> WorkflowRunRecord:
        """Execute a run from synchronous code."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run(run_id, project_id=project_id))
        raise WorkflowStateError("run_sync must be called outside an active event loop")

    def submit(
        self,
        run_id: str,
        *,
        project_id: str | None = None,
    ) -> Future[WorkflowRunRecord]:
        """Run in a bounded local worker pool and return its Future."""

        with self._lock:
            existing = self._futures.get(run_id)
            if existing is not None and not existing.done():
                return existing
            self.get_run(run_id, project_id=project_id)
            future = self._executor.submit(self.run_sync, run_id, project_id=project_id)
            self._futures[run_id] = future
            future.add_done_callback(lambda completed: self._forget_future(run_id, completed))
            return future

    async def resume(
        self,
        run_id: str,
        *,
        from_step_id: str | None = None,
        project_id: str | None = None,
    ) -> WorkflowRunRecord:
        """Continue from the first incomplete step, optionally guarded by its ID."""

        self._queue_for_resume(run_id, from_step_id=from_step_id, project_id=project_id)
        return await self.run(run_id, project_id=project_id)

    def submit_resume(
        self,
        run_id: str,
        *,
        from_step_id: str | None = None,
        project_id: str | None = None,
    ) -> Future[WorkflowRunRecord]:
        """Validate and queue a resume before executing it in the worker pool."""

        self._queue_for_resume(run_id, from_step_id=from_step_id, project_id=project_id)
        return self.submit(run_id, project_id=project_id)

    def first_incomplete_step(
        self,
        run_id: str,
        *,
        project_id: str | None = None,
    ) -> str | None:
        """Return the first persisted step that has not succeeded."""

        self.get_run(run_id, project_id=project_id)
        for step in self.list_step_runs(run_id, project_id=project_id):
            if step["status"] != StepStatus.SUCCEEDED.value:
                return step["step_id"]
        return None

    def validate_resume_from(
        self,
        run_id: str,
        from_step_id: str,
        *,
        project_id: str | None = None,
    ) -> str:
        """Require a resume guard to match the first incomplete persisted step."""

        normalized = from_step_id.strip()
        if not normalized:
            raise WorkflowStateError("resume step id must not be empty")
        run = self.get_run(run_id, project_id=project_id)
        if run["status"] in {WorkflowStatus.SUCCEEDED.value, WorkflowStatus.CANCELLED.value}:
            raise WorkflowStateError(f"workflow run is terminal: {run['status']}")
        expected = self.first_incomplete_step(run_id, project_id=project_id)
        if expected is None:
            raise WorkflowStateError("workflow run has no incomplete step")
        if normalized != expected:
            raise WorkflowStateError(f"resume step mismatch: expected {expected}, got {normalized}")
        return expected

    def request_cancel(
        self,
        run_id: str,
        *,
        project_id: str | None = None,
    ) -> WorkflowRunRecord:
        """Set a durable cooperative cancellation flag."""

        now = _utc_now()
        with self.storage.write_transaction() as connection:
            project_key = _normalize_project_id(project_id)
            where = "id=? AND project_id=?" if project_key is not None else "id=?"
            values: tuple[object, ...] = (
                (run_id, project_key) if project_key is not None else (run_id,)
            )
            row = connection.execute(
                f"SELECT status FROM workflow_runs WHERE {where}",
                values,
            ).fetchone()
            if row is None:
                raise RecordNotFoundError("workflow run not found")
            status = str(row["status"])
            if status in {WorkflowStatus.SUCCEEDED.value, WorkflowStatus.CANCELLED.value}:
                return self.get_run(run_id, project_id=project_key)
            connection.execute(
                "UPDATE workflow_runs SET cancel_requested=1, updated_at=? WHERE id=?",
                (now, run_id),
            )
        return self.get_run(run_id, project_id=project_key)

    def recover_interrupted(self) -> int:
        """Return interrupted running steps to resumable pending state."""

        now = _utc_now()
        with self.storage.write_transaction() as connection:
            run_ids = [
                str(row[0])
                for row in connection.execute(
                    "SELECT id FROM workflow_runs WHERE status='running'"
                ).fetchall()
            ]
            for run_id in run_ids:
                connection.execute(
                    """
                    UPDATE step_runs
                    SET status='pending',
                        attempt_count=CASE
                            WHEN attempt_count > 0 THEN attempt_count - 1
                            ELSE 0
                        END,
                        error_code=NULL, error_message=NULL,
                        updated_at=?, finished_at=NULL
                    WHERE run_id=? AND status='running'
                    """,
                    (now, run_id),
                )
                connection.execute(
                    """
                    UPDATE workflow_runs
                    SET status='queued', error_code=NULL, error_message=NULL, updated_at=?
                    WHERE id=?
                    """,
                    (now, run_id),
                )
        return len(run_ids)

    def close(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=not wait)

    def _prepare_run(
        self,
        run_id: str,
        *,
        project_id: str | None = None,
    ) -> tuple[WorkflowDefinition, WorkflowRunRecord]:
        run = self.get_run(run_id, project_id=project_id)
        if run["status"] == WorkflowStatus.WAITING_REVIEW.value:
            raise WorkflowStateError("review-paused run must be resumed explicitly")
        if run["status"] == WorkflowStatus.FAILED.value:
            raise WorkflowStateError("failed run must be resumed explicitly")
        if run["status"] == WorkflowStatus.RUNNING.value:
            # The row can survive a process stop. Explicit recovery or resume
            # distinguishes that case from two active callers in one process.
            with self._lock:
                active = self._futures.get(run_id)
                if active is not None and not active.done():
                    raise WorkflowStateError("workflow run is already active")
        definition = WorkflowDefinition.from_dict(run["definition"])
        now = _utc_now()
        with self.storage.write_transaction() as connection:
            connection.execute(
                """
                UPDATE workflow_runs
                SET status='running', started_at=COALESCE(started_at, ?), updated_at=?,
                    error_code=NULL, error_message=NULL
                WHERE id=?
                """,
                (now, now, run_id),
            )
        return definition, self.get_run(run_id, project_id=project_id)

    def _start_step(
        self,
        run_id: str,
        step: WorkflowStepDefinition,
        row: StepRunRecord,
    ) -> StepContext:
        now = _utc_now()
        run = self.get_run(run_id)
        attempt = row["attempt_count"] + 1
        input_snapshot = {"run_input": run["input"], "state": run["state"]}
        with self.storage.write_transaction() as connection:
            connection.execute(
                """
                UPDATE workflow_runs SET current_step_id=?, status='running', updated_at=?
                WHERE id=?
                """,
                (step.id, now, run_id),
            )
            connection.execute(
                """
                UPDATE step_runs
                SET status='running', attempt_count=?, input_json=?,
                    error_code=NULL, error_message=NULL,
                    started_at=COALESCE(started_at, ?), updated_at=?, finished_at=NULL
                WHERE run_id=? AND step_id=?
                """,
                (attempt, _dump_json(input_snapshot), now, now, run_id, step.id),
            )
        return StepContext(
            run_id=run_id,
            step_id=step.id,
            input=run["input"],
            state=run["state"],
            settings=dict(step.settings),
            checkpoint=row["checkpoint"],
            attempt=attempt,
            _checkpoint_writer=lambda value: self._save_checkpoint(run_id, step.id, value),
            _cancel_reader=lambda: self._cancel_requested(run_id),
        )

    def _complete_step(
        self,
        run_id: str,
        step: WorkflowStepDefinition,
        result: StepResult,
    ) -> WorkflowRunRecord:
        now = _utc_now()
        with self.storage.write_transaction() as connection:
            run_row = connection.execute(
                "SELECT state_json FROM workflow_runs WHERE id=?", (run_id,)
            ).fetchone()
            if run_row is None:
                raise RecordNotFoundError(f"workflow run not found: {run_id}")
            state = _load_object(str(run_row["state_json"]))
            state.update(_json_object(result.state_updates))
            output_asset_value = state.get("output_asset_id")
            if output_asset_value is not None and not isinstance(output_asset_value, str):
                raise TypeError("output_asset_id state value must be a string")
            connection.execute(
                """
                UPDATE step_runs
                SET status='succeeded', output_json=?, checkpoint_json=?,
                    error_code=NULL, error_message=NULL, updated_at=?, finished_at=?
                WHERE run_id=? AND step_id=?
                """,
                (
                    _dump_json(result.output),
                    _dump_json(result.checkpoint),
                    now,
                    now,
                    run_id,
                    step.id,
                ),
            )
            connection.execute(
                """
                UPDATE workflow_runs
                SET state_json=?,
                    output_asset_id=COALESCE(?, output_asset_id),
                    updated_at=?
                WHERE id=?
                """,
                (_dump_json(state), output_asset_value, now, run_id),
            )
        return self.get_run(run_id)

    def _fail_step(self, run_id: str, step_id: str, exc: Exception) -> StepRunRecord:
        now = _utc_now()
        code, message = _safe_failure(exc)
        with self.storage.write_transaction() as connection:
            connection.execute(
                """
                UPDATE step_runs
                SET status='failed', error_code=?, error_message=?,
                    updated_at=?, finished_at=?
                WHERE run_id=? AND step_id=?
                """,
                (code, message, now, now, run_id, step_id),
            )
        return self._get_step(run_id, step_id)

    def _mark_failed(
        self,
        run_id: str,
        step_id: str,
        exc: Exception,
    ) -> WorkflowRunRecord:
        now = _utc_now()
        code, message = _safe_failure(exc)
        with self.storage.write_transaction() as connection:
            connection.execute(
                """
                UPDATE workflow_runs
                SET status='failed', current_step_id=?, error_code=?,
                    error_message=?, updated_at=?, finished_at=?
                WHERE id=?
                """,
                (step_id, code, message, now, now, run_id),
            )
        return self.get_run(run_id)

    def _mark_waiting_review(self, run_id: str, step_id: str) -> WorkflowRunRecord:
        now = _utc_now()
        with self.storage.write_transaction() as connection:
            connection.execute(
                """
                UPDATE workflow_runs
                SET status='waiting_review', current_step_id=?, updated_at=?
                WHERE id=?
                """,
                (step_id, now, run_id),
            )
        return self.get_run(run_id)

    def _mark_succeeded(self, run_id: str) -> WorkflowRunRecord:
        now = _utc_now()
        with self.storage.write_transaction() as connection:
            connection.execute(
                """
                UPDATE workflow_runs
                SET status='succeeded', current_step_id=NULL,
                    error_code=NULL, error_message=NULL, updated_at=?, finished_at=?
                WHERE id=?
                """,
                (now, now, run_id),
            )
        return self.get_run(run_id)

    def _mark_cancelled(self, run_id: str, step_id: str) -> WorkflowRunRecord:
        now = _utc_now()
        with self.storage.write_transaction() as connection:
            connection.execute(
                """
                UPDATE step_runs
                SET status='cancelled', updated_at=?, finished_at=?
                WHERE run_id=? AND step_id=? AND status!='succeeded'
                """,
                (now, now, run_id, step_id),
            )
            connection.execute(
                """
                UPDATE workflow_runs
                SET status='cancelled', current_step_id=?, updated_at=?, finished_at=?
                WHERE id=?
                """,
                (step_id, now, now, run_id),
            )
        return self.get_run(run_id)

    def _queue_for_resume(
        self,
        run_id: str,
        *,
        from_step_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        run = self.get_run(run_id, project_id=project_id)
        if run["status"] in {WorkflowStatus.SUCCEEDED.value, WorkflowStatus.CANCELLED.value}:
            raise WorkflowStateError(f"workflow run is terminal: {run['status']}")
        if from_step_id is not None:
            self.validate_resume_from(run_id, from_step_id, project_id=project_id)
        with self._lock:
            active = self._futures.get(run_id)
            if run_id in self._active_runs or (active is not None and not active.done()):
                raise WorkflowStateError("workflow run is already active")
        now = _utc_now()
        with self.storage.write_transaction() as connection:
            connection.execute(
                """
                UPDATE step_runs
                SET status='pending', attempt_count=0, updated_at=?, finished_at=NULL
                WHERE run_id=? AND status IN ('running', 'failed')
                """,
                (now, run_id),
            )
            connection.execute(
                """
                UPDATE workflow_runs
                SET status='queued', cancel_requested=0, error_code=NULL,
                    error_message=NULL, updated_at=?, finished_at=NULL
                WHERE id=?
                """,
                (now, run_id),
            )

    def _save_checkpoint(
        self,
        run_id: str,
        step_id: str,
        checkpoint: Mapping[str, object],
    ) -> None:
        now = _utc_now()
        with self.storage.write_transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE step_runs SET checkpoint_json=?, updated_at=?
                WHERE run_id=? AND step_id=? AND status='running'
                """,
                (_dump_json(checkpoint), now, run_id, step_id),
            )
            if cursor.rowcount != 1:
                raise WorkflowStateError("checkpoint target is not a running step")

    def _cancel_requested(self, run_id: str) -> bool:
        with self.storage.read_connection() as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM workflow_runs WHERE id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"workflow run not found: {run_id}")
        return bool(row[0])

    def _get_step(self, run_id: str, step_id: str) -> StepRunRecord:
        with self.storage.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM step_runs WHERE run_id=? AND step_id=?", (run_id, step_id)
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"workflow step not found: {run_id}/{step_id}")
        return _step_run_from_row(row)

    def _handler(self, name: str) -> StepHandler:
        with self._lock:
            handler = self._handlers.get(name)
        if handler is None:
            raise StepHandlerNotFoundError(f"workflow step handler is not registered: {name}")
        return handler

    def _forget_future(
        self,
        run_id: str,
        completed: Future[WorkflowRunRecord],
    ) -> None:
        with self._lock:
            if self._futures.get(run_id) is completed:
                self._futures.pop(run_id, None)


def _coerce_result(value: StepResult | Mapping[str, object]) -> StepResult:
    if isinstance(value, StepResult):
        return value
    if isinstance(value, Mapping):
        return StepResult(output=_json_object(value))
    raise TypeError("workflow handler must return StepResult or a mapping")


def _workflow_run_from_row(row: Mapping[str, object]) -> WorkflowRunRecord:
    return {
        "id": str(row["id"]),
        "workflow_id": str(row["workflow_id"]),
        "workflow_version": str(row["workflow_version"]),
        "project_id": str(row["project_id"]) if row["project_id"] else None,
        "status": str(row["status"]),
        "current_step_id": str(row["current_step_id"]) if row["current_step_id"] else None,
        "cancel_requested": bool(row["cancel_requested"]),
        "input": _load_object(str(row["input_json"])),
        "state": _load_object(str(row["state_json"])),
        "definition": _load_object(str(row["definition_json"])),
        "output_asset_id": str(row["output_asset_id"]) if row["output_asset_id"] else None,
        "error_code": str(row["error_code"]) if row["error_code"] else None,
        "error_message": str(row["error_message"]) if row["error_message"] else None,
        "created_at": str(row["created_at"]),
        "started_at": str(row["started_at"]) if row["started_at"] else None,
        "updated_at": str(row["updated_at"]),
        "finished_at": str(row["finished_at"]) if row["finished_at"] else None,
    }


def _step_run_from_row(row: Mapping[str, object]) -> StepRunRecord:
    return {
        "id": str(row["id"]),
        "run_id": str(row["run_id"]),
        "step_id": str(row["step_id"]),
        "position": int(cast(int, row["position"])),
        "handler": str(row["handler"]),
        "status": str(row["status"]),
        "attempt_count": int(cast(int, row["attempt_count"])),
        "input": _load_object(str(row["input_json"])),
        "output": _load_object(str(row["output_json"])),
        "checkpoint": _load_object(str(row["checkpoint_json"])),
        "error_code": str(row["error_code"]) if row["error_code"] else None,
        "error_message": str(row["error_message"]) if row["error_message"] else None,
        "started_at": str(row["started_at"]) if row["started_at"] else None,
        "updated_at": str(row["updated_at"]),
        "finished_at": str(row["finished_at"]) if row["finished_at"] else None,
    }


def _json_object(value: Mapping[str, object]) -> dict[str, object]:
    loaded = json.loads(_dump_json(value))
    if not isinstance(loaded, dict):
        raise TypeError("value must serialize to a JSON object")
    return cast(dict[str, object], loaded)


def _load_object(value: str) -> dict[str, object]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise WorkflowEngineError("stored workflow JSON is not an object")
    return cast(dict[str, object], loaded)


def _dump_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise TypeError("workflow values must be JSON serializable") from exc


def _strict_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _strict_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


_SAFE_FAILURES: dict[str, tuple[str, str]] = {
    "ProviderAuthenticationError": (
        "ProviderAuthenticationError",
        "远程服务认证失败",
    ),
    "ProviderRateLimitError": ("ProviderRateLimitError", "远程服务触发频率限制"),
    "ProviderTimeoutError": ("ProviderTimeoutError", "远程服务请求超时"),
    "ProviderTransportError": ("ProviderTransportError", "远程服务连接失败"),
    "ProviderResponseError": ("ProviderResponseError", "远程服务响应格式异常"),
    "ProviderTaskFailedError": ("ProviderTaskFailedError", "远程服务任务执行失败"),
    "ProviderAPIError": ("ProviderAPIError", "远程服务返回错误"),
    "ProviderConfigurationError": (
        "ProviderConfigurationError",
        "远程服务配置有误",
    ),
    "ProviderError": ("ProviderError", "远程服务调用失败"),
    "MetadataTimeoutError": ("MetadataTimeoutError", "元数据服务请求超时"),
    "MetadataRateLimitError": ("MetadataRateLimitError", "元数据服务触发频率限制"),
    "MetadataConnectorError": ("MetadataConnectorError", "元数据服务调用失败"),
    "ModelGatewayError": ("ModelGatewayError", "模型服务响应异常"),
    "StepHandlerNotFoundError": (
        "StepHandlerNotFoundError",
        "工作流步骤处理器未注册",
    ),
    "WorkflowStateError": ("WorkflowStateError", "工作流状态不支持当前操作"),
    "TimeoutError": ("TimeoutError", "工作流步骤执行超时"),
}


def _safe_failure(exc: Exception) -> tuple[str, str]:
    """Map an exception chain to stable persisted values without storing its text."""

    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        for exception_type in type(current).__mro__:
            safe = _SAFE_FAILURES.get(exception_type.__name__)
            if safe is not None:
                return safe
        current = current.__cause__ or current.__context__
    return "WorkflowStepError", "工作流步骤执行失败"


def _normalize_project_id(project_id: str | None) -> str | None:
    if project_id is None:
        return None
    if not isinstance(project_id, str):
        raise ValueError("project_id must be a string")
    normalized = project_id.strip()
    if not 1 <= len(normalized) <= 128:
        raise ValueError("project_id must contain between 1 and 128 characters")
    return normalized


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "StepContext",
    "StepHandler",
    "StepHandlerNotFoundError",
    "StepResult",
    "StepStatus",
    "WorkflowDefinition",
    "WorkflowEngine",
    "WorkflowEngineError",
    "WorkflowStateError",
    "WorkflowStatus",
    "WorkflowStepDefinition",
]
