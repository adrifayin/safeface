"""video.phoneme_viseme: lip closure on bilabial sounds M, B, P (SRS FR-3.6).

After Agarwal et al. (CVPR-W 2020, "Detecting deep-fake videos from
phoneme–viseme mismatches"): to say M, B or P the lips must close. Whisper
gives word timings; for words that begin with a bilabial sound the mouth
opening is checked around the word onset. Lip-sync deepfakes often fail to
close the lips.

Bilabial onsets are approximated from spelling: English m/b/p and Malayalam
മ ബ പ ഭ ഫ. Forced phoneme alignment is approximated by Whisper word timings.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.modules._common import faces
from app.modules._common.imaging import r6
from app.modules._common.media import audio_pcm, tools_available
from app.modules._common.mouth import mouth_series
from app.modules._common.speech import WHISPER_FILES, asr_available, transcribe
from app.modules.base import Availability, Family, Finding, MediaType, ModuleBase, Score, WorkingCopy

RATE = 16000
BILABIAL_START = ("m", "b", "p", "മ", "ബ", "പ", "ഭ", "ഫ")


class PhonemeViseme(ModuleBase):
    id = "video.phoneme_viseme"
    version = "1.0.0"
    name = "Lip closure on M/B/P sounds"
    description = ("Whisper word timings + lip opening from 106-point landmarks: for words starting with a bilabial "
                   "sound, is the mouth closed near the word onset?")
    family = Family.AV
    media_types = {MediaType.VIDEO}  # noqa: RUF012
    tier = 2
    required_weights = [faces.DETECTOR, faces.LANDMARKS, *WHISPER_FILES]  # noqa: RUF012
    default_params = {"fps": 25.0, "seconds": 60, "closure_ratio": 0.6}  # noqa: RUF012
    headline = ("closure_failure_rate", 0.5)
    plain = "Checks the lips close on 'm', 'b' and 'p' sounds, as real speech requires."
    limitations = (
        "Needs a visible, frontal, unobstructed mouth and clear speech from that person. Bilabial onsets are guessed "
        "from spelling (English and Malayalam only); Whisper timings can be off by ~100 ms, and fast speech, "
        "co-articulation, low frame rates or compression can hide a real closure. Count failures only when many "
        "bilabial words were checked."
    )

    def availability(self) -> Availability:
        ok, reason = tools_available()
        if not ok:
            return Availability(False, reason)
        asr = asr_available()
        return asr if not asr.available else super().availability()

    def screen(self, scores: dict[str, float | None], details: dict[str, Any]) -> str | None:
        n, rate = scores.get("bilabial_words_checked") or 0, scores.get("closure_failure_rate")
        if n >= 5 and rate is not None and rate >= 0.5:
            return f"Lips did not close on {rate * 100:.0f}% of {n:.0f} M/B/P words (threshold 50%, minimum 5 words)"
        return None

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        p = self.merged_params(params)
        pcm = audio_pcm(item.path, RATE, int(p["seconds"]))
        if pcm is None:
            return Finding(scores=[Score("bilabial_words_checked", 0.0, None, "No audio track.")],
                           summary="No audio track.", limitations=self.limitations)
        words, language, whisper_hashes = transcribe(pcm)
        ms = mouth_series(item.path, item.workdir, float(p["fps"]), int(p["seconds"]))
        valid = ~np.isnan(ms.opening)
        if not words or valid.sum() < 10:
            return Finding(scores=[Score("bilabial_words_checked", 0.0, None, "No usable speech with a visible face.")],
                           summary="No transcribed speech with a visible face.", limitations=self.limitations,
                           details={"language": language}, provenance={"weights": {**ms.weights, **whisper_hashes}})
        typical_open = float(np.nanmedian(ms.opening))
        checks = []
        for w in words:
            token = w.text.lower().lstrip("\"'¿¡([")
            if not token.startswith(BILABIAL_START):
                continue
            window = (ms.times >= w.start - 0.08) & (ms.times <= w.start + 0.12) & valid
            if not window.any():
                continue
            low = float(np.nanmin(ms.opening[window]))
            closed = low <= float(p["closure_ratio"]) * typical_open
            checks.append({"word": w.text, "start": r6(w.start), "min_opening": r6(low), "closed": closed})
        fails = [c for c in checks if not c["closed"]]
        rate = len(fails) / len(checks) if checks else None
        return Finding(
            scores=[
                Score("words_transcribed", float(len(words)), None, f"Words transcribed by Whisper (language: {language})."),
                Score("bilabial_words_checked", float(len(checks)), None, "Words starting with M/B/P (or Malayalam bilabials) with a visible mouth."),
                Score("closure_failures", float(len(fails)), None, "Of those, words where the lips did not close."),
                Score("closure_failure_rate", r6(rate) if rate is not None else None, (0, 1),
                      "Fraction of checked bilabial words without lip closure (higher = more suspicious)."),
            ],
            summary=(f"{len(checks)} bilabial word(s) checked, {len(fails)} without lip closure."
                     + (f" Examples: {', '.join(str(c['word']) for c in fails[:5])}." if fails else "")),
            limitations=self.limitations,
            details={"language": language, "checks": checks, "transcript": " ".join(w.text for w in words)[:5000]},
            provenance={"weights": {**ms.weights, **whisper_hashes}},
        )


MODULE = PhonemeViseme()
