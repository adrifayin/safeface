"""video.temporal: temporal consistency of the main face (SRS FR-3.4).

Frame-by-frame generators and face swaps are often temporally unstable: the
swapped identity drifts or "flickers" between frames. The module tracks the
largest face at 5 fps and measures (a) ArcFace identity similarity between
consecutive frames and (b) frame-to-frame variation of the SBI face score,
when the SBI weights are installed.

Deviation from the TDD, stated plainly: FTCN (Zheng et al., ICCV 2021) is not
integrated — its repository has no licence and targets PyTorch 1.4 / SlowFast.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.modules._common import faces
from app.modules._common.imaging import r6, save_plot
from app.modules._common.media import load_frame, sample_frames, tools_available
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


class VideoTemporal(ModuleBase):
    id = "video.temporal"
    version = "1.0.0"
    name = "Temporal face consistency"
    description = ("Largest face at 5 fps: ArcFace identity similarity between consecutive frames (identity drift) "
                   "and SBI score flicker.")
    family = Family.AI_DETECTOR
    media_types = {MediaType.VIDEO}  # noqa: RUF012
    tier = 2
    requires_gpu = True
    triage_indicator = True
    required_weights = [faces.DETECTOR, faces.RECOGNISER]  # noqa: RUF012
    default_params = {"fps": 5.0, "seconds": 60, "dip_threshold": 0.5}  # noqa: RUF012
    headline = ("identity_dips", None)
    question = "face_swap"
    plain = 'Checks whether the face stays the same person from frame to frame.'
    limitations = (
        "TRIAGE INDICATOR ONLY. Camera cuts, a second person, fast head turns, occlusion, motion blur and heavy "
        "compression also lower consecutive-frame identity similarity. Stable identity does not exclude a "
        "well-made deepfake. FTCN, proposed in the TDD, is not integrated (no licence, incompatible framework)."
    )

    def availability(self) -> Availability:
        ok, reason = tools_available()
        return Availability(False, reason) if not ok else super().availability()

    def screen(self, scores: dict[str, float | None], details: dict[str, Any]) -> str | None:
        dips, n = scores.get("identity_dips") or 0, scores.get("frames_with_face") or 0
        if n >= 10 and dips / n >= 0.1:
            return f"Face identity changes abruptly between frames {dips:.0f} times in {n:.0f} frames (threshold 10%)"
        return None

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        from app.modules.video_face_frame_scores import MODULE as SBI

        p = self.merged_params(params)
        frames = sample_frames(item.path, item.workdir / "frames", float(p["fps"]), int(float(p["fps"]) * int(p["seconds"])), 0)
        det, det_sha = faces.load_detector()
        rec, rec_sha = faces.load_recogniser()
        use_sbi = SBI.availability().available
        times, embs, sbi = [], [], []
        for fr in frames:
            rgb = load_frame(fr)
            found = faces.detect(det, rgb)
            if not found:
                continue
            times.append(fr.t)
            embs.append(faces.embedding(rec, rgb, found[0]))
            if use_sbi:
                scored = SBI.score_faces(rgb, det)
                sbi.append(max(s for _, s in scored) if scored else np.nan)
        weights = {faces.DETECTOR: det_sha, faces.RECOGNISER: rec_sha}
        if len(embs) < 3:
            return Finding(scores=[Score("frames_with_face", float(len(embs)), None, "Frames with a face.")],
                           summary="Too few frames with a face for temporal analysis.", limitations=self.limitations,
                           provenance={"weights": weights})
        sims = [float(np.dot(embs[i], embs[i + 1])) for i in range(len(embs) - 1)]
        dips = int(sum(s < float(p["dip_threshold"]) for s in sims))
        traces = [{"type": "scatter", "mode": "lines+markers", "name": "identity similarity to previous frame",
                   "x": times[1:], "y": [r6(s) for s in sims]}]
        flicker = None
        if sbi and not np.all(np.isnan(sbi)):
            arr = np.array(sbi, dtype=np.float64)
            flicker = float(np.nanmean(np.abs(np.diff(arr))))
            traces.append({"type": "scatter", "mode": "lines", "name": "SBI score", "x": times,
                           "y": [None if np.isnan(v) else r6(v) for v in arr]})
            weights["sbi"] = "see video.face_frame_scores provenance"
        save_plot({"data": traces, "layout": {"title": "Temporal face consistency", "xaxis": {"title": "time (s) — click to jump"},
                                              "yaxis": {"range": [-0.1, 1.05]}}}, item.workdir / "temporal.json")
        return Finding(
            scores=[
                Score("frames_with_face", float(len(embs)), None, "Frames in which the main face was found."),
                Score("min_identity_similarity", r6(min(sims)), (-1, 1), "Lowest ArcFace similarity between consecutive frames."),
                Score("identity_dips", float(dips), None, f"Consecutive-frame similarities below {p['dip_threshold']}."),
                Score("sbi_flicker", r6(flicker) if flicker is not None else None, (0, 1),
                      "Mean absolute change of the SBI score between frames (null = SBI not installed)."),
            ],
            summary=f"{len(embs)} frames with a face; lowest consecutive identity similarity {min(sims):.2f}; {dips} dip(s).",
            limitations=self.limitations,
            artefacts=[Artefact("temporal.json", item.workdir / "temporal.json", ArtefactKind.PLOT,
                                "Identity similarity and SBI score over time", "application/json")],
            details={"similarities": [r6(s) for s in sims]},
            provenance={"weights": weights},
        )


MODULE = VideoTemporal()
