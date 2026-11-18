"""Generate the synthetic, non-explicit test images used by tests and the demo.

No real people and no explicit content: every image is a procedurally drawn
outdoor-like scene (sky, ground, buildings, a sun) with simulated sensor noise.

Outputs (default: backend/tests/fixtures/):
  scene_original.jpg   "camera" JPEG with EXIF Make/Model/DateTimeOriginal
  scene_original.png   the same pixels, lossless
  scene_reference.jpg  the original, slightly rescaled and shifted (a second
                       copy of the "victim's photo" for source matching)
  scene_edited.jpg     an object pasted in and a building removed by
                       inpainting, re-saved by "editing software"
  scene_edited_mask.png  ground-truth mask of the edited regions (255 = edited)

Run inside the worker image so library versions match the tests:
  docker run --rm -v "$PWD:/src" -w /src safeface/worker:dev python scripts/make_fixtures.py
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

W, H = 640, 480


def scene(rng: np.random.Generator) -> np.ndarray:
    y = np.linspace(0, 1, H)[:, None]
    img = np.zeros((H, W, 3), np.float64)
    sky = np.array([200, 160, 110]) * (1 - y) + np.array([235, 215, 180]) * y  # BGR
    img[:] = sky[:, None, :] if sky.ndim == 2 else sky
    img[int(H * 0.62):] = (70, 120, 90)  # ground
    for i, (x0, w, h, col) in enumerate([(40, 90, 170, (120, 120, 130)), (150, 70, 120, (90, 100, 150)),
                                         (250, 110, 210, (140, 130, 120)), (400, 80, 150, (100, 110, 100)),
                                         (500, 100, 190, (130, 140, 160))]):
        top = int(H * 0.62) - h
        cv2.rectangle(img, (x0, top), (x0 + w, int(H * 0.62)), col, -1)
        for wy in range(top + 12, int(H * 0.62) - 12, 24):  # windows (texture)
            for wx in range(x0 + 10, x0 + w - 14, 22):
                cv2.rectangle(img, (wx, wy), (wx + 10, wy + 12), (60 + 10 * i, 70, 80), -1)
    cv2.circle(img, (560, 70), 32, (120, 220, 250), -1)  # sun
    img = cv2.GaussianBlur(img, (3, 3), 0.8)
    img += rng.normal(0, 3.0, img.shape)  # sensor noise
    return np.clip(img, 0, 255).astype(np.uint8)


def exif_camera() -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "SafeFaceTestCam"   # Make
    exif[0x0110] = "Synthetic-1"       # Model
    exif[0x0132] = "2026:01:15 10:30:00"  # DateTime
    exif[0x8769] = {  # Exif sub-IFD (Pillow writes it only when assigned as a dict)
        0x9003: "2026:01:15 10:30:00",  # DateTimeOriginal
        0x829A: (1, 250),               # ExposureTime
        0x829D: (28, 10),               # FNumber
        0x8827: 100,                    # ISO
        0x920A: (50, 1),                # FocalLength
    }
    return exif.tobytes()


def exif_edited() -> bytes:
    exif = Image.Exif()
    exif[0x0131] = "GIMP 2.10.36"  # Software
    exif[0x0132] = "2026:02:01 18:05:00"
    return exif.tobytes()


def to_pil(bgr: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def save_jpeg(img: Image.Image, path: Path, quality: int, exif: bytes) -> None:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, subsampling=2, optimize=False, exif=exif)
    path.write_bytes(buf.getvalue())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="backend/tests/fixtures")
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20260118)

    original = scene(rng)
    save_jpeg(to_pil(original), out / "scene_original.jpg", 92, exif_camera())
    to_pil(original).save(out / "scene_original.png", optimize=False)
    # Decode the camera JPEG: edits start from what the "camera" produced.
    base = cv2.imdecode(np.frombuffer((out / "scene_original.jpg").read_bytes(), np.uint8),
                        cv2.IMREAD_COLOR)

    # Reference: 92% scale, small shift — the same photo, as saved elsewhere.
    m = np.array([[0.92, 0.0, 18.0], [0.0, 0.92, 12.0]])
    reference = cv2.warpAffine(base, m, (W, H), borderMode=cv2.BORDER_REFLECT)
    save_jpeg(to_pil(reference), out / "scene_reference.jpg", 90, exif_camera())

    # Edited: paste a smooth "object" (no sensor noise) and remove one building.
    edited = base.copy()
    mask = np.zeros((H, W), np.uint8)
    cv2.circle(edited, (330, 340), 45, (40, 40, 200), -1)
    cv2.circle(mask, (330, 340), 47, 255, -1)
    remove = np.zeros((H, W), np.uint8)
    cv2.rectangle(remove, (398, int(H * 0.62) - 152), (482, int(H * 0.62)), 255, -1)
    edited = cv2.inpaint(edited, remove, 5, cv2.INPAINT_TELEA)
    mask = cv2.bitwise_or(mask, remove)
    save_jpeg(to_pil(edited), out / "scene_edited.jpg", 85, exif_edited())
    Image.fromarray(mask).save(out / "scene_edited_mask.png", optimize=False)
    print(f"fixtures written to {out}")


if __name__ == "__main__":
    main()
