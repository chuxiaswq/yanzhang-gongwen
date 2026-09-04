# Chinese punctuation is intentional in fixture text.
# ruff: noqa: RUF001

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from yanzhang_core.storage import ProjectScopeError, RecordNotFoundError, WritingStorage
from yanzhang_core.workflow import (
    StepContext,
    StepResult,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowStateError,
    WorkflowStepDefinition,
)


def test_sync_workflow_retries_from_checkpoint_and_persists_state(tmp_path: Path) -> None:
    engine = WorkflowEngine(WritingStorage(tmp_path / "workflow.sqlite3"))
    attempts: list[int] = []

    def gather(context: StepContext) -> StepResult:
        attempts.append(context.attempt)
        if context.attempt == 1:
            context.save_checkpoint({"cursor": 3})
            raise RuntimeError("temporary failure")
        assert context.checkpoint == {"cursor": 3}
        return StepResult(
            output={"collected": 5},
            state_updates={"materials": 5},
            checkpoint={"cursor": 5},
        )

    def draft(context: StepContext) -> StepResult:
        return StepResult(
            output={"text": f"材料数：{context.state['materials']}"},
            state_updates={"completed": True},
        )

    engine.register_step("gather", gather)
    engine.register_step("draft", draft)
    definition = WorkflowDefinition(
        id="writing",
        version="1",
        steps=(
            WorkflowStepDefinition(id="gather", handler="gather", max_attempts=2),
            WorkflowStepDefinition(id="draft", handler="draft"),
        ),
    )
    run = engine.create_run(definition, {"topic": "绿色发展"}, run_id="run-1")

    completed = engine.run_sync(run["id"])

    assert completed["status"] == "succeeded"
    assert completed["state"] == {"materials": 5, "completed": True}
    steps = engine.list_step_runs(run["id"])
    assert [step["status"] for step in steps] == ["succeeded", "succeeded"]
    assert steps[0]["attempt_count"] == 2
    assert steps[0]["checkpoint"] == {"cursor": 5}
    assert attempts == [1, 2]
    engine.close()


def test_pause_resume_and_async_handler(tmp_path: Path) -> None:
    engine = WorkflowEngine(WritingStorage(tmp_path / "workflow.sqlite3"))

    async def prepare(context: StepContext) -> StepResult:
        await asyncio.sleep(0)
        return StepResult(state_updates={"prepared": context.input["topic"]})

    def finish(context: StepContext) -> StepResult:
        return StepResult(state_updates={"finished": context.state["prepared"]})

    engine.register_step("prepare", prepare)
    engine.register_step("finish", finish)
    definition = WorkflowDefinition(
        id="reviewable",
        version="1",
        steps=(
            WorkflowStepDefinition(id="prepare", handler="prepare", pause_after=True),
            WorkflowStepDefinition(id="finish", handler="finish"),
        ),
    )
    run = engine.create_run(definition, {"topic": "阶段二"})

    paused = asyncio.run(engine.run(run["id"]))
    assert paused["status"] == "waiting_review"
    completed = asyncio.run(engine.resume(run["id"]))
    assert completed["status"] == "succeeded"
    assert completed["state"] == {"prepared": "阶段二", "finished": "阶段二"}
    engine.close()


def test_background_cancel_is_durable_and_handler_holds_no_transaction(tmp_path: Path) -> None:
    storage = WritingStorage(tmp_path / "workflow.sqlite3")
    engine = WorkflowEngine(storage)
    started = threading.Event()
    continue_handler = threading.Event()

    def wait_step(context: StepContext) -> StepResult:
        started.set()
        assert continue_handler.wait(timeout=5)
        return StepResult(output={"observed_cancel": context.cancel_requested()})

    engine.register_step("wait", wait_step)
    definition = WorkflowDefinition(
        id="cancel-test",
        version="1",
        steps=(WorkflowStepDefinition(id="wait", handler="wait"),),
    )
    run = engine.create_run(definition, {})
    future = engine.submit(run["id"])
    assert started.wait(timeout=5)

    # This independent write completes while the handler is still running.
    project = storage.create_project("并发写入")
    assert storage.get_project(project.id) == project
    requested = engine.request_cancel(run["id"])
    assert requested["cancel_requested"] is True
    continue_handler.set()

    cancelled = future.result(timeout=5)
    assert cancelled["status"] == "cancelled"
    assert engine.get_run(run["id"])["cancel_requested"] is True
    engine.close()


def test_recover_interrupted_run_from_persisted_checkpoint(tmp_path: Path) -> None:
    storage = WritingStorage(tmp_path / "workflow.sqlite3")
    engine = WorkflowEngine(storage)
    engine.register_step(
        "continue",
        lambda context: StepResult(state_updates={"cursor": context.checkpoint.get("cursor", 0)}),
    )
    definition = WorkflowDefinition(
        id="recoverable",
        version="1",
        steps=(WorkflowStepDefinition(id="collect", handler="continue"),),
    )
    run = engine.create_run(definition, {})
    with storage.write_transaction() as connection:
        connection.execute("UPDATE workflow_runs SET status='running' WHERE id=?", (run["id"],))
        connection.execute(
            """
            UPDATE step_runs
            SET status='running', attempt_count=1, checkpoint_json='{"cursor":7}'
            WHERE run_id=? AND step_id='collect'
            """,
            (run["id"],),
        )

    assert engine.recover_interrupted() == 1
    assert engine.get_run(run["id"])["status"] == "queued"
    completed = engine.run_sync(run["id"])
    assert completed["status"] == "succeeded"
    assert completed["state"] == {"cursor": 7}
    assert engine.list_step_runs(run["id"])[0]["attempt_count"] == 1
    engine.close()


def test_missing_handler_records_sanitized_failure(tmp_path: Path) -> None:
    engine = WorkflowEngine(WritingStorage(tmp_path / "workflow.sqlite3"))
    definition = WorkflowDefinition(
        id="missing-handler",
        version="1",
        steps=(WorkflowStepDefinition(id="missing", handler="not-registered"),),
    )
    run = engine.create_run(definition, {})

    failed = engine.run_sync(run["id"])

    assert failed["status"] == "failed"
    assert failed["error_code"] == "StepHandlerNotFoundError"
    assert engine.list_step_runs(run["id"])[0]["status"] == "failed"
    engine.close()


def test_remote_failure_details_are_redacted_from_persisted_workflow_state(
    tmp_path: Path,
) -> None:
    class ProviderTransportError(RuntimeError):
        pass

    secret = "https://model.invalid?token=fixture-secret"
    storage = WritingStorage(tmp_path / "workflow.sqlite3")
    engine = WorkflowEngine(storage)

    def fail(_: StepContext) -> StepResult:
        raise ProviderTransportError(secret)

    engine.register_step("remote", fail)
    definition = WorkflowDefinition(
        id="remote-failure",
        version="1",
        steps=(WorkflowStepDefinition(id="remote", handler="remote"),),
    )
    run = engine.create_run(definition, {})

    failed = engine.run_sync(run["id"])
    step = engine.list_step_runs(run["id"])[0]

    assert failed["error_code"] == "ProviderTransportError"
    assert failed["error_message"] == "远程服务连接失败"
    assert step["error_code"] == "ProviderTransportError"
    assert step["error_message"] == "远程服务连接失败"
    assert secret not in str(failed)
    assert secret not in str(step)
    with storage.read_connection() as connection:
        persisted = " ".join(
            str(value)
            for value in connection.execute(
                "SELECT error_code, error_message FROM workflow_runs WHERE id=?",
                (run["id"],),
            ).fetchone()
        )
    assert secret not in persisted
    engine.close()


def test_project_scoped_workflow_operations_hide_cross_project_runs(tmp_path: Path) -> None:
    storage = WritingStorage(tmp_path / "workflow.sqlite3")
    first = storage.create_project("工作流项目一")
    second = storage.create_project("工作流项目二")
    engine = WorkflowEngine(storage)
    engine.register_step("finish", lambda _: StepResult(state_updates={"done": True}))
    definition = WorkflowDefinition(
        id="scoped",
        version="1",
        steps=(WorkflowStepDefinition(id="finish", handler="finish"),),
    )
    run = engine.create_run(definition, {}, project_id=first.id)

    with pytest.raises(ProjectScopeError):
        engine.create_run(definition, {"project_id": first.id})
    with pytest.raises(ProjectScopeError):
        engine.create_run(
            definition,
            {"project_id": second.id},
            project_id=first.id,
        )
    for action in (
        lambda: engine.get_run(run["id"], project_id=second.id),
        lambda: engine.list_step_runs(run["id"], project_id=second.id),
        lambda: engine.run_sync(run["id"], project_id=second.id),
        lambda: engine.request_cancel(run["id"], project_id=second.id),
        lambda: engine.first_incomplete_step(run["id"], project_id=second.id),
        lambda: engine.validate_resume_from(
            run["id"],
            "finish",
            project_id=second.id,
        ),
        lambda: asyncio.run(engine.resume(run["id"], from_step_id="finish", project_id=second.id)),
    ):
        with pytest.raises(RecordNotFoundError):
            action()

    completed = engine.run_sync(run["id"], project_id=first.id)
    assert completed["project_id"] == first.id
    assert completed["status"] == "succeeded"
    with storage.read_connection() as connection:
        indexes = {
            str(row["name"])
            for row in connection.execute("PRAGMA index_list('workflow_runs')").fetchall()
        }
    assert "idx_workflow_runs_project" in indexes
    engine.close()


def test_resume_guard_covers_queued_and_failed_runs(tmp_path: Path) -> None:
    engine = WorkflowEngine(WritingStorage(tmp_path / "workflow.sqlite3"))
    calls: list[str] = []
    draft_ready = False

    def research(context: StepContext) -> StepResult:
        _ = context
        calls.append("research")
        return StepResult(state_updates={"researched": True})

    def draft(context: StepContext) -> StepResult:
        _ = context
        calls.append("draft")
        if not draft_ready:
            raise RuntimeError("fixture failure")
        return StepResult(state_updates={"drafted": True})

    engine.register_step("research", research)
    engine.register_step("draft", draft)
    definition = WorkflowDefinition(
        id="guarded",
        version="1",
        steps=(
            WorkflowStepDefinition(id="research", handler="research"),
            WorkflowStepDefinition(id="draft", handler="draft"),
        ),
    )
    queued = engine.create_run(definition, {})
    assert engine.first_incomplete_step(queued["id"]) == "research"
    with pytest.raises(WorkflowStateError, match="resume step mismatch"):
        asyncio.run(engine.resume(queued["id"], from_step_id="draft"))

    failed = engine.run_sync(queued["id"])
    assert failed["status"] == "failed"
    assert engine.first_incomplete_step(queued["id"]) == "draft"
    with pytest.raises(WorkflowStateError, match="resume step mismatch"):
        asyncio.run(engine.resume(queued["id"], from_step_id="research"))

    draft_ready = True
    completed = asyncio.run(engine.resume(queued["id"], from_step_id="draft"))
    assert completed["status"] == "succeeded"
    assert calls == ["research", "draft", "draft"]
    engine.close()


def test_guarded_background_resume_and_terminal_states(tmp_path: Path) -> None:
    engine = WorkflowEngine(WritingStorage(tmp_path / "workflow.sqlite3"))
    definition = WorkflowDefinition(
        id="reviewable-guarded",
        version="1",
        steps=(
            WorkflowStepDefinition(
                id="prepare",
                handler="prepare",
                pause_after=True,
            ),
            WorkflowStepDefinition(id="finish", handler="finish"),
        ),
    )
    engine.register_step("prepare", lambda _: StepResult(state_updates={"prepared": True}))
    engine.register_step("finish", lambda _: StepResult(state_updates={"finished": True}))

    paused_run = engine.create_run(definition, {})
    paused = engine.run_sync(paused_run["id"])
    assert paused["status"] == "waiting_review"
    assert engine.first_incomplete_step(paused_run["id"]) == "finish"
    with pytest.raises(WorkflowStateError, match="resume step mismatch"):
        engine.submit_resume(paused_run["id"], from_step_id="prepare")

    completed = engine.submit_resume(paused_run["id"], from_step_id="finish").result(timeout=5)
    assert completed["status"] == "succeeded"
    assert engine.first_incomplete_step(paused_run["id"]) is None
    with pytest.raises(WorkflowStateError, match="terminal"):
        asyncio.run(engine.resume(paused_run["id"], from_step_id="finish"))

    cancelled_run = engine.create_run(definition, {})
    engine.request_cancel(cancelled_run["id"])
    cancelled = engine.run_sync(cancelled_run["id"])
    assert cancelled["status"] == "cancelled"
    with pytest.raises(WorkflowStateError, match="terminal"):
        asyncio.run(engine.resume(cancelled_run["id"], from_step_id="prepare"))
    engine.close()
