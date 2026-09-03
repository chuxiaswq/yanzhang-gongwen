"""HTTP integration tests for the phase-two official-document APIs."""

# Chinese official-document test data intentionally uses full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import importlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from gongwen_web.app import create_app
from gongwen_web.demo import generate_demo
from gongwen_web.models import GeneratedDocument, GenerateRequest, GenerationMeta
from gongwen_web.storage import GongwenStorage
from yanzhang.providers.errors import ProviderTimeoutError


@pytest.fixture
def storage(tmp_path: Path) -> GongwenStorage:
    """Create one isolated SQLite store shared by every service in the app."""

    return GongwenStorage(tmp_path / "phase2.sqlite3")


@pytest.fixture
def client(storage: GongwenStorage) -> Iterator[TestClient]:
    """Expose the real Starlette routes over an isolated local database."""

    with TestClient(create_app(storage=storage)) as test_client:
        yield test_client


def test_document_api_crud_search_versions_and_optimistic_conflict(
    client: TestClient,
) -> None:
    created_response = client.post(
        "/api/documents",
        json={
            "id": "phase2-draft",
            "title": "关于推进数字化工作的通知",
            "document_type": "通知",
            "content": "一、总体要求\n稳步推进数字化工作。",
            "metadata": {"fact_lock": True, "facts": ["已接入18个处室"]},
            "version_note": "初稿",
            "expected_version": 0,
        },
    )
    assert created_response.status_code == 201
    assert created_response.headers["cache-control"] == "no-store"
    created = created_response.json()
    assert created["id"] == "phase2-draft"
    assert created["current_version"] == 1
    assert created["metadata"] == {"fact_lock": True, "facts": ["已接入18个处室"]}

    listed_response = client.get("/api/documents", params={"q": "数字化", "limit": 5})
    assert listed_response.status_code == 200
    listed = listed_response.json()
    assert listed["limit"] == 5
    assert listed["offset"] == 0
    assert [item["id"] for item in listed["items"]] == ["phase2-draft"]
    assert listed["items"][0]["character_count"] == len(created["content"])

    fetched_response = client.get("/api/documents/phase2-draft")
    assert fetched_response.status_code == 200
    assert fetched_response.json() == created

    updated_response = client.post(
        "/api/documents",
        json={
            "id": "phase2-draft",
            "title": "关于进一步推进数字化工作的通知",
            "document_type": "通知",
            "content": "一、总体要求\n稳步推进数字化工作。\n二、工作安排\n9月底前完成目录。",
            "metadata": {"fact_lock": True, "facts": ["9月底前完成目录"]},
            "version_note": "补充工作安排",
            "expected_version": 1,
        },
    )
    assert updated_response.status_code == 201
    updated = updated_response.json()
    assert updated["current_version"] == 2
    assert updated["created_at"] == created["created_at"]

    conflict_response = client.post(
        "/api/documents",
        json={
            "id": "phase2-draft",
            "title": "过期页面中的标题",
            "content": "这次保存不应覆盖第二版。",
            "expected_version": 1,
        },
    )
    assert conflict_response.status_code == 409
    assert conflict_response.json()["error"]["code"] == "version_conflict"
    assert "期望 1，当前 2" in conflict_response.json()["error"]["message"]
    assert client.get("/api/documents/phase2-draft").json() == updated

    versions_response = client.get("/api/documents/phase2-draft/versions", params={"limit": 10})
    assert versions_response.status_code == 200
    versions = versions_response.json()["items"]
    assert [item["version"] for item in versions] == [2, 1]
    assert [item["note"] for item in versions] == ["补充工作安排", "初稿"]
    assert versions[0]["content"] == updated["content"]
    assert versions[1]["content"] == created["content"]

    invalid_page = client.get("/api/documents", params={"limit": 0})
    assert invalid_page.status_code == 400
    assert invalid_page.json()["error"]["code"] == "invalid_request"

    deleted_response = client.delete("/api/documents/phase2-draft")
    assert deleted_response.status_code == 200
    assert deleted_response.json() == {"deleted": True}
    assert client.get("/api/documents/phase2-draft").status_code == 404
    assert client.get("/api/documents/phase2-draft/versions").status_code == 404
    assert client.delete("/api/documents/phase2-draft").status_code == 404


def test_article_api_manual_import_search_source_filter_and_delete(
    client: TestClient,
) -> None:
    sources_response = client.get("/api/article-sources")
    assert sources_response.status_code == 200
    sources = sources_response.json()["items"]
    assert {item["id"] for item in sources} == {"people", "gmw", "qiushi"}
    assert all(item["homepage"].startswith("https://") for item in sources)

    imported_response = client.post(
        "/api/articles/import-text",
        json={
            "title": "数字政府建设要坚持协同推进",
            "content": (
                "数字政府建设需要强化跨部门协同。要以群众办事体验为导向，"
                "完善数据目录，推动事项办理提质增效。"
            ),
            "source_id": "manual",
            "source_name": "个人资料",
            "published_date": "2026-09-03",
            "summary": "围绕数字政府协同建设和办事体验展开。",
            "style_features": ["开篇点题", "层层推进"],
        },
    )
    assert imported_response.status_code == 201
    assert imported_response.headers["cache-control"] == "no-store"
    imported = imported_response.json()
    assert "content" not in imported
    assert imported["source_id"] == "manual"
    assert imported["source_name"] == "个人资料"
    assert imported["import_method"] == "manual"
    assert "短段凝练" in imported["style_features"]
    assert imported["style_features"][-2:] == ["开篇点题", "层层推进"]

    other_response = client.post(
        "/api/articles/import-text",
        json={
            "title": "理论学习工作简报",
            "content": "围绕理论学习组织专题研讨，持续提升学习质效。",
            "source_id": "manual",
            "source_name": "个人资料",
        },
    )
    assert other_response.status_code == 201

    search_response = client.get(
        "/api/articles",
        params={"q": "数据目录", "source_id": "manual", "limit": 10, "offset": 0},
    )
    assert search_response.status_code == 200
    page = search_response.json()
    assert page["query"] == "数据目录"
    assert page["total"] == 1
    assert page["limit"] == 10
    assert page["offset"] == 0
    assert [item["id"] for item in page["items"]] == [imported["id"]]
    assert "数据目录" in page["items"][0]["excerpt"]
    assert "content" not in page["items"][0]
    assert page["items"][0]["score"] > 0

    fetched_response = client.get(f"/api/articles/{imported['id']}")
    assert fetched_response.status_code == 200
    fetched = fetched_response.json()
    assert fetched["content"].startswith("数字政府建设需要强化跨部门协同")
    assert fetched["content_hash"] == imported["content_hash"]

    deleted_response = client.delete(f"/api/articles/{imported['id']}")
    assert deleted_response.status_code == 200
    assert deleted_response.json() == {"deleted": True}
    assert client.get(f"/api/articles/{imported['id']}").status_code == 404
    assert client.delete(f"/api/articles/{imported['id']}").status_code == 404
    assert client.get("/api/articles", params={"q": "数据目录"}).json()["total"] == 0


def test_fact_audit_api_returns_traceable_contradictions_and_validates_input(
    client: TestClient,
) -> None:
    materials = [
        "市数据资源管理局于2026年8月31日完成6个平台整合。",
        "平均办理时长缩短31%。",
    ]
    response = client.post(
        "/api/fact-audit",
        json={
            "title": "数字化转型工作总结",
            "content": "市数据资源管理局于2026年9月30日完成8个平台整合。",
            "materials": materials,
        },
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["sentences"][0]["status"] == "contradicted"
    assert {
        claim["value"]
        for claim in result["sentences"][0]["claims"]
        if claim["status"] == "contradicted"
    } == {"2026年9月30日", "8个"}
    assert result["metrics"]["contradicted_claim_count"] == 2
    assert result["metrics"]["contradicted_sentence_count"] == 1
    assert any(issue["category"] == "事实冲突" for issue in result["issues"])

    for fact in result["facts"]:
        source = materials[fact["source_index"] - 1]
        assert source[fact["start"] : fact["end"]] == fact["value"]

    invalid_response = client.post("/api/fact-audit", json={"content": ""})
    assert invalid_response.status_code == 422
    assert invalid_response.json()["error"]["code"] == "invalid_request"
    assert invalid_response.json()["error"]["details"][0]["field"] == "content"


def test_successful_live_model_metadata_is_recorded_and_aggregated(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_module = importlib.import_module("gongwen_web.app")

    async def fake_generate_live(command: GenerateRequest) -> GeneratedDocument:
        deterministic = generate_demo(command.model_copy(update={"live": False}))
        return deterministic.model_copy(
            update={
                "meta": GenerationMeta(
                    mode="live",
                    provider="fixture-provider",
                    model="fixture-model-v2",
                    input_tokens=123,
                    output_tokens=45,
                    total_tokens=168,
                )
            }
        )

    monkeypatch.setattr(app_module, "generate_live", fake_generate_live)

    empty_usage = client.get("/api/model-usage")
    assert empty_usage.status_code == 200
    assert empty_usage.json()["summary"] == {
        "call_count": 0,
        "successful_calls": 0,
        "failed_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "latency_ms": 0.0,
    }
    assert empty_usage.json()["items"] == []

    generated_response = client.post(
        "/api/generate",
        json={
            "topic": "模型用量统计",
            "document_type": "报告",
            "materials": "已完成6项任务。",
            "live": True,
            "provider": {"name": "fixture-provider"},
        },
    )
    assert generated_response.status_code == 200
    assert generated_response.json()["meta"] == {
        "mode": "live",
        "provider": "fixture-provider",
        "model": "fixture-model-v2",
        "input_tokens": 123,
        "output_tokens": 45,
        "total_tokens": 168,
    }

    usage_response = client.get("/api/model-usage")
    assert usage_response.status_code == 200
    assert usage_response.headers["cache-control"] == "no-store"
    usage = usage_response.json()
    summary = usage["summary"]
    assert summary["call_count"] == 1
    assert summary["successful_calls"] == 1
    assert summary["failed_calls"] == 0
    assert summary["input_tokens"] == 123
    assert summary["output_tokens"] == 45
    assert summary["total_tokens"] == 168
    assert summary["latency_ms"] >= 0

    assert len(usage["items"]) == 1
    item = usage["items"][0]
    assert item["operation"] == "generate"
    assert item["provider"] == "fixture-provider"
    assert item["model"] == "fixture-model-v2"
    assert item["input_tokens"] == 123
    assert item["output_tokens"] == 45
    assert item["total_tokens"] == 168
    assert item["success"] is True
    assert item["metadata"] == {"mode": "live"}
    assert item["latency_ms"] >= 0

    rejected_response = client.post("/api/generate", json={"live": False})
    assert rejected_response.status_code == 422
    assert client.get("/api/model-usage").json()["summary"]["call_count"] == 1


def test_failed_live_attempt_is_sanitized_and_recorded_without_request_content(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_module = importlib.import_module("gongwen_web.app")

    async def failing_generate_live(_: GenerateRequest) -> GeneratedDocument:
        raise ProviderTimeoutError("upstream body contained PRIVATE_MATERIAL", provider="fixture")

    monkeypatch.setattr(app_module, "generate_live", failing_generate_live)
    response = client.post(
        "/api/generate",
        json={
            "topic": "PRIVATE_MATERIAL",
            "live": True,
            "provider": {"name": "fixture", "model": "fixture-model"},
        },
    )

    assert response.status_code == 504
    assert "PRIVATE_MATERIAL" not in response.text
    usage = client.get("/api/model-usage").json()
    assert usage["summary"]["call_count"] == 1
    assert usage["summary"]["failed_calls"] == 1
    assert usage["items"][0]["success"] is False
    assert usage["items"][0]["error_code"] == "ProviderTimeoutError"
    assert usage["items"][0]["metadata"] == {"mode": "live"}
    assert "PRIVATE_MATERIAL" not in str(usage)
