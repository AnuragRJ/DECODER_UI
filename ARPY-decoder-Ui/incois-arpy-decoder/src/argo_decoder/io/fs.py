"""FileSystem abstraction (tiny protocol).

We only need a small subset of pathlib-like functionality; introducing this
protocol makes unit tests trivial (in-memory fs) and keeps the door open for
future S3/GCS-backed reference data.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class FileSystem(Protocol):
    def exists(self, path: str | Path) -> bool: ...
    def read_bytes(self, path: str | Path) -> bytes: ...
    def read_text(self, path: str | Path, encoding: str = "utf-8") -> str: ...
    def write_bytes(self, path: str | Path, data: bytes) -> None: ...
    def write_text(self, path: str | Path, text: str, encoding: str = "utf-8") -> None: ...
    def iterdir(self, path: str | Path) -> Iterable[Path]: ...
    def mkdir(self, path: str | Path, *, parents: bool = True, exist_ok: bool = True) -> None: ...


class LocalFileSystem:
    """Default FS backed by the local disk."""

    def exists(self, path: str | Path) -> bool:
        return Path(path).exists()

    def read_bytes(self, path: str | Path) -> bytes:
        return Path(path).read_bytes()

    def read_text(self, path: str | Path, encoding: str = "utf-8") -> str:
        return Path(path).read_text(encoding=encoding)

    def write_bytes(self, path: str | Path, data: bytes) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(data)

    def write_text(self, path: str | Path, text: str, encoding: str = "utf-8") -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding=encoding)

    def iterdir(self, path: str | Path) -> Iterable[Path]:
        yield from Path(path).iterdir()

    def mkdir(self, path: str | Path, *, parents: bool = True, exist_ok: bool = True) -> None:
        Path(path).mkdir(parents=parents, exist_ok=exist_ok)
