"""Keep academic structures aligned with the selected research task, offline."""

# ruff: noqa: RUF001 -- Chinese academic fixtures use full-width punctuation.

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from gongwen_web.app import create_app
from gongwen_web.storage import GongwenStorage
from yanzhang_academic import BibliographicRecord, EvidenceSnippet, JournalProfile, ResearchBrief
from yanzhang_academic.writing import create_outline

TASKS = [
    ("文献综述", "literature-review", ["问题与范围", "主题脉络", "证据与分歧", "研究空白"]),
    ("研究提纲", "research-outline", ["研究问题", "分析框架", "资料与方法", "章节结构"]),
    ("摘要", "abstract", ["背景与目的", "方法", "结果", "结论"]),
    ("审稿回复", "rebuttal", ["总体说明", "逐条回复", "修改定位", "保留意见"]),
]


@pytest.mark.parametrize(("document_type", "task_type", "headings"), TASKS)
def test_outline_uses_task_structure_and_distinct_section_questions(
    document_type: str, task_type: str, headings: list[str]
) -> None:
    brief = ResearchBrief(
        title="远程协作与团队知识共享",
        research_question="远程协作如何影响团队知识共享？",
        document_type=document_type,
    )
    outline = create_outline(brief)
    assert outline.task_type == task_type
    assert [section.heading for section in outline.sections] == headings
    assert len({tuple(section.questions) for section in outline.sections}) == len(headings)
    assert all(section.purpose and section.questions for section in outline.sections)
    assert not any(section.record_ids or section.evidence_ids for section in outline.sections)


def test_literature_review_does_not_present_a_planned_experiment_as_completed_findings() -> None:
    record = BibliographicRecord(
        title="协作研究", abstract="研究比较团队之间的协作差异。", import_source="manual"
    )
    evidence = EvidenceSnippet(
        record_id=record.id,
        record_source_hash=record.source_hash,
        text="研究样本局限于单一组织。",
        kind="limitation",
    )
    untrusted = evidence.model_copy(update={"id": "wrong-source", "record_source_hash": "old"})
    outline = create_outline(
        ResearchBrief(
            title="知识共享", research_question="研究存在哪些分歧？", document_type="文献综述"
        ),
        [record],
        [evidence, untrusted],
    )
    assert outline.sections[1].record_ids == [record.id]
    assert outline.sections[3].evidence_ids == [evidence.id]
    assert "材料未覆盖" in outline.sections[3].purpose
    assert all("wrong-source" not in section.evidence_ids for section in outline.sections)
    assert not {"研究设计", "研究发现", "实验结果"}.intersection(
        section.heading for section in outline.sections
    )


def test_explicit_journal_sections_still_override_default_structure() -> None:
    outline = create_outline(
        ResearchBrief(
            title="协作研究", research_question="协作如何发生？", document_type="文献综述"
        ),
        journal=JournalProfile(name="测试期刊", required_sections=["研究现状", "未来展望"]),
    )
    assert outline.task_type == "literature-review"
    assert [section.heading for section in outline.sections] == ["研究现状", "未来展望"]


@pytest.mark.parametrize(("document_type", "task_type", "headings"), TASKS)
def test_academic_outline_api_keeps_document_type_through_the_service_boundary(
    tmp_path: Path, document_type: str, task_type: str, headings: list[str]
) -> None:
    application = create_app(storage=GongwenStorage(tmp_path / "academic.sqlite3"))
    with TestClient(application) as client:
        project_response = client.post(
            "/api/v2/projects", json={"name": "结构回归项目", "scenario_pack_id": "academic"}
        )
        assert project_response.status_code == 201, project_response.text
        project_id = project_response.json()["project"]["id"]
        response = client.post(
            f"/api/v2/projects/{project_id}/academic/outline",
            json={
                "title": "知识共享",
                "research_question": "协作如何影响知识共享？",
                "document_type": document_type,
            },
        )
        assert response.status_code == 200, response.text
        outline = response.json()["outline"]
        assert outline["task_type"] == task_type
        assert [section["heading"] for section in outline["sections"]] == headings


def test_abstract_endpoint_returns_an_abstract_not_a_six_chapter_outline(tmp_path: Path) -> None:
    application = create_app(storage=GongwenStorage(tmp_path / "abstract.sqlite3"))
    with TestClient(application) as client:
        project = client.post(
            "/api/v2/projects", json={"name": "摘要回归项目", "scenario_pack_id": "academic"}
        ).json()["project"]
        response = client.post(
            f"/api/v2/projects/{project['id']}/academic/abstract",
            json={
                "title": "知识共享",
                "research_question": "协作如何影响知识共享？",
                "document_type": "摘要",
            },
        )
        assert response.status_code == 200, response.text
        draft = response.json()["abstract"]
        assert draft["task_type"] == "abstract"
        assert draft["text"]
        assert "sections" not in draft
        assert draft["placeholders"]
