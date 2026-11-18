"""image.trufor: TruFor forgery localization (Guillaro et al., CVPR 2023).

TruFor combines RGB with a learned camera-noise fingerprint (Noiseprint++)
in a SegFormer-based network and outputs:
- a localization (anomaly) map: per-pixel probability of manipulation;
- a confidence (reliability) map: where the localization map can be trusted;
- an integrity score: image-level probability that the image is manipulated.

Licensing: TruFor's code and weights are licensed by GRIP-UNINA for
non-profit use only, so neither is shipped in this repository. An admin
installs, offline and checksum-verified (scripts/fetch_models.md):
- ``trufor-src``: ``git archive`` of upstream ``test_docker/src`` at a pinned commit;
- ``trufor``: the official ``trufor.pth.tar`` checkpoint.
This wrapper reproduces the upstream ``trufor_test.py`` inference exactly
(input = RGB / 256, softmax channel 1, sigmoid confidence and score).
"""

from __future__ import annotations

import sys
import tarfile
import threading
from pathlib import Path
from typing import Any, cast

import numpy as np

from app.modules._common.imaging import Array, colormap, load_rgb, r6, save_png
from app.modules._common.torchutil import (
    deterministic_forward,
    device,
    load_checkpoint,
    torch_available,
)
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
from app.modules.weights import resolve, weights_availability

SRC_SUBDIR = "test_docker/src"
_cache: dict[str, Any] = {}
_lock = threading.Lock()


def _prepare_source() -> tuple[Path, str]:
    """Verify the source archive and extract it (once per process) to /tmp."""
    archive, sha = resolve("trufor-src")
    target = Path("/tmp") / f"safeface-trufor-{sha[:16]}"  # noqa: S108 - per-container tmpfs
    if not (target / SRC_SUBDIR / "trufor.yaml").exists():
        target.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as tar:
            tar.extractall(target, filter="data")  # refuses absolute paths, links out, devices
    return target / SRC_SUBDIR, sha


class TruFor(ModuleBase):
    id = "image.trufor"
    version = "1.0.0"
    name = "TruFor forgery localization"
    description = (
        "TruFor (Guillaro et al., CVPR 2023): RGB + Noiseprint++ SegFormer network giving a "
        "per-pixel localization map, a reliability (confidence) map and an image integrity score."
    )
    family = Family.CLASSICAL
    tier = 1
    requires_gpu = True
    screening_core = True

    def screen(self, scores: dict[str, float | None], details: dict[str, Any]) -> str | None:
        s = scores.get("integrity_score")
        if s is not None and s >= 0.5:
            return f"TruFor integrity score {s:.2f} is at or above the 0.50 screening threshold (see localization map)"
        return None
    required_weights = ["trufor-src", "trufor"]  # noqa: RUF012
    default_params = {"max_pixels": 12_000_000}  # noqa: RUF012
    headline = ("integrity_score", 0.5)
    plain = 'AI tool that marks where a photo may have been edited (0 = clean, 1 = edited).'
    limitations = (
        "Weaker on heavily recompressed, resized or screenshotted images (e.g. after messaging-app "
        "round-trips), where the camera-noise traces it relies on are lost. Trained mostly on "
        "splicing/copy-move/inpainting datasets; fully AI-generated images are not its target. "
        "Read the localization map only where the confidence map is high. Scores vary slightly "
        "across library versions and hardware. Research licence (non-profit use)."
    )

    def availability(self) -> Availability:
        if not torch_available():
            return Availability(False, "PyTorch is not installed in this image")
        return weights_availability(self.required_weights)

    def _model(self) -> tuple[Any, dict[str, str], list[str]]:
        with _lock:
            src_dir, src_sha = _prepare_source()
            ckpt, w_sha, w_path = load_checkpoint("trufor")
            key = src_sha + w_sha
            if key in _cache:
                return cast(tuple[Any, dict[str, str], list[str]], _cache[key])
            from app.modules._vendor import shims

            shim_names = shims.install()
            if str(src_dir) not in sys.path:
                sys.path.insert(0, str(src_dir))
            import config as tf_config  # upstream test_docker/src/config.py
            from models.cmx.builder_np_conf import myEncoderDecoder  # upstream

            cfg = tf_config._C.clone()
            cfg.defrost()
            cfg.merge_from_file(src_dir / "trufor.yaml")
            cfg.TEST.MODEL_FILE = str(w_path)
            cfg.MODEL.PRETRAINED = ""  # never let the constructor load anything else
            cfg.freeze()
            net = myEncoderDecoder(cfg=cfg)
            state = ckpt["state_dict"] if isinstance(ckpt, dict) and "state_dict" in ckpt else ckpt
            net.load_state_dict(state, strict=True)
            net = net.to(device()).eval()
            _cache.clear()
            entry = (net, {"trufor-src": src_sha, "trufor": w_sha}, shim_names)
            _cache[key] = entry
            return entry

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        import torch
        from torch.nn import functional as F

        p = self.merged_params(params)
        rgb, info = load_rgb(item.path)
        h, w = rgb.shape[:2]
        if h * w > int(p["max_pixels"]):
            raise ValueError(f"image has {h * w} pixels, above max_pixels={p['max_pixels']} for this "
                             "hardware; an examiner may raise the limit (needs more GPU memory)")
        net, weights, shim_names = self._model()
        dev = device()
        x = (torch.tensor(rgb.transpose(2, 0, 1), dtype=torch.float) / 256.0)[None].to(dev)

        def infer() -> tuple[Array, Array | None, float | None]:
            pred, conf, det, _ = net(x)
            loc = F.softmax(torch.squeeze(pred, 0), dim=0)[1].cpu().numpy()
            cmap = torch.sigmoid(torch.squeeze(conf, 0))[0].cpu().numpy() if conf is not None else None
            score = torch.sigmoid(det).item() if det is not None else None
            return loc, cmap, score

        (loc, conf, score), mode = deterministic_forward(infer)
        out = item.workdir
        save_png(colormap(loc, "inferno"), out / "trufor_localization.png")
        np.save(out / "trufor_localization.npy", loc.astype(np.float16))  # raw map for benchmark F1/IoU
        artefacts = [Artefact("trufor_localization.png", out / "trufor_localization.png",
                              ArtefactKind.HEATMAP, "TruFor localization map (bright = likely manipulated)"),
                     Artefact("trufor_localization.npy", out / "trufor_localization.npy", ArtefactKind.JSON,
                              "Raw localization map (NumPy float16)", "application/octet-stream")]
        if conf is not None:
            save_png(colormap(conf, "viridis"), out / "trufor_confidence.png")
            artefacts.append(Artefact("trufor_confidence.png", out / "trufor_confidence.png",
                                      ArtefactKind.HEATMAP,
                                      "TruFor confidence map (bright = localization is reliable)"))
        weighted = float((loc * conf).sum() / max(conf.sum(), 1e-9)) if conf is not None else None
        area = float((loc > 0.5).mean())
        return Finding(
            scores=[
                Score("integrity_score", r6(score) if score is not None else None, (0, 1),
                      "Image-level score: higher = TruFor considers the image more likely manipulated."),
                Score("localization_area", r6(area), (0, 1),
                      "Fraction of pixels with localization > 0.5 (candidate manipulated area)."),
                Score("confidence_weighted_localization", r6(weighted) if weighted is not None else None,
                      (0, 1), "Mean localization weighted by confidence: down-weights unreliable areas."),
                Score("mean_confidence", r6(float(conf.mean())) if conf is not None else None, (0, 1),
                      "Average reliability of the localization map."),
            ],
            summary=(f"TruFor integrity score {score:.3f}; {area * 100:.2f}% of pixels above 0.5 on the "
                     "localization map. Read the map only where the confidence map is bright."
                     if score is not None else "TruFor localization computed."),
            limitations=self.limitations, artefacts=artefacts,
            details={"decode": info, "device": str(dev), "shims": shim_names},
            provenance={"weights": weights, "determinism_mode": mode,
                        "upstream": "grip-unina/TruFor test_docker/src"},
        )


MODULE = TruFor()
