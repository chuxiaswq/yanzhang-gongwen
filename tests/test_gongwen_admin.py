"""Offline tests for deployment backup and database maintenance commands."""

# Chinese punctuation is intentional in test fixtures.
# ruff: noqa: RUF001

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from gongwen_web.admin import backup_database, inspect_database, main, restore_database
from gongwen_web.articles import ArticleLibrary, SQLiteArticleRepository
from gongwen_web.storage import GongwenStorage


def test_consistent_backup_and_atomic_restore(tmp_path: Path) -> None:
    source = tmp_path / "data" / "gongwen.sqlite3"
    storage = GongwenStorage(source)
    saved = storage.save_document(
        title="部署检查文稿",
        content="一、总体要求\n坚持稳妥推进。",
        expected_version=0,
    )
    storage.record_model_usage(
        operation="generate",
        provider="fixture",
        model="fixture-model",
        input_tokens=12,
        output_tokens=8,
    )
    article_library = ArticleLibrary(SQLiteArticleRepository(source))
    article_library.import_text(
        title="部署参考文章",
        content="这是一篇用于验证完整备份的参考文章。",
        source_id="manual",
        source_name="本地材料",
    )

    backup = backup_database(source, tmp_path / "backups" / "snapshot.sqlite3")
    backup.chmod(0o400)
    backup.parent.chmod(0o500)
    try:
        with sqlite3.connect(f"file:{backup.as_posix()}?mode=ro", uri=True) as connection:
            assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        status = inspect_database(backup)
    finally:
        backup.parent.chmod(0o700)
        backup.chmod(0o600)
    assert not Path(f"{backup}-wal").exists()
    assert not Path(f"{backup}-shm").exists()
    assert status["ok"] is True
    assert status["integrity"] == "ok"
    assert status["schema_version"] == 1
    assert status["schema_compatible"] is True
    assert status["schema_errors"] == []
    assert status["documents"] == 1
    assert status["document_versions"] == 1
    assert status["articles"] == 1
    assert status["model_usage"] == 1

    storage.save_document(
        document_id=saved["id"],
        title="部署检查文稿（修改版）",
        content="二、重点任务\n完成修改。",
        expected_version=1,
    )
    restored = restore_database(backup, source, overwrite=True)
    restored_storage = GongwenStorage(restored)
    record = restored_storage.get_document(saved["id"])
    assert record is not None
    assert record["title"] == "部署检查文稿"
    assert record["current_version"] == 1


def test_backup_requires_explicit_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "gongwen.sqlite3"
    GongwenStorage(source)
    destination = backup_database(source, tmp_path / "backup.sqlite3")

    with pytest.raises(FileExistsError) as caught:
        backup_database(source, destination)
    assert str(destination) in str(caught.value)


def test_admin_check_prints_machine_readable_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "gongwen.sqlite3"
    GongwenStorage(database)
    ArticleLibrary(SQLiteArticleRepository(database))
    assert main(["--database", str(database), "check"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["path"] == str(database.resolve())


def test_restore_rejects_unrelated_sqlite_and_preserves_destination(tmp_path: Path) -> None:
    destination = tmp_path / "gongwen.sqlite3"
    storage = GongwenStorage(destination)
    ArticleLibrary(SQLiteArticleRepository(destination))
    saved = storage.save_document(title="应保留的文稿", content="原始正文", expected_version=0)

    unrelated = tmp_path / "unrelated.sqlite3"
    with sqlite3.connect(unrelated) as connection:
        connection.execute("CREATE TABLE other_data (id INTEGER PRIMARY KEY)")

    status = inspect_database(unrelated)
    assert status["integrity"] == "ok"
    assert status["ok"] is False
    assert status["schema_compatible"] is False
    assert status["schema_errors"]
    with pytest.raises(RuntimeError, match="备份校验未通过"):
        restore_database(unrelated, destination, overwrite=True)

    preserved = GongwenStorage(destination).get_document(saved["id"])
    assert preserved is not None
    assert preserved["title"] == "应保留的文稿"
