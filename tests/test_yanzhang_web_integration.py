"""Composition-root and end-to-end tests for the mounted Yanzhang Web API."""

# Chinese fixture text intentionally uses full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from gongwen_web.app import create_app
from gongwen_web.models import ProviderSettings
from gongwen_web.runtime import RuntimeSettings
from gongwen_web.storage import GongwenStorage
from yanzhang_academic import ResearchClaim
from yanzhang_core import (
    ExtensionKind,
    ExtensionRegistry,
    StepContext,
    StepResult,
    WorkflowDefinition,
    WorkflowStepDefinition,
)


@pytest.fixture
def application(tmp_path: Path) -> Starlette:
    """Build the real composition root over one isolated SQLite database."""

    return create_app(storage=GongwenStorage(tmp_path / "gongwen.sqlite3"))


@pytest.fixture
def client(application: Starlette) -> Iterator[TestClient]:
    with TestClient(application) as test_client:
        yield test_client


def test_composition_root_shares_storage_artifacts_and_closes_engine_once(
    application: Starlette,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = application.state
    assert state.yanzhang_storage.path == state.gongwen_storage.path
    assert state.yanzhang_knowledge.storage is state.yanzhang_storage
    assert state.yanzhang_academic_repository.storage is state.yanzhang_storage
    assert state.yanzhang_platform.storage is state.yanzhang_storage
    assert state.yanzhang_platform.workflow_engine is state.yanzhang_workflow_engine
    assert state.yanzhang_platform.artifact_store is state.gongwen_artifact_store
    assert state.gongwen_mcp_context.yanzhang_platform is state.yanzhang_platform
    assert state.gongwen_mcp_context._workflow_engine is state.yanzhang_workflow_engine

    close_spy = Mock(wraps=state.yanzhang_workflow_engine.close)
    monkeypatch.setattr(state.yanzhang_workflow_engine, "close", close_spy)
    with TestClient(application) as test_client:
        assert test_client.get("/api/v2/bootstrap").status_code == 200
    close_spy.assert_called_once_with()


def test_composition_root_catalogs_and_executes_registered_workflow_extension(
    tmp_path: Path,
) -> None:
    registry = ExtensionRegistry()

    def factory() -> object:
        def handler(context: StepContext) -> StepResult:
            return StepResult(
                output={"handled": context.input["topic"]},
                state_updates={"extension_result": f"扩展:{context.input['topic']}"},
            )

        return handler

    registry.register(ExtensionKind.WORKFLOW_STEP, "fixture.step", factory)
    registry.register(ExtensionKind.PARSER, "fixture.parser", lambda: object())
    app = create_app(
        storage=GongwenStorage(tmp_path / "extensions.sqlite3"),
        extension_registry=registry,
    )

    with TestClient(app) as test_client:
        status = test_client.get("/api/v2/bootstrap")
        assert status.status_code == 200
        assert status.json()["extensions"]["workflow_step"] == ["fixture.step"]
        assert status.json()["extensions"]["parser"] == ["fixture.parser"]
        assert app.state.yanzhang_extension_workflow_wiring["registered"] == ["fixture.step"]

        project_id = test_client.post(
            "/api/v2/projects",
            json={"name": "扩展执行项目", "scenario_pack_id": "workplace"},
        ).json()["project"]["id"]
        definition = WorkflowDefinition(
            id="fixture-extension-workflow",
            version="1",
            steps=(WorkflowStepDefinition(id="extension", handler="fixture.step"),),
        )
        engine = app.state.yanzhang_workflow_engine
        run = engine.create_run(
            definition,
            {"topic": "绿色发展"},
            project_id=project_id,
        )
        completed = engine.run_sync(run["id"], project_id=project_id)
        assert completed["status"] == "succeeded"
        assert completed["state"] == {"extension_result": "扩展:绿色发展"}


def test_project_material_workflow_asset_review_export_cycle(client: TestClient) -> None:
    created_project = client.post(
        "/api/v2/projects",
        json={
            "name": "区委办专题材料",
            "scenario_pack_id": "gongwen",
            "tags": ["政绩观", "2026"],
        },
    )
    assert created_project.status_code == 201
    project = created_project.json()["project"]
    project_id = project["id"]
    assert project["tags"] == ["政绩观", "2026"]

    created_term = client.post(
        f"/api/v2/projects/{project_id}/terms",
        json={
            "term": "月报",
            "preferred_form": "月度工作报告",
            "discouraged_variants": ["月度报表"],
        },
    )
    assert created_term.status_code == 201
    term = created_term.json()["term"]
    assert term["project_id"] == project_id
    listed_terms = client.get(f"/api/v2/projects/{project_id}/terms")
    assert listed_terms.status_code == 200
    assert listed_terms.json()["items"] == [term]

    created_material = client.post(
        f"/api/v2/projects/{project_id}/materials",
        json={
            "title": "政绩观调研事实",
            "content": (
                "2026年开展基层调研12次，收集意见47条，并在月度报表中记录，坚持为民办实事。"
            ),
            "tags": ["已核对"],
        },
    )
    assert created_material.status_code == 201
    material_id = created_material.json()["material"]["id"]

    created_workflow = client.post(
        f"/api/v2/projects/{project_id}/workflows",
        json={
            "topic": "树立和践行正确政绩观",
            "goal": "形成专题交流文章",
            "audience": "区委办公室干部",
            "channel": "document",
            "content_type": "工作总结",
            "scenario_pack_id": "gongwen",
            "recipe_id": "work-summary",
            "material_ids": [material_id],
            "auto_review": True,
            "requested_exports": ["markdown"],
        },
    )
    assert created_workflow.status_code == 201
    workflow_id = created_workflow.json()["workflow"]["id"]

    completed = client.post(
        f"/api/v2/projects/{project_id}/workflows/{workflow_id}/run",
        json={"mode": "sync"},
    )
    assert completed.status_code == 200
    workflow = completed.json()["workflow"]
    assert workflow["status"] == "succeeded"
    assert [step["status"] for step in workflow["steps"]] == ["succeeded"] * 6
    asset_id = workflow["output_asset_id"]

    rejected_resume = client.post(
        f"/api/v2/projects/{project_id}/workflows/{workflow_id}/run",
        json={"mode": "background", "resume_from": "research"},
    )
    assert rejected_resume.status_code == 422
    assert rejected_resume.json()["error"]["code"] == "invalid_request"

    fetched_asset = client.get(
        f"/api/v2/projects/{project_id}/assets/{asset_id}",
        params={"chunk_size": 2_000},
    )
    assert fetched_asset.status_code == 200
    fetched_asset_payload = fetched_asset.json()["asset"]
    assert "树立和践行正确政绩观" in fetched_asset_payload["title"]
    paragraph_blocks = [
        block for block in fetched_asset_payload["blocks"] if block["kind"] == "paragraph"
    ]
    assert paragraph_blocks
    assert all(block["evidence_ids"] for block in paragraph_blocks)

    repository = client.app.state.yanzhang_knowledge
    claims = repository.list_claims(asset_id, project_id=project_id)
    citations = repository.list_citations(asset_id, project_id=project_id)
    assert claims
    assert citations
    assert all(claim.evidence_ids for claim in claims)
    assert {citation.claim_id for citation in citations} == {claim.id for claim in claims}

    reviewed = client.post(
        f"/api/v2/projects/{project_id}/assets/{asset_id}/review",
        json={
            "checks": ["structure", "facts", "terminology"],
            "material_ids": [material_id],
        },
    )
    assert reviewed.status_code == 200
    review = reviewed.json()["review"]
    assert review["asset_id"] == asset_id
    assert review["dimensions"]
    assert review["metrics"]["evidence_coverage"] == 100
    assert any(
        issue["dimension"] == "language" and issue["suggestion"] == "按项目约定使用“月度工作报告”。"
        for issue in review["issues"]
    )

    exported = client.post(
        f"/api/v2/projects/{project_id}/assets/{asset_id}/export",
        json={"format": "markdown", "filename": "政绩观交流文章.md"},
    )
    assert exported.status_code == 201
    artifact = exported.json()["artifact"]
    assert artifact["project_id"] == project_id
    assert artifact["asset_id"] == asset_id
    assert artifact["revision_id"]
    assert artifact["creator"] == "yanzhang_export_asset"
    downloaded = client.get(f"/api/v2/projects/{project_id}/exports/{artifact['artifact_id']}")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("text/markdown")
    assert hashlib.sha256(downloaded.content).hexdigest() == artifact["sha256"]
    assert client.get(f"/api/v2/exports/{artifact['artifact_id']}").status_code == 404

    exported_matrix = client.post(
        f"/api/v2/projects/{project_id}/assets/{asset_id}/export",
        json={"format": "csv", "filename": "政绩观证据矩阵.csv"},
    )
    assert exported_matrix.status_code == 201
    matrix_artifact = exported_matrix.json()["artifact"]
    downloaded_matrix = client.get(
        f"/api/v2/projects/{project_id}/exports/{matrix_artifact['artifact_id']}"
    )
    assert downloaded_matrix.status_code == 200
    rows = list(csv.DictReader(io.StringIO(downloaded_matrix.content.decode("utf-8"))))
    evidence_rows = [row for row in rows if row["evidence_id"]]
    assert evidence_rows
    assert {row["knowledge_item_id"] for row in evidence_rows} == {material_id}
    assert {row["locator"] for row in evidence_rows} == {"正文全文"}
    assert all(len(row["source_hash"]) == 64 for row in evidence_rows)

    deleted_term = client.delete(f"/api/v2/projects/{project_id}/terms/{term['id']}")
    assert deleted_term.status_code == 200
    assert deleted_term.json()["deleted"] is True
    assert client.get(f"/api/v2/projects/{project_id}/terms").json()["items"] == []


def test_workflow_http_operations_hide_cross_project_identifiers(client: TestClient) -> None:
    first = client.post(
        "/api/v2/projects",
        json={"name": "工作流所属项目", "scenario_pack_id": "gongwen"},
    ).json()["project"]["id"]
    second = client.post(
        "/api/v2/projects",
        json={"name": "其他项目", "scenario_pack_id": "gongwen"},
    ).json()["project"]["id"]
    created = client.post(
        f"/api/v2/projects/{first}/workflows",
        json={
            "topic": "项目作用域",
            "goal": "验证隔离",
            "audience": "项目组",
            "content_type": "工作总结",
            "scenario_pack_id": "gongwen",
            "recipe_id": "work-summary",
        },
    )
    assert created.status_code == 201
    workflow_id = created.json()["workflow"]["id"]

    assert client.get(f"/api/v2/projects/{second}/workflows/{workflow_id}").status_code == 404
    assert (
        client.post(
            f"/api/v2/projects/{second}/workflows/{workflow_id}/run",
            json={"mode": "sync"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v2/projects/{second}/workflows/{workflow_id}/cancel",
            json={},
        ).status_code
        == 404
    )


def test_v2_bootstrap_is_public_and_validation_does_not_reflect_values(tmp_path: Path) -> None:
    settings = RuntimeSettings(
        environment="test",
        access_token="FIXTURE_WEB_TOKEN",
        mcp_access_token="FIXTURE_MCP_TOKEN",
        allowed_hosts=("testserver",),
    )
    app = create_app(
        storage=GongwenStorage(tmp_path / "protected.sqlite3"),
        settings=settings,
    )
    submitted_value = "private-value-for-validation"

    with TestClient(app) as protected_client:
        bootstrap = protected_client.get("/api/v2/bootstrap")
        assert bootstrap.status_code == 200
        assert bootstrap.json()["routing_preset"] == "local_only"
        assert protected_client.get("/api/v2/projects").status_code == 401

        invalid = protected_client.post(
            "/api/v2/projects",
            headers={"Authorization": "Bearer FIXTURE_WEB_TOKEN"},
            json={
                "name": "边界校验",
                "scenario_pack_id": "gongwen",
                "unexpected": submitted_value,
            },
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "validation_error"
        assert submitted_value not in invalid.text


def test_configured_model_enables_balanced_live_routing(tmp_path: Path) -> None:
    settings = RuntimeSettings(
        environment="test",
        server_provider=ProviderSettings(
            name="fake",
            model="fixture-model",
            api_key="fixture-model-key",
        ),
    )
    app = create_app(
        storage=GongwenStorage(tmp_path / "live.sqlite3"),
        settings=settings,
    )

    with TestClient(app) as test_client:
        bootstrap = test_client.get("/api/v2/bootstrap")
        assert bootstrap.status_code == 200
        payload = bootstrap.json()
        assert payload["live_model_available"] is True
        assert payload["routing_preset"] == "balanced"
        assert payload["resolved_route"]["preset"] == "balanced"
        assert payload["resolved_route"]["allows_network"] is True
        assert "fixture-model-key" not in bootstrap.text


def test_academic_http_cycle_persists_across_real_app_restart(tmp_path: Path) -> None:
    """Exercise every academic route without contacting a model or metadata service."""

    database_path = tmp_path / "academic-cycle.sqlite3"
    first_app = create_app(storage=GongwenStorage(database_path))
    bibliography = """\
@article{liu2026,
  title={数字治理中的协同机制},
  author={Liu, Ming and Wang, Hua},
  year={2026},
  journal={治理研究},
  doi={10.1234/yanzhang.fixture}
}
"""
    evidence_text = (
        "研究结果表明，跨部门协同机制显著提升了信息共享质量。该结论来自对多部门样本的比较分析。"
    )
    claim = ResearchClaim(
        text="跨部门协同机制显著提升了信息共享质量",
        section="研究发现",
        requires_citation=True,
    ).model_dump(mode="json")

    with TestClient(first_app) as first_client:
        created_project = first_client.post(
            "/api/v2/projects",
            json={"name": "数字治理研究", "scenario_pack_id": "academic"},
        )
        assert created_project.status_code == 201
        project_id = created_project.json()["project"]["id"]

        other_project = first_client.post(
            "/api/v2/projects",
            json={"name": "隔离项目", "scenario_pack_id": "academic"},
        )
        assert other_project.status_code == 201
        other_project_id = other_project.json()["project"]["id"]

        imported = first_client.post(
            f"/api/v2/projects/{project_id}/academic/literature/import",
            json={"content": bibliography, "format": "bibtex", "tags": ["核心文献"]},
        )
        assert imported.status_code == 201
        assert imported.json()["count"] == 1
        record = imported.json()["items"][0]
        record_id = record["id"]
        assert record["import_source"] == "bibtex"
        assert record["doi"] == "10.1234/yanzhang.fixture"

        fetched = first_client.get(f"/api/v2/projects/{project_id}/academic/literature/{record_id}")
        assert fetched.status_code == 200
        assert fetched.json()["record"]["source_hash"] == record["source_hash"]

        extracted = first_client.post(
            f"/api/v2/projects/{project_id}/academic/evidence/extract",
            json={
                "record_id": record_id,
                "text": evidence_text,
                "query": "协同机制",
                "max_snippets": 10,
            },
        )
        assert extracted.status_code == 200
        assert extracted.json()["count"] == 1
        evidence = extracted.json()["items"][0]
        evidence_id = evidence["id"]
        assert evidence["record_source_hash"] == record["source_hash"]

        built_matrix = first_client.post(
            f"/api/v2/projects/{project_id}/academic/matrix",
            json={
                "record_ids": [record_id],
                "evidence_ids": [evidence_id],
                "query": "协同机制",
            },
        )
        assert built_matrix.status_code == 200
        matrix = built_matrix.json()["matrix"]
        matrix_id = matrix["id"]
        assert matrix["rows"][0]["evidence_ids"] == [evidence_id]

        link = {
            "claim_id": claim["id"],
            "record_id": record_id,
            "evidence_id": evidence_id,
            "relation": "supports",
        }
        verified = first_client.post(
            f"/api/v2/projects/{project_id}/academic/citations/verify",
            json={
                "record_ids": [record_id],
                "evidence_ids": [evidence_id],
                "claims": [claim],
                "links": [link],
            },
        )
        assert verified.status_code == 200
        audit = verified.json()["citation_audit"]
        assert audit["coverage"] == 1.0
        assert audit["links"][0]["status"] == "verified"
        verified_link = audit["links"][0]

        formatted = first_client.post(
            f"/api/v2/projects/{project_id}/academic/bibliography",
            json={"record_ids": [record_id], "style": "gb-t-7714"},
        )
        assert formatted.status_code == 200
        assert "数字治理中的协同机制" in formatted.json()["items"][0]

        academic_brief = {
            "title": "数字治理中的协同机制",
            "research_question": "跨部门协同如何影响信息共享？",
            "discipline": "公共管理",
            "purpose": "解释协同机制与信息共享的关系",
            "audience": "学术读者",
            "document_type": "研究论文",
            "language": "zh-CN",
            "keywords": ["数字治理", "协同机制"],
            "constraints": ["结论限于已导入证据"],
            "method_notes": "比较分析",
            "record_ids": [record_id],
        }
        titles = first_client.post(
            f"/api/v2/projects/{project_id}/academic/titles",
            json={**academic_brief, "count": 3},
        )
        assert titles.status_code == 200
        assert titles.json()["count"] == 3

        outline = first_client.post(
            f"/api/v2/projects/{project_id}/academic/outline",
            json={**academic_brief, "evidence_ids": [evidence_id]},
        )
        assert outline.status_code == 200
        assert outline.json()["outline"]["record_ids"] == [record_id]

        abstract = first_client.post(
            f"/api/v2/projects/{project_id}/academic/abstract",
            json={
                **academic_brief,
                "claims": [claim],
                "links": [verified_link],
                "max_characters": 800,
            },
        )
        assert abstract.status_code == 200
        assert abstract.json()["abstract"]["claim_ids"] == [claim["id"]]
        assert abstract.json()["abstract"]["placeholders"] == []

        integrity = first_client.post(
            f"/api/v2/projects/{project_id}/academic/integrity",
            json={
                "manuscript": (
                    "# 数字治理中的跨部门协同机制研究\n\n"
                    f"## 摘要\n{evidence_text}\n\n"
                    f"## 结论\n{evidence_text}"
                ),
                "record_ids": [record_id],
                "evidence_ids": [evidence_id],
                "claims": [claim],
                "links": [verified_link],
                "journal": {
                    "name": "治理研究",
                    "required_sections": ["摘要", "研究方法", "结论"],
                    "title_max_characters": 8,
                    "custom_rules": ["提交匿名稿"],
                },
            },
        )
        assert integrity.status_code == 200
        integrity_payload = integrity.json()
        integrity_review = integrity_payload["integrity_review"]
        assert integrity_review["citation_audit"]["coverage"] == 1.0
        messages = [item["message"] for item in integrity_review["comments"]]
        assert any("题名共" in message and "上限 8" in message for message in messages)
        assert any("研究方法" in message and "缺少" in message for message in messages)
        assert "期刊自定义要求需人工逐项核对：提交匿名稿" in messages
        assert integrity_payload["manuscript_words"] > 0
        assert integrity_payload["journal_profile_id"].startswith("journal_")

        rebuttal = first_client.post(
            f"/api/v2/projects/{project_id}/academic/rebuttal",
            json={
                "comments": [
                    {
                        "category": "style",
                        "message": "请进一步说明研究边界。",
                        "location": "结论",
                    }
                ],
                "changes": {},
            },
        )
        assert rebuttal.status_code == 200
        assert rebuttal.json()["count"] == 1

        isolated_record = first_client.get(
            f"/api/v2/projects/{other_project_id}/academic/literature/{record_id}"
        )
        assert isolated_record.status_code == 404
        assert isolated_record.json()["error"]["code"] == "not_found"
        isolated_matrix = first_client.post(
            f"/api/v2/projects/{other_project_id}/academic/matrix",
            json={"record_ids": [record_id], "evidence_ids": [evidence_id]},
        )
        assert isolated_matrix.status_code == 404

    rebuilt_app = create_app(storage=GongwenStorage(database_path))
    with TestClient(rebuilt_app) as rebuilt_client:
        persisted_record = rebuilt_client.get(
            f"/api/v2/projects/{project_id}/academic/literature/{record_id}"
        )
        assert persisted_record.status_code == 200
        assert persisted_record.json()["record"]["source_hash"] == record["source_hash"]

        recovered_collections = {
            "literature": record_id,
            "evidence": evidence_id,
            "matrices": matrix_id,
            "claims": claim["id"],
            "citation-links": verified_link["id"],
        }
        for collection, expected_id in recovered_collections.items():
            response = rebuilt_client.get(
                f"/api/v2/projects/{project_id}/academic/{collection}?limit=100&offset=0"
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["total"] == 1
            assert payload["count"] == 1
            assert payload["has_more"] is False
            assert payload["items"][0]["id"] == expected_id

        recovered_items = {
            f"literature/{record_id}": "record",
            f"evidence/{evidence_id}": "evidence",
            f"matrices/{matrix_id}": "matrix",
            f"claims/{claim['id']}": "claim",
            f"citation-links/{verified_link['id']}": "link",
        }
        for item_path, response_key in recovered_items.items():
            response = rebuilt_client.get(f"/api/v2/projects/{project_id}/academic/{item_path}")
            assert response.status_code == 200
            assert response.json()[response_key]["id"]

        for collection in recovered_collections:
            response = rebuilt_client.get(
                f"/api/v2/projects/{other_project_id}/academic/{collection}"
            )
            assert response.status_code == 200
            assert response.json()["items"] == []

        repository = rebuilt_app.state.yanzhang_academic_repository
        assert repository.get_evidence(project_id, evidence_id).record_id == record_id
        assert repository.get_matrix(project_id, matrix_id).rows[0].evidence_ids == [evidence_id]

        rebuilt_matrix = rebuilt_client.post(
            f"/api/v2/projects/{project_id}/academic/matrix",
            json={
                "record_ids": [record_id],
                "evidence_ids": [evidence_id],
                "query": "协同机制",
            },
        )
        assert rebuilt_matrix.status_code == 200
        assert rebuilt_matrix.json()["matrix"]["id"] == matrix_id

        still_isolated = rebuilt_client.get(
            f"/api/v2/projects/{other_project_id}/academic/literature/{record_id}"
        )
        assert still_isolated.status_code == 404
