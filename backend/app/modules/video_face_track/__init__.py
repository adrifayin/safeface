"""video.face_track: face detection and tracking on sampled frames (TDD §3.3).

InsightFace SCRFD detector on keyframes + 1 fps; faces are linked across
frames by box overlap. Used by the examiner to see who appears where, and as
the basis of face-level manipulation scores.
"""

from __future__ import annotations

from typing import Any

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


class VideoFaceTrack(ModuleBase):
    id = "video.face_track"
    version = "1.0.0"
    name = "Face tracks"
    description = "InsightFace (SCRFD) face detection on sampled frames, linked into tracks by box overlap."
    family = Family.COMPARISON
    media_types = {MediaType.VIDEO}  # noqa: RUF012
    tier = 1
    required_weights = [faces.DETECTOR]  # noqa: RUF012
    default_params = {"fps": 1.0, "max_frames": 60}  # noqa: RUF012
    headline = ("track_count", None)
    plain = 'Finds the faces in the video and follows them over time.'
    limitations = (
        "Small, blurred, profile or occluded faces are missed; tracks can break or merge when faces cross or "
        "the camera cuts. Only sampled frames are examined. Detection is not identification."
    )

    def availability(self) -> Availability:
        ok, reason = tools_available()
        return Availability(ok, reason) if not ok else super().availability()

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        p = self.merged_params(params)
        frames = sample_frames(item.path, item.workdir / "frames", float(p["fps"]), int(p["max_frames"]), 0)
        det, sha = faces.load_detector()
        per_frame = [(fr.t, faces.detect(det, load_frame(fr))) for fr in frames]
        tracks = faces.track(per_frame)
        with_face = sum(1 for _, f in per_frame if f)
        save_plot({"data": [{"type": "scatter", "mode": "markers", "name": f"track {i + 1}",
                             "x": [t for t, _ in tr], "y": [i + 1] * len(tr)} for i, tr in enumerate(tracks)],
                   "layout": {"title": "Face tracks over time", "xaxis": {"title": "time (s)"},
                              "yaxis": {"title": "track", "dtick": 1}}}, item.workdir / "face_tracks.json")
        return Finding(
            scores=[
                Score("frames_analysed", float(len(frames)), None, "Sampled frames examined."),
                Score("frames_with_face", r6(with_face / max(1, len(frames))), (0, 1), "Fraction of frames with at least one face."),
                Score("track_count", float(len(tracks)), None, "Number of distinct face tracks."),
                Score("max_faces_in_frame", float(max((len(f) for _, f in per_frame), default=0)), None,
                      "Largest number of faces in a single frame."),
            ],
            summary=f"{len(tracks)} face track(s); faces in {with_face} of {len(frames)} sampled frames.",
            limitations=self.limitations,
            artefacts=[Artefact("face_tracks.json", item.workdir / "face_tracks.json", ArtefactKind.PLOT,
                                "When each face track is visible", "application/json")],
            details={"tracks": [[{"t": t, "box": [r6(v) for v in f.box], "score": r6(f.score)} for t, f in tr]
                                for tr in tracks]},
            provenance={"weights": {faces.DETECTOR: sha}},
        )


MODULE = VideoFaceTrack()
