"""Provider-neutral object storage interfaces."""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath


class StorageError(RuntimeError):
    """Base class for storage failures."""


class InvalidStorageKey(StorageError, ValueError):
    """Raised when an object key is empty, absolute, or traverses its root."""


class ObjectNotFoundError(StorageError, FileNotFoundError):
    """Raised when a requested object does not exist."""


class StorageConfigurationError(StorageError):
    """Raised when a backend is missing required configuration or dependencies."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Backend-neutral object metadata."""

    key: str
    size: int
    content_type: str | None = None
    etag: str | None = None
    last_modified: datetime | None = None
    uri: str | None = None


def normalize_key(key: str | os.PathLike[str], *, allow_empty: bool = False) -> str:
    """Normalize a portable object key and reject traversal constructs."""

    raw = os.fspath(key)
    if not isinstance(raw, str):
        raw = os.fsdecode(raw)
    if "\x00" in raw or "\\" in raw:
        raise InvalidStorageKey("storage keys may not contain NUL or backslash characters")
    if raw.startswith("/"):
        raise InvalidStorageKey(f"absolute storage key is not allowed: {raw!r}")
    if allow_empty:
        raw = raw.rstrip("/")
    if not raw:
        if allow_empty:
            return ""
        raise InvalidStorageKey("storage key must not be empty")

    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise InvalidStorageKey(f"unsafe storage key: {raw!r}")
    normalized = path.as_posix()
    if normalized in {"", "."}:
        if allow_empty:
            return ""
        raise InvalidStorageKey("storage key must not be empty")
    return normalized


class StorageBackend(ABC):
    """Small synchronous interface with non-blocking async adapters.

    Backends implement the synchronous primitives.  Their ``a*`` counterparts
    run those primitives in a worker thread, which keeps CLI code simple while
    remaining safe to call from async MCP and workflow handlers.
    """

    @abstractmethod
    def put_bytes(
        self,
        key: str | os.PathLike[str],
        data: bytes | bytearray | memoryview,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        """Store bytes under *key*, replacing an existing object atomically."""

    @abstractmethod
    def read_bytes(self, key: str | os.PathLike[str]) -> bytes:
        """Read an object's complete contents."""

    @abstractmethod
    def stat(self, key: str | os.PathLike[str]) -> StoredObject:
        """Return object metadata."""

    @abstractmethod
    def exists(self, key: str | os.PathLike[str]) -> bool:
        """Return whether *key* refers to a stored object."""

    @abstractmethod
    def delete(self, key: str | os.PathLike[str], *, missing_ok: bool = True) -> bool:
        """Delete *key* and return whether an object was removed."""

    @abstractmethod
    def list_objects(self, prefix: str = "") -> Iterable[StoredObject]:
        """Iterate metadata for objects whose keys start with *prefix*."""

    @abstractmethod
    def uri_for(self, key: str | os.PathLike[str]) -> str:
        """Return a stable local or remote URI for *key*."""

    def get(self, key: str | os.PathLike[str]) -> bytes:
        return self.read_bytes(key)

    def put(
        self,
        key: str | os.PathLike[str],
        data: bytes | bytearray | memoryview,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        return self.put_bytes(key, data, content_type=content_type)

    # Common repository terminology aliases.
    load = get
    save = put

    def read_text(self, key: str | os.PathLike[str], *, encoding: str = "utf-8") -> str:
        return self.read_bytes(key).decode(encoding)

    def write_text(
        self,
        key: str | os.PathLike[str],
        text: str,
        *,
        encoding: str = "utf-8",
        content_type: str | None = "text/plain",
    ) -> StoredObject:
        return self.put_bytes(key, text.encode(encoding), content_type=content_type)

    def list_keys(self, prefix: str = "") -> list[str]:
        return [item.key for item in self.list_objects(prefix)]

    async def aput_bytes(
        self,
        key: str | os.PathLike[str],
        data: bytes | bytearray | memoryview,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        return await asyncio.to_thread(self.put_bytes, key, data, content_type=content_type)

    async def aread_bytes(self, key: str | os.PathLike[str]) -> bytes:
        return await asyncio.to_thread(self.read_bytes, key)

    async def astat(self, key: str | os.PathLike[str]) -> StoredObject:
        return await asyncio.to_thread(self.stat, key)

    async def aexists(self, key: str | os.PathLike[str]) -> bool:
        return await asyncio.to_thread(self.exists, key)

    async def adelete(self, key: str | os.PathLike[str], *, missing_ok: bool = True) -> bool:
        return await asyncio.to_thread(self.delete, key, missing_ok=missing_ok)

    async def alist_objects(self, prefix: str = "") -> list[StoredObject]:
        return await asyncio.to_thread(lambda: list(self.list_objects(prefix)))

    async def aget(self, key: str | os.PathLike[str]) -> bytes:
        return await self.aread_bytes(key)

    async def aput(
        self,
        key: str | os.PathLike[str],
        data: bytes | bytearray | memoryview,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        return await self.aput_bytes(key, data, content_type=content_type)

    async def aread_text(self, key: str | os.PathLike[str], *, encoding: str = "utf-8") -> str:
        return (await self.aread_bytes(key)).decode(encoding)

    async def awrite_text(
        self,
        key: str | os.PathLike[str],
        text: str,
        *,
        encoding: str = "utf-8",
        content_type: str | None = "text/plain",
    ) -> StoredObject:
        return await self.aput_bytes(key, text.encode(encoding), content_type=content_type)


Storage = StorageBackend


__all__ = [
    "InvalidStorageKey",
    "ObjectNotFoundError",
    "Storage",
    "StorageBackend",
    "StorageConfigurationError",
    "StorageError",
    "StoredObject",
    "normalize_key",
]
