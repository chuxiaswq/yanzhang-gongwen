"""Offline regression tests for production resource boundaries."""

# Chinese official-document test data intentionally uses full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import importlib
import threading
from pathlib import Path

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from gongwen_web.docx import build_batch_zip
from gongwen_web.fact_audit import audit_document, extract_material_facts
from gongwen_web.models import BatchExportRequest, ExportDocument, FactAuditRequest
from gongwen_web.resource_limits import (
    MAX_FACT_AUDIT_CLAIMS,
    MAX_FACT_AUDIT_CONTENT_CHARACTERS,
    MAX_FACT_AUDIT_CONTEXT_CHARACTERS,
    MAX_FACT_AUDIT_FACTS,
    MAX_FACT_AUDIT_MATERIAL_CHARACTERS,
    MAX_FACT_AUDIT_MATERIAL_ITEM_CHARACTERS,
    MAX_FACT_AUDIT_MATERIAL_ITEMS,
    MAX_FACT_AUDIT_MATERIAL_SENTENCES,
    MAX_FACT_AUDIT_MENTIONS_PER_SENTENCE,
    MAX_FACT_AUDIT_SENTENCE_CHARACTERS,
    MAX_FACT_AUDIT_SENTENCES,
    MAX_FACT_AUDIT_TITLE_CHARACTERS,
    MAX_FACT_AUDIT_TOTAL_CHARACTERS,
)
from gongwen_web.storage import GongwenStorage


def test_fact_audit_request_accepts_exact_combined_character_budget() -> None:
    content = "正" * MAX_FACT_AUDIT_CONTENT_CHARACTERS
    material_length = MAX_FACT_AUDIT_TOTAL_CHARACTERS - len(content)
    request = FactAuditRequest(
        title="工作情况",
        content=content,
        materials=["材" * (material_length // 2), "料" * (material_length // 2)],
    )

    assert len(request.content) + sum(len(item) for item in request.materials) == (
        MAX_FACT_AUDIT_TOTAL_CHARACTERS
    )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"content": "正" * (MAX_FACT_AUDIT_CONTENT_CHARACTERS + 1)},
            "String should have at most",
        ),
        (
            {
                "content": "正文",
                "materials": ["材料"] * (MAX_FACT_AUDIT_MATERIAL_ITEMS + 1),
            },
            "参考材料最多",
        ),
        (
            {
                "content": "正文",
                "materials": "材" * (MAX_FACT_AUDIT_MATERIAL_ITEM_CHARACTERS + 1),
            },
            "单项参考材料最多",
        ),
        (
            {
                "content": "正文",
                "materials": [
                    "甲" * 20_000,
                    "乙" * 20_000,
                    "丙" * (MAX_FACT_AUDIT_MATERIAL_CHARACTERS - 40_000 + 1),
                ],
            },
            "参考材料合计最多",
        ),
        (
            {
                "content": "正" * MAX_FACT_AUDIT_CONTENT_CHARACTERS,
                "materials": ["甲" * 15_001, "乙" * 15_000],
            },
            "正文和参考材料合计最多",
        ),
    ],
)
def test_fact_audit_request_rejects_oversized_inputs(
    payload: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        FactAuditRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("content", "materials", "message"),
    [
        (
            "长" * (MAX_FACT_AUDIT_SENTENCE_CHARACTERS + 1),
            "",
            "单句最多",
        ),
        (
            "说明。" * (MAX_FACT_AUDIT_SENTENCES + 1),
            "",
            "正文句子最多",
        ),
        (
            "正文。",
            "说明。" * (MAX_FACT_AUDIT_MATERIAL_SENTENCES + 1),
            "参考材料句子最多",
        ),
        (
            "正文。",
            "指标为100项。" * (MAX_FACT_AUDIT_FACTS + 1),
            "参考材料最多识别",
        ),
        (
            "甲指标100项，乙指标200项。" * (MAX_FACT_AUDIT_CLAIMS // 2 + 1),
            "",
            "正文最多识别",
        ),
        (
            "、".join(
                f"指标为{index + 100}项"
                for index in range(MAX_FACT_AUDIT_MENTIONS_PER_SENTENCE + 1)
            )
            + "。",
            "",
            "单句最多识别",
        ),
    ],
)
def test_fact_audit_rejects_derived_work_above_each_budget(
    content: str, materials: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        audit_document(content=content, materials=materials)


def test_fact_audit_direct_entry_point_bounds_title() -> None:
    with pytest.raises(ValueError, match="标题最多"):
        audit_document(
            title="题" * (MAX_FACT_AUDIT_TITLE_CHARACTERS + 1),
            content="正文。",
            materials="",
        )


def test_fact_audit_context_is_bounded_without_losing_source_offsets() -> None:
    materials = f"{'前' * 500}指标为100项{'后' * 500}。"
    facts = extract_material_facts(materials)
    number_fact = next(fact for fact in facts if fact.kind == "number")

    assert len(number_fact.excerpt) <= MAX_FACT_AUDIT_CONTEXT_CHARACTERS
    assert materials[number_fact.start : number_fact.end] == number_fact.value


def test_fact_audit_checks_candidates_beyond_the_old_prefix_shortlist() -> None:
    materials = "".join(["无关考核指标统计为100项。"] * 64 + ["政务平台整合数量为100项。"])
    result = audit_document(content="政务平台整合数量为200项。", materials=materials)
    number_claim = next(
        claim
        for sentence in result.sentences
        for claim in sentence.claims
        if claim.kind == "number"
    )

    assert number_claim.status == "contradicted"


def test_fact_audit_comparison_budget_rejects_instead_of_returning_partial_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fact_audit_module = importlib.import_module("gongwen_web.fact_audit")
    monkeypatch.setattr(fact_audit_module, "MAX_FACT_AUDIT_COMPARISONS", 5)

    with pytest.raises(ValueError, match="最多执行 5 次事实匹配"):
        audit_document(
            content="丁指标为200项。戊指标为201项。",
            materials="甲指标为100项。乙指标为101项。丙指标为102项。",
        )


def test_batch_rows_are_rejected_before_oversized_field_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docx_module = importlib.import_module("gongwen_web.docx")
    monkeypatch.setattr(docx_module, "MAX_BATCH_EXPANDED_CHARACTERS", 30)

    def unexpected_render(*_: object, **__: object) -> str:
        raise AssertionError("超限请求不应进入实际字段展开")

    monkeypatch.setattr(docx_module, "render_fields", unexpected_render)
    request = BatchExportRequest(
        template=ExportDocument(title="文", content="{{VALUE}}{{VALUE}}{{VALUE}}"),
        rows=[{"VALUE": "0123456789"}],
    )

    with pytest.raises(ValueError, match="展开后的内容超过 30 个字符预算"):
        build_batch_zip(request)


def test_ready_documents_share_the_batch_expansion_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docx_module = importlib.import_module("gongwen_web.docx")
    monkeypatch.setattr(docx_module, "MAX_BATCH_EXPANDED_CHARACTERS", 20)
    request = BatchExportRequest(
        documents=[
            ExportDocument(title="甲", content="正文" * 4),
            ExportDocument(title="乙", content="正文" * 6),
        ]
    )

    with pytest.raises(ValueError, match="展开后的内容超过 20 个字符预算"):
        build_batch_zip(request)


def test_cpu_heavy_routes_run_outside_the_request_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_module = importlib.import_module("gongwen_web.app")
    loop_thread_ids: set[int] = set()
    worker_thread_ids: dict[str, int] = {}

    original_request_payload = app_module._request_payload

    async def tracked_request_payload(request: object) -> dict[str, object]:
        loop_thread_ids.add(threading.get_ident())
        return await original_request_payload(request)

    monkeypatch.setattr(app_module, "_request_payload", tracked_request_payload)

    def track(name: str, original: object) -> object:
        def wrapper(*args: object, **kwargs: object) -> object:
            worker_thread_ids[name] = threading.get_ident()
            return original(*args, **kwargs)  # type: ignore[operator]

        return wrapper

    for name in (
        "generate_demo",
        "generate_titles_demo",
        "rewrite_demo",
        "review_demo",
        "audit_document",
        "build_docx",
        "build_batch_zip",
    ):
        monkeypatch.setattr(app_module, name, track(name, getattr(app_module, name)))

    storage = GongwenStorage(tmp_path / "resource-limits.sqlite3")
    with TestClient(app_module.create_app(storage=storage)) as client:
        responses = [
            client.post("/api/generate", json={"topic": "基层服务提质"}),
            client.post("/api/titles/generate", json={"topic": "基层服务提质"}),
            client.post("/api/rewrite", json={"text": "扎实做好有关工作。"}),
            client.post("/api/review", json={"content": "一、总体要求\n扎实推进工作。"}),
            client.post(
                "/api/fact-audit",
                json={"content": "完成10项任务。", "materials": "完成10项任务。"},
            ),
            client.post(
                "/api/export/docx",
                json={"title": "通知", "content": "请抓好落实。"},
            ),
            client.post(
                "/api/export/batch-docx",
                json={
                    "template": {"title": "{{单位}}通知", "content": "请抓好落实。"},
                    "rows": [{"单位": "甲单位"}],
                },
            ),
        ]

    assert [response.status_code for response in responses] == [200] * len(responses)
    assert set(worker_thread_ids) == {
        "generate_demo",
        "generate_titles_demo",
        "rewrite_demo",
        "review_demo",
        "audit_document",
        "build_docx",
        "build_batch_zip",
    }
    assert loop_thread_ids
    assert set(worker_thread_ids.values()).isdisjoint(loop_thread_ids)
