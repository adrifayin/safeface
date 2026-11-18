"""Mouth-opening time series for the main face in a video (InsightFace 106-point landmarks)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.modules._common import faces
from app.modules._common.imaging import Array
from app.modules._common.media import load_frame, sample_frames


@dataclass(frozen=True)
class MouthSeries:
    times: Array        # seconds
    opening: Array      # height/width of the lips; NaN where no face
    fps: float
    weights: dict[str, str]


def mouth_series(video: Path, workdir: Path, fps: float = 15.0, seconds: int = 60) -> MouthSeries:
    frames = sample_frames(video, workdir / "mouth_frames", fps, int(fps * seconds), 0, max_side=720)
    det, det_sha = faces.load_detector()
    lmk, lmk_sha = faces.load_landmarker()
    times, values = [], []
    for fr in frames:
        rgb = load_frame(fr)
        found = faces.detect(det, rgb)
        times.append(fr.t)
        values.append(faces.mouth_opening(faces.landmarks106(lmk, rgb, found[0])) if found else np.nan)
    return MouthSeries(np.array(times), np.array(values, dtype=np.float64), fps,
                       {faces.DETECTOR: det_sha, faces.LANDMARKS: lmk_sha})


def speech_envelope(pcm: Array, rate: int, times: Array, fps: float) -> Array:
    """RMS energy of the audio in a window of one video frame around each timestamp."""
    half = int(rate / fps / 2)
    out = []
    for t in times:
        c = int(t * rate)
        seg = pcm[max(0, c - half):c + half]
        out.append(float(np.sqrt(np.mean(seg ** 2))) if seg.size else 0.0)
    return np.array(out)
