"""image.prnu: camera sensor fingerprint (PRNU) test, SRS FR-2.8.

Method (Lukas, Fridrich & Goljan 2006; Goljan et al. 2009):
- noise residual W = I - F(I), F = wavelet denoising of the luminance;
- fingerprint K = sum(W_i * I_i) / sum(I_i^2) from >= 20 reference photos taken
  by the suspected camera (same resolution and orientation as the questioned image);
- zero-mean filtering of rows/columns removes non-unique artefacts;
- global test: peak-to-correlation energy (PCE) of W_q against I_q * K;
- regional test: normalised correlation in sliding blocks -> map where the
  fingerprint is missing (pasted or regenerated regions).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.modules._common.imaging import Array, colormap, load_rgb, r6, save_png
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

PCE_THRESHOLD = 60.0  # widely used decision threshold in the PRNU literature


def luminance(rgb: Array) -> Array:
    return rgb.astype(np.float64) @ np.array([0.299, 0.587, 0.114])


def residual(gray: Array) -> Array:
    from skimage.restoration import denoise_wavelet

    den = denoise_wavelet(gray / 255.0, wavelet="db8", mode="soft", method="BayesShrink", rescale_sigma=True) * 255.0
    return zero_mean(gray - den)


def zero_mean(x: Array) -> Array:
    x = x - x.mean(axis=1, keepdims=True)
    return x - x.mean(axis=0, keepdims=True)


def pce(a: Array, b: Array, exclude: int = 5) -> float:
    """Peak-to-correlation energy of the circular cross-correlation of a and b."""
    a, b = a - a.mean(), b - b.mean()
    xc = np.real(np.fft.ifft2(np.fft.fft2(a) * np.conj(np.fft.fft2(b))))
    peak_idx = np.unravel_index(np.argmax(xc), xc.shape)
    peak = xc[peak_idx]
    mask = np.ones_like(xc, dtype=bool)
    r0, c0 = peak_idx
    for dr in range(-exclude, exclude + 1):
        for dc in range(-exclude, exclude + 1):
            mask[(r0 + dr) % xc.shape[0], (c0 + dc) % xc.shape[1]] = False
    energy = float(np.mean(xc[mask] ** 2)) or 1e-12
    return float(np.sign(peak) * peak ** 2 / energy)


def ncc(a: Array, b: Array) -> float:
    a, b = a - a.mean(), b - b.mean()
    den = float(np.sqrt((a * a).sum() * (b * b).sum())) or 1e-12
    return float((a * b).sum() / den)


class PRNU(ModuleBase):
    id = "image.prnu"
    version = "1.0.0"
    name = "Camera fingerprint (PRNU)"
    description = ("Wavelet-denoised noise residuals; fingerprint estimated from the reference photos; global PCE "
                   "and sliding-window correlation map against the questioned image.")
    family = Family.COMPARISON
    tier = 2
    requires_reference = True
    default_params = {"min_references": 20, "block": 128, "max_side": 2048}  # noqa: RUF012
    headline = ("pce", 60.0)
    plain = "Matches the photo to a specific camera's sensor fingerprint."
    limitations = (
        "Needs at least 20 photos from the suspected camera at the same resolution and orientation (ideally flat, "
        "bright, unedited scenes). Fails after resizing, strong compression, digital zoom/stabilisation, or "
        "computational photography that resamples the image; many phones defeat PRNU. A missing fingerprint in a "
        "region also occurs in dark, saturated or very textured areas. A high PCE links the image to the camera "
        "only under these conditions."
    )

    def availability(self) -> Availability:
        return Availability(True)

    def screen(self, scores: dict[str, float | None], details: dict[str, Any]) -> str | None:
        pce_v, low = scores.get("pce"), scores.get("low_correlation_fraction")
        if pce_v is not None and pce_v >= PCE_THRESHOLD and low is not None and low >= 0.1:
            return f"Camera fingerprint matches overall (PCE {pce_v:.0f}) but is missing in {low * 100:.0f}% of the image"
        return None

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        p = self.merged_params(params)
        if len(refs) < int(p["min_references"]):
            raise ValueError(f"PRNU needs at least {p['min_references']} reference photos from the suspected camera; "
                             f"{len(refs)} attached")
        q_rgb, info = load_rgb(item.path)
        side = int(p["max_side"])
        h, w = q_rgb.shape[:2]
        ch, cw = min(h, side), min(w, side)
        top, left = (h - ch) // 2, (w - cw) // 2

        def crop(x: Array) -> Array:
            return x[top:top + ch, left:left + cw]

        num = np.zeros((ch, cw))
        den = np.zeros((ch, cw))
        used = 0
        for ref in refs:
            r_rgb, _ = load_rgb(ref.path)
            if r_rgb.shape[:2] != (h, w):
                continue  # PRNU requires identical geometry
            g = crop(luminance(r_rgb))
            num += residual(g) * g
            den += g * g
            used += 1
        if used < int(p["min_references"]):
            raise ValueError(f"only {used} references match the questioned image size {w}x{h}; need {p['min_references']}")
        fingerprint = zero_mean(num / np.maximum(den, 1e-9))
        gq = crop(luminance(q_rgb))
        wq = residual(gq)
        expected = gq * fingerprint
        global_pce = pce(wq, expected)
        b = int(p["block"])
        rows, cols = max(1, ch // b), max(1, cw // b)
        corr = np.zeros((rows, cols))
        for i in range(rows):
            for j in range(cols):
                sl = (slice(i * b, (i + 1) * b), slice(j * b, (j + 1) * b))
                corr[i, j] = ncc(wq[sl], expected[sl])
        ref_level = float(np.median(corr)) or 1e-9
        rel = np.clip(corr / ref_level, 0, 1.5) / 1.5
        import cv2

        full = cv2.resize(rel, (cw, ch), interpolation=cv2.INTER_NEAREST)
        save_png(colormap(full, "viridis"), item.workdir / "prnu_map.png")
        low = float((corr < 0.3 * ref_level).mean())
        kind = ArtefactKind.HEATMAP if (ch, cw) == (h, w) else ArtefactKind.IMAGE
        return Finding(
            scores=[
                Score("pce", r6(global_pce), None,
                      f"Peak-to-correlation energy of the questioned image against the fingerprint. Values above "
                      f"~{PCE_THRESHOLD:.0f} are commonly taken as a match to the camera; lower values are inconclusive."),
                Score("references_used", float(used), None, "Reference photos used to build the fingerprint."),
                Score("low_correlation_fraction", r6(low), (0, 1),
                      "Fraction of blocks where the fingerprint is weak (< 30% of the median block correlation)."),
            ],
            summary=(f"PCE {global_pce:.1f} from {used} references; fingerprint weak in {low * 100:.1f}% of blocks. "
                     "Dark/blue regions on the map lack the camera fingerprint."),
            limitations=self.limitations,
            artefacts=[Artefact("prnu_map.png", item.workdir / "prnu_map.png", kind,
                                f"Fingerprint correlation per {b}px block relative to the median (dark = missing)")],
            details={"decode": info, "grid": [rows, cols], "analysed_region": [left, top, cw, ch]},
        )


MODULE = PRNU()
