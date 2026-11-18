"""video.av_sync: audio–visual synchrony of speech and lip movement (SRS FR-3.5).

Lip-synced deepfakes and dubbed audio often move the mouth out of step with
the speech. The module correlates the speech energy envelope with the
mouth-opening series of the main face, estimates the lag, and lists 2-second
speech windows where they do not move together.

Deviation from the TDD, stated plainly: the TDD proposes comparing an ASR
transcript with a visual-speech-recognition (lip-reading) transcript. No
offline lip-reading model is integrated, so this module measures timing
synchrony instead; word-level content is checked by video.phoneme_viseme.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.modules._common import faces
from app.modules._common.imaging import Array, r6, save_plot
from app.modules._common.media import audio_pcm, tools_available
from app.modules._common.mouth import mouth_series, speech_envelope
from app.modules._common.speech import speech_segments, vad_available
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

RATE = 16000


def zscore(x: Array) -> Array:
    return (x - x.mean()) / (x.std() or 1.0)


def lagged_corr(a: Array, b: Array, lag: int) -> float:
    if lag > 0:
        a, b = a[lag:], b[:-lag]
    elif lag < 0:
        a, b = a[:lag], b[-lag:]
    return float(np.corrcoef(a, b)[0, 1]) if a.size > 3 and a.std() > 0 and b.std() > 0 else 0.0


class AVSync(ModuleBase):
    id = "video.av_sync"
    version = "1.0.0"
    name = "Audio–visual speech synchrony"
    description = ("Cross-correlation of the speech energy envelope with the lip-opening series (InsightFace 106-point "
                   "landmarks, 15 fps): best lag, overall correlation and out-of-sync speech windows.")
    family = Family.AV
    media_types = {MediaType.VIDEO}  # noqa: RUF012
    tier = 2
    required_weights = [faces.DETECTOR, faces.LANDMARKS]  # noqa: RUF012
    default_params = {"fps": 15.0, "seconds": 60, "max_lag_ms": 500}  # noqa: RUF012
    headline = ("out_of_sync_fraction", 0.5)
    plain = 'Checks whether lip movement matches the speech in time.'
    limitations = (
        "Needs a clearly visible, mostly frontal speaking face and audible speech from that person. Off-screen "
        "speakers, voice-over, music, several speakers, masks, beards and low frame rates break the measure. "
        "Platform re-encoding can shift audio by tens of milliseconds. A lip-reading (VSR) comparison as proposed "
        "in the TDD is not implemented; this measures timing only."
    )

    def availability(self) -> Availability:
        ok, reason = tools_available()
        if not ok:
            return Availability(False, reason)
        vad = vad_available()
        return vad if not vad.available else super().availability()

    def screen(self, scores: dict[str, float | None], details: dict[str, Any]) -> str | None:
        lag, frac = scores.get("best_lag_ms"), scores.get("out_of_sync_fraction")
        if lag is not None and abs(lag) >= 200 and (scores.get("peak_correlation") or 0) >= 0.2:
            return f"Speech and lip movement are offset by {lag:.0f} ms (threshold 200 ms)"
        if frac is not None and frac >= 0.5 and (scores.get("speech_windows") or 0) >= 3:
            return f"Lips and speech do not move together in {frac * 100:.0f}% of speech windows (threshold 50%)"
        return None

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        p = self.merged_params(params)
        pcm = audio_pcm(item.path, RATE, int(p["seconds"]))
        if pcm is None:
            return Finding(scores=[Score("speech_windows", 0.0, None, "No audio track.")],
                           summary="No audio track: synchrony cannot be measured.", limitations=self.limitations)
        ms = mouth_series(item.path, item.workdir, float(p["fps"]), int(p["seconds"]))
        env = speech_envelope(pcm, RATE, ms.times, ms.fps)
        speech = speech_segments(pcm, RATE)
        valid = ~np.isnan(ms.opening)
        if valid.sum() < ms.fps * 3 or not speech:
            return Finding(scores=[Score("speech_windows", 0.0, None, "Not enough speech with a visible face.")],
                           summary="Not enough speech with a visible face (needs ≥ 3 s) to measure synchrony.",
                           limitations=self.limitations, provenance={"weights": ms.weights})
        mouth = np.where(valid, ms.opening, np.nanmedian(ms.opening))
        a, m = zscore(env), zscore(mouth)
        max_lag = int(float(p["max_lag_ms"]) / 1000 * ms.fps)
        corrs = {lag: lagged_corr(a, m, lag) for lag in range(-max_lag, max_lag + 1)}
        best = max(corrs, key=lambda k: (corrs[k], -abs(k)))
        windows = []
        step = int(2 * ms.fps)
        for start in range(0, len(ms.times) - step + 1, step):
            t0, t1 = ms.times[start], ms.times[start + step - 1]
            in_speech = sum(max(0.0, min(t1, e) - max(t0, s)) for s, e in speech) / max(t1 - t0, 1e-9)
            if in_speech < 0.6 or valid[start:start + step].mean() < 0.8:
                continue
            c = lagged_corr(a[start:start + step], m[start:start + step], best)
            windows.append({"start": r6(t0), "end": r6(t1), "correlation": r6(c), "out_of_sync": c < 0.1})
        frac = float(np.mean([w["out_of_sync"] for w in windows])) if windows else None
        save_plot({"data": [
            {"type": "scatter", "mode": "lines", "name": "speech energy (z)", "x": ms.times.tolist(), "y": [r6(v) for v in a]},
            {"type": "scatter", "mode": "lines", "name": "lip opening (z)", "x": ms.times.tolist(), "y": [r6(v) for v in m]}],
            "layout": {"title": "Speech energy vs lip opening", "xaxis": {"title": "time (s) — click to jump"}}},
            item.workdir / "av_sync.json")
        lag_ms = best / ms.fps * 1000
        return Finding(
            scores=[
                Score("peak_correlation", r6(corrs[best]), (-1, 1), "Correlation of speech energy and lip opening at the best lag."),
                Score("best_lag_ms", r6(lag_ms), None, "Lag that best aligns lips with speech (positive = audio later).", "ms"),
                Score("speech_windows", float(len(windows)), None, "2-second windows with speech and a visible face."),
                Score("out_of_sync_fraction", r6(frac) if frac is not None else None, (0, 1),
                      "Fraction of those windows where lips and speech do not move together (correlation < 0.1)."),
            ],
            summary=(f"Best alignment at {lag_ms:.0f} ms (correlation {corrs[best]:.2f}); "
                     f"{len(windows)} speech window(s)" + (f", {frac * 100:.0f}% out of sync." if frac is not None else ".")),
            limitations=self.limitations,
            artefacts=[Artefact("av_sync.json", item.workdir / "av_sync.json", ArtefactKind.PLOT,
                                "Speech energy and lip opening over time", "application/json")],
            details={"windows": windows, "speech_regions": [[r6(s), r6(e)] for s, e in speech]},
            provenance={"weights": ms.weights},
        )


MODULE = AVSync()
