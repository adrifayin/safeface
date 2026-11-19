"""image.jpeg_ghost: JPEG ghosts (Farid, IEEE TIFS 2009), SRS FR-2.6.

The image is re-compressed at qualities 50..100; for each quality the
locally averaged squared difference to the input is computed. A region that
was previously compressed at quality q shows a local minimum ("ghost") at q.
Regions whose best-matching quality differs from the rest of the image
suggest content from a source with a different compression history.
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image

from app.modules._common.imaging import colormap, load_rgb, r6, save_plot, save_png
from app.modules.base import (
    Artefact,
    ArtefactKind,
    Availability,
    Family,
    Finding,
    ModuleBase,
    Score,
    WorkingCopy,
)


class JPEGGhost(ModuleBase):
    id = "image.jpeg_ghost"
    version = "1.0.0"
    name = "JPEG ghosts"
    description = ("Re-compression at JPEG qualities 50–100; locally averaged (16 px) squared difference; per-pixel "
                   "best-matching quality compared with the image's dominant quality.")
    family = Family.CLASSICAL
    tier = 2
    default_params = {"q_min": 50, "q_max": 100, "q_step": 5, "block": 16, "max_side": 2048}  # noqa: RUF012
    headline = ("inconsistent_area_fraction", 0.05)
    question = "edited"
    plain = 'Finds areas saved at a different JPEG quality from the rest.'
    limitations = (
        "Needs a JPEG compression history: uncompressed, PNG-only or heavily recompressed images show no ghosts. "
        "Destroyed by resizing, cropping off the 8x8 grid and repeated platform recompression. Flat and saturated "
        "areas give unreliable minima. Supporting evidence only."
    )

    def availability(self) -> Availability:
        return Availability(True)

    def screen(self, scores: dict[str, float | None], details: dict[str, Any]) -> str | None:
        frac = scores.get("inconsistent_area_fraction")
        if frac is not None and frac >= 0.05:
            return f"JPEG ghosts: {frac * 100:.1f}% of the image has a different compression history (threshold 5%)"
        return None

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        import cv2

        p = self.merged_params(params)
        rgb, info = load_rgb(item.path)
        side = int(p["max_side"])
        h, w = rgb.shape[:2]
        # Centre crop aligned to the 8x8 JPEG grid (keeps block alignment, bounds memory).
        top, left = (max(0, h - side) // 2) // 8 * 8, (max(0, w - side) // 2) // 8 * 8
        rgb = np.ascontiguousarray(rgb[top:top + side, left:left + side])
        info["analysed_region"] = [left, top, rgb.shape[1], rgb.shape[0]]
        img = rgb.astype(np.float64)
        qualities = list(range(int(p["q_min"]), int(p["q_max"]) + 1, int(p["q_step"])))
        block = int(p["block"])
        diffs = []
        for q in qualities:
            buf = io.BytesIO()
            Image.fromarray(rgb).save(buf, "JPEG", quality=q, subsampling=2, optimize=False)
            re = np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"), dtype=np.float64)
            d = ((img - re) ** 2).mean(axis=2)
            diffs.append(cv2.blur(d, (block, block)))
        stack = np.stack(diffs)                       # (Q, H, W)
        lo, hi = stack.min(axis=0), stack.max(axis=0)
        norm = (stack - lo) / np.maximum(hi - lo, 1e-9)  # per-pixel normalisation across qualities (Farid eq. 4)
        global_curve = stack.mean(axis=(1, 2))
        # Ignore q=100 (always near zero) when choosing the dominant quality.
        candidates = [i for i, q in enumerate(qualities) if q < 100] or list(range(len(qualities)))
        q_star_i = min(candidates, key=lambda i: global_curve[i])
        best = np.array(qualities)[np.argmin(np.where(np.array(qualities)[:, None, None] < 100, norm, np.inf), axis=0)]
        textured = cv2.blur(cv2.Laplacian(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), cv2.CV_64F) ** 2, (block, block)) > 4
        inconsistent = (np.abs(best - qualities[q_star_i]) >= 10) & textured
        out = item.workdir
        save_png(colormap(norm[q_star_i], "inferno"), out / "ghost_dominant_q.png")
        save_png(colormap(inconsistent.astype(np.float64) * 0.9 + 0.05, "viridis"), out / "ghost_inconsistency.png")
        save_plot({"data": [{"type": "scatter", "mode": "lines+markers", "x": qualities,
                             "y": [r6(v) for v in global_curve]}],
                   "layout": {"title": "Mean re-compression difference by JPEG quality (minimum = likely previous quality)",
                              "xaxis": {"title": "quality"}, "yaxis": {"title": "mean squared difference"}}},
                  out / "ghost_curve.json")
        frac = float(inconsistent.mean())
        # Maps overlay the viewer only when they cover the whole image (no crop).
        kind = ArtefactKind.HEATMAP if rgb.shape[:2] == (h, w) else ArtefactKind.IMAGE
        return Finding(
            scores=[
                Score("dominant_quality", float(qualities[q_star_i]), (50, 100),
                      "JPEG quality at which most of the image best matches (likely last compression quality)."),
                Score("inconsistent_area_fraction", r6(frac), (0, 1),
                      "Fraction of textured pixels whose best-matching quality differs by >= 10 from the dominant one."),
            ],
            summary=(f"Dominant quality ≈ {qualities[q_star_i]}; {frac * 100:.1f}% of textured pixels match a different "
                     "quality. Inspect the inconsistency map for compact regions."),
            limitations=self.limitations,
            artefacts=[
                Artefact("ghost_inconsistency.png", out / "ghost_inconsistency.png", kind,
                         "Pixels whose compression history differs from the dominant quality (bright)"),
                Artefact("ghost_dominant_q.png", out / "ghost_dominant_q.png", kind,
                         f"Normalised difference at quality {qualities[q_star_i]} (dark = ghost)"),
                Artefact("ghost_curve.json", out / "ghost_curve.json", ArtefactKind.PLOT,
                         "Difference vs quality", "application/json"),
            ],
            details={"decode": info, "qualities": qualities},
        )


MODULE = JPEGGhost()
