"""Small-screen and execution-mode presentation contracts."""

from pathlib import Path

_STYLES = Path(__file__).parents[1] / "gongwen_web" / "static" / "styles.css"


def _clarity_styles() -> str:
    styles = _STYLES.read_text(encoding="utf-8")
    return styles.split("/* Workspace clarity:", 1)[1]


def test_header_grows_with_visible_execution_explanation() -> None:
    styles = _clarity_styles()
    assert "grid-template-rows: auto minmax(0, 1fr)" in styles
    assert ".engine-banner {" in styles
    assert "grid-row: 3;" in styles
    for selector in (
        ".engine-banner-copy",
        ".engine-banner-title",
        ".engine-banner-detail",
        ".engine-banner-action",
        ".engine-explanation",
        ".document-execution",
        ".engine-tag",
        ".service-retry-button",
    ):
        assert selector in styles
    assert "overflow-wrap: anywhere;" in styles


def test_phone_navigation_and_project_picker_have_distinct_rows() -> None:
    styles = _clarity_styles().split("@media (max-width: 760px)", 1)[1]
    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in styles
    assert "grid-template-rows: 36px 36px 38px;" in styles
    project_picker = styles.split(".project-switcher {", 1)[1].split("}", 1)[0]
    assert "grid-column: 1 / -1;" in project_picker
    assert "grid-row: 3;" in project_picker
    assert "min-width: 0;" in project_picker
    assert "max-width: none;" in project_picker


def test_phone_brief_has_readable_controls_and_short_content_wraps() -> None:
    styles = _clarity_styles().split("@media (max-width: 760px)", 1)[1]
    assert ".brief-fields .form-row.split {" in styles
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in styles
    assert ".field textarea {\n    font-size: 16px;" in styles
    assert ".brief-action-buttons .primary-button.compact {" in styles
    assert "min-height: 40px;" in styles
    assert "white-space: normal;" in styles
    assert "@media (max-width: 360px)" in styles
