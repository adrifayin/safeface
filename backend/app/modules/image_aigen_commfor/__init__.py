"""image.aigen.commfor: Community Forensics detector (Park & Owens, CVPR 2025).

A ViT-Small/16 at 384x384 trained on images from 4,800+ different generators
(diffusion, GAN, commercial and open models), which is why it generalises to
recent generators far better than the ProGAN-trained UnivFD/NPR. Original
authors' weights (OwensLab/commfor-model-384, MIT) loaded from the local
weights directory; one logit, sigmoid = estimated likelihood of AI generation.

Preprocessing follows the authors' test pipeline (dataloader.py): PIL RGB,
resize the short side to 440 (bilinear), centre crop 384, scale to [0, 1],
ImageNet normalisation. Because the centre crop can miss the edges, the
whole frame resized to 384x384 is also scored and both are reported; the
headline is their mean.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image

from app.modules._common.imaging import Array, load_rgb, r6
from app.modules._common.torchutil import deterministic_forward, device, torch_available
from app.modules.base import Availability, Family, Finding, ModuleBase, Score, WorkingCopy
from app.modules.weights import resolve, weights_availability

WEIGHTS = "commfor-vit-s384"
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_cache: dict[str, Any] = {}


def prep(img: Image.Image, view: str) -> Array:
    if view == "centre":
        w, h = img.size
        s = 440 / min(w, h)
        img = img.resize((max(384, round(w * s)), max(384, round(h * s))), Image.Resampling.BILINEAR)
        w, h = img.size
        left, top = (w - 384) // 2, (h - 384) // 2
        img = img.crop((left, top, left + 384, top + 384))
    else:
        img = img.resize((384, 384), Image.Resampling.BILINEAR)
    x = (np.asarray(img, dtype=np.float32) / 255.0 - MEAN) / STD
    return x.transpose(2, 0, 1).astype(np.float32)


class CommunityForensics(ModuleBase):
    id = "image.aigen.commfor"
    version = "1.0.0"
    name = "AI-generation detector (Community Forensics)"
    description = ("Community Forensics (Park & Owens, CVPR 2025): ViT-S/16 trained on images from thousands of "
                   "generators; estimated likelihood that the picture was produced by an AI image/video generator.")
    family = Family.AI_DETECTOR
    tier = 1
    requires_gpu = True
    triage_indicator = True
    screening_core = True
    required_weights = [WEIGHTS]  # noqa: RUF012
    headline = ("ai_likelihood", 0.5)
    question = "ai_generated"
    plain = "Modern AI tool (trained on thousands of image generators) estimating whether the picture was made by AI."
    limitations = (
        "TRIAGE INDICATOR ONLY. The likelihood is the detector's own output and is not calibrated on SafeFace "
        "casework: it can be wrong in both directions. Accuracy drops after heavy compression, small resizes "
        "and screenshots, on generators released after the model was trained, and on photos that were only "
        "partly edited. Real photos with heavy filters, beauty mode or HDR can score high."
    )

    def availability(self) -> Availability:
        if not torch_available():
            return Availability(False, "PyTorch is not installed in this image")
        return weights_availability(self.required_weights)

    def _model(self) -> tuple[Any, str]:
        from app.modules._vendor.vit_small import load_commfor

        path, sha = resolve(WEIGHTS)
        if sha not in _cache:
            _cache.clear()
            _cache[sha] = load_commfor(path).to(device())
        return _cache[sha], sha

    def score(self, rgb: Array) -> tuple[float, dict[str, float], str]:
        """(likelihood, per-view likelihoods, weights sha) for one RGB image. Reused by video.aigen."""
        import torch

        model, sha = self._model()
        img = Image.fromarray(rgb).convert("RGB")
        x = torch.from_numpy(np.stack([prep(img, "centre"), prep(img, "whole")])).to(device())
        logits, _ = deterministic_forward(lambda: model(x).reshape(-1).double().cpu().numpy())
        probs = 1.0 / (1.0 + np.exp(-logits))
        views = {"centre": r6(probs[0]), "whole": r6(probs[1])}
        return r6(float(probs.mean())), views, sha

    def screen(self, scores: dict[str, float | None], details: dict[str, Any]) -> str | None:
        p = scores.get("ai_likelihood")
        if p is not None and p >= 0.5:
            return f"AI-generation detector: {p * 100:.0f}% likelihood that the picture was made by AI (threshold 50%)"
        return None

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        rgb, info = load_rgb(item.path)
        p, views, sha = self.score(rgb)
        return Finding(
            scores=[
                Score("ai_likelihood", p, (0, 1),
                      "Estimated likelihood (0-100%) that the picture was produced by an AI generator "
                      "(mean of the centre-crop and whole-picture views). Detector output, not proof."),
                Score("ai_likelihood_centre", views["centre"], (0, 1), "Likelihood on the central 384x384 crop."),
                Score("ai_likelihood_whole", views["whole"], (0, 1), "Likelihood on the whole picture resized."),
            ],
            summary=f"Community Forensics: {p * 100:.0f}% likelihood of AI generation "
                    f"(centre {views['centre'] * 100:.0f}%, whole picture {views['whole'] * 100:.0f}%).",
            limitations=self.limitations,
            details={"decode": info, "views": views, "device": str(device())},
            provenance={"weights": {WEIGHTS: sha}, "determinism_mode": "torch deterministic"},
        )


MODULE = CommunityForensics()
