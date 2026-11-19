"""video.aigen.cakelens: CakeLens v5 AI-generated-video detector (Launch Platform, 2025, MIT).

A space-time 3D CNN that looks at blocks of 9 consecutive frames (motion as
well as pixels) and was trained on 5,000+ real and AI videos collected from
social media (X), so platform re-encoding is part of its training data. It
outputs 17 sigmoid scores: AI_GEN (any AI video) plus one per known source
(Veo, Sora, Kling, Hailuo, Runway, ...). Only AI_GEN is used for screening;
the source labels are shown as a hint (the authors report they are much
less accurate than AI_GEN).

Preprocessing is the authors' (datasets.py / model.py): native-resolution
RGB frames, top-left 512x512 crop with zero padding, /255, their mean/std,
RGB of the 9 frames stacked into the depth axis. Upstream scores every
9-frame block of the video; to bound CPU time SafeFace scores up to
``max_framesets`` blocks spread evenly over the video (documented in the
finding) and averages them, as upstream does.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.modules._common.imaging import r6, run_tool, save_plot
from app.modules._common.media import ffprobe, tools_available, video_stream
from app.modules._common.torchutil import deterministic_forward, device, load_checkpoint, torch_available
from app.modules.base import (
    Artefact,
    ArtefactKind,
    Availability,
    Family,
    Finding,
    MediaType,
    ModuleBase,
    Score,
    WorkingCopy,
)
from app.modules.weights import weights_availability

WEIGHTS = "cakelens-v5"
THRESHOLD = 0.5
_cache: dict[str, Any] = {}


def read_block(path: Any, start: float, width: int, height: int, n: int = 9) -> list[np.ndarray]:
    """n consecutive RGB frames from ``start`` seconds at native resolution (ffmpeg rawvideo)."""
    res = run_tool(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{start:.3f}", "-i", str(path), "-frames:v", str(n),
                    "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], timeout=300)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {res.stderr.decode(errors='replace')[:300]}")
    size = width * height * 3
    buf = res.stdout
    return [np.frombuffer(buf[i * size:(i + 1) * size], dtype=np.uint8).reshape(height, width, 3)
            for i in range(len(buf) // size)]


class CakeLens(ModuleBase):
    id = "video.aigen.cakelens"
    version = "1.0.0"
    name = "AI-video detector (CakeLens, motion + pixels)"
    description = ("CakeLens v5: 3D CNN over blocks of 9 consecutive frames, trained on real and AI videos from "
                   "social media; estimated likelihood that the video was made by an AI video generator.")
    family = Family.AI_DETECTOR
    media_types = {MediaType.VIDEO}  # noqa: RUF012
    tier = 1
    requires_gpu = True
    triage_indicator = True
    screening_core = True
    required_weights = [WEIGHTS]  # noqa: RUF012
    default_params = {"max_framesets": 6}  # noqa: RUF012
    headline = ("ai_likelihood", THRESHOLD)
    question = "ai_generated"
    plain = "AI tool trained on AI videos from social media; looks at motion across frames as well as pixels."
    limitations = (
        "TRIAGE INDICATOR ONLY. Authors' test set (498 social-media videos): precision 0.77, recall 0.74 at the 50% "
        "threshold, i.e. roughly 1 in 4 AI videos is missed and 1 in 4 flags is a real video. Not validated on "
        "SafeFace casework. Generators newer than the training data, heavy editing, screen recordings and "
        "animation can mislead it. The source label (Veo, Sora, ...) is a weak hint only. Up to six 9-frame "
        "blocks are scored, not the whole video."
    )

    def availability(self) -> Availability:
        ok, reason = tools_available()
        if not ok:
            return Availability(False, reason)
        if not torch_available():
            return Availability(False, "PyTorch is not installed in this image")
        return weights_availability(self.required_weights)

    def _model(self) -> tuple[Any, str]:
        from app.modules._vendor.cakelens import build

        if not _cache:
            obj, sha, _ = load_checkpoint(WEIGHTS)
            state = obj.get("model_state_dict", obj) if isinstance(obj, dict) else obj
            _cache[sha] = build(state).to(device())
        sha = next(iter(_cache))
        return _cache[sha], sha

    def score_video(self, path: Any, max_framesets: int) -> dict[str, Any]:
        import torch

        from app.modules._vendor.cakelens import FRAMESET_COUNT, LABELS, frameset_tensor

        probe = ffprobe(path)
        vs = video_stream(probe)
        if vs is None:
            raise ValueError("no video stream")
        w, h = int(vs["width"]), int(vs["height"])
        dur = float(probe.get("format", {}).get("duration") or vs.get("duration") or 0) or 1.0
        fps = 25.0
        try:
            num, _, den = str(vs.get("avg_frame_rate", "25/1")).partition("/")
            fps = float(num) / float(den or 1) or 25.0
        except (ValueError, ZeroDivisionError):
            pass
        block_s = FRAMESET_COUNT / fps
        n = max(1, min(max_framesets, int(dur // block_s)))
        starts = [float(t) for t in np.linspace(0.0, max(0.0, dur - block_s), n)]
        model, sha = self._model()
        rows, times = [], []
        for t in starts:
            frames = read_block(path, t, w, h, FRAMESET_COUNT)
            if not frames:
                continue
            x = frameset_tensor(frames)[None].to(device())  # (1, 1, 27, 512, 512)
            with torch.no_grad():
                p, mode = deterministic_forward(lambda x=x: model(x).sigmoid()[0].double().cpu().numpy())
            rows.append(p)
            times.append(t)
        if not rows:
            raise ValueError("no frames could be decoded from the video")
        arr = np.vstack(rows)
        mean = arr.mean(axis=0)
        gen = {LABELS[i]: float(mean[i]) for i in range(4, len(LABELS))}
        top = max(gen, key=lambda k: gen[k])
        return {"ai": float(mean[0]), "per_block": [float(v) for v in arr[:, 0]], "times": times, "sha": sha,
                "labels": {LABELS[i]: r6(float(mean[i])) for i in range(len(LABELS))}, "top_source": top,
                "top_source_score": gen[top], "mode": mode, "blocks": len(rows), "width": w, "height": h}

    def screen(self, scores: dict[str, float | None], details: dict[str, Any]) -> str | None:
        p = scores.get("ai_likelihood")
        if p is not None and p >= THRESHOLD:
            return f"AI-video detector: {p * 100:.0f}% likelihood that the video was made by an AI video generator (threshold 50%)"
        return None

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        p = self.merged_params(params)
        r = self.score_video(item.path, int(p["max_framesets"]))
        save_plot({"data": [{"type": "scatter", "mode": "lines+markers", "name": "CakeLens AI_GEN",
                             "x": r["times"], "y": r["per_block"]}],
                   "layout": {"title": "AI-video likelihood per 9-frame block",
                              "xaxis": {"title": "time (s) — click to jump"}, "yaxis": {"title": "likelihood", "range": [0, 1]},
                              "shapes": [{"type": "line", "x0": 0, "x1": max(r["times"]) or 1, "y0": THRESHOLD,
                                          "y1": THRESHOLD, "line": {"dash": "dot", "color": "#b45309"}}]}},
                  item.workdir / "cakelens_timeline.json")
        ai = r6(r["ai"])
        hint = (f" Most similar known source: {r['top_source'].title()} ({r['top_source_score'] * 100:.0f}%, weak hint)."
                if r["top_source_score"] >= 0.3 else "")
        return Finding(
            scores=[
                Score("ai_likelihood", ai, (0, 1),
                      "Estimated likelihood (0-100%) that the video was made by an AI video generator (CakeLens "
                      "AI_GEN, mean over the scored 9-frame blocks). Detector output, not proof."),
                Score("ai_likelihood_max_block", r6(max(r["per_block"])), (0, 1), "Highest single-block likelihood."),
                Score("blocks_above_threshold", r6(float(np.mean(np.array(r["per_block"]) >= THRESHOLD))), (0, 1),
                      "Fraction of scored blocks at or above 50%."),
                Score("blocks_scored", float(r["blocks"]), None, "Number of 9-frame blocks scored."),
            ],
            summary=f"CakeLens: {ai * 100:.0f}% likelihood that this is an AI-generated video "
                    f"({r['blocks']} blocks of 9 frames).{hint}",
            limitations=self.limitations,
            artefacts=[Artefact("cakelens_timeline.json", item.workdir / "cakelens_timeline.json", ArtefactKind.PLOT,
                                "AI-video likelihood over time", "application/json")],
            details={"labels": r["labels"], "top_source": r["top_source"], "block_times": r["times"],
                     "per_block": r["per_block"], "frame_size": [r["width"], r["height"]],
                     "analysed_region": "top-left 512x512 of each frame (authors' preprocessing)", "device": str(device())},
            provenance={"weights": {WEIGHTS: r["sha"]}, "determinism_mode": r["mode"]},
        )


MODULE = CakeLens()
