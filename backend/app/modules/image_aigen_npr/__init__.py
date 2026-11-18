"""image.aigen.npr: NPR detector (Tan et al., CVPR 2024).

Scores up-sampling artefacts left by generative networks, using the
Neighbouring Pixel Relationships residual. Following the authors' test
protocol for full-size images, the image is not resized; very large images
are centre-cropped (not resized, which would destroy the artefacts) to at
most ``max_side`` pixels per side, and odd dimensions are trimmed by 1 px.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.modules._common.imaging import load_rgb, r6
from app.modules._common.torchutil import (
    deterministic_forward,
    device,
    load_checkpoint,
    strip_prefix,
    torch_available,
)
from app.modules.base import Availability, Family, Finding, ModuleBase, Score, WorkingCopy
from app.modules.weights import weights_availability

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
_cache: dict[str, Any] = {}


def unwrap_state(obj: Any) -> dict[str, Any]:
    """The official NPR.pth is {"model": state_dict, "optimizer": ..., "total_steps": ...}."""
    if isinstance(obj, dict) and isinstance(obj.get("model"), dict):
        obj = obj["model"]
    return strip_prefix(obj)


class NPR(ModuleBase):
    id = "image.aigen.npr"
    version = "1.0.0"
    name = "NPR AI-generation indicator"
    description = (
        "NPR (Tan et al., CVPR 2024): truncated ResNet-50 on the nearest-neighbour up-sampling "
        "residual; probability that the image shows generator up-sampling artefacts."
    )
    family = Family.AI_DETECTOR
    tier = 1
    requires_gpu = True
    triage_indicator = True
    required_weights = ["npr"]  # noqa: RUF012
    default_params = {"max_side": 1024}  # noqa: RUF012
    limitations = (
        "TRIAGE INDICATOR ONLY. Trained on ProGAN (4-class) images; it responds to up-sampling "
        "artefacts, which recompression, resizing and screenshots weaken or remove, and which some "
        "newer generators do not leave. Accuracy on in-the-wild images is substantially lower than "
        "published benchmark figures. Reported separately from UnivFD and never averaged with it."
    )

    def availability(self) -> Availability:
        if not torch_available():
            return Availability(False, "PyTorch is not installed in this image")
        return weights_availability(self.required_weights)

    def _model(self) -> tuple[Any, str]:
        from app.modules._vendor.npr_resnet import NPRNet

        state, sha, _ = load_checkpoint("npr")
        if sha not in _cache:
            net = NPRNet()
            net.load_state_dict(unwrap_state(state), strict=True)
            _cache.clear()
            _cache[sha] = net.to(device()).eval()
        return _cache[sha], sha

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        import torch

        p = self.merged_params(params)
        rgb, info = load_rgb(item.path)
        h, w = rgb.shape[:2]
        side = int(p["max_side"])
        ch, cw = min(h, side), min(w, side)
        top, left = (h - ch) // 2, (w - cw) // 2
        crop = rgb[top:top + ch, left:left + cw]
        crop = crop[: crop.shape[0] // 2 * 2, : crop.shape[1] // 2 * 2]
        net, sha = self._model()
        dev = device()
        x = torch.from_numpy(crop.astype(np.float32) / 255.0).permute(2, 0, 1)[None]
        x = ((x - torch.tensor(IMAGENET_MEAN).view(1, 3, 1, 1))
             / torch.tensor(IMAGENET_STD).view(1, 3, 1, 1)).to(dev)
        logit, mode = deterministic_forward(lambda: net(x).item())
        prob = r6(1.0 / (1.0 + np.exp(-logit)))
        region = "full image" if (ch, cw) == (h, w) else f"centre {crop.shape[1]}x{crop.shape[0]} crop"
        return Finding(
            scores=[
                Score("probability_generated", prob, (0, 1),
                      "Triage indicator. Higher = stronger generator up-sampling artefacts as learned "
                      "by NPR. Not a probability that this image is fake; not calibrated on our test set."),
                Score("logit", r6(logit), None, "Raw network output (sigmoid gives the score above)."),
            ],
            summary=(f"NPR triage indicator {prob:.3f} ({region}). Interpret only alongside the other "
                     "findings; this detector alone cannot establish whether the image is generated."),
            limitations=self.limitations,
            details={"decode": info, "analysed_region": region, "device": str(dev)},
            provenance={"weights": {"npr": sha}, "determinism_mode": mode},
        )


MODULE = NPR()
