"""Offline tests for the personal official-document SQLite repository."""

# Chinese punctuation is intentional test data.
# ruff: noqa: RUF001

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from gongwen_web import storage as storage_module
from gongwen_web.storage import (
    DocumentVersionConflict,
    GongwenStorage,
    default_data_dir,
    default_database_path,
)


@pytest.mark.parametrize(
    ("platform_name", "environment", "home", "expected"),
    [
        (
            "darwin",
            {"LOCALAPPDATA": "/ignored", "XDG_DATA_HOME": "/also-ignored"},
            Path("/home/fixture"),
            Path("/home/fixture/Library/Application Support/Yanzhang/Gongwen"),
        ),
        (
            "win32",
            {"LOCALAPPDATA": "C:/fixture/AppData/Local"},
            Path("C:/fixture"),
            Path("C:/fixture/AppData/Local/Yanzhang/Gongwen"),
        ),
        (
            "win32",
            {},
            Path("C:/fixture"),
            Path("C:/fixture/AppData/Local/Yanzhang/Gongwen"),
        ),
        (
            "linux",
            {"XDG_DATA_HOME": "/home/example/.data"},
            Path("/home/example"),
            Path("/home/example/.data/yanzhang/gongwen"),
        ),
        (
            "linux",
            {},
            Path("/home/example"),
            Path("/home/example/.local/share/yanzhang/gongwen"),
        ),
    ],
)
def test_platform_default_data_dir_uses_os_conventions(
    platform_name: str,
    environment: dict[str, str],
    home: Path,
    expected: Path,
) -> None:
    assert (
        storage_module._platform_default_data_dir(
            platform_name=platform_name,
            environment=environment,
            home=home,
        )
        == expected
    )


def test_default_data_dir_prefers_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "explicit-data"
    monkeypatch.setenv("GONGWEN_DATA_DIR", f"  {configured}  ")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "windows-default"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "linux-default"))

    assert default_data_dir() == configured


def test_default_path_uses_configured_data_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "personal-data"
    monkeypatch.setenv("GONGWEN_DATA_DIR", str(data_dir))

    assert default_database_path() == data_dir / "gongwen.sqlite3"
    store = GongwenStorage()

    assert store.path == data_dir / "gongwen.sqlite3"
    assert store.path.is_file()
    with sqlite3.connect(store.path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        schema_version = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()
    assert {"documents", "document_versions", "model_usage"} <= tables
    assert schema_version == ("1",)

    # Initialization is idempotent and preserves previously created records.
    saved = store.save_document(title="测试文稿", content="正文。")
    store.initialize()
    assert store.get_document(saved["id"]) == saved


def test_initialization_rejects_unknown_schema_without_rewriting_it(tmp_path: Path) -> None:
    database = tmp_path / "future.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_metadata(key, value) VALUES ('schema_version', '999')"
        )

    with pytest.raises(RuntimeError, match="schema version mismatch"):
        GongwenStorage(database)

    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()
        documents_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'documents'"
        ).fetchone()
    assert version == ("999",)
    assert documents_table is None


def test_initialization_rejects_unversioned_partial_core_table(tmp_path: Path) -> None:
    database = tmp_path / "partial.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE documents (id TEXT PRIMARY KEY)")

    with pytest.raises(RuntimeError, match="documents: missing columns"):
        GongwenStorage(database)

    with sqlite3.connect(database) as connection:
        metadata_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_metadata'"
        ).fetchone()
    assert metadata_table is None


def test_document_crud_search_and_versions_are_json_serializable(tmp_path: Path) -> None:
    store = GongwenStorage(tmp_path / "gongwen.sqlite3")

    first = store.save_document(
        document_id="draft-1",
        title="关于推进数字化工作的通知",
        document_type="通知",
        content="一、总体要求\n稳步推进数字化工作。",
        metadata={"facts": ["已接入18个处室"], "fact_lock": True},
        version_note="初稿",
        expected_version=0,
    )
    second = store.save_document(
        document_id="draft-1",
        title="关于进一步推进数字化工作的通知",
        document_type="通知",
        content="一、总体要求\n稳步推进数字化工作。\n二、工作安排\n9月底前完成目录。",
        metadata={"facts": ["已接入18个处室", "9月底前完成目录"]},
        version_note="补充工作安排",
        expected_version=1,
    )
    other = store.save_document(
        title="包含100%字样的报告",
        document_type="报告",
        content="用于检查查询通配符的正文。",
    )

    assert first["current_version"] == 1
    assert second["current_version"] == 2
    assert second["created_at"] == first["created_at"]
    assert store.get_document("draft-1") == second
    assert json.loads(json.dumps(second, ensure_ascii=False))["metadata"]["facts"]

    listed = store.list_documents()
    assert {item["id"] for item in listed} == {"draft-1", other["id"]}
    selected = store.list_documents(search="9月底")
    assert [item["id"] for item in selected] == ["draft-1"]
    literal_percent = store.list_documents(search="100%")
    assert [item["id"] for item in literal_percent] == [other["id"]]

    versions = store.list_versions("draft-1")
    assert [item["version"] for item in versions] == [2, 1]
    assert versions[0]["note"] == "补充工作安排"
    assert store.get_version("draft-1", 1) == versions[1]
    assert store.get_version("draft-1", 99) is None

    assert store.delete_document("draft-1") is True
    assert store.delete_document("draft-1") is False
    assert store.get_document("draft-1") is None
    assert store.list_versions("draft-1") == []


def test_optimistic_conflict_rolls_back_without_partial_version(tmp_path: Path) -> None:
    store = GongwenStorage(tmp_path / "gongwen.sqlite3")
    saved = store.save_document(document_id="draft", title="初稿", content="第一版。")

    with pytest.raises(DocumentVersionConflict, match="期望 0，当前 1"):
        store.save_document(
            document_id="draft",
            title="错误覆盖",
            content="不应保存。",
            expected_version=0,
        )

    assert store.get_document("draft") == saved
    assert [version["version"] for version in store.list_versions("draft")] == [1]


def test_concurrent_saves_create_complete_monotonic_history(tmp_path: Path) -> None:
    store = GongwenStorage(tmp_path / "gongwen.sqlite3")
    store.save_document(document_id="shared", title="并发文稿", content="初稿。")

    def save_revision(number: int) -> int:
        return store.save_document(
            document_id="shared",
            title="并发文稿",
            content=f"第{number}次修改。",
        )["current_version"]

    with ThreadPoolExecutor(max_workers=8) as executor:
        observed_versions = list(executor.map(save_revision, range(1, 21)))

    assert sorted(observed_versions) == list(range(2, 22))
    assert store.get_document("shared")["current_version"] == 21  # type: ignore[index]
    assert [item["version"] for item in store.list_versions("shared")] == list(range(21, 0, -1))


def test_model_usage_records_aggregate_and_survive_document_deletion(tmp_path: Path) -> None:
    store = GongwenStorage(tmp_path / "gongwen.sqlite3")
    document = store.save_document(title="用量测试", content="正文。")

    success = store.record_model_usage(
        document_id=document["id"],
        operation="generate",
        provider="openai",
        model="model-a",
        input_tokens=120,
        output_tokens=80,
        latency_ms=240.5,
        metadata={"mode": "live"},
    )
    failure = store.record_model_usage(
        operation="review",
        provider="openai",
        model="model-a",
        input_tokens=20,
        output_tokens=0,
        total_tokens=20,
        latency_ms=50,
        success=False,
        error_code="timeout",
    )

    assert success["total_tokens"] == 200
    assert failure["success"] is False
    assert json.dumps(store.list_model_usage(), ensure_ascii=False)
    assert store.summarize_model_usage() == {
        "call_count": 2,
        "successful_calls": 1,
        "failed_calls": 1,
        "input_tokens": 140,
        "output_tokens": 80,
        "total_tokens": 220,
        "latency_ms": 290.5,
    }
    assert store.summarize_model_usage(document_id=document["id"])["call_count"] == 1

    assert store.delete_document(document["id"])
    persisted = store.list_model_usage()
    linked = next(item for item in persisted if item["operation"] == "generate")
    assert linked["document_id"] is None
    assert store.summarize_model_usage()["total_tokens"] == 220


@pytest.mark.parametrize(
    ("method", "message"),
    [
        (lambda store: store.save_document(title="", content="正文"), "标题"),
        (lambda store: store.save_document(title="标题", content="  "), "正文"),
        (lambda store: store.list_documents(limit=0), "limit"),
        (
            lambda store: store.record_model_usage(
                operation="generate",
                provider="openai",
                model="model-a",
                input_tokens=-1,
            ),
            "input_tokens",
        ),
    ],
)
def test_invalid_storage_inputs_are_rejected(
    tmp_path: Path,
    method: object,
    message: str,
) -> None:
    store = GongwenStorage(tmp_path / "gongwen.sqlite3")
    assert callable(method)
    with pytest.raises(ValueError, match=message):
        method(store)
