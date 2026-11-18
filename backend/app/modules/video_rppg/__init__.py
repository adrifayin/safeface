"""video.rppg: remote photoplethysmography consistency — EXPERIMENTAL (SRS FR-3.7).

Blood flow slightly changes skin colour with each heartbeat. For the main face
track the face is split into a 3x3 grid; the POS method (Wang et al., IEEE TBME
2017) gives a pulse signal per region, band-passed to 0.7–4 Hz (42–240 bpm).
In a real face all regions should share one dominant pulse frequency; low
spatial coherence can indicate a synthesised face.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.modules._common import faces
from app.modules._common.imaging import r6, save_plot
from app.modules._common.media import load_frame, sample_frames, tools_available
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


def pos(rgb_means: np.ndarray, fps: float) -> np.ndarray:
    """POS algorithm over a (T, 3) series of mean RGB values."""
    n = rgb_means.shape[0]
    win = max(2, int(1.6 * fps))
    h = np.zeros(n)
    proj = np.array([[0, 1, -1], [-2, 1, 1]], dtype=np.float64)
    for t in range(n - win + 1):
        c = rgb_means[t:t + win]
        cn = c / np.maximum(c.mean(axis=0), 1e-9)
        s = cn @ proj.T
        p = s[:, 0] + (s[:, 0].std() / max(s[:, 1].std(), 1e-9)) * s[:, 1]
        h[t:t + win] += p - p.mean()
    return h


def bandpass(x: np.ndarray, fps: float, lo: float = 0.7, hi: float = 4.0) -> np.ndarray:
    from scipy.signal import butter, filtfilt

    nyq = fps / 2
    b, a = butter(3, [lo / nyq, min(hi / nyq, 0.99)], btype="band")
    return filtfilt(b, a, x) if x.size > 3 * max(len(a), len(b)) else x


def dominant_hz(x: np.ndarray, fps: float) -> float:
    spec = np.abs(np.fft.rfft(x * np.hanning(x.size)))
    freqs = np.fft.rfftfreq(x.size, 1 / fps)
    band = (freqs >= 0.7) & (freqs <= 4.0)
    return float(freqs[band][np.argmax(spec[band])]) if band.any() else 0.0


class VideoRPPG(ModuleBase):
    id = "video.rppg"
    version = "1.0.0"
    name = "Pulse-signal consistency (rPPG) — EXPERIMENTAL"
    description = ("POS rPPG on a 3x3 grid of face regions over up to 20 s at 15 fps; dominant pulse frequency per "
                   "region and spatial coherence.")
    family = Family.AV
    media_types = {MediaType.VIDEO}  # noqa: RUF012
    tier = 2
    required_weights = [faces.DETECTOR]  # noqa: RUF012
    default_params = {"fps": 15.0, "seconds": 20}  # noqa: RUF012
    headline = ("spatial_coherence", None)
    plain = "EXPERIMENTAL: looks for a consistent pulse signal in the face's skin."
    limitations = (
        "EXPERIMENTAL — not validated for evidential use. High-quality deepfakes can inherit the pulse of the "
        "driving video, so a coherent pulse does NOT indicate authenticity. Compression, low light, make-up, motion, "
        "talking and lighting changes destroy the signal; a short clip or a small face gives meaningless results."
    )

    def availability(self) -> Availability:
        ok, reason = tools_available()
        return Availability(False, reason) if not ok else super().availability()

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        p = self.merged_params(params)
        fps = float(p["fps"])
        frames = sample_frames(item.path, item.workdir / "frames", fps, int(fps * int(p["seconds"])), 0, max_side=720)
        det, sha = faces.load_detector()
        series: list[np.ndarray] = []
        last_box = None
        for fr in frames:
            rgb = load_frame(fr)
            found = faces.detect(det, rgb)
            if found:
                last_box = found[0].box
            if last_box is None:
                continue
            x0, y0, x1, y1 = (int(v) for v in last_box)
            face = rgb[max(0, y0):max(0, y1), max(0, x0):max(0, x1)].astype(np.float64)
            if face.size == 0:
                continue
            hh, ww = face.shape[:2]
            cells = [face[i * hh // 3:(i + 1) * hh // 3, j * ww // 3:(j + 1) * ww // 3].reshape(-1, 3).mean(axis=0)
                     for i in range(3) for j in range(3)]
            series.append(np.array(cells))
        if len(series) < fps * 5:
            return Finding(scores=[Score("frames_with_face", float(len(series)), None, "Frames with the tracked face.")],
                           summary="Not enough frames with a visible face (needs at least 5 s) for rPPG.",
                           limitations=self.limitations, provenance={"weights": {faces.DETECTOR: sha}})
        data = np.stack(series)  # (T, 9, 3)
        signals = [bandpass(pos(data[:, k, :], fps), fps) for k in range(9)]
        freqs = np.array([dominant_hz(s, fps) for s in signals])
        median_f = float(np.median(freqs))
        coherence = float(np.mean(np.abs(freqs - median_f) <= 0.15))
        t = [round(i / fps, 3) for i in range(data.shape[0])]
        save_plot({"data": [{"type": "scatter", "mode": "lines", "name": f"region {k + 1}", "x": t,
                             "y": [r6(v) for v in signals[k]]} for k in range(9)],
                   "layout": {"title": "Band-passed pulse signal per face region (EXPERIMENTAL)",
                              "xaxis": {"title": "time (s)"}, "yaxis": {"title": "POS signal"}}},
                  item.workdir / "rppg_signals.json")
        return Finding(
            scores=[
                Score("frames_with_face", float(len(series)), None, "Frames used."),
                Score("median_pulse_bpm", r6(median_f * 60), (42, 240), "Median dominant frequency across regions.", "bpm"),
                Score("spatial_coherence", r6(coherence), (0, 1),
                      "Fraction of the 9 regions whose dominant frequency is within 9 bpm of the median. EXPERIMENTAL."),
            ],
            summary=(f"EXPERIMENTAL: median pulse {median_f * 60:.0f} bpm; {coherence * 100:.0f}% of face regions agree. "
                     "Not evidence of authenticity or manipulation on its own."),
            limitations=self.limitations,
            artefacts=[Artefact("rppg_signals.json", item.workdir / "rppg_signals.json", ArtefactKind.PLOT,
                                "Pulse signals per face region", "application/json")],
            details={"region_bpm": [r6(f * 60) for f in freqs]},
            provenance={"weights": {faces.DETECTOR: sha}},
        )


MODULE = VideoRPPG()
