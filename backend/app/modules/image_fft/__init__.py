"""image.fft: frequency spectrum of the noise residual (SRS FR-2.7).

Generative networks that up-sample by transposed convolution or interpolation
often leave periodic patterns that appear as isolated peaks in the spectrum
of the high-pass residual. The module shows the log-magnitude spectrum and
measures how strongly the largest off-centre peaks stand out.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.modules._common.imaging import colormap, load_rgb, r6, save_png
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


class ResidualFFT(ModuleBase):
    id = "image.fft"
    version = "1.0.0"
    name = "Residual frequency spectrum"
    description = ("Log-magnitude 2-D FFT of the high-pass residual (luminance minus 3x3 median), Hann-windowed, "
                   "centre 1024 px; peak-to-background ratio of off-centre peaks.")
    family = Family.CLASSICAL
    tier = 2
    default_params = {"size": 1024}  # noqa: RUF012
    headline = ("peak_to_background", None)
    question = "ai_generated"
    plain = 'Looks for repeating patterns that AI image generators often leave.'
    limitations = (
        "Interpretation needs training. JPEG's 8x8 grid, resizing, sharpening and screen captures also create "
        "periodic peaks; a clean spectrum does not exclude generation. Supporting evidence only."
    )

    def availability(self) -> Availability:
        return Availability(True)

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        import cv2

        p = self.merged_params(params)
        rgb, info = load_rgb(item.path)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        n = int(p["size"])
        h, w = gray.shape
        s = min(n, h, w)
        top, left = (h - s) // 2, (w - s) // 2
        g = gray[top:top + s, left:left + s]
        residual = g.astype(np.float64) - cv2.medianBlur(g, 3).astype(np.float64)
        win = np.outer(np.hanning(s), np.hanning(s))
        spec = np.fft.fftshift(np.abs(np.fft.fft2(residual * win)))
        logspec = np.log1p(spec)
        norm = (logspec - logspec.min()) / max(logspec.max() - logspec.min(), 1e-9)
        save_png(colormap(norm, "viridis"), item.workdir / "residual_spectrum.png")
        yy, xx = np.mgrid[:s, :s]
        r = np.hypot(yy - s / 2, xx - s / 2)
        ring = (r > s * 0.05) & (r < s * 0.49)
        vals = spec[ring]
        med = float(np.median(vals)) or 1e-9
        top_peaks = np.sort(vals)[-8:]
        ratio = float(top_peaks.mean() / med)
        return Finding(
            scores=[
                Score("peak_to_background", r6(ratio), None,
                      "Mean of the 8 strongest off-centre peaks divided by the median magnitude (unbounded). Higher = "
                      "stronger periodic pattern; compare with camera images of similar size and compression."),
                Score("analysed_size", float(s), None, "Side of the square region analysed.", "px"),
            ],
            summary=f"Residual spectrum of the central {s}x{s} region; peak-to-background ratio {ratio:.1f}.",
            limitations=self.limitations,
            artefacts=[Artefact("residual_spectrum.png", item.workdir / "residual_spectrum.png", ArtefactKind.IMAGE,
                                "Log-magnitude spectrum of the noise residual (centre = low frequencies)")],
            details={"decode": info},
        )


MODULE = ResidualFFT()
