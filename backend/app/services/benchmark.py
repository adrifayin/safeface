"""Phase 4 benchmark: measure a module on a labelled test set (SRS FR-6.4, TDD §6.2).

Dataset layout (supplied by the user, e.g. Deepfake-Eval-2024 or the team test set; never committed),
under ``SAFEFACE_DATASETS_DIR/<name>/``:
    real/*                 authentic items (label 0)
    fake/*                 generated or manipulated items (label 1)
    masks/<stem>.png       optional ground-truth masks (white = manipulated) for localization

Metrics: AUC, TPR at 1% and 5% FPR (false accusations matter most), expected calibration error, and
pixel F1/IoU at 0.5 for modules that save a raw localization map (.npy). Robustness: the same metrics
after JPEG quality 70, 50% resize, and a messaging-app-like round trip (long side 1600 px + JPEG 75).
"""

from __future__ import annotations

import io
import itertools
import shutil
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from app.core.environment import set_deterministic
from app.core.hashing import hash_file
from app.modules.base import MediaType, WorkingCopy
from app.modules.registry import get_module

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}
# Score each module is judged on (higher = more likely manipulated or generated).
PRIMARY = {
    "image.aigen.univfd": "probability_generated", "image.aigen.npr": "probability_generated",
    "image.trufor": "integrity_score", "video.aigen": "npr_max", "video.face_frame_scores": "max_face_score",
    "audio.spoof": "max_spoof_score", "image.jpeg_ghost": "inconsistent_area_fraction",
}
ROBUSTNESS = ("jpeg70", "resize50", "messaging")


Arr = np.ndarray[Any, Any]


def roc(scores: Arr, labels: Arr) -> tuple[Arr, Arr]:
    order = np.argsort(-scores, kind="mergesort")
    s, y = scores[order], labels[order]
    distinct = np.r_[np.where(np.diff(s))[0], y.size - 1]
    tps = np.cumsum(y)[distinct]
    fps = np.cumsum(1 - y)[distinct]
    return np.r_[0, fps / max(1, (1 - y).sum())], np.r_[0, tps / max(1, y.sum())]


def auc(scores: np.ndarray[Any, Any], labels: np.ndarray[Any, Any]) -> float:
    fpr, tpr = roc(scores, labels)
    return float(np.trapz(tpr, fpr))


def tpr_at(scores: np.ndarray[Any, Any], labels: np.ndarray[Any, Any], max_fpr: float) -> float:
    fpr, tpr = roc(scores, labels)
    ok = fpr <= max_fpr
    return float(tpr[ok].max()) if ok.any() else 0.0


def ece(scores: np.ndarray[Any, Any], labels: np.ndarray[Any, Any], bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in itertools.pairwise(edges):
        m = (scores >= lo) & ((scores < hi) if hi < 1 else (scores <= hi))
        if m.any():
            total += float(m.mean() * abs(scores[m].mean() - labels[m].mean()))
    return total


def f1_iou(pred: np.ndarray[Any, Any], mask: np.ndarray[Any, Any]) -> tuple[float, float]:
    tp = float((pred & mask).sum())
    fp = float((pred & ~mask).sum())
    fn = float((~pred & mask).sum())
    return 2 * tp / max(1.0, 2 * tp + fp + fn), tp / max(1.0, tp + fp + fn)


def perturb(src: Path, kind: str, dst: Path) -> Path:
    from PIL import Image

    im = Image.open(src).convert("RGB")
    if kind == "jpeg70":
        out = dst.with_suffix(".jpg")
        im.save(out, "JPEG", quality=70)
    elif kind == "resize50":
        out = dst.with_suffix(".png")
        im.resize((max(1, im.width // 2), max(1, im.height // 2)), Image.Resampling.BILINEAR).save(out)
    elif kind == "messaging":
        scale = min(1.0, 1600 / max(im.size))
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.Resampling.BILINEAR)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=75)
        out = dst.with_suffix(".jpg")
        out.write_bytes(buf.getvalue())
    else:
        raise ValueError(kind)
    return out


def media_type(path: Path) -> MediaType | None:
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return MediaType.IMAGE
    if ext in VIDEO_EXT:
        return MediaType.VIDEO
    if ext in AUDIO_EXT:
        return MediaType.AUDIO
    return None


def dataset_items(root: Path) -> list[tuple[Path, int]]:
    items = [(p, 0) for p in sorted((root / "real").glob("*")) if media_type(p)]
    return items + [(p, 1) for p in sorted((root / "fake").glob("*")) if media_type(p)]


def list_datasets(base: Path) -> list[dict[str, Any]]:
    if not base.is_dir():
        return []
    out = []
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        items = dataset_items(d)
        if items:
            out.append({"name": d.name, "items": len(items), "fake": sum(lbl for _, lbl in items),
                        "masks": (d / "masks").is_dir()})
    return out


def evaluate(module_id: str, items: list[tuple[Path, int]], masks: Path | None,
             transform: str | None) -> dict[str, Any]:
    module = get_module(module_id)
    key = PRIMARY.get(module_id)
    if key is None:
        raise ValueError(f"no primary score defined for {module_id}")
    scores, labels, f1s, ious, failed = [], [], [], [], 0
    for path, label in items:
        mt = media_type(path)
        if mt is None or mt not in module.media_types or (transform and mt != MediaType.IMAGE):
            continue
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            src = perturb(path, transform, t / "perturbed") if transform else path
            (t / "out").mkdir()
            dest = t / f"item{src.suffix.lower()}"
            shutil.copyfile(src, dest)
            d = hash_file(dest)
            wc = WorkingCopy(path.stem, dest, d.sha256, d.md5, mt, path.name, "questioned", d.sha256, d.md5, t / "out")
            set_deterministic(0)
            try:
                finding = module.run(wc, [], {})
            except Exception:  # noqa: BLE001 - count and continue
                failed += 1
                continue
            value = next((s.value for s in finding.scores if s.name == key), None)
            if value is None:
                failed += 1
                continue
            scores.append(float(value))
            labels.append(label)
            npy = next((a.path for a in finding.artefacts if a.name.endswith(".npy")), None)
            mask_file = masks / f"{path.stem}.png" if masks else None
            if npy is not None and mask_file is not None and mask_file.exists() and transform is None:
                from PIL import Image

                pred = np.load(npy) >= 0.5
                gt = np.asarray(Image.open(mask_file).convert("L").resize(pred.shape[::-1])) > 127
                f1, iou = f1_iou(pred, gt)
                f1s.append(f1)
                ious.append(iou)
    s, y = np.array(scores), np.array(labels)
    result: dict[str, Any] = {"n": int(y.size), "n_fake": int(y.sum()), "n_failed": failed}
    if y.size and 0 < y.sum() < y.size:
        result.update(auc=round(auc(s, y), 4), tpr_at_1pct_fpr=round(tpr_at(s, y, 0.01), 4),
                      tpr_at_5pct_fpr=round(tpr_at(s, y, 0.05), 4), ece=round(ece(np.clip(s, 0, 1), y), 4))
    if f1s:
        result.update(pixel_f1=round(float(np.mean(f1s)), 4), pixel_iou=round(float(np.mean(ious)), 4))
    return result


def run_benchmark(module_id: str, root: Path, robustness: bool) -> dict[str, Any]:
    items = dataset_items(root)
    if not items:
        raise ValueError(f"no items under {root}/real and {root}/fake")
    masks = root / "masks" if (root / "masks").is_dir() else None
    record: dict[str, Any] = {"dataset": root.name, "module_version": get_module(module_id).version,
                              "primary_score": PRIMARY.get(module_id),
                              "clean": evaluate(module_id, items, masks, None)}
    if robustness:
        for kind in ROBUSTNESS:
            record[kind] = evaluate(module_id, items, None, kind)
    return record
