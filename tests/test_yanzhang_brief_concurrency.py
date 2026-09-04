"""Concurrency regression coverage for immutable writing briefs."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from gongwen_mcp.artifacts import ArtifactStore
from gongwen_web.writing_service import YanzhangPlatformService
from yanzhang_core import ContentBlock, WritingBrief
from yanzhang_core.storage import BriefConflictError, WritingStorage


def _brief(goal: str, *, brief_id: str = "brief-concurrent") -> WritingBrief:
    return WritingBrief(
        id=brief_id,
        title="数字化转型阶段复盘",
        goal=goal,
        audience="各处室",
        channel="document",
        content_type="工作总结",
        scenario_pack_id="gongwen",
        recipe_id="work-summary",
        constraints=("所有数字须有来源",),
    )


def _save_after_barrier(
    storage: WritingStorage,
    barrier: threading.Barrier,
    brief: WritingBrief,
    project_id: str,
) -> WritingBrief | BriefConflictError:
    barrier.wait(timeout=5)
    try:
        return storage.save_brief(brief, project_id=project_id)
    except BriefConflictError as exc:
        return exc


def test_concurrent_different_briefs_keep_the_first_committed_payload(tmp_path: Path) -> None:
    database = tmp_path / "writing.sqlite3"
    first_storage = WritingStorage(database)
    second_storage = WritingStorage(database)
    project = first_storage.create_project("并发简报", project_id="project-concurrent")
    first = _brief("总结阶段进展")
    second = _brief("部署下一阶段任务")
    barrier = threading.Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [
            future.result(timeout=10)
            for future in (
                executor.submit(_save_after_barrier, first_storage, barrier, first, project.id),
                executor.submit(_save_after_barrier, second_storage, barrier, second, project.id),
            )
        ]

    saved = [item for item in outcomes if isinstance(item, WritingBrief)]
    conflicts = [item for item in outcomes if isinstance(item, BriefConflictError)]
    assert len(saved) == 1
    assert len(conflicts) == 1
    assert first_storage.get_brief(first.id, project_id=project.id) == saved[0]
    assert len(first_storage.list_briefs(project_id=project.id)) == 1


def test_concurrent_identical_brief_retries_are_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "writing.sqlite3"
    first_storage = WritingStorage(database)
    second_storage = WritingStorage(database)
    project = first_storage.create_project("幂等简报", project_id="project-idempotent")
    brief = _brief("总结阶段进展", brief_id="brief-idempotent")
    barrier = threading.Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [
            future.result(timeout=10)
            for future in (
                executor.submit(_save_after_barrier, first_storage, barrier, brief, project.id),
                executor.submit(_save_after_barrier, second_storage, barrier, brief, project.id),
            )
        ]

    assert outcomes == [brief, brief]
    assert first_storage.list_briefs(project_id=project.id) == [brief]


def test_asset_creation_cannot_overwrite_an_existing_brief(tmp_path: Path) -> None:
    storage = WritingStorage(tmp_path / "writing.sqlite3")
    project = storage.create_project("资产边界", project_id="project-asset")
    saved = storage.save_brief(_brief("原始目标"), project_id=project.id)

    with pytest.raises(BriefConflictError, match="brief content conflicts"):
        storage.create_text_asset(
            _brief("冲突目标"),
            (ContentBlock(id="paragraph-1", order=0, text="正文"),),
            project_id=project.id,
        )

    assert storage.get_brief(saved.id, project_id=project.id) == saved
    assert storage.list_text_assets(project_id=project.id) == []


class _BarrierWritingStorage(WritingStorage):
    def __init__(self, db_path: Path, barrier: threading.Barrier) -> None:
        self._brief_barrier = barrier
        self._coordinate_next_save = True
        super().__init__(db_path)

    def save_brief(self, brief: WritingBrief, *, project_id: str | None = None) -> WritingBrief:
        if self._coordinate_next_save:
            self._coordinate_next_save = False
            self._brief_barrier.wait(timeout=5)
        return super().save_brief(brief, project_id=project_id)


def _service_payload(project_id: str, goal: str) -> dict[str, object]:
    return {
        "project_id": project_id,
        "brief_id": "brief-service-race",
        "topic": "数字化转型阶段复盘",
        "goal": goal,
        "audience": "各处室",
        "channel": "document",
        "content_type": "旧客户端展示标签",
        "scenario_pack_id": "gongwen",
        "recipe_id": "work-summary",
        "constraints": ["所有数字须有来源"],
    }


@pytest.mark.asyncio
async def test_create_brief_concurrent_conflict_is_a_stable_service_error(tmp_path: Path) -> None:
    database = tmp_path / "writing.sqlite3"
    barrier = threading.Barrier(2)
    first_storage = _BarrierWritingStorage(database, barrier)
    second_storage = _BarrierWritingStorage(database, barrier)
    first_service = YanzhangPlatformService(
        first_storage,
        artifact_store=ArtifactStore(tmp_path / "first-artifacts"),
    )
    second_service = YanzhangPlatformService(
        second_storage,
        artifact_store=ArtifactStore(tmp_path / "second-artifacts"),
    )
    project = first_storage.create_project("服务并发", project_id="project-service")
    payloads = (
        _service_payload(project.id, "总结阶段进展"),
        _service_payload(project.id, "部署下一阶段任务"),
    )

    try:
        outcomes = await asyncio.gather(
            first_service.create_brief(payloads[0]),
            second_service.create_brief(payloads[1]),
            return_exceptions=True,
        )

        successes = [item for item in outcomes if isinstance(item, Mapping)]
        errors = [item for item in outcomes if isinstance(item, BriefConflictError)]
        assert len(successes) == 1
        assert len(errors) == 1
        assert str(errors[0]) == "stable brief id is already bound to other content"

        winner_index = next(
            index for index, outcome in enumerate(outcomes) if isinstance(outcome, Mapping)
        )
        winner = successes[0]
        stored = first_storage.get_brief("brief-service-race", project_id=project.id)
        assert stored.goal == payloads[winner_index]["goal"]
        assert winner["brief"] == stored.model_dump(mode="json")

        normalized_retry = {
            **payloads[winner_index],
            "topic": "  数字化转型阶段复盘  ",
            "goal": f"  {stored.goal}  ",
            "audience": "  各处室  ",
            "constraints": ["  所有数字须有来源  "],
            "content_type": "另一旧标签",
        }
        replay = await (first_service, second_service)[winner_index].create_brief(normalized_retry)
        assert replay == winner

        with pytest.raises(BriefConflictError, match="stable brief id is already bound"):
            await (first_service, second_service)[1 - winner_index].create_brief(
                payloads[1 - winner_index]
            )
        assert first_storage.get_brief("brief-service-race", project_id=project.id) == stored
    finally:
        first_service.close()
        second_service.close()
