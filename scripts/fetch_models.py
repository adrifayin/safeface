#!/usr/bin/env python3
"""Fetch model weights on an INTERNET-CONNECTED build machine (never on the server).

Downloads each file listed below, checks it against the published SHA-256
where one exists, places it under models/ at the registry path, and records
newly computed hashes in models/registry.yaml (entries whose sha256 is null).
Copy the resulting models/ folder to the air-gapped server (see fetch_models.md).

Standard library only. Usage:
    python scripts/fetch_models.py [--only npr,univfd-fc] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
REGISTRY = MODELS / "registry.yaml"


@dataclass
class Item:
    name: str            # registry name
    dest: str            # path under models/
    kind: str            # url | url-zip-member | git-file | git-archive
    source: str          # URL or git repo
    member: str = ""     # zip member / file in repo / archive subpath
    commit: str = ""


ITEMS = [
    Item("clip-vit-l14", "clip/ViT-L-14.pt", "url",
         "https://openaipublic.azureedge.net/clip/models/b8cca3fd41ae0c99ba7e8951adf17d267cdb84cd88be6f7c2e0eca1737a03836/ViT-L-14.pt"),
    Item("univfd-fc", "univfd/fc_weights.pth", "git-file", "https://github.com/WisconsinAIVision/UniversalFakeDetect.git",
         member="pretrained_weights/fc_weights.pth", commit="030495aea3300a8b54c0ec37ec7fe1dd7e63c619"),
    Item("npr", "npr/NPR.pth", "git-file", "https://github.com/chuangchuangtan/NPR-DeepfakeDetection.git",
         member="NPR.pth", commit="781ced3f7ca2cdc69ec9dd4ef27e8d0b3c07752a"),
    Item("trufor-src", "trufor/trufor-src-ae54475.tar", "git-archive", "https://github.com/grip-unina/TruFor.git",
         member="test_docker/src", commit="ae54475df6f41a491d7615100feb19263dec13f7"),
    Item("trufor", "trufor/trufor.pth.tar", "url-zip-member",
         "https://www.grip.unina.it/download/prog/TruFor/TruFor_weights.zip", member="trufor.pth.tar"),
    Item("insightface-det-10g", "insightface/buffalo_l/det_10g.onnx", "url-zip-member",
         "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip", member="det_10g.onnx"),
    Item("insightface-2d106det", "insightface/buffalo_l/2d106det.onnx", "url-zip-member",
         "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip", member="2d106det.onnx"),
    Item("whisper-small-model", "whisper/small/model.bin", "url",
         "https://huggingface.co/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120/model.bin"),
    Item("whisper-small-config", "whisper/small/config.json", "url",
         "https://huggingface.co/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120/config.json"),
    Item("whisper-small-tokenizer", "whisper/small/tokenizer.json", "url",
         "https://huggingface.co/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120/tokenizer.json"),
    Item("whisper-small-vocabulary", "whisper/small/vocabulary.txt", "url",
         "https://huggingface.co/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120/vocabulary.txt"),
    Item("aasist", "aasist/AASIST.pth", "git-file", "https://github.com/clovaai/aasist.git",
         member="models/weights/AASIST.pth", commit="a04c9863f63d44471dde8a6abcb3b082b07cd1d1"),
    Item("sbi", "sbi/FFc23.tar", "url",
         "https://drive.usercontent.google.com/download?id=1X0-NYT8KPursLZZdxduRQju6E52hauV0&export=download&confirm=t"),
    Item("insightface-w600k-r50", "insightface/buffalo_l/w600k_r50.onnx", "url-zip-member",
         "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip", member="w600k_r50.onnx"),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str) -> bytes:
    print(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "model-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310 - fixed, reviewed URLs
        return resp.read()


_zip_cache: dict[str, bytes] = {}


def fetch(item: Item, out: Path, work: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if item.kind == "url":
        out.write_bytes(download(item.source))
    elif item.kind == "url-zip-member":
        data = _zip_cache.get(item.source) or download(item.source)
        _zip_cache[item.source] = data
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            name = next(n for n in zf.namelist() if n.rsplit("/", 1)[-1] == item.member)
            out.write_bytes(zf.read(name))
    elif item.kind in ("git-file", "git-archive"):
        repo = work / re.sub(r"\W", "_", item.source)
        if not repo.exists():
            subprocess.run(["git", "clone", "-q", "--filter=blob:none", item.source, str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "checkout", "-q", item.commit], check=True)
        if item.kind == "git-file":
            shutil.copyfile(repo / item.member, out)
        else:
            subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", "-o", str(out), item.commit, item.member],
                           check=True)
    else:
        raise ValueError(item.kind)


def registry_sha(text: str, name: str) -> str | None:
    m = re.search(rf"- name: {re.escape(name)}\n(?:.*\n)*?\s+sha256: (\S+)", text)
    return None if m is None or m.group(1) == "null" else m.group(1)


def record_sha(text: str, name: str, digest: str) -> str:
    pattern = rf"(- name: {re.escape(name)}\n(?:.*\n)*?\s+sha256: )null"
    return re.sub(pattern, rf"\g<1>{digest}  # recorded by fetch_models.py; second person to verify", text, count=1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    only = {s for s in args.only.split(",") if s}
    text = REGISTRY.read_text(encoding="utf-8").replace(chr(13) + chr(10), chr(10))
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        for item in ITEMS:
            if only and item.name not in only:
                continue
            out = MODELS / item.dest
            expected = registry_sha(text, item.name)
            print(f"[{item.name}]")
            try:
                if args.force or not out.exists():
                    fetch(item, out, Path(tmp))
                digest = sha256(out)
            except Exception as exc:  # noqa: BLE001 - report and continue with the others
                print(f"  FAILED: {exc}")
                failures += 1
                continue
            if expected and digest != expected:
                print(f"  CHECKSUM MISMATCH: got {digest}, registry has {expected}. File removed.")
                out.unlink()
                failures += 1
            elif expected:
                print(f"  ok, sha256 matches {digest}")
            else:
                text = record_sha(text, item.name, digest)
                print(f"  ok, recorded sha256 {digest}")
    REGISTRY.write_bytes(text.encode("utf-8"))  # keep LF line endings
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
