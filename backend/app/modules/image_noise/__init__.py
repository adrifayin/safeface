"""image.noise: local noise-variance map from a wavelet residual.

A camera image carries sensor noise that is roughly consistent across the
frame (for a given brightness). Regions pasted from elsewhere, synthesised,
heavily smoothed or inpainted often carry a different noise level.

Method: one-level 2-D discrete wavelet transform (Daubechies-8) of the
luminance; in each block of the diagonal detail sub-band (HH) the noise
standard deviation is estimated robustly as median(|HH|) / 0.6745 (Donoho's
MAD estimator).
"""

from __future__ import annotations

from typing import Any

import numpy as np

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


class NoiseVariance(ModuleBase):
    id = "image.noise"
    version = "1.0.0"
    name = "Local noise-level map"
    description = (
        "Block-wise noise standard deviation estimated with the MAD estimator on the diagonal "
        "(HH) sub-band of a one-level db8 wavelet transform of the luminance."
    )
    family = Family.CLASSICAL
    tier = 1
    default_params = {"block": 32, "wavelet": "db8"}  # noqa: RUF012
    headline = ("low_noise_fraction", None)
    plain = 'Maps camera grain; pasted or painted-over areas often have less of it.'
    limitations = (
        "Strongly textured regions (foliage, hair, fabric) raise the estimate and flat, dark or "
        "saturated regions lower it, which can mimic or mask anomalies. Noise reduction, "
        "resizing and recompression (as done by messaging apps) flatten noise everywhere. "
        "A different noise level is a reason to look closer, not proof of editing."
    )

    def availability(self) -> Availability:
        try:
            import pywt  # noqa: F401
        except ImportError:
            return Availability(False, "PyWavelets is not installed")
        return Availability(True)

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        import cv2
        import pywt

        p = self.merged_params(params)
        block = int(p["block"])
        if block < 8 or block % 2:
            raise ValueError("block must be an even number >= 8")
        rgb, info = load_rgb(item.path)
        h, w = rgb.shape[:2]
        luma = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)[:, :, 0].astype(np.float64)
        _, (_, _, hh) = pywt.dwt2(luma, str(p["wavelet"]), mode="symmetric")
        sb = block // 2  # block size in the half-resolution sub-band
        rows, cols = max(1, hh.shape[0] // sb), max(1, hh.shape[1] // sb)
        sigma = np.zeros((rows, cols))
        for r in range(rows):
            for c in range(cols):
                tile = hh[r * sb:(r + 1) * sb, c * sb:(c + 1) * sb]
                sigma[r, c] = np.median(np.abs(tile)) / 0.6745

        med = float(np.median(sigma))
        safe_med = med if med > 1e-9 else 1e-9
        ratio = sigma / safe_med
        heat = np.clip(ratio / 2.0, 0, 1)  # 0.5 on the map == median noise level
        full = cv2.resize(heat, (w, h), interpolation=cv2.INTER_NEAREST)
        out = item.workdir
        save_png(colormap(full, "viridis"), out / "noise_map.png")
        hist, edges = np.histogram(sigma, bins=40)
        save_plot({
            "data": [{"type": "bar", "x": [r6(e) for e in edges[:-1]], "y": [int(v) for v in hist]}],
            "layout": {"title": "Block noise sigma distribution", "xaxis": {"title": "sigma"},
                       "yaxis": {"title": "blocks"}},
        }, out / "noise_histogram.json")

        cv = float(np.std(sigma) / safe_med)
        low = float(np.mean(ratio < 0.5))
        high = float(np.mean(ratio > 2.0))
        return Finding(
            scores=[
                Score("median_sigma", r6(med), (0, 255),
                      "Typical noise standard deviation across blocks (grey levels).", "levels"),
                Score("relative_spread", r6(cv), None,
                      "Unbounded, >= 0. Standard deviation of block noise divided by the median. Higher means noise "
                      "is less uniform across the image."),
                Score("low_noise_fraction", r6(low), (0, 1),
                      "Fraction of blocks with less than half the median noise (smoothed, "
                      "synthetic, inpainted or simply flat/dark areas)."),
                Score("high_noise_fraction", r6(high), (0, 1),
                      "Fraction of blocks with more than twice the median noise (texture or "
                      "regions from a noisier source)."),
            ],
            summary=(f"Median block noise sigma {med:.3f}; {low * 100:.1f}% of blocks below half "
                     f"and {high * 100:.1f}% above twice the median. Compare the map with image "
                     "content: anomalies that do not follow texture or brightness merit attention."),
            limitations=self.limitations,
            artefacts=[
                Artefact("noise_map.png", out / "noise_map.png", ArtefactKind.HEATMAP,
                         f"Noise level relative to the median (block {block}px; mid-colour = median)"),
                Artefact("noise_histogram.json", out / "noise_histogram.json", ArtefactKind.PLOT,
                         "Distribution of block noise levels", "application/json"),
            ],
            details={"decode": info, "grid": [rows, cols]},
        )


MODULE = NoiseVariance()
