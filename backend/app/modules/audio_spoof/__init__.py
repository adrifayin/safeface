"""audio.spoof: synthetic-speech (voice clone / TTS) indicator with AASIST (SRS FR-4.1).

AASIST (Jung et al., ICASSP 2022), trained on ASVspoof 2019 LA. Input follows
the authors' code: 16 kHz mono waveform in windows of 64,600 samples (~4 s),
short clips padded by repetition. Spoof probability = softmax channel 0
(channel 1 is "bona fide" in the authors' scoring). Applies to audio files
and to the audio track of videos.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.modules._common.imaging import Array, r6, save_plot
from app.modules._common.media import audio_pcm, tools_available
from app.modules._common.speech import speech_segments, vad_available
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

RATE = 16000
WINDOW = 64600
THRESHOLD = 0.5
AASIST_CONFIG = {
    "architecture": "AASIST", "nb_samp": 64600, "first_conv": 128,
    "filts": [70, [1, 32], [32, 32], [32, 64], [64, 64]], "gat_dims": [64, 32],
    "pool_ratios": [0.5, 0.7, 0.5, 0.5], "temperatures": [2.0, 2.0, 100.0, 100.0],
}
_cache: dict[str, Any] = {}


def pad_repeat(x: Array, n: int = WINDOW) -> Array:
    """The authors' ``pad``: tile short clips, truncate long ones."""
    if x.shape[0] >= n:
        return x[:n]
    return np.tile(x, int(n / max(1, x.shape[0])) + 1)[:n]


class AudioSpoof(ModuleBase):
    id = "audio.spoof"
    version = "1.0.0"
    name = "Synthetic-speech indicator (AASIST)"
    description = ("AASIST anti-spoofing network on ~4-second windows (2-second hop) of the 16 kHz audio that are "
                   "mostly speech (Silero voice-activity detection); per-segment spoof scores and a timeline.")
    family = Family.AUDIO
    media_types = {MediaType.AUDIO, MediaType.VIDEO}  # noqa: RUF012
    tier = 1
    requires_gpu = True
    triage_indicator = True
    screening_core = True
    required_weights = ["aasist"]  # noqa: RUF012
    default_params = {"hop_seconds": 2.0, "max_seconds": 600}  # noqa: RUF012
    headline = ("segments_above_threshold", 0.25)
    plain = 'AI tool that estimates whether the voice is synthetic or cloned.'
    limitations = (
        "TRIAGE INDICATOR ONLY. Trained on ASVspoof 2019 studio-quality English speech from older TTS and "
        "voice-conversion systems; accuracy drops sharply on in-the-wild audio, phone and messaging-app codecs, "
        "background noise, music, non-English speech and modern voice clones. Silence and non-speech segments "
        "give meaningless scores. Not a speaker identification."
    )

    def availability(self) -> Availability:
        if not torch_available():
            return Availability(False, "PyTorch is not installed in this image")
        ok, reason = tools_available()
        return Availability(False, reason) if not ok else super().availability()

    def screen(self, scores: dict[str, float | None], details: dict[str, Any]) -> str | None:
        frac = scores.get("segments_above_threshold")
        if frac is not None and frac >= 0.25:
            return f"AASIST synthetic-speech score >= 0.50 on {frac * 100:.0f}% of audio segments (threshold: 25%)"
        return None

    def _model(self) -> tuple[Any, str]:
        from app.modules._vendor.aasist import Model

        state, sha, _ = load_checkpoint("aasist")
        if sha not in _cache:
            net = Model(AASIST_CONFIG)
            net.load_state_dict(strip_prefix(state), strict=True)
            _cache.clear()
            _cache[sha] = net.to(device()).eval()
        return _cache[sha], sha

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        import torch

        p = self.merged_params(params)
        pcm = audio_pcm(item.path, RATE, int(p["max_seconds"]))
        if pcm is None or pcm.size < RATE // 2:
            return Finding(scores=[Score("segments_analysed", 0.0, None, "No usable audio track.")],
                           summary="No audio track (or less than 0.5 s of audio): nothing to analyse.",
                           limitations=self.limitations)
        net, sha = self._model()
        # Score only windows that contain speech: AASIST's output on music, tones or silence is meaningless
        # (a pure tone scores ~1.0), so non-speech must never raise a doubt.
        speech: list[tuple[float, float]] | None = None
        if vad_available().available:
            speech = speech_segments(pcm, RATE)
            if not speech:
                return Finding(scores=[Score("segments_analysed", 0.0, None, "No speech detected by the VAD.")],
                               summary="No speech detected (voice-activity detection), so AASIST was not applied.",
                               limitations=self.limitations, provenance={"weights": {"aasist": sha}, "vad": "silero (bundled)"})
        hop = int(float(p["hop_seconds"]) * RATE)
        starts = list(range(0, max(1, pcm.size - WINDOW + 1), hop)) or [0]

        def speech_fraction(s: int) -> float:
            if speech is None:
                return 1.0
            a, b = s / RATE, (s + WINDOW) / RATE
            return sum(max(0.0, min(b, e) - max(a, st)) for st, e in speech) / (b - a)

        starts = [s for s in starts if speech_fraction(s) >= 0.5] or ([starts[0]] if speech is None else [])
        if not starts:
            return Finding(scores=[Score("segments_analysed", 0.0, None, "No 4 s window is mostly speech.")],
                           summary="Speech segments are too short or sparse for AASIST windows.",
                           limitations=self.limitations, provenance={"weights": {"aasist": sha}})
        times, scores_ = [], []
        mode = "strict"
        for s in starts:
            x = torch.from_numpy(pad_repeat(pcm[s:s + WINDOW]).astype(np.float32))[None].to(device())
            def spoof_prob(x: Any = x) -> float:
                return float(net(x)[1].softmax(1)[0, 0].item())

            prob, mode = deterministic_forward(spoof_prob)
            times.append(round(s / RATE, 3))
            scores_.append(r6(prob))
        arr = np.array(scores_)
        save_plot({"data": [{"type": "scatter", "mode": "lines+markers", "name": "AASIST", "x": times, "y": scores_}],
                   "layout": {"title": "Synthetic-speech indicator per 4 s segment", "xaxis": {"title": "segment start (s)"},
                              "yaxis": {"title": "spoof score", "range": [0, 1]}}}, item.workdir / "aasist_timeline.json")
        return Finding(
            scores=[
                Score("segments_analysed", float(len(scores_)), None, "Number of ~4 s windows scored."),
                Score("max_spoof_score", r6(arr.max()), (0, 1), "Highest segment score (triage indicator)."),
                Score("mean_spoof_score", r6(arr.mean()), (0, 1), "Mean segment score."),
                Score("segments_above_threshold", r6((arr >= THRESHOLD).mean()), (0, 1),
                      f"Fraction of segments scoring >= {THRESHOLD}."),
            ],
            summary=(f"{len(scores_)} segment(s) over {pcm.size / RATE:.1f} s of audio; highest spoof score "
                     f"{arr.max():.2f}, mean {arr.mean():.2f}. Indicator only."),
            limitations=self.limitations,
            artefacts=[Artefact("aasist_timeline.json", item.workdir / "aasist_timeline.json", ArtefactKind.PLOT,
                                "AASIST score per segment", "application/json")],
            details={"segments": [{"t": t, "score": v} for t, v in zip(times, scores_, strict=True)],
                     "audio_seconds": r6(pcm.size / RATE),
                     "speech_regions": [[r6(a), r6(b)] for a, b in speech] if speech is not None else "VAD unavailable"},
            provenance={"weights": {"aasist": sha}, "determinism_mode": mode,
                        "vad": "silero (bundled with faster-whisper)" if speech is not None else "none"},
        )


MODULE = AudioSpoof()
