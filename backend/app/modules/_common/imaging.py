"""Image decoding and figure writing shared by the image modules.

All pixel modules analyse the image in its *display orientation* (EXIF
orientation applied), so heatmaps line up with what the browser shows.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

Array = np.ndarray[Any, Any]

# Refuse decompression bombs: 200 megapixels is far above any real camera.
Image.MAX_IMAGE_PIXELS = 200_000_000
_heif_registered = False


def _register_heif() -> None:
    global _heif_registered
    if not _heif_registered:
        import pillow_heif

        pillow_heif.register_heif_opener()
        _heif_registered = True


def open_image(path: Path) -> Image.Image:
    _register_heif()
    img = Image.open(path)
    img.load()
    return img


def load_rgb(path: Path) -> tuple[Array, dict[str, Any]]:
    """Decode to uint8 RGB (H, W, 3) in display orientation, plus decode facts."""
    img = open_image(path)
    info: dict[str, Any] = {"format": img.format, "mode": img.mode, "size": list(img.size)}
    orientation = int(img.getexif().get(0x0112, 1) or 1)
    info["exif_orientation"] = orientation
    oriented = (ImageOps.exif_transpose(img) or img) if orientation != 1 else img
    rgb = np.asarray(oriented.convert("RGB"), dtype=np.uint8)
    return rgb, info


def colormap(values: Array, name: str = "inferno") -> Array:
    """Map an array in [0, 1] to an RGB uint8 image."""
    import cv2

    cmap = {"inferno": cv2.COLORMAP_INFERNO, "jet": cv2.COLORMAP_JET,
            "viridis": cv2.COLORMAP_VIRIDIS}[name]
    v = np.clip(np.nan_to_num(values, nan=0.0), 0.0, 1.0)
    bgr = cv2.applyColorMap((v * 255).round().astype(np.uint8), cmap)
    return bgr[:, :, ::-1].copy()


def save_png(rgb: Array, path: Path) -> Path:
    """Deterministic PNG (no timestamps, fixed compression)."""
    Image.fromarray(rgb).save(path, format="PNG", optimize=False, compress_level=6)
    return path


def save_plot(spec: dict[str, Any], path: Path) -> Path:
    """Write a Plotly figure spec (data + layout) as JSON for the web UI."""
    path.write_text(json.dumps(spec, sort_keys=True), encoding="utf-8")
    return path


def run_tool(args: list[str], timeout: int = 120, cwd: Path | None = None) -> subprocess.CompletedProcess[bytes]:
    """Run a forensic CLI with a timeout and a minimal environment."""
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",  # noqa: S108 - private tmpfs in a read-only container
        "LANG": "C.UTF-8",
    }
    return subprocess.run(args, capture_output=True, timeout=timeout, cwd=cwd, env=env, check=False)


def r6(x: float) -> float:
    """Round to 6 decimals: stable across runs, still precise."""
    return float(round(float(x), 6))
