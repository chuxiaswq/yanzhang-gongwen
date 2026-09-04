"""Static contracts for the Phase 2 AI writing workspace."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

_STATIC = Path(__file__).parents[1] / "gongwen_web" / "static"


class _AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.remote_assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(str(values["id"]))
        for key in ("src", "href"):
            value = values.get(key) or ""
            if value.startswith(("http://", "https://", "//")):
                self.remote_assets.append(value)


def _sources() -> tuple[str, str, str]:
    return tuple(
        (_STATIC / filename).read_text(encoding="utf-8")
        for filename in ("index.html", "app.js", "styles.css")
    )  # type: ignore[return-value]


def test_phase2_navigation_and_product_name_are_present() -> None:
    html, _, _ = _sources()

    assert "砚章 · AI文字工作台" in html
    assert "公文写作工作台" in html
    routes = re.findall(r'data-suite-view="([^"]+)"', html)
    assert routes == [
        "home",
        "projects",
        "knowledge",
        "recipes",
        "review",
        "delivery",
        "academic",
        "settings",
    ]
    for label in ("首页", "项目", "素材库", "写作配方", "审校中心", "交付中心", "学术研究", "设置"):
        assert f"<span>{label}</span>" in html


def test_new_workspaces_keep_legacy_controls_and_unique_ids() -> None:
    html, _, _ = _sources()
    parser = _AssetParser()
    parser.feed(html)

    assert len(parser.ids) == len(set(parser.ids))
    for element_id in (
        "writingForm",
        "generateButton",
        "documentEditor",
        "reviewButton",
        "exportDocxButton",
        "accessModal",
        "briefCard",
        "expressionLab",
        "variantStudio",
        "academicRecords",
        "academicMatrixBody",
        "academicClaimLinks",
        "academicRebuttalOutput",
        "academicIntegrityResult",
        "academicIntegrityStatus",
        "academicIntegritySummary",
        "projectSelect",
        "projectModal",
        "briefScenarioPack",
        "briefRecipe",
        "runProjectWorkflowButton",
        "addProjectMaterialButton",
        "localDraftMode",
        "clearAllLocalDataButton",
    ):
        assert element_id in parser.ids


def test_phase2_progressive_api_contracts_are_wired() -> None:
    _, script, _ = _sources()

    for endpoint in (
        "/api/v2/bootstrap",
        "/api/v2/projects?limit=100&offset=0",
        "/briefs`",
        "/materials`",
        "/headlines`",
        "/workflows`",
        "/assets?limit=${limit}&offset=${offset}",
        "/variants`",
        "/revisions`",
        "/review`",
        "/export`",
        "/exports/${encodeURIComponent(artifactId)}",
        "/api/v2/workflow-definitions",
        "/academic/literature/import`",
        "/academic/matrix`",
        "/academic/evidence/extract`",
        "/academic/citations/verify`",
        "/academic/bibliography`",
        "/academic/integrity`",
        "/academic/rebuttal`",
    ):
        assert endpoint in script

    assert "target_channel: channel" in script
    assert "record_ids:" in script
    assert "evidence_ids:" in script
    assert "validAcademicLinks" in script
    assert 'channel: "document"' in script
    assert "serverGenerationBriefPayload" in script
    assert "phase2State.local_draft_mode !== false" in script
    assert (
        "/api/v2/projects/${encodeURIComponent(projectId)}/workflows/"
        "${encodeURIComponent(workflow.id)}/run"
    ) in script
    assert (
        "/api/v2/projects/${encodeURIComponent(projectId)}/exports/"
        "${encodeURIComponent(artifactId)}"
    ) in script
    assert "projectRequestController.abort" in script
    assert 'readAcademicProjectCollection(projectId, "literature"' in script
    assert 'readAcademicProjectCollection(projectId, "evidence")' in script
    assert 'readAcademicProjectCollection(projectId, "matrices")' in script
    assert 'readAcademicProjectCollection(projectId, "claims")' in script
    assert 'readAcademicProjectCollection(projectId, "citation-links")' in script
    assert "isAbstract ? `${academicBase}/abstract` : `${academicBase}/outline`" in script


def test_expression_contract_and_full_local_data_reset_are_explicit() -> None:
    html, script, _ = _sources()

    assert re.findall(r'data-expression-focus="([^"]+)"', html) == [
        "title",
        "opening",
        "section_heading",
        "topic_sentence",
    ]
    assert "headline_kind: focus" in script
    assert "[STORAGE_KEY, SETTINGS_KEY, HISTORY_KEY, PHASE2_KEY]" in script
    assert script.count("window.confirm(") >= 3
    assert "clearAccessToken();" in script
    assert "学术完整性当前为本地预览结果" in script
    assert "修订服务没有返回有效版本" in script


def test_brief_and_fact_card_copy_are_unambiguous() -> None:
    html, script, styles = _sources()

    assert 'id="briefDeadline" type="text"' in html
    assert 'placeholder="YYYY-MM-DD"' in html
    assert "&#x20;" not in html
    assert "日期、关键词和约束均为选填项" in html
    assert 'title="统计主题、写作目的、阅读对象、内容形态、首要渠道和写作配方"' in html
    assert 'isComplete ? "核心要素已齐" : `待补 ${missingFields.length} 项`' in script
    assert 'dates: "时间", numbers: "数字", organizations: "机构", tasks: "任务"' in script
    assert "icon.textContent = labels[key][1]" not in script
    assert 'head.className = "fact-group-heading"' in script
    assert 'list.className = "fact-values"' in script
    assert "normalizeGeneratedPunctuation(appState.document.html)" in script
    assert "normalizeGeneratedPunctuation(item.content)" in script
    assert ".fact-group-heading" in styles
    assert ".fact-group-marker" in styles


def test_response_semantics_and_stale_input_guards_are_wired() -> None:
    html, script, _ = _sources()

    assert html.index("/static/response_validators.js") < html.index("/static/app.js")
    for contract in (
        "validateCitationAudit",
        "validateIntegrityReview",
        "validateProjectReviewEnvelope",
        "captureInputOperation",
        "inputOperationIsStale",
        "currentBriefBindingHash",
        "payload_hash",
        "invalidateSavedBriefBinding",
    ):
        assert contract in script
    assert "if (inputOperationIsStale(inputOperation)) return;" in script
    assert "if (inputOperationIsStale(inputOperation)) return null;" in script


def test_task_context_is_atomic_and_marks_retained_drafts_stale() -> None:
    html, script, styles = _sources()

    assert html.index("/static/workspace_context.js") < html.index("/static/app.js")
    assert 'id="documentContextStatus"' in html
    assert 'id="documentType" name="document_type" disabled' in html
    for contract in (
        'reconcileTaskContext("content_type")',
        'reconcileTaskContext("scenario_pack")',
        'reconcileTaskContext("recipe")',
        'reconcileTaskContext("academic_task")',
        'reconcileTaskContext("document_type")',
        'reconcileTaskContext("restore", { invalidate: false',
        "ensureDocumentTypeOption(context.documentType)",
        "phase2State.document_stale = hasRetainedDraft",
        'phase2State.document_stale ? "上一版草稿 · 待重生成" : "草稿"',
        "phase2State.output_binding_hash = currentBriefBindingHash()",
        "methodologyCatalogReady",
        (
            "phase2State.document_stale = Boolean(els.documentTitle.value.trim() "
            "|| documentPlainText())"
        ),
    ):
        assert contract in script
    assert "event?.target === els.documentTitle" in script
    assert "phase2State.selected_title = appState.document.title" in script
    assert "selectedId === recipeMethodology.id) return []" in script
    assert "function generationMethodologyPayload()" in script
    assert 'if (els.contentMethodology.value !== "custom") return null;' in script
    assert 'form.content_methodology_id === "custom"' in script
    assert "els.customMethodologyDetails.open = Boolean(savedCustomMethod)" in script
    assert "syncProjectAssets(" in script
    assert "outputAssetId," in script
    assert "inputOperation," in script
    assert "if (responseIsStale()) return null;" in script
    assert "本次文件未导入" in script
    assert (
        "phase2State.project_id && (phase2State.master_asset_id || documentPlainText()) "
        "&& !phase2State.output_binding_hash"
    ) in script
    assert "phase2State.output_binding_hash = currentBriefBindingHash();\n    }" not in script
    assert "workspaceContext.resolveWorkspaceContext" in script
    assert "workspaceContext.resolveStandaloneDocumentContext" in script
    assert "phase2State.standalone_document = true" in script
    assert "selected_title: phase2State.selected_title" in script
    assert ".document-workspace.has-stale-context" in styles


def test_frontend_async_results_keep_their_project_and_document_binding() -> None:
    _, script, _ = _sources()

    for contract in (
        "briefBindingHash: currentBriefBindingHash()",
        "workspaceContext.operationMatches",
        "workspaceContext.assetMatchesBinding",
        "expectedBriefId",
        "inputOperationIsStale(workflowInputOperation, error)",
        "workspaceContext.documentSaveResponseMatches",
        'String(phase2State.master_asset_id || "") !== operation.assetId',
        "workspaceContext.catalogRequestMatches",
        "invalidateMethodologyCatalogRequest()",
        "openStandaloneDocumentState",
        "standalone_document: true",
        '"独立文稿 · 未关联项目"',
    ):
        assert contract in script


def test_workflow_material_sync_reuses_project_scoped_slots() -> None:
    _, script, _ = _sources()

    assert 'workflowManagedMaterialId(projectId, "source", "primary-material")' in script
    assert "workflowStyleReferenceSourceKey(reference, index)" in script
    assert "return `article-id:${referenceId}`" in script
    assert 'workflowManagedMaterialId(projectId, "source", primary)' not in script
    assert (
        "!/^workspace-(?:source|style)-/.test(String(id)) "
        "&& !/^local-material-workspace-(?:source|style)-/.test(String(id))"
    ) in script


def test_frontend_has_no_remote_runtime_assets_and_has_responsive_styles() -> None:
    html, _, styles = _sources()
    parser = _AssetParser()
    parser.feed(html)

    assert parser.remote_assets == []
    for selector in (
        ".suite-nav",
        ".home-hero",
        ".universal-brief",
        ".expression-lab",
        ".variant-studio",
        ".academic-workspace",
        ".academic-module",
        ".academic-integrity-result",
        ".academic-placeholder-note",
    ):
        assert selector in styles
    assert "@media (max-width: 1080px)" in styles
    assert "@media (max-width: 760px)" in styles
