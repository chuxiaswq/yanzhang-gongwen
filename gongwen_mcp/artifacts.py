"""Bounded, persistent storage for MCP-generated document exports.

Artifact payloads are written through :class:`storage.LocalStorage`, whose
temporary-file-and-replace implementation keeps readers from observing a
partial file.  A metadata sidecar is published last and acts as the commit
marker for the artifact.  Caller-provided filenames are display metadata only;
filesystem keys are derived exclusively from random, validated identifiers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Literal, Self

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on non-POSIX platforms
    fcntl = None  # type: ignore[assignment]

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gongwen_web.docx import unique_filename
from gongwen_web.storage import default_data_dir
from yanzhang.storage import LocalStorage, ObjectNotFoundError, StorageBackend, StoredObject

DOCX_MIME: Final = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ZIP_MIME: Final = "application/zip"
ArtifactMime = Literal[
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/zip",
]

MAX_DOCX_BYTES: Final = 16 * 1024 * 1024
MAX_ZIP_BYTES: Final = 64 * 1024 * 1024
DEFAULT_TTL_SECONDS: Final = 24 * 60 * 60
DEFAULT_MAX_TOTAL_BYTES: Final = 2 * 1024 * 1024 * 1024
STALE_TEMP_GRACE_SECONDS: Final = 60 * 60

_ARTIFACT_ID = re.compile(r"[0-9a-f]{32}\Z")
_METADATA_KEY = re.compile(r"(?P<artifact_id>[0-9a-f]{32})\.json\Z")
_PAYLOAD_KEY = re.compile(r"(?P<artifact_id>[0-9a-f]{32})\.(?:docx|zip)\Z")
_LOCK_FILENAME: Final = ".gongwen-artifacts.lock"
_TEMP_PREFIX: Final = ".yanzhang-tmp-"
_EXTENSION_BY_MIME: Final[dict[str, str]] = {
    DOCX_MIME: ".docx",
    ZIP_MIME: ".zip",
}
_LIMIT_BY_MIME: Final[dict[str, int]] = {
    DOCX_MIME: MAX_DOCX_BYTES,
    ZIP_MIME: MAX_ZIP_BYTES,
}

_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}


class ArtifactError(RuntimeError):
    """Base class for artifact repository errors."""


class InvalidArtifactId(ArtifactError, ValueError):
    """Raised when an artifact id is not one opaque lowercase-hex segment."""


class UnsupportedArtifactType(ArtifactError, ValueError):
    """Raised when a payload is not a supported export type."""


class ArtifactTooLarge(ArtifactError, ValueError):
    """Raised when an export exceeds its per-type or repository budget."""


class ArtifactNotFound(ArtifactError, FileNotFoundError):
    """Raised when an artifact id does not identify a committed export."""


class ArtifactCorrupt(ArtifactError):
    """Raised when persisted metadata and payload bytes disagree."""


class ArtifactMetadata(BaseModel):
    """Public, path-free metadata for one generated export."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    filename: str = Field(min_length=1, max_length=90)
    mime: ArtifactMime
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resource_uri: str
    created_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _validate_identity_and_lifetime(self) -> Self:
        expected_uri = artifact_resource_uri(self.artifact_id)
        if self.resource_uri != expected_uri:
            raise ValueError("artifact resource URI does not match its id")
        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("artifact timestamps must include a timezone")
        if self.expires_at <= self.created_at:
            raise ValueError("artifact expiry must be later than creation")
        return self


class CleanupResult(BaseModel):
    """Summary of one expiry and capacity cleanup pass."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    removed_artifact_ids: tuple[str, ...] = ()
    removed_count: int = Field(ge=0)
    reclaimed_bytes: int = Field(ge=0)
    remaining_bytes: int = Field(ge=0)


class _InventoryItem(BaseModel):
    """Internal cleanup record; keys never cross the public MCP boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    artifact_id: str
    payload_key: str
    metadata_key: str | None
    created_at: datetime
    expires_at: datetime
    size: int


def artifact_resource_uri(artifact_id: str) -> str:
    """Build the stable MCP resource URI for a validated artifact id."""

    validated = _validate_artifact_id(artifact_id)
    return f"gongwen://exports/{validated}"


class ArtifactStore:
    """Persistent, size-bounded repository for DOCX and ZIP export bytes.

    ``data_dir`` is the application's persistent data directory; objects are
    always kept in its ``exports`` child.  Supplying ``storage`` is intended for
    deterministic tests and alternate local implementations already rooted at
    the desired exports directory.
    """

    def __init__(
        self,
        data_dir: str | os.PathLike[str] | None = None,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        clock: Callable[[], datetime] | None = None,
        storage: StorageBackend | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be positive")
        if storage is not None and data_dir is not None:
            raise ValueError("provide data_dir or storage, not both")

        if storage is None:
            base = Path(data_dir).expanduser() if data_dir is not None else default_data_dir()
            storage = LocalStorage(base / "exports")
        self._storage = storage
        self._ttl_seconds = ttl_seconds
        self._max_total_bytes = max_total_bytes
        self._clock = clock or _utc_now
        self._lock = threading.RLock()
        self._local_root = storage.root if isinstance(storage, LocalStorage) else None
        self._process_lock = _shared_process_lock(storage)
        # Construction is explicit, so it is also a convenient bounded place to
        # collect exports left by an earlier process.
        self.cleanup()

    def put(
        self,
        data: bytes | bytearray | memoryview,
        *,
        filename: str,
        mime: str,
        ttl_seconds: int | None = None,
    ) -> ArtifactMetadata:
        """Atomically persist an export and return public metadata for it."""

        normalized_mime = _normalize_mime(mime)
        limit = _LIMIT_BY_MIME[normalized_mime]
        data_size = memoryview(data).nbytes
        if data_size > limit:
            raise ArtifactTooLarge(
                f"{normalized_mime} export is {data_size} bytes; limit is {limit} bytes"
            )
        if data_size > self._max_total_bytes:
            raise ArtifactTooLarge(
                f"export is {data_size} bytes; repository limit is {self._max_total_bytes} bytes"
            )
        lifetime = self._ttl_seconds if ttl_seconds is None else ttl_seconds
        if lifetime <= 0:
            raise ValueError("ttl_seconds must be positive")

        payload = bytes(data)
        now = self._now()
        extension = _EXTENSION_BY_MIME[normalized_mime]
        display_filename = unique_filename(filename, suffix=extension)

        with self._repository_lock():
            self._cleanup_unlocked(now=now)
            artifact_id = self._new_artifact_id()
            metadata = ArtifactMetadata(
                artifact_id=artifact_id,
                filename=display_filename,
                mime=normalized_mime,
                size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                resource_uri=artifact_resource_uri(artifact_id),
                created_at=now,
                expires_at=now + timedelta(seconds=lifetime),
            )
            payload_key = self._payload_key(artifact_id, normalized_mime)
            metadata_key = self._metadata_key(artifact_id)
            try:
                # The payload is complete before its JSON commit marker becomes
                # visible.  Both individual writes are atomic in LocalStorage.
                self._storage.put_bytes(payload_key, payload, content_type=normalized_mime)
                self._storage.put_bytes(
                    metadata_key,
                    _metadata_bytes(metadata),
                    content_type="application/json",
                )
            except BaseException:
                self._storage.delete(metadata_key, missing_ok=True)
                self._storage.delete(payload_key, missing_ok=True)
                raise

            self._cleanup_unlocked(now=now, protected_artifact_id=artifact_id)
            return metadata

    def put_bytes(
        self,
        data: bytes | bytearray | memoryview,
        *,
        filename: str,
        mime: str,
        ttl_seconds: int | None = None,
    ) -> ArtifactMetadata:
        """Compatibility spelling for :meth:`put`."""

        return self.put(data, filename=filename, mime=mime, ttl_seconds=ttl_seconds)

    def get_metadata(self, artifact_id: str) -> ArtifactMetadata:
        """Return persisted public metadata for an unexpired artifact."""

        validated = _validate_artifact_id(artifact_id)
        with self._repository_lock():
            self._cleanup_unlocked(now=self._now())
            return self._load_metadata(validated)

    def read_bytes(self, artifact_id: str) -> bytes:
        """Read and integrity-check a committed artifact by opaque id."""

        validated = _validate_artifact_id(artifact_id)
        with self._repository_lock():
            self._cleanup_unlocked(now=self._now())
            metadata = self._load_metadata(validated)
            payload_key = self._payload_key(validated, metadata.mime)
            try:
                payload = self._storage.read_bytes(payload_key)
            except ObjectNotFoundError as exc:
                raise ArtifactCorrupt(f"artifact payload is missing: {validated}") from exc
            if len(payload) != metadata.size:
                raise ArtifactCorrupt(f"artifact size does not match metadata: {validated}")
            digest = hashlib.sha256(payload).hexdigest()
            if digest != metadata.sha256:
                raise ArtifactCorrupt(f"artifact digest does not match metadata: {validated}")
            return payload

    def read(self, artifact_id: str) -> bytes:
        """Concise compatibility spelling for :meth:`read_bytes`."""

        return self.read_bytes(artifact_id)

    def delete(self, artifact_id: str, *, missing_ok: bool = True) -> bool:
        """Delete one artifact without accepting a path-like identifier."""

        validated = _validate_artifact_id(artifact_id)
        with self._repository_lock():
            removed, _ = self._delete_artifact(validated)
        if not removed and not missing_ok:
            raise ArtifactNotFound(validated)
        return removed

    def cleanup(self, *, now: datetime | None = None) -> CleanupResult:
        """Delete expired exports, then oldest exports until under the cap."""

        cleanup_time = self._normalize_time(now) if now is not None else self._now()
        with self._repository_lock():
            return self._cleanup_unlocked(now=cleanup_time)

    def _cleanup_unlocked(
        self,
        *,
        now: datetime,
        protected_artifact_id: str | None = None,
    ) -> CleanupResult:
        stale_temp_bytes = self._cleanup_stale_temp_files(now)
        inventory, invalid_ids = self._inventory(now)
        removed_ids: list[str] = []
        reclaimed = stale_temp_bytes

        for artifact_id in sorted(invalid_ids):
            removed, removed_bytes = self._delete_artifact(artifact_id)
            if removed:
                removed_ids.append(artifact_id)
                reclaimed += removed_bytes

        retained: list[_InventoryItem] = []
        for item in inventory:
            if item.expires_at <= now and item.artifact_id != protected_artifact_id:
                removed, removed_bytes = self._delete_artifact(item.artifact_id)
                if removed:
                    removed_ids.append(item.artifact_id)
                    reclaimed += removed_bytes
                continue
            retained.append(item)

        total = sum(item.size for item in retained)
        for item in sorted(retained, key=lambda value: (value.created_at, value.artifact_id)):
            if total <= self._max_total_bytes:
                break
            if item.artifact_id == protected_artifact_id:
                continue
            removed, removed_bytes = self._delete_artifact(item.artifact_id)
            if removed:
                removed_ids.append(item.artifact_id)
                reclaimed += removed_bytes
                total -= item.size

        return CleanupResult(
            removed_artifact_ids=tuple(dict.fromkeys(removed_ids)),
            removed_count=len(set(removed_ids)),
            reclaimed_bytes=reclaimed,
            remaining_bytes=max(total, 0),
        )

    def _inventory(self, now: datetime) -> tuple[list[_InventoryItem], set[str]]:
        objects = [item for item in self._storage.list_objects() if item.key != _LOCK_FILENAME]
        by_key = {item.key: item for item in objects}
        inventory: list[_InventoryItem] = []
        invalid_ids: set[str] = set()
        claimed_payloads: set[str] = set()

        for item in objects:
            match = _METADATA_KEY.fullmatch(item.key)
            if match is None:
                continue
            artifact_id = match.group("artifact_id")
            try:
                metadata = self._load_metadata(artifact_id)
                payload_key = self._payload_key(artifact_id, metadata.mime)
                payload_object = by_key[payload_key]
            except (ArtifactError, KeyError, ValueError):
                invalid_ids.add(artifact_id)
                continue
            claimed_payloads.add(payload_key)
            inventory.append(
                _InventoryItem(
                    artifact_id=artifact_id,
                    payload_key=payload_key,
                    metadata_key=item.key,
                    created_at=metadata.created_at.astimezone(UTC),
                    expires_at=metadata.expires_at.astimezone(UTC),
                    size=payload_object.size,
                )
            )

        # A crash after payload publication but before the metadata commit can
        # leave an orphan.  It participates in TTL/cap cleanup by its mtime.
        for item in objects:
            match = _PAYLOAD_KEY.fullmatch(item.key)
            if match is None or item.key in claimed_payloads:
                continue
            artifact_id = match.group("artifact_id")
            if artifact_id in invalid_ids:
                continue
            created_at = _object_time(item, fallback=now)
            inventory.append(
                _InventoryItem(
                    artifact_id=artifact_id,
                    payload_key=item.key,
                    metadata_key=None,
                    created_at=created_at,
                    expires_at=created_at + timedelta(seconds=self._ttl_seconds),
                    size=item.size,
                )
            )
        return inventory, invalid_ids

    def _cleanup_stale_temp_files(self, now: datetime) -> int:
        """Remove old LocalStorage crash remnants while holding the repository lock."""

        root = self._local_root
        if root is None or not root.is_dir():
            return 0
        cutoff = now.timestamp() - STALE_TEMP_GRACE_SECONDS
        reclaimed = 0
        for candidate in root.rglob(f"{_TEMP_PREFIX}*"):
            try:
                info = candidate.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_mtime > cutoff:
                    continue
                resolved_parent = candidate.parent.resolve(strict=True)
                resolved_parent.relative_to(root)
                candidate.unlink()
            except (FileNotFoundError, OSError, ValueError):
                continue
            reclaimed += info.st_size
        return reclaimed

    @contextmanager
    def _repository_lock(self) -> Iterator[None]:
        """Serialize inventory, commit, and quota cleanup across stores and processes."""

        with self._process_lock, self._lock:
            descriptor = self._acquire_file_lock()
            try:
                yield
            finally:
                _release_file_lock(descriptor)

    def _acquire_file_lock(self) -> int | None:
        root = self._local_root
        if root is None or fcntl is None:
            return None
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(root / _LOCK_FILENAME, flags, 0o600)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ArtifactError("artifact repository lock is not a regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except ArtifactError:
            if descriptor is not None:
                os.close(descriptor)
            raise
        except OSError as exc:
            if descriptor is not None:
                os.close(descriptor)
            raise ArtifactError("artifact repository lock is unavailable") from exc
        return descriptor

    def _load_metadata(self, artifact_id: str) -> ArtifactMetadata:
        metadata_key = self._metadata_key(artifact_id)
        try:
            raw = self._storage.read_bytes(metadata_key)
        except ObjectNotFoundError as exc:
            raise ArtifactNotFound(artifact_id) from exc
        try:
            metadata = ArtifactMetadata.model_validate_json(raw)
        except ValueError as exc:
            raise ArtifactCorrupt(f"artifact metadata is invalid: {artifact_id}") from exc
        if metadata.artifact_id != artifact_id:
            raise ArtifactCorrupt(f"artifact metadata id mismatch: {artifact_id}")
        return metadata

    def _delete_artifact(self, artifact_id: str) -> tuple[bool, int]:
        removed = False
        reclaimed = 0
        for extension in _EXTENSION_BY_MIME.values():
            payload_key = f"{artifact_id}{extension}"
            try:
                stored = self._storage.stat(payload_key)
            except ObjectNotFoundError:
                stored = None
            if self._storage.delete(payload_key, missing_ok=True):
                removed = True
                if stored is not None:
                    reclaimed += stored.size
        if self._storage.delete(self._metadata_key(artifact_id), missing_ok=True):
            removed = True
        return removed, reclaimed

    def _new_artifact_id(self) -> str:
        for _ in range(100):
            artifact_id = uuid.uuid4().hex
            if self._storage.exists(self._metadata_key(artifact_id)):
                continue
            if any(
                self._storage.exists(f"{artifact_id}{extension}")
                for extension in _EXTENSION_BY_MIME.values()
            ):
                continue
            return artifact_id
        raise ArtifactError("could not allocate a unique artifact id")

    def _payload_key(self, artifact_id: str, mime: str) -> str:
        validated = _validate_artifact_id(artifact_id)
        normalized_mime = _normalize_mime(mime)
        return f"{validated}{_EXTENSION_BY_MIME[normalized_mime]}"

    def _metadata_key(self, artifact_id: str) -> str:
        return f"{_validate_artifact_id(artifact_id)}.json"

    def _now(self) -> datetime:
        return self._normalize_time(self._clock())

    @staticmethod
    def _normalize_time(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)


def _shared_process_lock(storage: StorageBackend) -> threading.RLock:
    """Return one in-process lock for every view of the same local repository."""

    identity = (
        f"local:{storage.root}"
        if isinstance(storage, LocalStorage)
        else f"storage-object:{id(storage)}"
    )
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(identity)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_LOCKS[identity] = lock
        return lock


def _release_file_lock(descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        # Closing the descriptor releases a POSIX flock even if an explicit
        # unlock reports an interrupted or filesystem-specific error.
        pass
    finally:
        os.close(descriptor)


def _validate_artifact_id(artifact_id: str) -> str:
    if not isinstance(artifact_id, str) or _ARTIFACT_ID.fullmatch(artifact_id) is None:
        raise InvalidArtifactId("artifact id must be exactly 32 lowercase hexadecimal characters")
    return artifact_id


def _normalize_mime(mime: str) -> ArtifactMime:
    normalized = mime.strip().casefold()
    if normalized == DOCX_MIME:
        return DOCX_MIME
    if normalized == ZIP_MIME:
        return ZIP_MIME
    raise UnsupportedArtifactType(f"unsupported artifact MIME type: {mime!r}")


def _metadata_bytes(metadata: ArtifactMetadata) -> bytes:
    value = metadata.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _object_time(item: StoredObject, *, fallback: datetime) -> datetime:
    if item.last_modified is None:
        return fallback
    if item.last_modified.tzinfo is None:
        return item.last_modified.replace(tzinfo=UTC)
    return item.last_modified.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "DEFAULT_MAX_TOTAL_BYTES",
    "DEFAULT_TTL_SECONDS",
    "DOCX_MIME",
    "MAX_DOCX_BYTES",
    "MAX_ZIP_BYTES",
    "STALE_TEMP_GRACE_SECONDS",
    "ZIP_MIME",
    "ArtifactCorrupt",
    "ArtifactError",
    "ArtifactMetadata",
    "ArtifactNotFound",
    "ArtifactStore",
    "ArtifactTooLarge",
    "CleanupResult",
    "InvalidArtifactId",
    "UnsupportedArtifactType",
    "artifact_resource_uri",
]
