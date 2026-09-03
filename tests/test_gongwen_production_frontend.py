"""Static contract checks for the deployable browser authentication flow."""

from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).parents[1] / "gongwen_web" / "static"


def test_access_gate_is_present_and_uses_session_storage() -> None:
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    script = (_STATIC / "app.js").read_text(encoding="utf-8")

    assert 'id="accessModal"' in html
    assert 'id="accessToken"' in html
    assert 'id="unlockAppButton"' in html
    assert "sessionStorage.setItem(ACCESS_TOKEN_KEY" in script
    assert "sessionStorage.removeItem(ACCESS_TOKEN_KEY" in script
    assert "localStorage.setItem(ACCESS_TOKEN_KEY" not in script
    assert "headers.Authorization = `Bearer ${sessionAccessToken}`" in script


def test_every_download_request_uses_authenticated_headers() -> None:
    script = (_STATIC / "app.js").read_text(encoding="utf-8")

    assert 'fetch("/api/export/docx", { method: "POST", headers: requestHeaders(' in script
    assert 'fetch("/api/export/batch-docx", { method: "POST", headers: requestHeaders(' in script


def test_server_model_configuration_has_a_secret_free_ui_state() -> None:
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    script = (_STATIC / "app.js").read_text(encoding="utf-8")

    assert 'id="serverProviderCard"' in html
    assert "data.model?.server_provider_configured" in script
    assert "data.model?.provider_name" in script
    assert "data.model?.default_model" in script
    assert "serverProvider.configured && serverProvider.providerName" not in script
