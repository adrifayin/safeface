"""image.ela: Error Level Analysis.

The image is re-saved once as JPEG at a fixed quality and the absolute
per-pixel difference to the input is amplified into a picture. Regions that
were compressed a different number of times, or pasted from another source,
can show a different error level from their surroundings.
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image

from app.modules._common.imaging import load_rgb, r6, save_plot, save_png
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


class ErrorLevelAnalysis(ModuleBase):
    id = "image.ela"
    version = "1.0.0"
    name = "Error Level Analysis (ELA)"
    description = (
        "Re-save as JPEG at a fixed quality (default 90, 4:2:0 chroma subsampling) and show the "
        "absolute per-pixel difference, multiplied by a fixed amplification factor."
    )
    family = Family.CLASSICAL
    tier = 1
    default_params = {"quality": 90, "amplification": 15}  # noqa: RUF012
    headline = ("p99_error", None)
    question = "edited"
    plain = 'Re-saves the photo and shows areas that react differently (edits can stand out).'
    limitations = (
        "ELA has a high false-positive rate. Edges, fine texture, saturated colours and areas of "
        "high contrast naturally show high error levels; uniform areas show low levels whether or "
        "not they were edited. Results depend on the image's compression history and are "
        "destroyed by resizing or repeated recompression. Use only as supporting evidence."
    )

    def availability(self) -> Availability:
        return Availability(True)

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        p = self.merged_params(params)
        quality, amp = int(p["quality"]), float(p["amplification"])
        if not 1 <= quality <= 100:
            raise ValueError("quality must be 1..100")
        rgb, info = load_rgb(item.path)
        buf = io.BytesIO()
        Image.fromarray(rgb).save(buf, "JPEG", quality=quality, subsampling=2, optimize=False)
        resaved = np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"), dtype=np.int16)
        diff = np.abs(rgb.astype(np.int16) - resaved)
        ela = np.clip(diff.astype(np.float64) * amp, 0, 255).astype(np.uint8)
        per_pixel = diff.max(axis=2)

        out = item.workdir
        save_png(ela, out / "ela.png")
        hist, edges = np.histogram(per_pixel, bins=64, range=(0, 64))
        save_plot({
            "data": [{"type": "bar", "x": [int(e) for e in edges[:-1]], "y": [int(h) for h in hist]}],
            "layout": {"title": "ELA per-pixel error (max over channels)",
                       "xaxis": {"title": "error level"}, "yaxis": {"title": "pixels", "type": "log"}},
        }, out / "ela_histogram.json")

        mean_err, p99, mx = r6(diff.mean()), r6(np.percentile(per_pixel, 99)), r6(per_pixel.max())
        return Finding(
            scores=[
                Score("mean_error", mean_err, (0, 255),
                      "Mean absolute difference after one re-save. Higher means the image changes "
                      "more on re-compression (e.g. it was saved at a higher quality before).", "levels"),
                Score("p99_error", p99, (0, 255),
                      "99th-percentile per-pixel error. Compare regions visually; this number alone "
                      "does not indicate editing.", "levels"),
                Score("max_error", mx, (0, 255), "Largest per-pixel error.", "levels"),
            ],
            summary=(f"ELA at quality {quality}: mean error {mean_err:.3f}, 99th percentile {p99:.1f}. "
                     "Inspect the ELA map for regions whose error level differs from similar "
                     "texture elsewhere in the image."),
            limitations=self.limitations,
            artefacts=[
                Artefact("ela.png", out / "ela.png", ArtefactKind.HEATMAP,
                         f"ELA map (quality {quality}, x{amp:g} amplification)"),
                Artefact("ela_histogram.json", out / "ela_histogram.json", ArtefactKind.PLOT,
                         "Histogram of per-pixel error levels", "application/json"),
            ],
            details={"decode": info},
        )


MODULE = ErrorLevelAnalysis()
