"""image.aigen.univfd: UnivFD (Ojha, Li & Lee, CVPR 2023).

A frozen CLIP ViT-L/14 image encoder followed by a linear probe trained to
separate real from generated images (trained on ProGAN data). Preprocessing
follows the authors' evaluation code: centre crop 224x224, no resize, CLIP
normalisation.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.modules._common.imaging import Array, load_rgb, r6
from app.modules._common.torchutil import (
    deterministic_forward,
    device,
    load_checkpoint,
    torch_available,
)
from app.modules.base import Availability, Family, Finding, ModuleBase, Score, WorkingCopy
from app.modules.weights import weights_availability

_cache: dict[str, Any] = {}


def center_crop(rgb: Array, size: int) -> Array:
    """Centre crop; images smaller than ``size`` are reflect-padded (never resized)."""
    h, w = rgb.shape[:2]
    if h < size or w < size:
        ph, pw = max(0, size - h), max(0, size - w)
        rgb = np.pad(rgb, ((ph // 2, ph - ph // 2), (pw // 2, pw - pw // 2), (0, 0)), mode="reflect")
        h, w = rgb.shape[:2]
    top, left = (h - size) // 2, (w - size) // 2
    return rgb[top:top + size, left:left + size]


class UnivFD(ModuleBase):
    id = "image.aigen.univfd"
    version = "1.0.0"
    name = "UnivFD AI-generation indicator"
    description = (
        "UnivFD (Ojha et al., CVPR 2023): frozen CLIP ViT-L/14 features + linear probe; probability "
        "that the central 224x224 region resembles generated images seen in training."
    )
    family = Family.AI_DETECTOR
    tier = 1
    requires_gpu = True
    triage_indicator = True
    required_weights = ["clip-vit-l14", "univfd-fc"]  # noqa: RUF012
    default_params = {"crop": 224}  # noqa: RUF012
    limitations = (
        "TRIAGE INDICATOR ONLY. Trained on ProGAN images; accuracy degrades substantially on newer "
        "generators, on edited (rather than fully generated) images and after social-media "
        "compression or resizing. Only the central 224x224 pixels are analysed. Open-source "
        "detectors lose roughly half their accuracy on in-the-wild deepfakes (Deepfake-Eval-2024). "
        "Reported separately from other detectors and never averaged with them."
    )

    def availability(self) -> Availability:
        if not torch_available():
            return Availability(False, "PyTorch is not installed in this image")
        return weights_availability(self.required_weights)

    def _model(self) -> tuple[Any, Any, dict[str, str]]:
        import torch

        from app.modules._vendor.clip_visual import visual_from_clip_state

        clip_state, clip_sha, _ = load_checkpoint("clip-vit-l14")
        fc_state, fc_sha, _ = load_checkpoint("univfd-fc")
        key = clip_sha + fc_sha
        if key not in _cache:
            visual = visual_from_clip_state(clip_state)
            fc = torch.nn.Linear(visual.proj.shape[1], 1)
            fc.load_state_dict({k: v.float() for k, v in fc_state.items()}, strict=True)
            dev = device()
            _cache.clear()
            _cache[key] = (visual.to(dev).eval(), fc.to(dev).eval())
        visual, fc = _cache[key]
        return visual, fc, {"clip-vit-l14": clip_sha, "univfd-fc": fc_sha}

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        import torch

        from app.modules._vendor.clip_visual import CLIP_MEAN, CLIP_STD

        p = self.merged_params(params)
        rgb, info = load_rgb(item.path)
        crop = center_crop(rgb, int(p["crop"]))
        visual, fc, weights = self._model()
        dev = device()
        x = torch.from_numpy(crop.astype(np.float32) / 255.0).permute(2, 0, 1)[None]
        mean = torch.tensor(CLIP_MEAN).view(1, 3, 1, 1)
        std = torch.tensor(CLIP_STD).view(1, 3, 1, 1)
        x = ((x - mean) / std).to(dev)
        logit, mode = deterministic_forward(lambda: fc(visual(x)).item())
        prob = r6(1.0 / (1.0 + np.exp(-logit)))
        return Finding(
            scores=[
                Score("probability_generated", prob, (0, 1),
                      "Triage indicator. Higher = the central crop's CLIP features are closer to the "
                      "generated images UnivFD was trained on. Not a probability that this image is "
                      "fake; not calibrated on our test set."),
                Score("logit", r6(logit), None, "Raw linear-probe output (sigmoid gives the score above)."),
            ],
            summary=(f"UnivFD triage indicator {prob:.3f} on the central {p['crop']}px crop. "
                     "Interpret only alongside the other findings; this detector alone cannot "
                     "establish whether the image is generated."),
            limitations=self.limitations,
            details={"decode": info, "analysed_region": "centre crop", "device": str(dev)},
            provenance={"weights": weights, "determinism_mode": mode},
        )


MODULE = UnivFD()
