"""Video/audio helpers built on FFmpeg/ffprobe (run as subprocesses with timeouts).

Frame sampling is deterministic: frames at a fixed rate (default 1 fps) plus
the stream's keyframes, decoded to PNG, each tagged with its timestamp.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.modules._common.imaging import Array, run_tool


def tools_available() -> tuple[bool, str]:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            return False, f"{tool} is not installed in the worker image"
    return True, ""


def ffprobe(path: Path) -> dict[str, Any]:
    res = run_tool(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                   timeout=120)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {res.stderr.decode(errors='replace')[:300]}")
    data: dict[str, Any] = json.loads(res.stdout or b"{}")
    return data


def video_stream(probe: dict[str, Any]) -> dict[str, Any] | None:
    return next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)


def audio_stream(probe: dict[str, Any]) -> dict[str, Any] | None:
    return next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), None)


def keyframe_times(path: Path, limit: int) -> list[float]:
    res = run_tool(["ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
                    "-show_entries", "frame=pts_time", "-of", "json", str(path)], timeout=300)
    if res.returncode != 0:
        return []
    frames = json.loads(res.stdout or b"{}").get("frames", [])
    times = sorted({round(float(f["pts_time"]), 3) for f in frames if f.get("pts_time") not in (None, "N/A")})
    return times[:limit]


@dataclass(frozen=True)
class Frame:
    t: float          # seconds from start
    path: Path
    keyframe: bool


def sample_frames(path: Path, out: Path, fps: float = 1.0, max_frames: int = 60, max_keyframes: int = 30,
                  max_side: int = 1280) -> list[Frame]:
    """Uniform frames at ``fps`` plus keyframes, scaled so the long side <= max_side."""
    out.mkdir(parents=True, exist_ok=True)
    scale = f"scale='if(gt(iw,ih),min({max_side},iw),-2)':'if(gt(iw,ih),-2,min({max_side},ih))'"
    res = run_tool(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-vf", f"fps={fps},{scale}",
                    "-frames:v", str(max_frames), "-start_number", "0", str(out / "u_%05d.png")], timeout=600)
    if res.returncode != 0:
        raise RuntimeError(f"frame extraction failed: {res.stderr.decode(errors='replace')[:300]}")
    frames = [Frame(round(i / fps, 3), p, False) for i, p in enumerate(sorted(out.glob("u_*.png")))]
    taken = [f.t for f in frames]
    for i, t in enumerate(keyframe_times(path, max_keyframes)):
        if any(abs(t - x) < 0.25 for x in taken):
            continue
        target = out / f"k_{i:05d}.png"
        r = run_tool(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{t:.3f}", "-i", str(path), "-vf", scale,
                      "-frames:v", "1", str(target)], timeout=120)
        if r.returncode == 0 and target.exists():
            frames.append(Frame(t, target, True))
            taken.append(t)
    return sorted(frames, key=lambda f: f.t)


def load_frame(frame: Frame) -> Array:
    from PIL import Image

    with Image.open(frame.path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


def audio_pcm(path: Path, rate: int = 16000, max_seconds: int = 1800) -> Array | None:
    """Mono float32 PCM in [-1, 1] at ``rate`` Hz, or None if there is no audio stream."""
    if audio_stream(ffprobe(path)) is None:
        return None
    res = run_tool(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-vn", "-ac", "1", "-ar", str(rate),
                    "-t", str(max_seconds), "-f", "s16le", "-acodec", "pcm_s16le", "-"], timeout=600)
    if res.returncode != 0:
        raise RuntimeError(f"audio decoding failed: {res.stderr.decode(errors='replace')[:300]}")
    return np.frombuffer(res.stdout, dtype="<i2").astype(np.float32) / 32768.0


def contact_sheet(images: list[tuple[str, Array]], height: int = 220) -> Array:
    """Images side by side at a common height, each captioned (used for 'top frames' figures)."""
    import cv2

    tiles = []
    for caption, rgb in images:
        h, w = rgb.shape[:2]
        tile = cv2.resize(rgb, (max(1, int(w * height / h)), height), interpolation=cv2.INTER_AREA)
        bar = np.full((24, tile.shape[1], 3), 255, np.uint8)
        cv2.putText(bar, caption, (4, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        tiles.append(np.concatenate([tile, bar], axis=0))
        tiles.append(np.full((height + 24, 6, 3), 255, np.uint8))
    return np.concatenate(tiles[:-1], axis=1) if tiles else np.full((height, height, 3), 255, np.uint8)
