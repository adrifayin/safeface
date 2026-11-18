"""Hashes must match independent tools (SRS acceptance: 'matches sha256sum')."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.hashing import StreamHasher, hash_chunks, hash_file
from tests.conftest import FIXTURES


@pytest.mark.parametrize("name", ["scene_original.jpg", "scene_edited.jpg", "scene_original.png"])
def test_hash_matches_sha256sum_and_md5sum(name: str) -> None:
    path = FIXTURES / name
    digests = hash_file(path)
    if shutil.which("sha256sum"):
        out = subprocess.run(["sha256sum", str(path)], capture_output=True, text=True, check=True)
        assert digests.sha256 == out.stdout.split()[0]
        out = subprocess.run(["md5sum", str(path)], capture_output=True, text=True, check=True)
        assert digests.md5 == out.stdout.split()[0]
    data = path.read_bytes()
    assert digests.sha256 == hashlib.sha256(data).hexdigest()
    assert digests.md5 == hashlib.md5(data).hexdigest()
    assert digests.size == len(data)


def test_chunking_does_not_change_hash(tmp_path: Path) -> None:
    data = bytes(range(256)) * 10_000
    whole = hash_chunks([data])
    for size in (1, 7, 4096, 1_000_003):
        h = StreamHasher()
        for i in range(0, len(data), size):
            h.update(data[i : i + size])
        assert h.result() == whole


def test_known_vector() -> None:
    d = hash_chunks([b"abc"])
    assert d.sha256 == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert d.md5 == "900150983cd24fb0d6963f7d28e17f72"
