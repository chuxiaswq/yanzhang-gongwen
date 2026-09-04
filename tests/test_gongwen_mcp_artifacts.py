from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gongwen_mcp.artifacts import (
    CSV_MIME,
    DEFAULT_MAX_TOTAL_BYTES,
    DEFAULT_TTL_SECONDS,
    DOCX_MIME,
    HTML_MIME,
    LATEX_MIME,
    MARKDOWN_MIME,
    MAX_CSV_BYTES,
    MAX_DOCX_BYTES,
    MAX_HTML_BYTES,
    MAX_LATEX_BYTES,
    MAX_MARKDOWN_BYTES,
    MAX_PDF_BYTES,
    MAX_TEXT_BYTES,
    MAX_ZIP_BYTES,
    PDF_MIME,
    STALE_TEMP_GRACE_SECONDS,
    TEXT_MIME,
    ZIP_MIME,
    ArtifactCorrupt,
    ArtifactNotFound,
    ArtifactStore,
    ArtifactTooLarge,
    InvalidArtifactId,
    UnsupportedArtifactType,
    artifact_resource_uri,
    project_artifact_resource_uri,
)
from yanzhang.storage import LocalStorage, StoredObject


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class _FailMetadataStorage(LocalStorage):
    def put_bytes(
        self,
        key: str | os.PathLike[str],
        data: bytes | bytearray | memoryview,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        if os.fspath(key).endswith(".json"):
            raise OSError("fixture metadata failure")
        return super().put_bytes(key, data, content_type=content_type)


class _CoordinatedQuotaStorage(LocalStorage):
    """Force the unsafe two-store quota race to complete deterministically."""

    def __init__(
        self,
        root: Path,
        *,
        commit_barrier: threading.Barrier,
        inventory_barrier: threading.Barrier,
    ) -> None:
        super().__init__(root)
        self._commit_barrier = commit_barrier
        self._inventory_barrier = inventory_barrier
        self._committed = False

    def put_bytes(
        self,
        key: str | os.PathLike[str],
        data: bytes | bytearray | memoryview,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        stored = super().put_bytes(key, data, content_type=content_type)
        if os.fspath(key).endswith(".json"):
            self._committed = True
            self._wait(self._commit_barrier)
        return stored

    def list_objects(self, prefix: str = "") -> Iterable[StoredObject]:
        # Materialize the snapshot before rendezvousing.  Without repository
        # serialization, both writers then evict from the same over-cap view.
        objects = tuple(super().list_objects(prefix))
        if self._committed:
            self._wait(self._inventory_barrier)
        return objects

    @staticmethod
    def _wait(barrier: threading.Barrier) -> None:
        try:
            barrier.wait(timeout=0.25)
        except threading.BrokenBarrierError:
            pass


def test_artifact_round_trip_is_persistent_and_metadata_is_json_safe(tmp_path: Path) -> None:
    payload = b"PK\x03\x04minimal-docx-fixture"
    created = datetime(2026, 9, 4, 8, 30, tzinfo=UTC)
    clock = _Clock(created)
    store = ArtifactStore(tmp_path, clock=clock)

    metadata = store.put(payload, filename="工作通知.docx", mime=DOCX_MIME)

    assert len(metadata.artifact_id) == 32
    assert metadata.filename == "工作通知.docx"
    assert metadata.mime == DOCX_MIME
    assert metadata.size == len(payload)
    assert metadata.sha256 == hashlib.sha256(payload).hexdigest()
    assert metadata.resource_uri == f"gongwen://exports/{metadata.artifact_id}"
    assert metadata.created_at == created
    assert metadata.expires_at == created + timedelta(seconds=DEFAULT_TTL_SECONDS)
    assert store.read_bytes(metadata.artifact_id) == payload
    json.dumps(metadata.model_dump(mode="json"), ensure_ascii=False)

    restarted = ArtifactStore(tmp_path, clock=clock)
    assert restarted.get_metadata(metadata.artifact_id) == metadata
    assert restarted.read(metadata.artifact_id) == payload
    assert (tmp_path / "exports" / f"{metadata.artifact_id}.docx").read_bytes() == payload


def test_project_scoped_metadata_persists_and_enforces_read_scope(tmp_path: Path) -> None:
    payload = "项目交付".encode()
    store = ArtifactStore(tmp_path)
    metadata = store.put(
        payload,
        filename="项目交付.txt",
        mime=TEXT_MIME,
        project_id="项目 A",
        asset_id="asset-a",
        revision_id="revision-a",
        creator="yanzhang_export_asset",
    )

    assert metadata.project_id == "项目 A"
    assert metadata.asset_id == "asset-a"
    assert metadata.revision_id == "revision-a"
    assert metadata.creator == "yanzhang_export_asset"
    assert metadata.resource_uri == project_artifact_resource_uri("项目 A", metadata.artifact_id)
    assert "%E9%A1%B9%E7%9B%AE%20A" in metadata.resource_uri
    assert store.read_bytes(metadata.artifact_id, project_id="项目 A") == payload
    with pytest.raises(ArtifactNotFound):
        store.read_bytes(metadata.artifact_id, project_id="项目 B")
    with pytest.raises(ArtifactNotFound):
        store.read_bytes(metadata.artifact_id, legacy_only=True)

    restarted = ArtifactStore(tmp_path)
    assert restarted.get_metadata(metadata.artifact_id, project_id="项目 A") == metadata


def test_legacy_metadata_sidecar_defaults_to_v1_creator(tmp_path: Path) -> None:
    created = datetime(2026, 9, 4, 8, 30, tzinfo=UTC)
    store = ArtifactStore(tmp_path, clock=_Clock(created))
    metadata = store.put(b"legacy", filename="legacy.txt", mime=TEXT_MIME)
    sidecar = tmp_path / "exports" / f"{metadata.artifact_id}.json"
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload.pop("creator")
    payload.pop("project_id")
    payload.pop("asset_id")
    payload.pop("revision_id")
    sidecar.write_text(json.dumps(payload), encoding="utf-8")

    reopened = ArtifactStore(tmp_path, clock=_Clock(created))
    loaded = reopened.get_metadata(metadata.artifact_id)
    assert loaded.creator == "gongwen_v1"
    assert loaded.project_id is None
    assert reopened.read_bytes(metadata.artifact_id, legacy_only=True) == b"legacy"


def test_partial_project_scope_metadata_is_rejected(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    with pytest.raises(ValueError, match="requires project, asset and revision"):
        store.put(
            b"partial",
            filename="partial.txt",
            mime=TEXT_MIME,
            project_id="project-a",
        )


@pytest.mark.parametrize(
    ("mime", "extension", "payload"),
    [
        (DOCX_MIME, ".docx", b"PK\x03\x04docx"),
        (ZIP_MIME, ".zip", b"PK\x03\x04zip"),
        (PDF_MIME, ".pdf", b"%PDF-1.7\n%%EOF"),
        (MARKDOWN_MIME, ".md", "# 标题\n\n正文".encode()),
        (TEXT_MIME, ".txt", "纯文本正文".encode()),
        (HTML_MIME, ".html", "<!doctype html><title>标题</title>".encode()),
        (LATEX_MIME, ".tex", b"\\documentclass{article}\\begin{document}x\\end{document}"),
        (CSV_MIME, ".csv", "标题,状态\n材料,完成\n".encode()),
    ],
)
def test_every_supported_export_has_fixed_mime_extension_and_integrity(
    tmp_path: Path,
    mime: str,
    extension: str,
    payload: bytes,
) -> None:
    created = datetime(2026, 9, 4, 9, tzinfo=UTC)
    store = ArtifactStore(tmp_path, clock=_Clock(created))

    metadata = store.put(payload, filename="../../通用导出.wrong", mime=mime.upper())

    assert metadata.filename == f"通用导出.wrong{extension}"
    assert metadata.mime == mime
    assert metadata.size == len(payload)
    assert metadata.sha256 == hashlib.sha256(payload).hexdigest()
    assert metadata.created_at == created
    assert metadata.expires_at == created + timedelta(seconds=DEFAULT_TTL_SECONDS)
    assert metadata.resource_uri == artifact_resource_uri(metadata.artifact_id)
    assert store.read(metadata.artifact_id) == payload

    public_json = json.dumps(metadata.model_dump(mode="json"), ensure_ascii=False)
    assert str(tmp_path) not in public_json
    expected_path = tmp_path / "exports" / f"{metadata.artifact_id}{extension}"
    assert expected_path.read_bytes() == payload

    restarted = ArtifactStore(tmp_path, clock=_Clock(created))
    assert restarted.get_metadata(metadata.artifact_id) == metadata
    assert restarted.read_bytes(metadata.artifact_id) == payload


@pytest.mark.parametrize(
    "mime",
    (PDF_MIME, MARKDOWN_MIME, TEXT_MIME, HTML_MIME, LATEX_MIME, CSV_MIME),
)
def test_universal_exports_use_the_existing_expiry_mechanism(
    tmp_path: Path,
    mime: str,
) -> None:
    clock = _Clock(datetime(2026, 9, 4, 10, tzinfo=UTC))
    store = ArtifactStore(tmp_path, clock=clock, ttl_seconds=5)
    metadata = store.put(b"fixture", filename="expiring", mime=mime)

    clock.value += timedelta(seconds=6)

    with pytest.raises(ArtifactNotFound):
        store.read_bytes(metadata.artifact_id)
    assert not any(path.stem == metadata.artifact_id for path in (tmp_path / "exports").iterdir())


def test_filename_is_display_only_and_never_selects_a_storage_path(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    metadata = store.put(b"PK", filename="../../outside.docx", mime=DOCX_MIME)

    assert metadata.filename == "outside.docx"
    assert not (tmp_path.parent / "outside.docx").exists()
    names = {path.name for path in (tmp_path / "exports").iterdir()}
    names.discard(".gongwen-artifacts.lock")
    assert names == {f"{metadata.artifact_id}.docx", f"{metadata.artifact_id}.json"}
    assert all("outside" not in name for name in names)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "../0123456789abcdef0123456789abcdef",
        "/0123456789abcdef0123456789abcdef",
        "0123456789abcdef0123456789abcdef/extra",
        "0123456789ABCDEF0123456789ABCDEF",
        "0123456789abcdef0123456789abcdeg",
        "0123456789abcdef0123456789abcdef\x00",
    ],
)
def test_artifact_id_rejects_path_and_noncanonical_values(tmp_path: Path, value: str) -> None:
    store = ArtifactStore(tmp_path)

    with pytest.raises(InvalidArtifactId):
        store.read_bytes(value)
    with pytest.raises(InvalidArtifactId):
        artifact_resource_uri(value)


def test_unknown_id_is_reported_without_exposing_a_path(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    artifact_id = "a" * 32

    with pytest.raises(ArtifactNotFound) as raised:
        store.read_bytes(artifact_id)

    assert str(tmp_path) not in str(raised.value)


def test_per_type_limits_and_repository_defaults_are_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert MAX_DOCX_BYTES == 16 * 1024 * 1024
    assert MAX_ZIP_BYTES == 64 * 1024 * 1024
    assert MAX_PDF_BYTES == 32 * 1024 * 1024
    assert MAX_MARKDOWN_BYTES == 8 * 1024 * 1024
    assert MAX_TEXT_BYTES == 8 * 1024 * 1024
    assert MAX_HTML_BYTES == 16 * 1024 * 1024
    assert MAX_LATEX_BYTES == 8 * 1024 * 1024
    assert MAX_CSV_BYTES == 16 * 1024 * 1024
    assert DEFAULT_MAX_TOTAL_BYTES == 2 * 1024 * 1024 * 1024
    store = ArtifactStore(tmp_path)

    # Lower only the test-local lookup entry to exercise the same branch without
    # allocating a 64 MiB fixture.
    from gongwen_mcp import artifacts

    monkeypatch.setitem(artifacts._LIMIT_BY_MIME, DOCX_MIME, 3)
    monkeypatch.setitem(artifacts._LIMIT_BY_MIME, ZIP_MIME, 5)
    with pytest.raises(ArtifactTooLarge):
        store.put(b"1234", filename="large.docx", mime=DOCX_MIME)
    with pytest.raises(ArtifactTooLarge):
        store.put(b"123456", filename="large.zip", mime=ZIP_MIME)
    for mime in (PDF_MIME, MARKDOWN_MIME, TEXT_MIME, HTML_MIME, LATEX_MIME, CSV_MIME):
        monkeypatch.setitem(artifacts._LIMIT_BY_MIME, mime, 1)
        with pytest.raises(ArtifactTooLarge):
            store.put(b"12", filename="large", mime=mime)
    with pytest.raises(UnsupportedArtifactType):
        store.put(b"x", filename="payload.bin", mime="application/octet-stream")


def test_metadata_is_commit_marker_and_failed_commit_leaves_no_payload(tmp_path: Path) -> None:
    backend = _FailMetadataStorage(tmp_path / "exports")
    store = ArtifactStore(storage=backend)

    with pytest.raises(OSError, match="fixture metadata failure"):
        store.put(b"PK", filename="atomic.docx", mime=DOCX_MIME)

    assert {item.key for item in backend.list_objects()} <= {".gongwen-artifacts.lock"}


def test_cleanup_expires_then_evicts_oldest_to_meet_capacity(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 9, 4, tzinfo=UTC))
    store = ArtifactStore(tmp_path, clock=clock, ttl_seconds=10, max_total_bytes=6)
    first = store.put(b"1111", filename="first.docx", mime=DOCX_MIME)
    clock.value += timedelta(seconds=1)

    second = store.put(b"2222", filename="second.docx", mime=DOCX_MIME)

    with pytest.raises(ArtifactNotFound):
        store.read_bytes(first.artifact_id)
    assert store.read_bytes(second.artifact_id) == b"2222"
    assert store.cleanup().remaining_bytes == 4

    clock.value += timedelta(seconds=11)
    result = store.cleanup()
    assert result.removed_artifact_ids == (second.artifact_id,)
    assert result.removed_count == 1
    assert result.reclaimed_bytes == 4
    assert result.remaining_bytes == 0
    with pytest.raises(ArtifactNotFound):
        store.get_metadata(second.artifact_id)


def test_duplicate_payloads_receive_distinct_stable_ids(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    first = store.put(b"same", filename="same.docx", mime=DOCX_MIME)
    second = store.put_bytes(b"same", filename="same.docx", mime=DOCX_MIME)

    assert first.artifact_id != second.artifact_id
    assert store.get_metadata(first.artifact_id).artifact_id == first.artifact_id
    assert store.get_metadata(second.artifact_id).artifact_id == second.artifact_id


def test_payload_integrity_is_checked_on_read(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    metadata = store.put(b"original", filename="document.docx", mime=DOCX_MIME)
    backend = LocalStorage(tmp_path / "exports")
    backend.put_bytes(f"{metadata.artifact_id}.docx", b"tampered", content_type=DOCX_MIME)

    with pytest.raises(ArtifactCorrupt, match="digest"):
        store.read_bytes(metadata.artifact_id)


def test_two_store_instances_serialize_quota_commit_and_cleanup(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    commit_barrier = threading.Barrier(2)
    inventory_barrier = threading.Barrier(2)
    stores = tuple(
        ArtifactStore(
            storage=_CoordinatedQuotaStorage(
                exports,
                commit_barrier=commit_barrier,
                inventory_barrier=inventory_barrier,
            ),
            max_total_bytes=4,
        )
        for _ in range(2)
    )
    start = threading.Barrier(3)

    def write(store: ArtifactStore, payload: bytes) -> str:
        start.wait(timeout=2)
        return store.put(payload, filename="race.docx", mime=DOCX_MIME).artifact_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(write, stores[0], b"1111"),
            executor.submit(write, stores[1], b"2222"),
        ]
        start.wait(timeout=2)
        artifact_ids = {future.result(timeout=5) for future in futures}

    payloads = list(exports.glob("*.docx"))
    sidecars = list(exports.glob("*.json"))
    assert len(payloads) == 1
    assert len(sidecars) == 1
    assert payloads[0].stem == sidecars[0].stem
    assert payloads[0].stem in artifact_ids

    restarted = ArtifactStore(tmp_path, max_total_bytes=4)
    assert restarted.read_bytes(payloads[0].stem) in {b"1111", b"2222"}
    assert restarted.cleanup().remaining_bytes == 4


def test_cleanup_removes_stale_temp_files_but_not_fresh_or_lock_files(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 4, 12, tzinfo=UTC)
    store = ArtifactStore(tmp_path, clock=_Clock(now), max_total_bytes=1)
    exports = tmp_path / "exports"
    stale = exports / ".yanzhang-tmp-stale"
    fresh = exports / ".yanzhang-tmp-fresh"
    lock_file = exports / ".gongwen-artifacts.lock"
    stale.write_bytes(b"stale-remnant")
    fresh.write_bytes(b"active")
    lock_file.write_bytes(b"lock-marker")
    stale_time = now - timedelta(seconds=STALE_TEMP_GRACE_SECONDS + 1)
    os.utime(stale, (stale_time.timestamp(), stale_time.timestamp()))
    os.utime(fresh, (now.timestamp(), now.timestamp()))

    result = store.cleanup(now=now)

    assert not stale.exists()
    assert fresh.read_bytes() == b"active"
    assert lock_file.exists()
    assert result.removed_count == 0
    assert result.reclaimed_bytes == len(b"stale-remnant")
    assert result.remaining_bytes == 0
