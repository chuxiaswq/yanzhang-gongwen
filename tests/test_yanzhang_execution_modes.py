"""Offline regressions for explicit model execution and truthful UI lineage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from gongwen_mcp.writing_schemas import CreateWorkflowRequest
from gongwen_web.app import create_app
from gongwen_web.models import ProviderSettings
from gongwen_web.runtime import RuntimeSettings
from gongwen_web.storage import GongwenStorage
from yanzhang_core import YanzhangComposer


def _brief() -> dict[str, object]:
    return {
        "topic": "项目复盘",
        "selected_title": "项目复盘",
        "goal": "明确改进计划",
        "audience": "项目组",
        "channel": "document",
        "content_type": "工作总结",
        "scenario_pack_id": "gongwen",
        "recipe_id": "work-summary",
        "structure_override": [{"id": "progress", "title": "主要进展", "purpose": "归纳进展"}],
    }


@pytest.mark.parametrize("live", [None, False, True])
def test_workflow_requires_explicit_live_opt_in_and_retains_actual_model(
    tmp_path: Path, live: bool | None
) -> None:
    calls: list[str] = []

    async def callback(_: str, prompt: str) -> str:
        calls.append(prompt)
        return json.dumps(
            {"title": "项目复盘", "sections": [{"id": "progress", "content": "待补充进展。"}]}
        )

    settings = RuntimeSettings(
        environment="test",
        server_provider=ProviderSettings(
            name="fake",
            model="fixture-real-model",
            api_key="fixture-secret",
            base_url="https://fixture.invalid/private-source/v1",
        ),
    )
    app = create_app(storage=GongwenStorage(tmp_path / "writing.sqlite3"), settings=settings)
    app.state.yanzhang_platform.composer = YanzhangComposer(callback)
    with TestClient(app) as client:
        bootstrap = client.get("/api/v2/bootstrap").json()
        assert bootstrap["execution"]["mode"] == "local"
        assert bootstrap["execution"]["model"] is None
        assert bootstrap["model"]["default_model"] == "fixture-real-model"
        assert bootstrap["resolved_route"]["allows_network"] is False
        project_id = client.post(
            "/api/v2/projects", json={"name": "模式测试", "scenario_pack_id": "gongwen"}
        ).json()["project"]["id"]
        payload = {**_brief(), "auto_review": True}
        if live is not None:
            payload["live"] = live
        created = client.post(f"/api/v2/projects/{project_id}/workflows", json=payload)
        assert created.status_code == 201
        workflow = created.json()["workflow"]
        assert workflow["input"]["live"] is bool(live)
        assert workflow["execution"]["uses_model"] is bool(live)
        run = client.post(
            f"/api/v2/projects/{project_id}/workflows/{workflow['id']}/run", json={"mode": "sync"}
        )
        assert run.status_code == 200
        completed = run.json()["workflow"]
        assert completed["status"] == "succeeded", json.dumps(completed, ensure_ascii=False)
        assert len(calls) == (1 if live else 0)
        compose = next(step for step in completed["steps"] if step["step_id"] == "draft")
        execution = compose["output"]["execution"]
        assert execution["mode"] == ("live" if live else "local")
        assert execution["model"] == ("fixture-real-model" if live else None)
        assert execution["provider"] == ("fake" if live else None)
        assert execution["engine"] == ("language_model" if live else "deterministic")
        assert execution["model"] != "balanced"
        for step in completed["steps"]:
            if step["step_id"] in {"titles", "outline", "review"}:
                assert step["output"]["execution"]["uses_model"] is False
        asset = client.get(f"/api/v2/projects/{project_id}/assets/{completed['output_asset_id']}")
        assert asset.status_code == 200
        assert asset.json()["execution"] == execution
        serialized = json.dumps([bootstrap, created.json(), completed, asset.json()])
        assert "fixture-secret" not in serialized
        assert "private-source" not in serialized
        assert "fixture.invalid" not in serialized
        titles = client.post(f"/api/v2/projects/{project_id}/headlines", json=_brief())
        assert titles.status_code == 200
        assert titles.json()["execution"]["uses_model"] is False
        assert len(calls) == (1 if live else 0)


def test_workflow_live_without_model_is_a_configuration_error(tmp_path: Path) -> None:
    app = create_app(
        storage=GongwenStorage(tmp_path / "writing.sqlite3"),
        settings=RuntimeSettings(environment="test"),
    )
    with TestClient(app) as client:
        project_id = client.post(
            "/api/v2/projects", json={"name": "离线模式", "scenario_pack_id": "gongwen"}
        ).json()["project"]["id"]
        response = client.post(
            f"/api/v2/projects/{project_id}/workflows", json={**_brief(), "live": True}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "model_configuration_error"
        assert app.state.yanzhang_storage.list_text_assets(project_id=project_id) == []


def test_workflow_request_schema_defaults_to_offline() -> None:
    request = CreateWorkflowRequest.model_validate({**_brief(), "project_id": "fixture"})
    assert request.live is False
    assert CreateWorkflowRequest.model_json_schema()["properties"]["live"]["default"] is False
