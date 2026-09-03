"""Filesystem-backed asset storage with traversal and symlink protection."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .base import (
    InvalidStorageKey,
    ObjectNotFoundError,
    StorageBackend,
    StoredObject,
    normalize_key,
)


class LocalStorage(StorageBackend):
    """Store assets underneath one absolute filesystem root.

    Paths are treated as portable POSIX object keys.  Absolute paths,
    ``..`` components, backslashes, and paths escaping through a symlink are
    rejected.  Writes use a temporary sibling followed by ``os.replace`` so a
    reader sees either the old object or the complete new object.
    """

    def __init__(self, root: str | os.PathLike[str], *, create: bool = True) -> None:
        self._root = Path(root).expanduser().resolve(strict=False)
        if create:
            self._root.mkdir(parents=True, exist_ok=True)
        if self._root.exists() and not self._root.is_dir():
            raise NotADirectoryError(self._root)

    @property
    def root(self) -> Path:
        return self._root

    def resolve_path(self, key: str | os.PathLike[str]) -> Path:
        """Resolve *key* below the root, checking existing symlink components."""

        normalized = normalize_key(key)
        candidate = self._root.joinpath(*normalized.split("/"))
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise InvalidStorageKey(f"storage key escapes root: {normalized!r}") from exc
        return resolved

    # A concise compatibility name used by callers that need a local Path.
    path_for = resolve_path

    def _metadata(
        self,
        key: str,
        path: Path,
        *,
        content_type: str | None = None,
        etag: str | None = None,
    ) -> StoredObject:
        try:
            info = path.stat()
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(key) from exc
        if not path.is_file():
            raise ObjectNotFoundError(key)
        guessed_type = content_type or mimetypes.guess_type(key)[0]
        return StoredObject(
            key=key,
            size=info.st_size,
            content_type=guessed_type,
            etag=etag,
            last_modified=datetime.fromtimestamp(info.st_mtime, tz=UTC),
            uri=path.as_uri(),
        )

    def put_bytes(
        self,
        key: str | os.PathLike[str],
        data: bytes | bytearray | memoryview,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        normalized = normalize_key(key)
        path = self.resolve_path(normalized)
        payload = bytes(data)

        path.parent.mkdir(parents=True, exist_ok=True)
        # Re-resolve after mkdir: a pre-existing parent could have been a
        # symlink and a concurrent actor may have replaced a component.
        path = self.resolve_path(normalized)
        path.parent.mkdir(parents=True, exist_ok=True)

        descriptor, temporary_name = tempfile.mkstemp(prefix=".yanzhang-tmp-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

        digest = hashlib.sha256(payload).hexdigest()
        return self._metadata(normalized, path, content_type=content_type, etag=f"sha256:{digest}")

    def read_bytes(self, key: str | os.PathLike[str]) -> bytes:
        normalized = normalize_key(key)
        path = self.resolve_path(normalized)
        try:
            if not path.is_file():
                raise ObjectNotFoundError(normalized)
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(normalized) from exc

    def stat(self, key: str | os.PathLike[str]) -> StoredObject:
        normalized = normalize_key(key)
        return self._metadata(normalized, self.resolve_path(normalized))

    def exists(self, key: str | os.PathLike[str]) -> bool:
        path = self.resolve_path(key)
        return path.is_file()

    def delete(self, key: str | os.PathLike[str], *, missing_ok: bool = True) -> bool:
        normalized = normalize_key(key)
        path = self.resolve_path(normalized)
        try:
            path.unlink()
        except FileNotFoundError:
            if missing_ok:
                return False
            raise ObjectNotFoundError(normalized) from None
        except IsADirectoryError:
            if missing_ok:
                return False
            raise ObjectNotFoundError(normalized) from None

        # Tidy empty object directories without ever removing the root.
        parent = path.parent
        while parent != self._root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
        return True

    def list_objects(self, prefix: str = "") -> Iterable[StoredObject]:
        normalized_prefix = normalize_key(prefix, allow_empty=True)
        if not self._root.is_dir():
            return ()

        def objects() -> Iterable[StoredObject]:
            for path in sorted(self._root.rglob("*")):
                if not path.is_file():
                    continue
                try:
                    resolved = path.resolve(strict=True)
                    resolved.relative_to(self._root)
                except (OSError, ValueError):
                    # Ignore broken or escaping symlinks rather than exposing
                    # anything outside the configured asset root.
                    continue
                key = path.relative_to(self._root).as_posix()
                if key.startswith(".yanzhang-tmp-") or "/.yanzhang-tmp-" in key:
                    continue
                if normalized_prefix and not key.startswith(normalized_prefix):
                    continue
                yield self._metadata(key, resolved)

        return objects()

    def uri_for(self, key: str | os.PathLike[str]) -> str:
        return self.resolve_path(key).as_uri()

    def put_file(
        self,
        key: str | os.PathLike[str],
        source: str | os.PathLike[str],
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        """Copy a file into storage using the same atomic write path."""

        return self.put_bytes(key, Path(source).read_bytes(), content_type=content_type)

    def export_file(
        self,
        key: str | os.PathLike[str],
        destination: str | os.PathLike[str],
        *,
        overwrite: bool = False,
    ) -> Path:
        """Copy an object to a caller-selected destination."""

        target = Path(destination).expanduser()
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.read_bytes(key))
        return target


__all__ = ["LocalStorage"]
