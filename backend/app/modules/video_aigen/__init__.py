"""video.aigen: frame-level AI-generation indicators (SRS FR-3.2).

Samples keyframes plus 1 frame per second and scores each frame with the same
UnivFD and NPR implementations as the image modules. The two detectors are
reported separately, never averaged; a score timeline and the most
suspicious frames are produced for the examiner.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.modules._common.imaging import r6, save_plot, save_png
from app.modules._common.media import contact_sheet, load_frame, sample_frames, tools_available
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
from app.modules.image_aigen_commfor import MODULE as COMMFOR
from app.modules.image_aigen_npr import MODULE as NPR
from app.modules.image_aigen_univfd import MODULE as UNIVFD

THRESHOLD = 0.5


class VideoAIGen(ModuleBase):
    id = "video.aigen"
    version = "1.1.0"
    name = "Frame-level AI-generation indicators"
    description = ("Keyframes plus 1 frame/second scored by the AI-generation detectors (Community Forensics, "
                   "UnivFD, NPR), reported separately with a per-frame timeline and the most suspicious frames.")
    family = Family.AI_DETECTOR
    media_types = {MediaType.VIDEO}  # noqa: RUF012
    tier = 1
    requires_gpu = True
    triage_indicator = True
    screening_core = True
    default_params = {"fps": 1.0, "max_frames": 60, "max_keyframes": 30}  # noqa: RUF012
    headline = ("ai_likelihood", 0.5)
    question = "ai_generated"
    plain = 'Runs the AI-generation tests on frames across the video.'
    limitations = (
        "TRIAGE INDICATOR ONLY. Inherits every limitation of UnivFD and NPR: trained on still images from older "
        "generators, weakened by video compression, resizing and platform re-encoding, and blind to manipulations "
        "confined to small regions (e.g. a swapped face in a wide shot). Only sampled frames are analysed. "
        "Detectors are reported separately and never averaged."
    )

    def availability(self) -> Availability:
        ok, reason = tools_available()
        if not ok:
            return Availability(False, reason)
        u, n, c = UNIVFD.availability(), NPR.availability(), COMMFOR.availability()
        if not (u.available or n.available or c.available):
            return Availability(False, f"neither UnivFD nor NPR weights are available ({u.reason})")
        return Availability(True)

    def screen(self, scores: dict[str, float | None], details: dict[str, Any]) -> str | None:
        p = scores.get("ai_likelihood")
        if p is not None and p >= THRESHOLD:
            return (f"AI-generation detector: {p * 100:.0f}% average likelihood across the sampled frames that the "
                    "video was made by AI (threshold 50%)")
        hits = []
        for det in ("univfd", "npr"):
            frac = scores.get(f"{det}_frames_above_threshold")
            if frac is not None and frac >= 0.25:
                hits.append(f"{det.upper()} on {frac * 100:.0f}% of sampled frames")
        if hits:
            return f"Frame-level AI-generation scores at or above 0.50: {'; '.join(hits)} (threshold: 25% of frames)"
        return None

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        p = self.merged_params(params)
        frames = sample_frames(item.path, item.workdir / "frames", float(p["fps"]), int(p["max_frames"]),
                               int(p["max_keyframes"]))
        if not frames:
            raise ValueError("no frames could be decoded from the video")
        use_u, use_n = UNIVFD.availability().available, NPR.availability().available
        use_c = COMMFOR.availability().available
        if not (use_u or use_n or use_c):
            from app.modules.base import ModuleUnavailable

            raise ModuleUnavailable("neither UnivFD nor NPR weights are available")
        times, u_scores, n_scores, c_scores, weights, modes = [], [], [], [], {}, set()
        for fr in frames:
            rgb = load_frame(fr)
            times.append(fr.t)
            if use_c:
                prob, _, sha = COMMFOR.score(rgb)
                c_scores.append(prob)
                weights["commfor-vit-s384"] = sha
            if use_u:
                prob, _, mode, w = UNIVFD.score(rgb)
                u_scores.append(prob)
                weights.update(w)
                modes.add(mode)
            if use_n:
                prob, _, mode, sha, _ = NPR.score(rgb)
                n_scores.append(prob)
                weights["npr"] = sha
                modes.add(mode)

        out = item.workdir
        traces = []
        if c_scores:
            traces.append({"type": "scatter", "mode": "lines+markers", "name": "Community Forensics", "x": times,
                           "y": c_scores})
        if u_scores:
            traces.append({"type": "scatter", "mode": "lines+markers", "name": "UnivFD", "x": times, "y": u_scores})
        if n_scores:
            traces.append({"type": "scatter", "mode": "lines+markers", "name": "NPR", "x": times, "y": n_scores})
        save_plot({"data": traces, "layout": {
            "title": "AI-generation indicator per sampled frame (separate detectors)",
            "xaxis": {"title": "time (s) — click to jump"}, "yaxis": {"title": "score", "range": [0, 1]},
            "shapes": [{"type": "line", "x0": 0, "x1": max(times) if times else 1, "y0": THRESHOLD, "y1": THRESHOLD,
                        "line": {"dash": "dot", "color": "#b45309"}}]}}, out / "frame_timeline.json")
        combined = c_scores or ([max(a, b) for a, b in zip(u_scores, n_scores, strict=True)]
                                if u_scores and n_scores else (u_scores or n_scores))
        top = sorted(range(len(frames)), key=lambda i: (-combined[i], times[i]))[:4]
        save_png(contact_sheet([(f"t={times[i]:.1f}s  AI={combined[i] * 100:.0f}%",
                                 load_frame(frames[i])) for i in sorted(top)]), out / "top_frames.png")

        def stats(name: str, vals: list[float]) -> list[Score]:
            if not vals:
                return [Score(f"{name}_max", None, (0, 1), f"{name.upper()} weights not installed: not computed.")]
            arr = np.array(vals)
            return [
                Score(f"{name}_max", r6(arr.max()), (0, 1), f"Highest {name.upper()} frame score (triage indicator)."),
                Score(f"{name}_mean", r6(arr.mean()), (0, 1), f"Mean {name.upper()} frame score."),
                Score(f"{name}_frames_above_threshold", r6((arr >= THRESHOLD).mean()), (0, 1),
                      f"Fraction of sampled frames with {name.upper()} score >= {THRESHOLD}."),
            ]

        scores = [Score("frames_analysed", float(len(frames)), None, "Number of sampled frames scored.")]
        if c_scores:
            ca = np.array(c_scores)
            scores += [
                Score("ai_likelihood", r6(ca.mean()), (0, 1),
                      "Estimated likelihood (0-100%) that the video was made by AI: average Community Forensics "
                      "score over the sampled frames. Detector output, not proof."),
                Score("ai_likelihood_max", r6(ca.max()), (0, 1), "Highest single-frame likelihood."),
                Score("ai_frames_above_threshold", r6((ca >= THRESHOLD).mean()), (0, 1),
                      "Fraction of sampled frames with likelihood >= 50%."),
            ]
        scores += stats("univfd", u_scores) + stats("npr", n_scores)
        parts = [f"{len(frames)} frames over {times[-1]:.0f} s"]
        if c_scores:
            parts.append(f"AI-generation likelihood {np.mean(c_scores) * 100:.0f}% (average over frames, "
                         f"{(np.array(c_scores) >= THRESHOLD).mean() * 100:.0f}% of frames above 50%)")
        if u_scores:
            parts.append(f"UnivFD max {max(u_scores):.2f}")
        if n_scores:
            parts.append(f"NPR max {max(n_scores):.2f}")
        return Finding(
            scores=scores,
            summary="; ".join(parts) + ". See the timeline for where scores rise; scores are indicators only.",
            limitations=self.limitations,
            artefacts=[
                Artefact("frame_timeline.json", out / "frame_timeline.json", ArtefactKind.PLOT,
                         "Per-frame scores over time", "application/json"),
                Artefact("top_frames.png", out / "top_frames.png", ArtefactKind.IMAGE, "Highest-scoring sampled frames"),
            ],
            details={"frames": [{"t": t, "commfor": c_scores[i] if c_scores else None,
                                 "univfd": u_scores[i] if u_scores else None,
                                 "npr": n_scores[i] if n_scores else None, "keyframe": frames[i].keyframe}
                                for i, t in enumerate(times)]},
            provenance={"weights": weights, "determinism_mode": ", ".join(sorted(modes))},
        )


MODULE = VideoAIGen()
