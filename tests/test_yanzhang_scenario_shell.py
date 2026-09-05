"""Presentation contracts for the single-context writing workspace."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

_STATIC = Path(__file__).parents[1] / "gongwen_web" / "static"


class _ShellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.attrs_by_id: dict[str, dict[str, str | None]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        element_id = values.get("id")
        if element_id:
            self.ids.append(element_id)
            self.attrs_by_id[element_id] = values


def _html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def test_scenario_has_one_prominent_selector_and_explicit_linkage() -> None:
    html = _html()
    parser = _ShellParser()
    parser.feed(html)
    assert len(parser.ids) == len(set(parser.ids))
    assert parser.ids.count("briefScenarioPack") == 1
    assert html.index('id="scenarioOverview"') < html.index('id="briefScenarioPack"')
    assert html.index('id="briefScenarioPack"') < html.index('id="briefCard"')
    for element_id in ("scenarioName", "scenarioDescription", "scenarioCapabilities"):
        assert element_id in parser.ids
    assert parser.attrs_by_id["briefScenarioPack"]["aria-describedby"] == "scenarioDescription"
    assert "配方、表达方法、语气、参考资料与审校标准" in html
    assert "open" not in parser.attrs_by_id["briefAdvancedSettings"]


def test_writing_controls_allow_full_scenario_rendering() -> None:
    html = _html()
    parser = _ShellParser()
    parser.feed(html)
    for element_id in (
        "topicLabel",
        "purposeLabel",
        "audienceLabel",
        "materialsLabel",
        "requirementsLabel",
        "keywordsLabel",
        "referenceStyleLabel",
        "referenceStyleDescription",
        "materialSectionLabel",
        "generateButtonLabel",
    ):
        assert element_id in parser.ids
    selector = html.split('id="referenceStyle"', 1)[1].split("</select>", 1)[0]
    assert "正在载入当前场景的表达方法" in selector
    for newspaper in ("人民日报", "光明日报", "求是"):
        assert newspaper not in selector
    tones = html.split('id="toneSelector"', 1)[1].split("</div>", 1)[0]
    assert 'type="radio"' not in tones
    assert "生成公文初稿" not in html
    assert 'aria-label="公文标题"' not in html
    assert html.index("/static/scenario_catalog.js") < html.index("/static/scenario_workspace.js")
    assert html.index("/static/scenario_workspace.js") < html.index("/static/workspace_context.js")


def test_references_and_review_have_separate_scene_specific_slots() -> None:
    html = _html()
    parser = _ShellParser()
    parser.feed(html)
    for element_id in (
        "referencePickerTitle",
        "referencePickerDescription",
        "sceneReferenceActions",
        "openArticleLibraryButton",
        "openProjectMaterialsButton",
        "openAcademicReferencesButton",
        "selectedReferences",
        "sceneEvidenceNote",
        *(f"checklistLabel{index}" for index in range(6)),
    ):
        assert element_id in parser.ids
    assert "写作风格和媒体文章不替代学术证据" in html
    assert "hidden" in parser.attrs_by_id["sceneEvidenceNote"]
    checklist = html.split('<details class="checklist"', 1)[1].split("</details>", 1)[0]
    assert checklist.count('type="checkbox"') == 6
    assert "文种和行文关系正确" not in checklist


def test_scene_styles_are_readable_and_do_not_mask_hidden_controls() -> None:
    styles = (_STATIC / "styles.css").read_text(encoding="utf-8")
    scene_styles = styles.split("/* Scenario workspace:", 1)[1]
    for scene in ("workplace", "media", "academic"):
        assert f'.scenario-overview[data-scenario="{scene}"]' in scene_styles
    assert "--scene-accent:" in scene_styles
    assert ".scene-reference-action[hidden]" in scene_styles
    assert ".scene-evidence-note[hidden]" in scene_styles
    assert "overflow-wrap: anywhere;" in scene_styles
    phone_styles = scene_styles.split("@media (max-width: 760px)", 1)[1]
    assert "font-size: 16px;" in phone_styles
    assert "min-height: 40px;" in phone_styles
    assert "@media print" in scene_styles
