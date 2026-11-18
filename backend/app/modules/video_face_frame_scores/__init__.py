"""video.face_frame_scores: face-manipulation scores per frame with SBI (SRS FR-3.3).

Self-Blended Images detector (Shiohara & Yamasaki, CVPR 2022): EfficientNet-B4
trained to spot blending boundaries left by face swaps and reenactment.
Preprocessing follows the authors' inference code: face box enlarged by 1/8
on each side, resized to 380x380, RGB / 255, softmax channel 1 = "fakeness".
The authors use RetinaFace for detection; SafeFace uses InsightFace SCRFD.
Also applies to still images (single "frame").
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.modules._common import faces
from app.modules._common.imaging import Array, load_rgb, r6, save_plot, save_png
from app.modules._common.media import contact_sheet, load_frame, sample_frames, tools_available
from app.modules._common.torchutil import deterministic_forward, device, load_checkpoint, strip_prefix, torch_available
from app.modules.base import (
    Artefact,
    ArtefactKind,
    Availability,
    Family,
    Finding,
    MediaType,
    ModuleBase,
    Score,
    WorkingCopy,
)

THRESHOLD = 0.5
_cache: dict[str, Any] = {}


def sbi_crop(rgb: Array, face: faces.Face, size: int = 380) -> Array:
    """SBI test-time crop: bbox + 1/8 margin each side (crop_face(..., phase='test'))."""
    import cv2

    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = face.box
    bw, bh = x1 - x0, y1 - y0
    mx, my = bw / 8, bh / 8
    crop = rgb[max(0, int(y0 - my)):min(h, int(y1 + my) + 1), max(0, int(x0 - mx)):min(w, int(x1 + mx) + 1)]
    return cv2.resize(crop, (size, size))


class FaceFrameScores(ModuleBase):
    id = "video.face_frame_scores"
    version = "1.0.0"
    name = "Face-swap indicator (SBI)"
    description = ("Self-Blended Images detector (EfficientNet-B4) on every detected face in sampled frames; "
                   "per-frame score timeline and the most suspicious faces.")
    family = Family.AI_DETECTOR
    media_types = {MediaType.VIDEO, MediaType.IMAGE}  # noqa: RUF012
    tier = 1
    requires_gpu = True
    triage_indicator = True
    screening_core = True
    required_weights = [faces.DETECTOR, "sbi"]  # noqa: RUF012
    default_params = {"fps": 1.0, "max_frames": 60}  # noqa: RUF012
    headline = ("max_face_score", 0.5)
    plain = 'AI tool that looks for signs of a swapped or altered face.'
    limitations = (
        "TRIAGE INDICATOR ONLY. Face region only: manipulations elsewhere in the frame are not examined, and no "
        "face means no result. Trained on FaceForensics++ face swaps; accuracy drops on newer generators, heavy "
        "compression, low resolution and unusual poses. SafeFace uses a different face detector from the authors "
        "(SCRFD instead of RetinaFace), so crops differ slightly. Research licence (non-commercial)."
    )

    def availability(self) -> Availability:
        if not torch_available():
            return Availability(False, "PyTorch is not installed in this image")
        ok, reason = tools_available()
        return Availability(False, reason) if not ok else super().availability()

    def screen(self, scores: dict[str, float | None], details: dict[str, Any]) -> str | None:
        frac = scores.get("frames_above_threshold")
        peak = scores.get("max_face_score")
        if frac is not None and frac >= 0.25:
            return f"SBI face-swap score >= 0.50 on {frac * 100:.0f}% of frames with faces (threshold: 25%)"
        if scores.get("frames_with_face") == 1 and peak is not None and peak >= THRESHOLD:
            return f"SBI face-swap score {peak:.2f} on the face (threshold 0.50)"
        return None

    def _model(self) -> tuple[Any, str]:
        from app.modules._vendor.efficientnet import EfficientNet

        state, sha, _ = load_checkpoint("sbi")
        if sha not in _cache:
            sd = state["model"] if isinstance(state, dict) and isinstance(state.get("model"), dict) else state
            sd = {k[len("net."):] if k.startswith("net.") else k: v for k, v in strip_prefix(sd).items()}
            net = EfficientNet.from_name("efficientnet-b4", num_classes=2)
            net.load_state_dict(sd, strict=True)
            _cache.clear()
            _cache[sha] = net.to(device()).eval()
        return _cache[sha], sha

    def score_faces(self, rgb: Array, det: Any) -> list[tuple[faces.Face, float]]:
        import torch

        found = faces.detect(det, rgb)
        if not found:
            return []
        net, _ = self._model()
        batch = np.stack([sbi_crop(rgb, f).transpose(2, 0, 1) for f in found]).astype(np.float32) / 255.0
        x = torch.from_numpy(batch).to(device())
        probs, _ = deterministic_forward(lambda: net(x).softmax(1)[:, 1].cpu().numpy().tolist())
        return list(zip(found, [float(p) for p in probs], strict=True))

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        p = self.merged_params(params)
        det, det_sha = faces.load_detector()
        _, sbi_sha = self._model()
        if item.media_type == MediaType.IMAGE:
            rgb, _ = load_rgb(item.path)
            frames = [(0.0, rgb)]
        else:
            frames = [(fr.t, load_frame(fr)) for fr in
                      sample_frames(item.path, item.workdir / "frames", float(p["fps"]), int(p["max_frames"]), 0)]
        times, per_frame_max, top = [], [], []
        for t, rgb in frames:
            scored = self.score_faces(rgb, det)
            if not scored:
                continue
            best_face, best = max(scored, key=lambda fs: fs[1])
            times.append(t)
            per_frame_max.append(r6(best))
            top.append((best, t, sbi_crop(rgb, best_face, 160)))
        out = item.workdir
        artefacts: list[Artefact] = []
        if per_frame_max:
            save_plot({"data": [{"type": "scatter", "mode": "lines+markers", "name": "SBI", "x": times, "y": per_frame_max}],
                       "layout": {"title": "Face-swap indicator per frame (highest face)",
                                  "xaxis": {"title": "time (s) — click to jump"}, "yaxis": {"title": "score", "range": [0, 1]}}},
                      out / "sbi_timeline.json")
            artefacts.append(Artefact("sbi_timeline.json", out / "sbi_timeline.json", ArtefactKind.PLOT,
                                      "SBI score per frame", "application/json"))
            best4 = sorted(top, key=lambda x: (-x[0], x[1]))[:4]
            save_png(contact_sheet([(f"t={t:.1f}s  {s:.2f}", crop) for s, t, crop in sorted(best4, key=lambda x: x[1])], 160),
                     out / "top_faces.png")
            artefacts.append(Artefact("top_faces.png", out / "top_faces.png", ArtefactKind.IMAGE,
                                      "Faces with the highest SBI scores"))
        arr = np.array(per_frame_max) if per_frame_max else None
        scores = [
            Score("frames_with_face", float(len(per_frame_max)), None, "Frames (or images) in which a face was scored."),
            Score("max_face_score", r6(arr.max()) if arr is not None else None, (0, 1),
                  "Highest SBI score of any face (triage indicator; higher = more like blended/swapped faces)."),
            Score("mean_frame_score", r6(arr.mean()) if arr is not None else None, (0, 1),
                  "Mean over frames of the highest face score (the authors' video-level score)."),
            Score("frames_above_threshold", r6((arr >= THRESHOLD).mean()) if arr is not None else None, (0, 1),
                  f"Fraction of frames with a face scoring >= {THRESHOLD}."),
        ]
        summary = (f"SBI scored faces in {len(per_frame_max)} of {len(frames)} frame(s); highest {arr.max():.2f}, "
                   f"mean {arr.mean():.2f}." if arr is not None else "No face was detected, so SBI produced no score.")
        return Finding(scores=scores, summary=summary, limitations=self.limitations, artefacts=artefacts,
                       details={"frames": [{"t": t, "score": s} for t, s in zip(times, per_frame_max, strict=True)]},
                       provenance={"weights": {faces.DETECTOR: det_sha, "sbi": sbi_sha}})


MODULE = FaceFrameScores()
