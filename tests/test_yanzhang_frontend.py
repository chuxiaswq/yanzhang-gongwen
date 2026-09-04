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
