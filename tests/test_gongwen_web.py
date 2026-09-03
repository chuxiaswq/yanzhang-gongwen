"""Offline acceptance tests for the personal official-document web demo."""

# ruff: noqa: RUF001 -- Chinese official-document punctuation is intentional test data.

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree

import pytest
from starlette.testclient import TestClient

from gongwen_web.app import create_app
from gongwen_web.docx import build_batch_zip, render_fields, unique_filename
from gongwen_web.models import BatchExportRequest, ExportDocument
from gongwen_web.storage import GongwenStorage

_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_REQUIRED_DOCX_PARTS = {
    "[Content_Types].xml",
    "_rels/.rels",
    "docProps/core.xml",
    "docProps/app.xml",
    "word/document.xml",
    "word/styles.xml",
    "word/settings.xml",
    "word/_rels/document.xml.rels",
}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """Serve a fresh local app; all requests below explicitly use demo mode."""

    storage = GongwenStorage(tmp_path / "gongwen.sqlite3")
    with TestClient(create_app(storage=storage)) as test_client:
        yield test_client


def _inspect_docx(payload: bytes) -> tuple[set[str], str]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        assert _REQUIRED_DOCX_PARTS <= names
        for name in names:
            if name.endswith((".xml", ".rels")):
                ElementTree.fromstring(archive.read(name))
        document_xml = archive.read("word/document.xml").decode("utf-8")
    return names, document_xml


def test_homepage_and_bootstrap_are_available_without_setup(client: TestClient) -> None:
    homepage = client.get("/")
    assert homepage.status_code == 200
    assert homepage.headers["content-type"].startswith("text/html")
    assert "砚章" in homepage.text
    assert "公文写作工作台" in homepage.text
    assert 'href="/static/styles.css"' in homepage.text
    assert 'src="/static/app.js"' in homepage.text

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {
        "ok": True,
        "service": "gongwen-web",
        "mode": "single-user",
    }

    response = client.get("/api/bootstrap")
    assert response.status_code == 200
    bootstrap = response.json()
    assert bootstrap["app_name"] == "砚章"
    assert {"通知", "请示", "报告", "工作总结", "实施方案", "讲话稿"} <= set(
        bootstrap["document_types"]
    )
    assert bootstrap["demo_input"]["topic"]
    assert bootstrap["capabilities"] == {
        "demo_generation": True,
        "live_provider": True,
        "review": True,
        "docx": True,
        "merge_fields": True,
        "batch_zip": True,
        "server_persistence": True,
        "document_versions": True,
        "article_library": True,
        "automatic_article_discovery": True,
        "people_auto_discovery": False,
        "title_workbench": True,
        "content_methodologies": True,
        "advanced_fact_audit": True,
        "provider_probe": True,
    }


def test_people_auto_collection_is_server_blocked_by_default_without_query_echo(
    client: TestClient,
) -> None:
    keyword = "只用于验证响应不会回显的检索条件"

    response = client.post(
        "/api/articles/auto-collect",
        json={"keywords": [keyword], "source_ids": ["people"], "limit": 5},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["source_error_count"] == 1
    assert result["source_errors"][0]["reason_code"] == "insecure_transport_disabled"
    message = result["source_errors"][0]["message"]
    assert "GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH=true" in message
    assert "明文传输" in message
    assert keyword not in message


def test_generate_returns_repeatable_unwrapped_demo_document(client: TestClient) -> None:
    request = {
        "document_type": "通知",
        "topic": "基层治理数字化提升",
        "purpose": "统一工作安排并明确责任分工",
        "audience": "各有关单位",
        "materials": "已完成6个服务事项整合。平均办理时长缩短31%。",
        "requirements": "明确节点，压实责任。",
        "tone": "严谨规范",
        "length": "标准",
        "live": False,
    }

    first = client.post("/api/generate", json=request)
    second = client.post("/api/generate", json=request)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()

    document = first.json()
    # The endpoint intentionally returns the model itself, not a {"data": ...} envelope.
    assert "data" not in document
    assert document["title"] == "关于基层治理数字化提升的通知"
    assert document["meta"]["mode"] == "demo"
    assert len(document["title_candidates"]) >= 3
    assert document["title_candidates"][0]["selected"] is True
    assert [item["heading"] for item in document["outline"]] == [
        "一、明确总体要求",
        "二、聚焦重点任务",
        "三、强化组织保障",
    ]
    assert document["facts"] == [
        "已完成6个服务事项整合。",
        "平均办理时长缩短31%。",
    ]
    assert document["source_cards"][0]["source_type"] == "用户材料"
    assert document["content"].startswith("各有关单位：")
    assert "请结合实际认真抓好贯彻落实。" in document["content"]


def test_rewrite_and_review_are_repeatable_in_demo_mode(client: TestClient) -> None:
    rewrite_request = {
        "text": "我们马上把这项工作搞好，确保做到位。",
        "instruction": "提升表达的规范性和准确性",
        "mode": "polish",
        "tone": "严谨规范",
        "live": False,
    }
    rewritten_once = client.post("/api/rewrite", json=rewrite_request)
    rewritten_twice = client.post("/api/rewrite", json=rewrite_request)
    assert rewritten_once.status_code == rewritten_twice.status_code == 200
    assert rewritten_once.json() == rewritten_twice.json()
    rewrite = rewritten_once.json()
    assert rewrite["text"] == "本单位及时把这项工作切实做好，确保落实到位。"
    assert rewrite["changes"]
    assert rewrite["meta"]["mode"] == "demo"

    review_request = {
        "title": "关于推进重点工作的通知",
        "document_type": "通知",
        "content": (
            "一、工作安排\n"
            "请有关单位于【完成日期】前进一步做好任务分解。\n"
            "二、落实要求\n"
            "建立责任清单，加强过程调度，确保各项工作落实到位。"
        ),
        "live": False,
    }
    reviewed_once = client.post("/api/review", json=review_request)
    reviewed_twice = client.post("/api/review", json=review_request)
    assert reviewed_once.status_code == reviewed_twice.status_code == 200
    assert reviewed_once.json() == reviewed_twice.json()
    review = reviewed_once.json()
    assert 0 <= review["score"] < 100
    assert review["metrics"]["heading_count"] == 2
    assert review["metrics"]["placeholder_count"] == 1
    assert review["metrics"]["vague_expression_count"] >= 2
    assert any(
        issue["level"] == "error" and issue["category"] == "待补信息" for issue in review["issues"]
    )
    assert review["meta"]["mode"] == "demo"


def test_docx_export_is_a_valid_deterministic_ooxml_package(client: TestClient) -> None:
    request = {
        "title": "关于开展专项工作的通知",
        "content": "各有关单位：\n\n一、总体要求\n请{{责任单位}}扎实推进专项工作。",
        "metadata": {
            "doc_number": "示发〔2026〕3号",
            "issuing_org": "示例单位",
            "issue_date": "2026年9月3日",
        },
        "filename": "专项工作通知.docx",
    }
    first = client.post("/api/export/docx", json=request)
    second = client.post("/api/export/docx", json=request)
    assert first.status_code == second.status_code == 200
    assert first.headers["content-type"] == _DOCX_CONTENT_TYPE
    assert "attachment" in first.headers["content-disposition"]
    assert first.content == second.content

    _, document_xml = _inspect_docx(first.content)
    assert "关于开展专项工作的通知" in document_xml
    assert "示发〔2026〕3号" in document_xml
    assert "一、总体要求" in document_xml
    assert "示例单位" in document_xml
    assert "MERGEFIELD" in document_xml
    assert "责任单位" in document_xml
    assert 'w:fldCharType="begin"' in document_xml
    assert 'w:fldCharType="end"' in document_xml

    control_character = client.post(
        "/api/export/docx",
        json={"title": "控制字符", "content": "正文\u000b仍可打开。"},
    )
    assert control_character.status_code == 200
    _inspect_docx(control_character.content)


def test_batch_export_merges_rows_into_individual_docx_files(client: TestClient) -> None:
    request = {
        "template": {
            "title": "关于{{TOPIC}}的通知",
            "content": "{{UNIT}}：\n\n一、工作要求\n请于{{DATE}}前完成{{TOPIC}}。",
            "metadata": {"issuing_org": "{{ISSUER}}"},
        },
        "rows": [
            {
                "UNIT": "甲单位",
                "TOPIC": "材料报送",
                "DATE": "9月10日",
                "ISSUER": "综合处",
                "filename": "甲单位通知.docx",
            },
            {
                "UNIT": "乙单位",
                "TOPIC": "情况核验",
                "DATE": "9月12日",
                "ISSUER": "办公室",
                "filename": "乙单位通知.docx",
            },
        ],
        "filename": "批量通知.zip",
    }
    response = client.post("/api/export/batch-docx", json=request)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(response.content)) as outer:
        assert outer.testzip() is None
        docx_names = sorted(name for name in outer.namelist() if name.endswith(".docx"))
        assert docx_names == ["乙单位通知.docx", "甲单位通知.docx"]
        assert "生成清单.txt" in outer.namelist()
        manifest = outer.read("生成清单.txt").decode("utf-8")
        assert all(name in manifest for name in docx_names)
        inner_documents = {name: _inspect_docx(outer.read(name))[1] for name in docx_names}

    assert "甲单位" in inner_documents["甲单位通知.docx"]
    assert "材料报送" in inner_documents["甲单位通知.docx"]
    assert "9月10日" in inner_documents["甲单位通知.docx"]
    assert "综合处" in inner_documents["甲单位通知.docx"]
    assert "乙单位" in inner_documents["乙单位通知.docx"]
    assert "情况核验" in inner_documents["乙单位通知.docx"]
    assert all("{{" not in document for document in inner_documents.values())


def test_batch_fields_are_normalized_and_replaced_only_once(client: TestClient) -> None:
    assert (
        render_fields("{{  UNIT  }} / {{NEXT}}", {"UNIT": "{{NEXT}}", "NEXT": "最终值"})
        == "{{NEXT}} / 最终值"
    )

    response = client.post(
        "/api/export/batch-docx",
        json={
            "template": {
                "title": "{{  UNIT  }}工作安排",
                "content": "请{{ UNIT }}核对。",
                "metadata": {
                    "issuing_org": "{{ISSUER}}",
                    "issue_date": "2026年9月3日",
                },
            },
            "rows": [{"UNIT": "甲单位", "ISSUER": "综合处"}],
        },
    )
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as outer:
        docx_name = next(name for name in outer.namelist() if name.endswith(".docx"))
        _, document_xml = _inspect_docx(outer.read(docx_name))
    assert "甲单位工作安排" in document_xml
    assert "综合处" in document_xml
    assert "2026年9月3日" in document_xml
    assert "MERGEFIELD" not in document_xml

    with pytest.raises(ValueError, match="DOC_TITLE"):
        build_batch_zip(
            BatchExportRequest(
                template=ExportDocument(
                    title="固定标题",
                    content="正文标题：{{DOC_TITLE}}",
                ),
                rows=[{}],
            )
        )

    assert unique_filename("示例.docx", {"示例.DOCX"}, suffix=".docx") == "示例-2.docx"


def test_api_reports_structured_input_errors_and_sanitizes_download_names(
    client: TestClient,
) -> None:
    malformed = client.post(
        "/api/generate",
        content=b"{not-json",
        headers={"content-type": "application/json"},
    )
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "invalid_json"

    missing_topic = client.post("/api/generate", json={"document_type": "通知"})
    assert missing_topic.status_code == 422
    error = missing_topic.json()["error"]
    assert error["code"] == "invalid_request"
    assert any(item["field"] == "topic" for item in error["details"])

    unknown_provider = client.post(
        "/api/generate",
        json={
            "topic": "连接测试",
            "live": True,
            "provider": {"name": "missing-provider", "api_key": "DO_NOT_ECHO"},
        },
    )
    assert unknown_provider.status_code == 400
    provider_error = unknown_provider.json()["error"]
    assert provider_error["code"] == "provider_configuration_error"
    assert "DO_NOT_ECHO" not in unknown_provider.text

    empty_batch = client.post("/api/export/batch-docx", json={"rows": []})
    assert empty_batch.status_code == 400
    assert empty_batch.json()["error"]["code"] == "invalid_request"

    missing_batch_field = client.post(
        "/api/export/batch-docx",
        json={
            "template": {"title": "{{单位}}", "content": "请于{{日期}}前完成。"},
            "rows": [{"单位": "甲单位"}],
        },
    )
    assert missing_batch_field.status_code == 400
    assert "日期" in missing_batch_field.json()["error"]["message"]

    sanitized = client.post(
        "/api/export/docx",
        json={
            "title": "下载测试",
            "content": "用于验证文件名处理。",
            "filename": "../../outside.docx",
        },
    )
    assert sanitized.status_code == 200
    disposition = sanitized.headers["content-disposition"]
    assert ".." not in disposition
    assert "%2F" not in disposition.upper()
    _inspect_docx(sanitized.content)
