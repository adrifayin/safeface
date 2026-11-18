"""Evidence hashing: SHA-256 (primary) and MD5 (legacy compatibility).

MD5 is recorded only because many courts and older tools still expect it; it
is never used for any security decision. SHA-256 is authoritative.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Digests:
    """Hashes and size of one byte stream."""

    sha256: str
    md5: str
    size: int


class StreamHasher:
    """Incrementally hash a stream with SHA-256 and MD5 at the same time."""

    def __init__(self) -> None:
        self._sha256 = hashlib.sha256()
        self._md5 = hashlib.md5(usedforsecurity=False)
        self._size = 0

    def update(self, chunk: bytes) -> None:
        self._sha256.update(chunk)
        self._md5.update(chunk)
        self._size += len(chunk)

    @property
    def size(self) -> int:
        return self._size

    def result(self) -> Digests:
        return Digests(self._sha256.hexdigest(), self._md5.hexdigest(), self._size)


def hash_chunks(chunks: Iterable[bytes]) -> Digests:
    hasher = StreamHasher()
    for chunk in chunks:
        hasher.update(chunk)
    return hasher.result()


def hash_file(path: Path) -> Digests:
    with path.open("rb") as fh:
        return hash_chunks(iter(lambda: fh.read(CHUNK), b""))


def sha256_file(path: Path) -> str:
    return hash_file(path).sha256


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
