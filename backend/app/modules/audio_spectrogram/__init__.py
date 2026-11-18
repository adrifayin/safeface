"""audio.spectrogram: log-mel spectrogram and audio stream facts (SRS FR-4.2).

Computed with NumPy (STFT, Hann window, Slaney-style mel filterbank) so no
extra audio library is needed. Visual inspection aid for splices, abrupt
background changes, band-limiting and synthetic-speech artefacts.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.modules._common.imaging import colormap, r6, save_png
from app.modules._common.media import audio_pcm, audio_stream, ffprobe, tools_available
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


def mel_filterbank(n_mels: int, n_fft: int, rate: int) -> np.ndarray:
    def hz_to_mel(f: np.ndarray) -> np.ndarray:
        return 2595.0 * np.log10(1.0 + f / 700.0)

    mels = np.linspace(hz_to_mel(np.array(0.0)), hz_to_mel(np.array(rate / 2)), n_mels + 2)
    hz = 700.0 * (10 ** (mels / 2595.0) - 1.0)
    bins = np.floor((n_fft + 1) * hz / rate).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1))
    for m in range(1, n_mels + 1):
        lo, c, hi = bins[m - 1], bins[m], bins[m + 1]
        for k in range(lo, c):
            fb[m - 1, k] = (k - lo) / max(1, c - lo)
        for k in range(c, hi):
            fb[m - 1, k] = (hi - k) / max(1, hi - c)
    return fb


class AudioSpectrogram(ModuleBase):
    id = "audio.spectrogram"
    version = "1.0.0"
    name = "Spectrogram and audio metadata"
    description = "Log-mel spectrogram (25 ms Hann window, 10 ms hop, 80 bands) of the 16 kHz mono audio, plus stream facts."
    family = Family.AUDIO
    media_types = {MediaType.AUDIO, MediaType.VIDEO}  # noqa: RUF012
    tier = 2
    default_params = {"max_seconds": 300}  # noqa: RUF012
    headline = ("audio_seconds", None)
    plain = 'Picture of the sound over time, for the examiner to inspect.'
    limitations = ("Interpretation needs training. Resampling to 16 kHz removes content above 8 kHz; codecs "
                   "(MP3, AAC, Opus) leave their own band-limiting and artefacts that can resemble editing.")

    def availability(self) -> Availability:
        ok, reason = tools_available()
        return Availability(ok, reason)

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        p = self.merged_params(params)
        stream = audio_stream(ffprobe(item.path)) or {}
        pcm = audio_pcm(item.path, RATE, int(p["max_seconds"]))
        if pcm is None or pcm.size < 400:
            return Finding(scores=[Score("audio_seconds", 0.0, None, "No audio track.", "s")],
                           summary="No audio track.", limitations=self.limitations, details={"stream": stream})
        n_fft, hop = 400, 160
        frames = np.lib.stride_tricks.sliding_window_view(pcm, n_fft)[::hop] * np.hanning(n_fft)
        power = np.abs(np.fft.rfft(frames, axis=1)) ** 2
        mel = power @ mel_filterbank(80, n_fft, RATE).T
        db = 10 * np.log10(np.maximum(mel, 1e-10))
        norm = np.clip((db - (db.max() - 80)) / 80, 0, 1).T[::-1]  # low frequencies at the bottom
        img = colormap(norm, "inferno")
        if img.shape[1] > 4000:  # keep the figure a sensible size
            import cv2

            img = cv2.resize(img, (4000, img.shape[0] * 3), interpolation=cv2.INTER_AREA)
        else:
            img = np.repeat(img, 3, axis=0)
        save_png(img, item.workdir / "spectrogram.png")
        rms = float(np.sqrt(np.mean(pcm ** 2)))
        return Finding(
            scores=[
                Score("audio_seconds", r6(pcm.size / RATE), None, "Duration analysed.", "s"),
                Score("sample_rate_original", float(stream.get("sample_rate", 0) or 0) or None, None,
                      "Sample rate of the original audio stream.", "Hz"),
                Score("rms_level_dbfs", r6(20 * np.log10(max(rms, 1e-10))), None, "Average loudness.", "dBFS"),
            ],
            summary=f"{pcm.size / RATE:.1f} s of audio ({stream.get('codec_name', '?')}, {stream.get('sample_rate', '?')} Hz).",
            limitations=self.limitations,
            artefacts=[Artefact("spectrogram.png", item.workdir / "spectrogram.png", ArtefactKind.IMAGE,
                                "Log-mel spectrogram (time left to right, frequency bottom to top)")],
            details={"stream": stream},
        )


MODULE = AudioSpectrogram()
