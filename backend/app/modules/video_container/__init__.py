"""video.container: container and stream structure (ffprobe + MediaInfo), SRS FR-3.1.

Reports codecs, encoder/writing-application tags, frame-rate consistency,
timestamps and stream durations, and flags indicators of re-encoding or of
generation/editing software.
"""

from __future__ import annotations

import json
import shutil
from typing import Any

from app.modules._common.imaging import r6, run_tool
from app.modules._common.media import audio_stream, ffprobe, tools_available, video_stream
from app.modules.base import Availability, Family, Finding, MediaType, ModuleBase, Score, WorkingCopy
from app.modules.image_metadata import AI_GENERATORS, EDITORS

VIDEO_EDITORS = [*EDITORS, "premiere", "final cut", "davinci", "resolve", "capcut", "kinemaster", "vegas",
                           "filmora", "imovie", "handbrake", "shotcut", "openshot", "vn video"]
VIDEO_AI = [*AI_GENERATORS, "deepfacelab", "faceswap", "roop", "facefusion", "synthesia", "heygen", "d-id",
                            "sora", "pika", "kling", "luma", "hailuo", "wav2lip", "liveportrait", "veo"]
# Encoder strings that indicate the file was (re-)encoded by a generic library rather than a camera.
GENERIC_ENCODERS = ["lavf", "lavc", "libx264", "libx265", "x264", "x265", "ffmpeg", "gstreamer"]


def _frac(v: str | None) -> float | None:
    if not v or v in ("0/0", "N/A"):
        return None
    num, _, den = v.partition("/")
    try:
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return None


class VideoContainer(ModuleBase):
    id = "video.container"
    version = "1.0.0"
    name = "Container and stream analysis"
    description = ("ffprobe and MediaInfo report of codecs, encoder and writing-application tags, frame rate, "
                   "timestamps and stream durations, with re-encoding and editing indicators.")
    family = Family.PROVENANCE
    media_types = {MediaType.VIDEO}  # noqa: RUF012
    tier = 1
    headline = ("anomaly_count", None)
    plain = "Reads the video file's structure and the software that wrote it."
    limitations = (
        "Social-media and messaging platforms re-encode almost every video, so re-encoding indicators are "
        "context, not proof of manipulation. Tags are easily removed or forged; their absence proves nothing. "
        "A generic encoder tag (e.g. Lavf/x264) is written by many legitimate tools as well as deepfake pipelines."
    )

    def availability(self) -> Availability:
        ok, reason = tools_available()
        return Availability(ok, reason)

    def screen(self, scores: dict[str, float | None], details: dict[str, Any]) -> str | None:
        if scores.get("ai_tool_tag") == 1:
            return "Video tags name an AI video-generation or face-swap tool"
        if scores.get("editing_tool_tag") == 1:
            return "Video tags show the file was written by video-editing software"
        return None

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        self.merged_params(params)
        probe = ffprobe(item.path)
        fmt = probe.get("format", {})
        v, a = video_stream(probe), audio_stream(probe)
        mediainfo: dict[str, Any] = {}
        if shutil.which("mediainfo"):
            res = run_tool(["mediainfo", "--Output=JSON", str(item.path)], timeout=120)
            if res.returncode == 0 and res.stdout:
                mediainfo = json.loads(res.stdout)
        tags: list[str] = []
        for src in [fmt.get("tags", {})] + [s.get("tags", {}) for s in probe.get("streams", [])]:
            tags += [f"{k}={val}" for k, val in src.items()]
        for track in (mediainfo.get("media") or {}).get("track", []):
            for key in ("Encoded_Application", "Encoded_Library", "Writing_Application", "Writing_Library"):
                if track.get(key):
                    tags.append(f"{key}={track[key]}")
        low = " ".join(tags).lower()
        anomalies: list[dict[str, str]] = []
        editing = [t for t in VIDEO_EDITORS if t in low]
        ai = [t for t in VIDEO_AI if t in low]
        generic = [t for t in GENERIC_ENCODERS if t in low]
        if ai:
            anomalies.append({"check": "ai_tool_tag", "value": ", ".join(ai),
                              "explanation": "A tag names an AI generation or face-swap tool."})
        if editing:
            anomalies.append({"check": "editing_tool_tag", "value": ", ".join(editing),
                              "explanation": "A tag names video-editing software."})
        if generic:
            anomalies.append({"check": "generic_encoder", "value": ", ".join(generic),
                              "explanation": "Encoded by a generic library (re-encoded after capture or by a platform)."})
        avg, real = (_frac(v.get("avg_frame_rate")), _frac(v.get("r_frame_rate"))) if v else (None, None)
        vfr = bool(avg and real and abs(avg - real) / real > 0.02)
        if vfr:
            anomalies.append({"check": "variable_frame_rate", "value": f"avg {avg:.3f} vs nominal {real:.3f} fps",
                              "explanation": "Variable frame rate: typical of phone recordings, screen captures and some edits."})
        vdur = float(v.get("duration", 0) or 0) if v else 0.0
        adur = float(a.get("duration", 0) or 0) if a else 0.0
        mismatch = abs(vdur - adur) if (v and a and vdur and adur) else None
        if mismatch is not None and mismatch > 0.5:
            anomalies.append({"check": "stream_duration_mismatch", "value": f"{mismatch:.2f} s",
                              "explanation": "Audio and video streams differ in length (possible splicing or dubbing)."})
        if not (fmt.get("tags", {}).get("creation_time")):
            anomalies.append({"check": "no_creation_time", "value": "",
                              "explanation": "No creation time tag (common after platform re-encoding)."})
        summary = (f"{(v or {}).get('codec_name', 'no video')} {(v or {}).get('width', '?')}x{(v or {}).get('height', '?')}, "
                   f"{float(fmt.get('duration', 0) or 0):.1f} s, audio: {(a or {}).get('codec_name', 'none')}. "
                   f"{len(anomalies)} observation(s): {', '.join(x['check'] for x in anomalies) or 'none'}.")
        return Finding(
            scores=[
                Score("anomaly_count", float(len(anomalies)), None, "Number of observations listed (not a measure of manipulation)."),
                Score("ai_tool_tag", 1.0 if ai else 0.0, (0, 1), "1 = a tag names an AI video or face-swap tool."),
                Score("editing_tool_tag", 1.0 if editing else 0.0, (0, 1), "1 = a tag names video-editing software."),
                Score("reencode_indicator", 1.0 if generic else 0.0, (0, 1), "1 = encoded by a generic library (re-encoded)."),
                Score("variable_frame_rate", 1.0 if vfr else 0.0, (0, 1), "1 = average and nominal frame rates differ by > 2%."),
                Score("av_duration_mismatch", r6(mismatch) if mismatch is not None else None, None,
                      "Difference between audio and video stream durations, seconds (null = one stream missing).", "s"),
            ],
            summary=summary, limitations=self.limitations,
            details={"anomalies": anomalies, "format": fmt, "streams": probe.get("streams", []), "tags": tags,
                     "mediainfo": mediainfo},
            provenance={"tools": {"ffprobe": run_tool(["ffprobe", "-version"], timeout=10).stdout.decode()[:60]}},
        )


MODULE = VideoContainer()
