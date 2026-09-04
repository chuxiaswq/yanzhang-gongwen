# Chinese punctuation is intentional in fixture text.
# ruff: noqa: RUF001

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gongwen_web.storage import GongwenStorage
from yanzhang_core.knowledge import KnowledgeRepository
from yanzhang_core.models import (
    Citation,
    Claim,
    ContentBlock,
    Evidence,
    KnowledgeItem,
    ProjectTerm,
    WritingBrief,
)
from yanzhang_core.storage import (
    ProjectScopeError,
    RecordNotFoundError,
    RevisionConflictError,
    WritingStorage,
)


def _brief(*, brief_id: str = "brief-1") -> WritingBrief:
    return WritingBrief(
        id=brief_id,
        title="绿色发展年度总结",
        goal="形成一份准确、可复核的年度总结",
        audience="项目负责人",
        channel="document",
        content_type="work_summary",
        scenario_pack_id="workplace",
        recipe_id="work-summary",
        keywords=("绿色发展", "年度总结"),
    )


def _blocks(text: str = "第一阶段任务已经完成。") -> tuple[ContentBlock, ...]:
    return (ContentBlock(id="block-1", order=0, text=text),)


def test_project_brief_asset_revision_and_independent_schema_marker(tmp_path: Path) -> None:
    database = tmp_path / "gongwen.sqlite3"
    legacy = GongwenStorage(database)
    with sqlite3.connect(database) as connection:
        original = connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()

    storage = WritingStorage(database)
    project = storage.create_project("年度材料", project_id="project-1", tags=("年度", "重点项目"))
    brief = storage.save_brief(_brief(), project_id=project.id)
    asset = storage.create_text_asset(
        brief,
        _blocks(),
        project_id=project.id,
        asset_id="asset-1",
    )

    assert storage.get_project(project.id) == project
    assert storage.get_brief(brief.id, project_id=project.id) == brief
    assert (
        storage.get_text_asset(asset.id, project_id=project.id).plain_text()
        == "第一阶段任务已经完成。"
    )

    updated_blocks = _blocks("第二阶段任务正在推进。")
    revision = storage.save_revision(
        asset.id,
        updated_blocks,
        expected_revision=1,
        note="更新进展",
    )
    assert revision.version == 2
    assert storage.get_text_asset(asset.id).blocks == updated_blocks
    assert [item.version for item in storage.list_revisions(asset.id)] == [2, 1]
    with pytest.raises(RevisionConflictError):
        storage.save_revision(asset.id, updated_blocks, expected_revision=1)

    with sqlite3.connect(database) as connection:
        legacy_marker = connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()
        writing_marker = connection.execute(
            "SELECT value FROM schema_metadata WHERE key='writing_schema_version'"
        ).fetchone()
    assert legacy_marker == original
    assert writing_marker == ("3",)
    legacy.check_ready()
    storage.check_ready()


def test_writing_schema_v1_migrates_project_tags_without_data_loss(tmp_path: Path) -> None:
    database = tmp_path / "writing-v1.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_metadata(key, value) VALUES ('writing_schema_version', '1')"
        )
        connection.execute(
            """
            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                default_pack_id TEXT NOT NULL DEFAULT 'workplace',
                default_model_profile_id TEXT,
                archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO projects(
                id, name, description, default_pack_id, default_model_profile_id,
                archived, created_at, updated_at
            )
            VALUES ('project-1', '迁移项目', '', 'workplace', NULL, 0,
                    '2026-09-04T00:00:00+00:00', '2026-09-04T00:00:00+00:00')
            """
        )

    migrated = WritingStorage(database)
    assert migrated.get_project("project-1").tags == ()
    assert migrated.create_project(
        "新项目", project_id="project-2", tags=("政策", "调研")
    ).tags == ("政策", "调研")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT value FROM schema_metadata WHERE key='writing_schema_version'"
        ).fetchone() == ("3",)


def test_knowledge_upsert_returns_the_persisted_creation_timestamp(tmp_path: Path) -> None:
    storage = WritingStorage(tmp_path / "writing.sqlite3")
    project = storage.create_project("资料同步", project_id="project-material-sync")
    repository = KnowledgeRepository(storage)
    original_created_at = datetime(2025, 1, 2, 3, 4, tzinfo=UTC)
    replacement_created_at = datetime(2030, 6, 7, 8, 9, tzinfo=UTC)

    first = repository.upsert_item(
        KnowledgeItem(
            id="stable-material",
            project_id=project.id,
            title="第一版",
            content="第一版内容。",
            created_at=original_created_at,
        )
    )
    updated = repository.upsert_item(
        KnowledgeItem(
            id="stable-material",
            project_id=project.id,
            title="第二版",
            content="第二版内容。",
            created_at=replacement_created_at,
        )
    )
    persisted = repository.get_item("stable-material", project_id=project.id)

    assert first.created_at == original_created_at
    assert updated == persisted
    assert updated.created_at == original_created_at
    assert updated.title == "第二版"
    assert updated.content == "第二版内容。"


def test_knowledge_fts_evidence_claim_citation_terms_and_audit(tmp_path: Path) -> None:
    storage = WritingStorage(tmp_path / "writing.sqlite3")
    project = storage.create_project("知识库", project_id="project-1")
    brief = storage.save_brief(_brief(), project_id=project.id)
    asset = storage.create_text_asset(brief, _blocks(), project_id=project.id)
    repository = KnowledgeRepository(storage)
    created = datetime(2026, 9, 4, tzinfo=UTC)
    item = KnowledgeItem(
        id="source-1",
        project_id=project.id,
        kind="source",
        title="绿色发展工作材料",
        content="今年围绕绿色发展完成三项重点任务，并建立月度复盘机制。",
        source_url="https://example.test/source",
        tags=("绿色发展", "事实材料"),
        created_at=created,
    )
    repository.upsert_item(item)

    results = repository.search("绿色发展", project_id=project.id)
    assert [result.item.id for result in results] == [item.id]
    assert "绿色发展" in results[0].excerpt
    assert repository.get_item(item.id, project_id=project.id) == item

    evidence = Evidence(
        id="evidence-1",
        knowledge_item_id=item.id,
        excerpt="完成三项重点任务",
        locator="正文第1段",
        source_url=item.source_url,
        source_hash="a" * 64,
    )
    repository.add_evidence(evidence)
    claim = Claim(
        id="claim-1",
        asset_id=asset.id,
        block_id="block-1",
        text="完成三项重点任务",
        status="supported",
        evidence_ids=(evidence.id,),
        confidence=95,
    )
    repository.save_claim(claim)
    citation = Citation(
        id="citation-1",
        asset_id=asset.id,
        block_id="block-1",
        claim_id=claim.id,
        evidence_id=evidence.id,
        label="材料第1段",
    )
    repository.save_citation(citation)

    assert repository.list_evidence(item.id) == [evidence]
    assert repository.get_claim(claim.id, project_id=project.id) == claim
    assert repository.get_citation(citation.id, project_id=project.id) == citation
    assert repository.list_citations(asset.id, project_id=project.id) == [citation]

    term = ProjectTerm(
        id="term-1",
        project_id=project.id,
        term="月报",
        preferred_form="月度工作报告",
        discouraged_variants=("月度报表",),
    )
    storage.save_project_term(term)
    assert storage.list_project_terms(project.id) == [term]
    assert not storage.delete_project_term(term.id, project_id="other-project")
    assert storage.delete_project_term(term.id, project_id=project.id)
    assert storage.list_project_terms(project.id) == []
    event = storage.append_audit_event(
        project_id=project.id,
        action="knowledge.import",
        entity_type="knowledge_item",
        entity_id=item.id,
        summary="导入事实材料",
    )
    assert storage.list_audit_events(project_id=project.id) == [event]


def test_legacy_migration_is_transactional_and_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "gongwen.sqlite3"
    legacy = GongwenStorage(database)
    first = legacy.save_document(
        title="旧稿",
        content="第一版正文",
        document_type="工作总结",
        metadata={"source": "legacy"},
        document_id="legacy-document",
        expected_version=0,
    )
    legacy.save_document(
        title="旧稿修订版",
        content="第二版正文",
        document_type="工作总结",
        metadata={"source": "legacy"},
        document_id=first["id"],
        expected_version=1,
    )
    storage = WritingStorage(database)

    first_report = storage.migrate_legacy_gongwen()
    second_report = storage.migrate_legacy_gongwen()

    assert first_report == {
        "legacy_available": True,
        "assets_created": 1,
        "assets_existing": 0,
        "revisions_created": 2,
        "revisions_existing": 0,
    }
    assert second_report == {
        "legacy_available": True,
        "assets_created": 0,
        "assets_existing": 1,
        "revisions_created": 0,
        "revisions_existing": 2,
    }
    migrated = storage.get_text_asset(first["id"])
    assert migrated.title == "旧稿修订版"
    assert migrated.current_revision == 2
    assert migrated.plain_text() == "第二版正文"
    assert [revision.version for revision in storage.list_revisions(first["id"])] == [2, 1]
    assert legacy.get_document(first["id"])["content"] == "第二版正文"


def test_invalid_legacy_sequence_rolls_back_new_rows(tmp_path: Path) -> None:
    database = tmp_path / "gongwen.sqlite3"
    legacy = GongwenStorage(database)
    saved = legacy.save_document(
        title="待校验旧稿",
        content="正文",
        document_id="broken-document",
        expected_version=0,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE documents SET current_version=2 WHERE id=?",
            (saved["id"],),
        )
    storage = WritingStorage(database)

    with pytest.raises(RuntimeError, match="incomplete version sequence"):
        storage.migrate_legacy_gongwen()

    assert storage.list_text_assets() == []


def test_project_scope_guards_assets_and_knowledge_graph(tmp_path: Path) -> None:
    storage = WritingStorage(tmp_path / "writing.sqlite3")
    first_project = storage.create_project("甲项目", project_id="project-a")
    second_project = storage.create_project("乙项目", project_id="project-b")
    first_brief = storage.save_brief(_brief(brief_id="brief-a"), project_id=first_project.id)
    second_brief = storage.save_brief(_brief(brief_id="brief-b"), project_id=second_project.id)
    first_asset = storage.create_text_asset(
        first_brief,
        _blocks(),
        project_id=first_project.id,
        asset_id="asset-a",
    )

    variant = storage.create_text_asset(
        first_brief,
        _blocks("适配社交渠道的内容。"),
        project_id=first_project.id,
        parent_asset_id=first_asset.id,
        channel="social",
        asset_id="asset-social",
    )
    assert variant.channel == "social"
    assert variant.parent_asset_id == first_asset.id

    with pytest.raises(ProjectScopeError):
        storage.create_text_asset(
            first_brief,
            _blocks(),
            project_id=second_project.id,
            asset_id="wrong-brief-project",
        )
    with pytest.raises(ProjectScopeError):
        storage.create_text_asset(
            second_brief,
            _blocks(),
            project_id=second_project.id,
            parent_asset_id=first_asset.id,
            asset_id="wrong-parent-project",
        )
    with pytest.raises(RecordNotFoundError):
        storage.get_brief(first_brief.id, project_id=second_project.id)
    with pytest.raises(RecordNotFoundError):
        storage.get_text_asset(first_asset.id, project_id=second_project.id)
    with pytest.raises(RecordNotFoundError):
        storage.get_revision(first_asset.id, 1, project_id=second_project.id)
    with pytest.raises(RecordNotFoundError):
        storage.save_revision(
            first_asset.id,
            _blocks("错误项目更新。"),
            project_id=second_project.id,
        )

    repository = KnowledgeRepository(storage)
    first_item = repository.upsert_item(
        KnowledgeItem(
            id="item-a",
            project_id=first_project.id,
            title="甲项目材料",
            content="甲项目事实材料。",
        )
    )
    second_item = repository.upsert_item(
        KnowledgeItem(
            id="item-b",
            project_id=second_project.id,
            title="乙项目材料",
            content="乙项目事实材料。",
        )
    )
    first_evidence = repository.add_evidence(
        Evidence(
            id="evidence-a",
            knowledge_item_id=first_item.id,
            excerpt="甲项目事实材料",
        ),
        project_id=first_project.id,
    )
    second_evidence = repository.add_evidence(
        Evidence(
            id="evidence-b",
            knowledge_item_id=second_item.id,
            excerpt="乙项目事实材料",
        ),
        project_id=second_project.id,
    )
    claim = repository.save_claim(
        Claim(
            id="claim-a",
            asset_id=first_asset.id,
            block_id="block-1",
            text="甲项目事实材料",
            status="supported",
            evidence_ids=(first_evidence.id,),
            confidence=100,
        ),
        project_id=first_project.id,
    )
    citation = repository.save_citation(
        Citation(
            id="citation-a",
            asset_id=first_asset.id,
            block_id="block-1",
            claim_id=claim.id,
            evidence_id=first_evidence.id,
        ),
        project_id=first_project.id,
    )

    with pytest.raises(RecordNotFoundError):
        repository.get_item(first_item.id, project_id=second_project.id)
    with pytest.raises(RecordNotFoundError):
        repository.get_evidence(first_evidence.id, project_id=second_project.id)
    with pytest.raises(RecordNotFoundError):
        repository.get_claim(claim.id, project_id=second_project.id)
    with pytest.raises(RecordNotFoundError):
        repository.get_citation(citation.id, project_id=second_project.id)
    with pytest.raises(ProjectScopeError):
        repository.save_claim(
            Claim(
                id="cross-project-claim",
                asset_id=first_asset.id,
                block_id="block-1",
                text="错误引用乙项目材料",
                evidence_ids=(second_evidence.id,),
            ),
            project_id=first_project.id,
        )
    with pytest.raises(ProjectScopeError):
        repository.save_citation(
            Citation(
                id="cross-project-citation",
                asset_id=first_asset.id,
                block_id="block-1",
                claim_id=claim.id,
                evidence_id=second_evidence.id,
            ),
            project_id=first_project.id,
        )
