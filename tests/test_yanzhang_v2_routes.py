"""Offline forwarding and boundary tests for the formal Yanzhang Web V2 API."""

# Chinese fixture text intentionally uses full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable, Iterator, Mapping
from pathlib import Path

import pytest
from httpx import Response as HTTPResponse
from starlette.applications import Starlette
from starlette.testclient import TestClient

from gongwen_mcp.artifacts import TEXT_MIME, ArtifactStore
from gongwen_mcp.writing_schemas import WritingRequest
from gongwen_web.v2 import v2_routes
from gongwen_web.writing_service import YanzhangPlatformService
from yanzhang_core.storage import WritingStorage


class _FakePlatform:
    def __init__(self) -> None:
        self.calls: list[tuple[str, WritingRequest]] = []
        self.fail_operation: str | None = None

    def __getattr__(
        self,
        name: str,
    ) -> Callable[[WritingRequest], Awaitable[Mapping[str, object]]]:
        if not name.startswith("yanzhang_") and name not in {
            "create_asset",
            "create_brief",
            "create_revision",
        }:
            raise AttributeError(name)

        async def invoke(request: WritingRequest) -> Mapping[str, object]:
            self.calls.append((name, request))
            if self.fail_operation == name:
                raise RuntimeError("provider secret FIXTURE_PROVIDER_CREDENTIAL")
            return {
                "operation": name,
                "request_type": type(request).__name__,
                "request": request.model_dump(mode="json"),
            }

        return invoke


@pytest.fixture
def platform() -> _FakePlatform:
    return _FakePlatform()


@pytest.fixture
def client(
    tmp_path: Path,
    platform: _FakePlatform,
) -> Iterator[TestClient]:
    app = Starlette(routes=v2_routes())
    app.state.yanzhang_platform = platform
    app.state.gongwen_artifact_store = ArtifactStore(tmp_path)
    with TestClient(app) as test_client:
        yield test_client


def _brief() -> dict[str, object]:
    return {
        "topic": "基层治理数字化",
        "goal": "形成可执行的工作方案",
        "audience": "业务处室",
        "channel": "document",
        "content_type": "工作总结",
        "scenario_pack_id": "gongwen",
        "recipe_id": "work-summary",
    }


def _academic_brief() -> dict[str, object]:
    return {
        "title": "数字治理研究",
        "research_question": "数字工具如何提升基层治理效能？",
        "discipline": "公共管理",
    }


def _saved_brief() -> dict[str, object]:
    payload = _brief()
    payload["title"] = payload.pop("topic")
    return payload


def _assert_forwarded(
    response: HTTPResponse,
    *,
    operation: str,
    request_type: str,
) -> None:
    assert response.status_code in {200, 201}
    payload = response.json()
    assert payload["operation"] == operation
    assert payload["request_type"] == request_type
    assert response.headers["cache-control"] == "no-store"


def test_bootstrap_scene_packs_and_project_crud_forward_strict_dtos(client: TestClient) -> None:
    cases = [
        (
            client.get("/api/v2/bootstrap"),
            "yanzhang_get_status",
            "StatusRequest",
        ),
        (
            client.get("/api/v2/scene-packs?channel=document"),
            "yanzhang_list_scene_packs",
            "ListScenePacksRequest",
        ),
        (
            client.get("/api/v2/scene-packs/gongwen"),
            "yanzhang_get_scene_pack",
            "GetScenePackRequest",
        ),
        (
            client.post(
                "/api/v2/projects",
                json={"name": "区委办材料项目", "scenario_pack_id": "gongwen"},
            ),
            "yanzhang_create_project",
            "CreateProjectRequest",
        ),
        (
            client.get("/api/v2/projects?limit=10&offset=0"),
            "yanzhang_list_projects",
            "ListProjectsRequest",
        ),
        (
            client.get("/api/v2/projects/proj-1"),
            "yanzhang_get_project",
            "GetProjectRequest",
        ),
    ]
    for response, operation, request_type in cases:
        _assert_forwarded(response, operation=operation, request_type=request_type)


def test_materials_search_and_headlines_preserve_project_identity(client: TestClient) -> None:
    added = client.post(
        "/api/v2/projects/proj-1/materials",
        json={"title": "调研材料", "content": "基层事项平均办理时间下降。"},
    )
    _assert_forwarded(
        added,
        operation="yanzhang_add_material",
        request_type="AddMaterialRequest",
    )
    assert added.json()["request"]["project_id"] == "proj-1"

    cases = [
        (
            client.get("/api/v2/projects/proj-1/materials?query=办理&kind=source&tags=调研,治理"),
            "yanzhang_list_materials",
            "ListMaterialsRequest",
        ),
        (
            client.get("/api/v2/projects/proj-1/materials/mat-1?chunk_size=500"),
            "yanzhang_get_material",
            "GetMaterialRequest",
        ),
        (
            client.get("/api/v2/projects/proj-1/search?query=基层治理&scope=all"),
            "yanzhang_search",
            "UnifiedSearchRequest",
        ),
        (
            client.post(
                "/api/v2/projects/proj-1/headlines",
                json={
                    **_brief(),
                    "count": 6,
                    "headline_kind": "title",
                    "formula_ids": ["parallel-triad"],
                },
            ),
            "yanzhang_generate_titles",
            "GenerateTitlesRequest",
        ),
    ]
    for response, operation, request_type in cases:
        _assert_forwarded(response, operation=operation, request_type=request_type)
        assert response.json()["request"]["project_id"] == "proj-1"
    assert cases[-1][0].json()["request"]["formula_ids"] == ["parallel-triad"]


def test_topic_and_persisted_title_share_the_300_character_boundary(
    client: TestClient,
    platform: _FakePlatform,
) -> None:
    too_long = "题" * 301

    headlines = client.post(
        "/api/v2/projects/proj-1/headlines",
        json={**_brief(), "topic": too_long},
    )
    workflow = client.post(
        "/api/v2/projects/proj-1/workflows",
        json={**_brief(), "topic": too_long},
    )
    brief = client.post(
        "/api/v2/projects/proj-1/briefs",
        json={**_saved_brief(), "title": too_long},
    )

    assert [response.status_code for response in (headlines, workflow, brief)] == [422, 422, 422]
    assert all(
        response.json()["error"]["code"] == "validation_error"
        for response in (
            headlines,
            workflow,
            brief,
        )
    )
    assert platform.calls == []


def test_workflow_lifecycle_routes_forward_without_fabricated_state(client: TestClient) -> None:
    created = client.post(
        "/api/v2/projects/proj-1/workflows",
        json={
            **_brief(),
            "auto_review": True,
            "requested_exports": [
                "docx",
                "markdown",
                "text",
                "html",
                "pdf",
                "latex",
                "csv",
            ],
        },
    )
    _assert_forwarded(
        created,
        operation="yanzhang_create_workflow",
        request_type="CreateWorkflowRequest",
    )

    cases = [
        (
            client.post(
                "/api/v2/projects/proj-1/workflows/flow-1/run",
                json={"mode": "background"},
            ),
            "yanzhang_run_workflow",
            "RunWorkflowRequest",
        ),
        (
            client.get("/api/v2/projects/proj-1/workflows/flow-1"),
            "yanzhang_get_workflow",
            "GetWorkflowRequest",
        ),
        (
            client.post("/api/v2/projects/proj-1/workflows/flow-1/cancel", json={}),
            "yanzhang_cancel_workflow",
            "CancelWorkflowRequest",
        ),
    ]
    for response, operation, request_type in cases:
        _assert_forwarded(response, operation=operation, request_type=request_type)
        assert response.json()["request"]["workflow_id"] == "flow-1"
        assert response.json()["request"]["project_id"] == "proj-1"


def test_workbench_context_fields_cross_http_boundaries_unchanged(client: TestClient) -> None:
    structure = [
        {
            "id": "review",
            "title": "一、在回望中看清来路",
            "purpose": "回顾总体进展。",
        },
        {
            "id": "action",
            "title": "二、在攻坚中打开新局",
            "purpose": "部署下一步行动。",
        },
    ]
    material = client.post(
        "/api/v2/projects/proj-1/materials",
        json={
            "material_id": "workspace-source-stable",
            "title": "主参考材料",
            "content": "已完成12项任务。",
            "kind": "source",
        },
    )
    _assert_forwarded(
        material,
        operation="yanzhang_add_material",
        request_type="AddMaterialRequest",
    )
    assert material.json()["request"]["material_id"] == "workspace-source-stable"

    brief_payload = {
        **_saved_brief(),
        "brief_id": "brief-workbench",
        "material_ids": ["workspace-source-stable"],
        "selected_title": "以实干破难题 以实绩开新局",
        "structure_override": structure,
    }
    saved = client.post("/api/v2/projects/proj-1/briefs", json=brief_payload)
    _assert_forwarded(saved, operation="create_brief", request_type="CreateBriefRequest")
    assert saved.json()["request"]["brief_id"] == "brief-workbench"
    assert saved.json()["request"]["selected_title"] == "以实干破难题 以实绩开新局"
    assert saved.json()["request"]["structure_override"] == [
        {**section, "required": True} for section in structure
    ]

    workflow_payload = {
        **_brief(),
        "brief_id": "brief-workbench",
        "material_ids": ["workspace-source-stable"],
        "selected_title": "以实干破难题 以实绩开新局",
        "structure_override": structure,
    }
    created = client.post(
        "/api/v2/projects/proj-1/workflows",
        json=workflow_payload,
    )
    _assert_forwarded(
        created,
        operation="yanzhang_create_workflow",
        request_type="CreateWorkflowRequest",
    )
    assert created.json()["request"]["brief_id"] == "brief-workbench"
    assert created.json()["request"]["selected_title"] == "以实干破难题 以实绩开新局"
    assert created.json()["request"]["structure_override"] == [
        {**section, "required": True} for section in structure
    ]


def test_asset_read_variant_revision_review_and_export_routes(client: TestClient) -> None:
    cases = [
        (
            client.get("/api/v2/projects/proj-1/assets?status=draft"),
            "yanzhang_list_assets",
            "ListAssetsRequest",
        ),
        (
            client.get("/api/v2/projects/proj-1/assets/asset-1?chunk_size=500"),
            "yanzhang_get_asset",
            "GetAssetRequest",
        ),
        (
            client.post(
                "/api/v2/projects/proj-1/assets/asset-1/variants",
                json={"target_channel": "social", "instruction": "压缩为摘要"},
            ),
            "yanzhang_create_variant",
            "CreateVariantRequest",
        ),
        (
            client.get("/api/v2/projects/proj-1/assets/asset-1/revisions"),
            "yanzhang_list_revisions",
            "ListRevisionsRequest",
        ),
        (
            client.post(
                "/api/v2/projects/proj-1/assets/asset-1/review",
                json={"checks": ["structure", "facts"]},
            ),
            "yanzhang_review_asset",
            "ReviewAssetRequest",
        ),
        (
            client.post(
                "/api/v2/projects/proj-1/assets/asset-1/export",
                json={"format": "markdown", "filename": "治理方案.md"},
            ),
            "yanzhang_export_asset",
            "ExportAssetRequest",
        ),
    ]
    for response, operation, request_type in cases:
        _assert_forwarded(response, operation=operation, request_type=request_type)
        request_payload = response.json()["request"]
        assert request_payload["project_id"] == "proj-1"
        if "asset_id" in request_payload:
            assert request_payload["asset_id"] == "asset-1"


@pytest.mark.parametrize("export_format", ["latex", "csv"])
def test_extended_export_formats_reach_the_platform(
    client: TestClient,
    export_format: str,
) -> None:
    response = client.post(
        "/api/v2/projects/proj-1/assets/asset-1/export",
        json={"format": export_format},
    )

    _assert_forwarded(
        response,
        operation="yanzhang_export_asset",
        request_type="ExportAssetRequest",
    )
    assert response.json()["request"]["format"] == export_format


def test_brief_asset_and_revision_writes_use_real_persistence_extensions(
    client: TestClient,
) -> None:
    brief = client.post(
        "/api/v2/projects/proj-1/briefs",
        json=_saved_brief(),
    )
    _assert_forwarded(brief, operation="create_brief", request_type="CreateBriefRequest")
    assert brief.json()["request"]["project_id"] == "proj-1"

    asset = client.post(
        "/api/v2/projects/proj-1/assets",
        json={"brief_id": "brief-1", "title": "基层治理工作方案"},
    )
    _assert_forwarded(asset, operation="create_asset", request_type="CreateAssetRequest")
    assert asset.json()["request"]["brief_id"] == "brief-1"

    revision = client.post(
        "/api/v2/projects/proj-1/assets/asset-1/revisions",
        json={
            "expected_revision": 1,
            "note": "调整开头",
            "blocks": [{"kind": "paragraph", "order": 0, "text": "开门见山提出任务。"}],
        },
    )
    _assert_forwarded(
        revision,
        operation="create_revision",
        request_type="CreateRevisionRequest",
    )
    assert revision.json()["request"]["asset_id"] == "asset-1"


def test_workflow_definition_catalog_is_bounded_and_actionable(client: TestClient) -> None:
    response = client.get("/api/v2/workflow-definitions?scenario_pack_id=gongwen&limit=2&offset=0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["total"] >= 2
    assert all(item["scenario_pack_id"] == "gongwen" for item in payload["items"])
    assert all(item["steps"] for item in payload["items"])
    assert response.headers["cache-control"] == "no-store"


def test_canonical_writes_persist_with_the_concrete_platform(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "data")
    platform = YanzhangPlatformService(
        WritingStorage(tmp_path / "data" / "writing.sqlite3"),
        artifact_store=store,
    )
    app = Starlette(routes=v2_routes())
    app.state.yanzhang_platform = platform
    app.state.gongwen_artifact_store = store
    try:
        with TestClient(app) as real_client:
            project_response = real_client.post(
                "/api/v2/projects",
                json={"name": "持久化项目", "scenario_pack_id": "gongwen"},
            )
            assert project_response.status_code == 201
            project_id = project_response.json()["project"]["id"]

            brief_response = real_client.post(
                f"/api/v2/projects/{project_id}/briefs",
                json=_saved_brief(),
            )
            assert brief_response.status_code == 201
            brief_id = brief_response.json()["brief"]["id"]

            asset_response = real_client.post(
                f"/api/v2/projects/{project_id}/assets",
                json={"brief_id": brief_id, "title": "基层治理工作总结"},
            )
            assert asset_response.status_code == 201
            asset = asset_response.json()["asset"]

            revision_response = real_client.post(
                f"/api/v2/projects/{project_id}/assets/{asset['id']}/revisions",
                json={
                    "expected_revision": asset["current_revision"],
                    "note": "确认首稿",
                    "blocks": asset["blocks"],
                },
            )
            assert revision_response.status_code == 201
            assert revision_response.json()["revision"]["version"] == 2

            persisted = real_client.get(
                f"/api/v2/projects/{project_id}/assets/{asset['id']}?chunk_size=20000"
            )
            assert persisted.status_code == 200
            assert persisted.json()["asset"]["current_revision"] == 2
    finally:
        platform.close()


def test_cross_project_material_id_returns_stable_scope_error(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "data")
    platform = YanzhangPlatformService(
        WritingStorage(tmp_path / "data" / "writing.sqlite3"),
        artifact_store=store,
    )
    app = Starlette(routes=v2_routes())
    app.state.yanzhang_platform = platform
    app.state.gongwen_artifact_store = store
    try:
        with TestClient(app) as real_client:
            first = real_client.post(
                "/api/v2/projects",
                json={"name": "材料项目一", "scenario_pack_id": "gongwen"},
            ).json()["project"]["id"]
            second = real_client.post(
                "/api/v2/projects",
                json={"name": "材料项目二", "scenario_pack_id": "gongwen"},
            ).json()["project"]["id"]
            material_id = "stable-project-scoped-material"
            created = real_client.post(
                f"/api/v2/projects/{first}/materials",
                json={
                    "material_id": material_id,
                    "title": "项目一材料",
                    "content": "仅属于项目一。",
                },
            )
            assert created.status_code == 201

            crossed = real_client.post(
                f"/api/v2/projects/{second}/materials",
                json={
                    "material_id": material_id,
                    "title": "项目二材料",
                    "content": "跨项目复用 ID。",
                },
            )

            assert crossed.status_code == 409
            assert crossed.json() == {
                "error": {
                    "code": "project_scope_error",
                    "message": "资源不属于当前项目",
                }
            }
            assert material_id not in crossed.text
    finally:
        platform.close()


def test_stable_brief_id_is_idempotent_and_conflicts_without_reflection(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "data")
    platform = YanzhangPlatformService(
        WritingStorage(tmp_path / "data" / "writing.sqlite3"),
        artifact_store=store,
    )
    app = Starlette(routes=v2_routes())
    app.state.yanzhang_platform = platform
    app.state.gongwen_artifact_store = store
    try:
        with TestClient(app) as real_client:
            project_id = real_client.post(
                "/api/v2/projects",
                json={"name": "简报幂等项目", "scenario_pack_id": "gongwen"},
            ).json()["project"]["id"]
            brief_id = "stable-private-brief-id"
            payload = {**_saved_brief(), "brief_id": brief_id}

            created = real_client.post(
                f"/api/v2/projects/{project_id}/briefs",
                json=payload,
            )
            replayed = real_client.post(
                f"/api/v2/projects/{project_id}/briefs",
                json=payload,
            )
            conflicted = real_client.post(
                f"/api/v2/projects/{project_id}/briefs",
                json={**payload, "goal": "敏感冲突正文 FIXTURE_PRIVATE_GOAL"},
            )

            assert created.status_code == replayed.status_code == 201
            assert created.json() == replayed.json()
            assert created.json()["brief_id"] == brief_id
            assert conflicted.status_code == 409
            assert conflicted.json() == {
                "error": {
                    "code": "brief_conflict",
                    "message": "任务简报标识已绑定其他内容",
                }
            }
            assert brief_id not in conflicted.text
            assert "FIXTURE_PRIVATE_GOAL" not in conflicted.text
            persisted = platform.storage.get_brief(brief_id, project_id=project_id)
            assert persisted.goal == payload["goal"]
    finally:
        platform.close()


def test_cross_project_brief_id_returns_stable_scope_error(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "data")
    platform = YanzhangPlatformService(
        WritingStorage(tmp_path / "data" / "writing.sqlite3"),
        artifact_store=store,
    )
    app = Starlette(routes=v2_routes())
    app.state.yanzhang_platform = platform
    app.state.gongwen_artifact_store = store
    try:
        with TestClient(app) as real_client:
            first = real_client.post(
                "/api/v2/projects",
                json={"name": "简报项目一", "scenario_pack_id": "gongwen"},
            ).json()["project"]["id"]
            second = real_client.post(
                "/api/v2/projects",
                json={"name": "简报项目二", "scenario_pack_id": "gongwen"},
            ).json()["project"]["id"]
            brief_id = "stable-project-scoped-brief"
            payload = {**_saved_brief(), "brief_id": brief_id}
            created = real_client.post(
                f"/api/v2/projects/{first}/briefs",
                json=payload,
            )
            assert created.status_code == 201

            crossed = real_client.post(
                f"/api/v2/projects/{second}/briefs",
                json=payload,
            )

            assert crossed.status_code == 409
            assert crossed.json() == {
                "error": {
                    "code": "project_scope_error",
                    "message": "资源不属于当前项目",
                }
            }
            assert brief_id not in crossed.text
            assert platform.storage.list_briefs(project_id=second) == []
    finally:
        platform.close()


def test_academic_routes_cover_research_and_evidence_workflow(client: TestClient) -> None:
    claim = {"id": "claim-1", "text": "数字工具提升了治理效能。"}
    comment = {
        "id": "comment-1",
        "category": "citation",
        "message": "补充来源页码",
    }
    cases: list[tuple[str, dict[str, object], str, str]] = [
        (
            "/api/v2/projects/proj-1/academic/literature/search",
            {"query": "digital governance", "provider": "crossref"},
            "yanzhang_search_literature",
            "SearchLiteratureRequest",
        ),
        (
            "/api/v2/projects/proj-1/academic/literature/import",
            {"content": "@article{a,title={Demo}}", "format": "bibtex"},
            "yanzhang_import_literature",
            "ImportLiteratureRequest",
        ),
        (
            "/api/v2/projects/proj-1/academic/evidence/extract",
            {"record_id": "ref-1", "text": "研究发现数字工具提升了办理效率。"},
            "yanzhang_extract_evidence",
            "ExtractEvidenceRequest",
        ),
        (
            "/api/v2/projects/proj-1/academic/matrix",
            {"record_ids": ["ref-1"]},
            "yanzhang_build_literature_matrix",
            "BuildLiteratureMatrixRequest",
        ),
        (
            "/api/v2/projects/proj-1/academic/citations/verify",
            {
                "record_ids": ["ref-1"],
                "evidence_ids": ["ev-1"],
                "claims": [claim],
            },
            "yanzhang_verify_citations",
            "VerifyCitationsRequest",
        ),
        (
            "/api/v2/projects/proj-1/academic/bibliography",
            {"record_ids": ["ref-1"], "style": "gb-t-7714"},
            "yanzhang_format_bibliography",
            "FormatBibliographyRequest",
        ),
        (
            "/api/v2/projects/proj-1/academic/titles",
            {**_academic_brief(), "count": 5},
            "yanzhang_suggest_academic_titles",
            "SuggestAcademicTitlesRequest",
        ),
        (
            "/api/v2/projects/proj-1/academic/outline",
            {**_academic_brief(), "record_ids": ["ref-1"], "evidence_ids": ["ev-1"]},
            "yanzhang_create_academic_outline",
            "CreateAcademicOutlineRequest",
        ),
        (
            "/api/v2/projects/proj-1/academic/abstract",
            {**_academic_brief(), "claims": [claim]},
            "yanzhang_draft_abstract",
            "DraftAbstractRequest",
        ),
        (
            "/api/v2/projects/proj-1/academic/integrity",
            {"manuscript": "数字工具提升了治理效能。", "claims": [claim]},
            "yanzhang_review_academic_integrity",
            "ReviewAcademicIntegrityRequest",
        ),
        (
            "/api/v2/projects/proj-1/academic/rebuttal",
            {"comments": [comment], "changes": {"comment-1": "已补充第3页。"}},
            "yanzhang_prepare_rebuttal",
            "PrepareRebuttalRequest",
        ),
    ]
    for path, body, operation, request_type in cases:
        response = client.post(path, json=body)
        _assert_forwarded(response, operation=operation, request_type=request_type)
        assert response.json()["request"]["project_id"] == "proj-1"

    record = client.get("/api/v2/projects/proj-1/academic/literature/ref-1?include_abstract=false")
    _assert_forwarded(
        record,
        operation="yanzhang_get_literature",
        request_type="GetLiteratureRequest",
    )
    assert record.json()["request"]["include_abstract"] is False

    read_cases = [
        (
            client.get(
                "/api/v2/projects/proj-1/academic/literature"
                "?query=digital&include_abstract=true&limit=5&offset=1"
            ),
            "yanzhang_list_literature",
            "ListLiteratureRequest",
        ),
        (
            client.get(
                "/api/v2/projects/proj-1/academic/evidence?record_id=ref-1&limit=5&offset=0"
            ),
            "yanzhang_list_evidence",
            "ListEvidenceRequest",
        ),
        (
            client.get("/api/v2/projects/proj-1/academic/evidence/ev-1"),
            "yanzhang_get_evidence",
            "GetEvidenceRequest",
        ),
        (
            client.get("/api/v2/projects/proj-1/academic/matrices?limit=5&offset=0"),
            "yanzhang_list_literature_matrices",
            "ListLiteratureMatricesRequest",
        ),
        (
            client.get("/api/v2/projects/proj-1/academic/matrices/matrix-1"),
            "yanzhang_get_literature_matrix",
            "GetLiteratureMatrixRequest",
        ),
        (
            client.get("/api/v2/projects/proj-1/academic/claims?limit=5&offset=0"),
            "yanzhang_list_research_claims",
            "ListResearchClaimsRequest",
        ),
        (
            client.get("/api/v2/projects/proj-1/academic/claims/claim-1"),
            "yanzhang_get_research_claim",
            "GetResearchClaimRequest",
        ),
        (
            client.get(
                "/api/v2/projects/proj-1/academic/citation-links"
                "?claim_id=claim-1&record_id=ref-1&evidence_id=ev-1"
            ),
            "yanzhang_list_citation_links",
            "ListCitationLinksRequest",
        ),
        (
            client.get("/api/v2/projects/proj-1/academic/citation-links/link-1"),
            "yanzhang_get_citation_link",
            "GetCitationLinkRequest",
        ),
    ]
    for response, operation, request_type in read_cases:
        _assert_forwarded(response, operation=operation, request_type=request_type)
        assert response.json()["request"]["project_id"] == "proj-1"


@pytest.mark.parametrize("mode,minimum_calls", [("merge", 1), ("blocks", 3)])
def test_base64_document_import_parses_then_persists_materials(
    client: TestClient,
    platform: _FakePlatform,
    mode: str,
    minimum_calls: int,
) -> None:
    markdown = "# 总体情况\n\n基层治理稳步推进。\n\n## 下一步\n\n持续提升服务效能。"
    encoded = base64.b64encode(markdown.encode()).decode()

    response = client.post(
        "/api/v2/projects/proj-import/materials/import",
        json={
            "filename": "治理调研.md",
            "media_type": "text/markdown",
            "data_base64": encoded,
            "mode": mode,
            "tags": ["调研"],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["mode"] == mode
    assert payload["document"]["block_count"] >= 3
    assert len(payload["items"]) >= minimum_calls
    recent = [call for call in platform.calls if call[0] == "yanzhang_add_material"]
    assert len(recent) >= minimum_calls
    assert all(command.model_dump()["project_id"] == "proj-import" for _, command in recent)


def test_export_artifact_download_is_project_scoped_with_legacy_compatibility(
    client: TestClient,
    tmp_path: Path,
) -> None:
    app = Starlette(routes=v2_routes())
    store = ArtifactStore(tmp_path / "artifacts")
    metadata = store.put(
        "成稿内容".encode(),
        filename="治理成稿.txt",
        mime=TEXT_MIME,
        project_id="project-one",
        asset_id="asset-one",
        revision_id="revision-one",
        creator="yanzhang_export_asset",
    )
    legacy = store.put("旧稿内容".encode(), filename="旧版.txt", mime=TEXT_MIME)
    app.state.yanzhang_platform = _FakePlatform()
    app.state.gongwen_artifact_store = store

    with TestClient(app) as artifact_client:
        response = artifact_client.get(
            f"/api/v2/projects/project-one/exports/{metadata.artifact_id}"
        )
        wrong_project = artifact_client.get(
            f"/api/v2/projects/project-two/exports/{metadata.artifact_id}"
        )
        flat_scoped = artifact_client.get(f"/api/v2/exports/{metadata.artifact_id}")
        flat_legacy = artifact_client.get(f"/api/v2/exports/{legacy.artifact_id}")

    assert response.status_code == 200
    assert response.content == "成稿内容".encode()
    assert response.headers["content-type"] == TEXT_MIME
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert wrong_project.status_code == 404
    assert wrong_project.json()["error"]["code"] == "artifact_not_found"
    assert flat_scoped.status_code == 404
    assert flat_scoped.json()["error"]["code"] == "artifact_not_found"
    assert flat_legacy.status_code == 200
    assert flat_legacy.content == "旧稿内容".encode()


def test_validation_identity_and_platform_errors_are_explicit_and_redacted(
    client: TestClient,
    platform: _FakePlatform,
) -> None:
    validation = client.post(
        "/api/v2/projects",
        json={"name": "", "api_key": "FIXTURE_PROVIDER_CREDENTIAL"},
    )
    assert validation.status_code == 422
    assert validation.json()["error"]["code"] == "validation_error"
    assert "FIXTURE_PROVIDER_CREDENTIAL" not in validation.text
    assert validation.headers["cache-control"] == "no-store"

    mismatch = client.post(
        "/api/v2/projects/proj-1/materials",
        json={
            "project_id": "proj-other",
            "title": "材料",
            "content": "内容",
        },
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "identity_mismatch"

    platform.fail_operation = "yanzhang_get_project"
    failed = client.get("/api/v2/projects/proj-secret")
    assert failed.status_code == 500
    assert failed.json()["error"]["code"] == "internal_error"
    assert "FIXTURE_PROVIDER_CREDENTIAL" not in failed.text


def test_json_and_import_limits_fail_before_platform_dispatch(
    platform: _FakePlatform,
    tmp_path: Path,
) -> None:
    app = Starlette(routes=v2_routes())
    app.state.yanzhang_platform = platform
    app.state.gongwen_artifact_store = ArtifactStore(tmp_path)
    app.state.gongwen_runtime = type("Runtime", (), {"max_request_bytes": 128})()

    with TestClient(app) as limited:
        oversized = limited.post(
            "/api/v2/projects",
            content=b"{" + b'"name":"' + (b"x" * 200) + b'"}',
            headers={"content-type": "application/json"},
        )
        malformed = limited.post(
            "/api/v2/projects",
            content=b"{bad-json",
            headers={"content-type": "application/json"},
        )
        invalid_base64 = limited.post(
            "/api/v2/projects/proj-1/materials/import",
            json={"filename": "demo.txt", "content_base64": "%%%"},
        )

    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "request_too_large"
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "invalid_json"
    assert invalid_base64.status_code == 422
    assert invalid_base64.json()["error"]["code"] == "invalid_base64"
    assert platform.calls == []


def test_aliases_are_strict_and_brief_alias_is_backed_by_persistence(client: TestClient) -> None:
    search = client.get("/api/v2/knowledge/search?project_id=proj-1&query=治理")
    _assert_forwarded(
        search,
        operation="yanzhang_search",
        request_type="UnifiedSearchRequest",
    )

    headline = client.post(
        "/api/v2/headlines/generate",
        json={**_brief(), "project_id": "proj-1"},
    )
    _assert_forwarded(
        headline,
        operation="yanzhang_generate_titles",
        request_type="GenerateTitlesRequest",
    )

    missing_project = client.get("/api/v2/assets")
    assert missing_project.status_code == 422
    assert missing_project.json()["error"]["code"] == "validation_error"

    brief = client.post(
        "/api/v2/writing/briefs",
        json={**_saved_brief(), "project_id": "proj-1"},
    )
    _assert_forwarded(brief, operation="create_brief", request_type="CreateBriefRequest")


def test_missing_platform_and_artifact_are_stable_failures(tmp_path: Path) -> None:
    app = Starlette(routes=v2_routes())
    app.state.gongwen_artifact_store = ArtifactStore(tmp_path)
    with TestClient(app) as bare_client:
        platform = bare_client.get("/api/v2/bootstrap")
        artifact = bare_client.get("/api/v2/exports/not-an-artifact-id")

    assert platform.status_code == 503
    assert platform.json()["error"]["code"] == "platform_unavailable"
    assert artifact.status_code == 404
    assert artifact.json()["error"]["code"] == "artifact_not_found"
