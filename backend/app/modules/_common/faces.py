"""Face detection and identity embeddings (InsightFace ONNX models, checksum-verified).

SafeFace loads the two model files individually from the registry instead of
using InsightFace's ``FaceAnalysis`` (which would load every .onnx in the
folder unverified and download missing models).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from app.modules._common.imaging import Array
from app.modules.base import Availability
from app.modules.weights import resolve, weights_availability

DETECTOR = "insightface-det-10g"
RECOGNISER = "insightface-w600k-r50"
_models: dict[str, Any] = {}


def detector_available() -> Availability:
    return weights_availability([DETECTOR])


def recogniser_available() -> Availability:
    return weights_availability([DETECTOR, RECOGNISER])


def load_detector() -> tuple[Any, str]:
    path, sha = resolve(DETECTOR)
    if ("det", sha) not in _models:
        from insightface.model_zoo import model_zoo

        det = model_zoo.get_model(str(path), providers=["CPUExecutionProvider"])
        det.prepare(ctx_id=-1, input_size=(640, 640), det_thresh=0.5)
        _models[("det", sha)] = det
    return _models[("det", sha)], sha


def load_recogniser() -> tuple[Any, str]:
    path, sha = resolve(RECOGNISER)
    if ("rec", sha) not in _models:
        from insightface.model_zoo import model_zoo

        rec = model_zoo.get_model(str(path), providers=["CPUExecutionProvider"])
        rec.prepare(ctx_id=-1)
        _models[("rec", sha)] = rec
    return _models[("rec", sha)], sha


@dataclass(frozen=True)
class Face:
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 in pixels
    score: float
    landmarks: Array

    @property
    def area(self) -> float:
        return max(0.0, self.box[2] - self.box[0]) * max(0.0, self.box[3] - self.box[1])


def detect(det: Any, rgb: Array) -> list[Face]:
    bgr = np.ascontiguousarray(rgb[:, :, ::-1])
    boxes, kps = det.detect(bgr, max_num=0, metric="default")
    if boxes is None:
        return []
    faces = [Face((float(b[0]), float(b[1]), float(b[2]), float(b[3])), float(b[4]), kps[i])
             for i, b in enumerate(boxes)]
    return sorted(faces, key=lambda f: (-f.area, f.box))


def embedding(rec: Any, rgb: Array, face: Face) -> Array:
    from insightface.utils import face_align

    bgr = np.ascontiguousarray(rgb[:, :, ::-1])
    crop = face_align.norm_crop(bgr, landmark=face.landmarks, image_size=rec.input_size[0])
    emb = np.asarray(rec.get_feat(crop), dtype=np.float64).flatten()
    return emb / (np.linalg.norm(emb) + 1e-12)


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def track(per_frame: list[tuple[float, list[Face]]], min_iou: float = 0.3) -> list[list[tuple[float, Face]]]:
    """Greedy IoU tracking of faces across sampled frames (deterministic order)."""
    tracks: list[list[tuple[float, Face]]] = []
    for t, faces in per_frame:
        free = list(range(len(tracks)))
        for face in faces:
            best, best_iou = None, min_iou
            for k in free:
                overlap = iou(tracks[k][-1][1].box, face.box)
                if overlap >= best_iou:
                    best, best_iou = k, overlap
            if best is None:
                tracks.append([(t, face)])
            else:
                tracks[best].append((t, face))
                free.remove(best)
    return tracks


LANDMARKS = "insightface-2d106det"
MOUTH = slice(52, 72)  # points 52–71 of InsightFace's 106-point layout: the lips


def landmarks_available() -> Availability:
    return weights_availability([DETECTOR, LANDMARKS])


def load_landmarker() -> tuple[Any, str]:
    path, sha = resolve(LANDMARKS)
    if ("lmk", sha) not in _models:
        from insightface.model_zoo import model_zoo

        lmk = model_zoo.get_model(str(path), providers=["CPUExecutionProvider"])
        lmk.prepare(ctx_id=-1)
        _models[("lmk", sha)] = lmk
    return _models[("lmk", sha)], sha


def landmarks106(lmk: Any, rgb: Array, face: Face) -> Array:
    from insightface.app.common import Face as IFace

    bgr = np.ascontiguousarray(rgb[:, :, ::-1])
    f = IFace(bbox=np.array(face.box, dtype=np.float32), kps=face.landmarks, det_score=face.score)
    return np.asarray(lmk.get(bgr, f), dtype=np.float64)


def mouth_opening(points: Array) -> float:
    """Height / width of the lip points: rises when the mouth opens, falls at lip closure."""
    m = points[MOUTH]
    width = float(m[:, 0].max() - m[:, 0].min()) or 1e-9
    return float(m[:, 1].max() - m[:, 1].min()) / width
