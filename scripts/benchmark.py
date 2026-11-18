"""Phase 4 benchmark runner: measure a module on a labelled test set (SRS FR-6.4, TDD §6.2).

Dataset layout (supplied by the user — e.g. Deepfake-Eval-2024 or the team test set; never committed):
    <dataset>/real/*      authentic items (label 0)
    <dataset>/fake/*      generated or manipulated items (label 1)
    <dataset>/masks/<stem>.png   optional ground-truth masks (white = manipulated) for localization

Metrics: AUC, TPR at 1% and 5% FPR (false accusations matter most), expected calibration error,
and — for modules that save a localization map — pixel F1 and IoU at 0.5. With --robustness the
same metrics are recomputed after JPEG quality 70, 50% resize, and a messaging-app-like round trip
(long side 1600 px + JPEG 75 + metadata stripped).

Results are written to models/validation.yaml under the module id; the API shows them beside every
score and reports print them. Run inside the worker image:

  docker run --rm -v "$PWD/models:/models" -v "$PWD/backend:/app" -v /path/to/set:/data:ro -w /app \
      safeface/worker:dev python /app/../scripts/benchmark.py --module image.aigen.npr --dataset /data
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, "/app")

from app.core.environment import set_deterministic  # noqa: E402
from app.core.hashing import hash_file  # noqa: E402
from app.modules.base import MediaType, WorkingCopy  # noqa: E402
from app.modules.registry import get_module  # noqa: E402

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}
# Which score a module is judged on (higher = more likely manipulated/generated).
PRIMARY = {
    "image.aigen.univfd": "probability_generated", "image.aigen.npr": "probability_generated",
    "image.trufor": "integrity_score", "video.aigen": "npr_max", "video.face_frame_scores": "max_face_score",
    "audio.spoof": "max_spoof_score", "image.jpeg_ghost": "inconsistent_area_fraction",
}


# --- metrics (NumPy only) ------------------------------------------------------------------------

def roc(scores: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(-scores, kind="mergesort")
    s, y = scores[order], labels[order]
    distinct = np.r_[np.where(np.diff(s))[0], y.size - 1]
    tps = np.cumsum(y)[distinct]
    fps = np.cumsum(1 - y)[distinct]
    tpr = np.r_[0, tps / max(1, y.sum())]
    fpr = np.r_[0, fps / max(1, (1 - y).sum())]
    return fpr, tpr


def auc(scores: np.ndarray, labels: np.ndarray) -> float:
    fpr, tpr = roc(scores, labels)
    return float(np.trapz(tpr, fpr))


def tpr_at(scores: np.ndarray, labels: np.ndarray, max_fpr: float) -> float:
    fpr, tpr = roc(scores, labels)
    ok = fpr <= max_fpr
    return float(tpr[ok].max()) if ok.any() else 0.0


def ece(scores: np.ndarray, labels: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (scores >= lo) & ((scores < hi) if hi < 1 else (scores <= hi))
        if m.any():
            total += m.mean() * abs(scores[m].mean() - labels[m].mean())
    return float(total)


def f1_iou(pred: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
    tp = float((pred & mask).sum())
    fp = float((pred & ~mask).sum())
    fn = float((~pred & mask).sum())
    f1 = 2 * tp / max(1.0, 2 * tp + fp + fn)
    iou = tp / max(1.0, tp + fp + fn)
    return f1, iou


# --- perturbations -------------------------------------------------------------------------------

def perturb(src: Path, kind: str, dst: Path) -> Path:
    from PIL import Image

    im = Image.open(src).convert("RGB")
    if kind == "jpeg70":
        im.save(dst.with_suffix(".jpg"), "JPEG", quality=70)
    elif kind == "resize50":
        im.resize((max(1, im.width // 2), max(1, im.height // 2)), Image.Resampling.BILINEAR).save(dst.with_suffix(".png"))
    elif kind == "messaging":
        scale = min(1.0, 1600 / max(im.size))
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.Resampling.BILINEAR)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=75)
        dst.with_suffix(".jpg").write_bytes(buf.getvalue())
    else:
        raise ValueError(kind)
    return next(p for p in dst.parent.glob(dst.stem + ".*"))


# --- runner --------------------------------------------------------------------------------------

def media_type(path: Path) -> MediaType | None:
    ext = path.suffix.lower()
    return MediaType.IMAGE if ext in IMAGE_EXT else MediaType.VIDEO if ext in VIDEO_EXT else \
        MediaType.AUDIO if ext in AUDIO_EXT else None


def evaluate(module_id: str, items: list[tuple[Path, int]], masks: Path | None, transform: str | None) -> dict[str, Any]:
    module = get_module(module_id)
    key = PRIMARY.get(module_id)
    if key is None:
        raise SystemExit(f"no primary score defined for {module_id}; add it to PRIMARY")
    scores, labels, f1s, ious, failed = [], [], [], [], 0
    for path, label in items:
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            src = path
            if transform:
                if media_type(path) != MediaType.IMAGE:
                    continue
                src = perturb(path, transform, t / "perturbed")
            (t / "out").mkdir()
            dest = t / f"item{src.suffix.lower()}"
            shutil.copyfile(src, dest)
            d = hash_file(dest)
            wc = WorkingCopy(path.stem, dest, d.sha256, d.md5, media_type(path) or MediaType.IMAGE, path.name,
                             "questioned", d.sha256, d.md5, t / "out")
            set_deterministic(0)
            try:
                finding = module.run(wc, [], {})
            except Exception as exc:  # noqa: BLE001 - count and continue
                print(f"  failed on {path.name}: {exc}")
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", required=True)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--name", default=None, help="dataset name recorded with the results")
    ap.add_argument("--robustness", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("/models/validation.yaml"))
    args = ap.parse_args()
    items = [(p, 0) for p in sorted((args.dataset / "real").glob("*")) if media_type(p)]
    items += [(p, 1) for p in sorted((args.dataset / "fake").glob("*")) if media_type(p)]
    if not items:
        raise SystemExit("no items found under real/ and fake/")
    masks = args.dataset / "masks" if (args.dataset / "masks").is_dir() else None
    record: dict[str, Any] = {
        "dataset": args.name or args.dataset.name, "module_version": get_module(args.module).version,
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "primary_score": PRIMARY.get(args.module), "clean": evaluate(args.module, items, masks, None),
    }
    if args.robustness:
        for kind in ("jpeg70", "resize50", "messaging"):
            record[kind] = evaluate(args.module, items, None, kind)
    print(json.dumps(record, indent=2))
    import yaml

    data = yaml.safe_load(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    data = data or {}
    data.setdefault(args.module, []).append(record)
    args.out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    print(f"results appended to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
