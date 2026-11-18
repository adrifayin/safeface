"""image.geometry: examiner-assisted perspective and shadow consistency (SRS FR-2.10).

The examiner draws lines on the image:
- perspective: lines that are parallel in the real scene (edges of a building,
  a road, a table) must meet at one vanishing point;
- shadow: lines from a point on each shadow to the matching point on the
  object that casts it must meet at the projection of the light source.
The module fits the common point by least squares (homogeneous coordinates,
SVD) and reports each line's angular disagreement. A pasted object usually
has perspective or shadow lines that do not fit the rest of the scene.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.modules._common.imaging import load_rgb, r6, save_png
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


def common_point(lines: np.ndarray) -> np.ndarray:
    """Least-squares intersection (homogeneous) of lines given as rows x1, y1, x2, y2."""
    h = np.array([np.cross([x1, y1, 1.0], [x2, y2, 1.0]) for x1, y1, x2, y2 in lines])
    h /= np.linalg.norm(h[:, :2], axis=1, keepdims=True)
    _, _, vt = np.linalg.svd(h)
    return vt[-1]


def angle_errors(lines: np.ndarray, point: np.ndarray) -> np.ndarray:
    """Angle (degrees) between each line and the direction from its midpoint to the common point."""
    errs = []
    for x1, y1, x2, y2 in lines:
        d = np.array([x2 - x1, y2 - y1])
        mid = np.array([(x1 + x2) / 2, (y1 + y2) / 2])
        if abs(point[2]) < 1e-9:                     # point at infinity: compare directions
            to = point[:2]
        else:
            to = point[:2] / point[2] - mid
        cos = abs(float(np.dot(d, to))) / max(np.linalg.norm(d) * np.linalg.norm(to), 1e-12)
        errs.append(float(np.degrees(np.arccos(min(1.0, cos)))))
    return np.array(errs)


class Geometry(ModuleBase):
    id = "image.geometry"
    version = "1.0.0"
    name = "Perspective / shadow consistency (examiner-drawn)"
    description = ("Least-squares vanishing point (perspective) or light-source projection (shadow) of examiner-drawn "
                   "lines, with each line's angular error.")
    family = Family.CLASSICAL
    tier = 2
    default_params = {"mode": "perspective", "lines": [], "tolerance_deg": 2.0}  # noqa: RUF012
    headline = ("inconsistent_lines", None)
    plain = 'Checks whether perspective lines or shadows drawn by the examiner agree.'
    limitations = (
        "Depends entirely on the examiner choosing lines that really are parallel (perspective) or really are "
        "shadow–object pairs (shadow); lens distortion, curved or non-parallel scene edges, several light sources "
        "and soft shadows produce errors. Imprecise clicks matter more for short lines. Use at least 4 lines spread "
        "across the scene; results are reproducible only with the same lines (recorded in the parameters)."
    )

    def availability(self) -> Availability:
        return Availability(True)

    def screen(self, scores: dict[str, float | None], details: dict[str, Any]) -> str | None:
        bad, n = scores.get("inconsistent_lines") or 0, scores.get("lines") or 0
        if n >= 4 and bad >= 1:
            return f"{bad:.0f} of {n:.0f} examiner-drawn {details.get('mode', '')} lines do not meet the common point"
        return None

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        import cv2

        p = self.merged_params(params)
        mode = str(p["mode"])
        if mode not in ("perspective", "shadow"):
            raise ValueError("mode must be 'perspective' or 'shadow'")
        lines = np.array(p["lines"], dtype=np.float64).reshape(-1, 4)
        if len(lines) < 3:
            raise ValueError("draw at least 3 lines (4 or more recommended)")
        point = common_point(lines)
        errs = angle_errors(lines, point)
        tol = float(p["tolerance_deg"])
        rgb, info = load_rgb(item.path)
        out = rgb.copy()
        for (x1, y1, x2, y2), e in zip(lines, errs, strict=True):
            colour = (0, 200, 0) if e <= tol else (230, 0, 0)
            cv2.line(out, (int(x1), int(y1)), (int(x2), int(y2)), colour, 3, cv2.LINE_AA)
            cv2.putText(out, f"{e:.1f}", (int(x2) + 4, int(y2)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2, cv2.LINE_AA)
        vp = None
        if abs(point[2]) > 1e-9:
            vp = point[:2] / point[2]
            h, w = out.shape[:2]
            if 0 <= vp[0] < w and 0 <= vp[1] < h:
                cv2.drawMarker(out, (int(vp[0]), int(vp[1])), (255, 200, 0), cv2.MARKER_CROSS, 30, 3)
        save_png(out, item.workdir / "geometry.png")
        bad = int((errs > tol).sum())
        label = "vanishing point" if mode == "perspective" else "light-source projection"
        return Finding(
            scores=[
                Score("lines", float(len(lines)), None, "Lines drawn by the examiner."),
                Score("max_angle_error_deg", r6(errs.max()), (0, 90), f"Largest disagreement with the common {label}.", "°"),
                Score("mean_angle_error_deg", r6(errs.mean()), (0, 90), "Mean disagreement.", "°"),
                Score("inconsistent_lines", float(bad), None, f"Lines off by more than {tol}° (drawn in red)."),
            ],
            summary=(f"{mode.title()} check on {len(lines)} lines: {bad} inconsistent (> {tol}°); largest error {errs.max():.1f}°."),
            limitations=self.limitations,
            artefacts=[Artefact("geometry.png", item.workdir / "geometry.png", ArtefactKind.HEATMAP,
                                f"Examiner lines (green = consistent, red = inconsistent) and the {label}")],
            details={"mode": mode, "line_errors_deg": [r6(e) for e in errs],
                     "common_point": [r6(v) for v in vp] if vp is not None else "at infinity", "decode": info},
        )


MODULE = Geometry()
