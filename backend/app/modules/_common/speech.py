"""Speech helpers: voice-activity detection and word-timed transcription (faster-whisper).

- VAD: the Silero model bundled inside the faster-whisper package (no download).
- ASR: Whisper "small" converted to CTranslate2, loaded ONLY from the
  checksum-verified local directory models/whisper/small (never a hub name).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules._common.imaging import Array
from app.modules.base import Availability
from app.modules.weights import resolve, weights_availability

WHISPER_FILES = ["whisper-small-model", "whisper-small-config", "whisper-small-tokenizer", "whisper-small-vocabulary"]
_models: dict[str, Any] = {}


def vad_available() -> Availability:
    try:
        import faster_whisper.vad  # noqa: F401
    except ImportError:
        return Availability(False, "faster-whisper (bundled Silero VAD) is not installed in the worker image")
    return Availability(True)


def asr_available() -> Availability:
    vad = vad_available()
    return vad if not vad.available else weights_availability(WHISPER_FILES)


def speech_segments(pcm: Array, rate: int = 16000) -> list[tuple[float, float]]:
    """Speech regions in seconds, from the bundled Silero VAD."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    stamps = get_speech_timestamps(pcm, VadOptions(min_silence_duration_ms=300))
    return [(s["start"] / rate, s["end"] / rate) for s in stamps]


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float
    probability: float


def transcribe(pcm: Array) -> tuple[list[Word], str, dict[str, str]]:
    """Words with timings, detected language, and the verified file hashes."""
    hashes = {}
    model_dir = None
    for name in WHISPER_FILES:
        path, sha = resolve(name)  # verifies every file
        hashes[name] = sha
        model_dir = path.parent
    key = "|".join(hashes.values())
    if key not in _models:
        from faster_whisper import WhisperModel

        _models.clear()
        _models[key] = WhisperModel(str(model_dir), device="cpu", compute_type="int8", local_files_only=True)
    model = _models[key]
    segments, info = model.transcribe(pcm, beam_size=5, word_timestamps=True, vad_filter=True,
                                      condition_on_previous_text=False, temperature=0.0)
    words = [Word(w.word.strip(), float(w.start), float(w.end), float(w.probability))
             for seg in segments for w in (seg.words or []) if w.word.strip()]
    return words, str(info.language), hashes
