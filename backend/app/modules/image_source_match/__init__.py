"""image.source_match: compare the questioned image with reference images (FR-2.5).

1. Keypoint alignment: SIFT keypoints, Lowe ratio test, RANSAC homography that
   maps the reference onto the questioned image.
2. Aligned difference: after a per-channel brightness/contrast match inside the
   overlap, the absolute difference highlights content present in one image
   but not the other.
3. Face identity (optional): ArcFace (InsightFace w600k_r50) cosine similarity
   between the largest face in each image, when the face weights are installed.

The reference that aligns best (most RANSAC inliers) is reported in the scores;
every reference is listed in the details.
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
from app.modules.weights import WeightsError, resolve, weights_availability

FACE_WEIGHTS = ["insightface-det-10g", "insightface-w600k-r50"]
_face_models: dict[str, Any] = {}


def _faces_available() -> Availability:
    return weights_availability(FACE_WEIGHTS)


def _load_face_models() -> tuple[Any, Any, dict[str, str]]:
    """Load detector and recogniser from checksum-verified files only."""
    det_path, det_sha = resolve("insightface-det-10g")
    rec_path, rec_sha = resolve("insightface-w600k-r50")
    key = det_sha + rec_sha
    if key not in _face_models:
        from insightface.model_zoo import model_zoo

        providers = ["CPUExecutionProvider"]
        det = model_zoo.get_model(str(det_path), providers=providers)
        det.prepare(ctx_id=-1, input_size=(640, 640), det_thresh=0.5)
        rec = model_zoo.get_model(str(rec_path), providers=providers)
        rec.prepare(ctx_id=-1)
        _face_models[key] = (det, rec)
    det, rec = _face_models[key]
    return det, rec, {"insightface-det-10g": det_sha, "insightface-w600k-r50": rec_sha}


def _largest_face_embedding(det: Any, rec: Any, rgb: Array) -> Array | None:
    from insightface.utils import face_align

    bgr = np.ascontiguousarray(rgb[:, :, ::-1])
    bboxes, kpss = det.detect(bgr, max_num=0, metric="default")
    if bboxes is None or len(bboxes) == 0:
        return None
    areas = (bboxes[:, 2] - bboxes[:, 0]) * (bboxes[:, 3] - bboxes[:, 1])
    i = int(np.argmax(areas))
    crop = face_align.norm_crop(bgr, landmark=kpss[i], image_size=rec.input_size[0])
    emb = np.asarray(rec.get_feat(crop), dtype=np.float64).flatten()
    return emb / (np.linalg.norm(emb) + 1e-12)


def _gray(rgb: Array) -> Array:
    import cv2

    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


class SourceMatch(ModuleBase):
    id = "image.source_match"
    version = "1.0.0"
    name = "Source matching against reference images"
    description = (
        "SIFT keypoints with Lowe ratio test and RANSAC homography align each reference to the "
        "questioned image; the photometrically matched absolute difference is mapped. Optional "
        "ArcFace (InsightFace) identity similarity of the largest face in each image."
    )
    family = Family.COMPARISON
    tier = 2
    requires_reference = True
    default_params = {  # noqa: RUF012
        "ratio": 0.75, "ransac_threshold_px": 4.0, "max_features": 5000,
        "min_inliers": 15, "change_threshold": 25,
    }
    limitations = (
        "Needs the original or a near-original reference of the same scene. A single homography "
        "models a flat scene or a pure camera rotation; with parallax, lens distortion or "
        "non-rigid changes (pose, expression) the difference map also lights up where nothing "
        "was edited. Strong recompression and resizing add uniform difference. Face identity "
        "similarity indicates whether two faces look like the same person to the ArcFace model; "
        "it is not calibrated on our test set and is not an identification."
    )

    def availability(self) -> Availability:
        import cv2

        if not hasattr(cv2, "SIFT_create"):
            return Availability(False, "OpenCV build lacks SIFT")
        return Availability(True)

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        import cv2

        p = self.merged_params(params)
        if not refs:
            raise ValueError("source matching requires at least one reference image")
        q_rgb, q_info = load_rgb(item.path)
        h, w = q_rgb.shape[:2]
        sift = cv2.SIFT_create(  # type: ignore[attr-defined]
           nfeatures=int(p["max_features"]))
        q_kp, q_desc = sift.detectAndCompute(_gray(q_rgb), None)

        faces = _faces_available()
        face_models = None
        face_weights: dict[str, str] = {}
        q_emb = None
        if faces.available:
            try:
                det, rec, face_weights = _load_face_models()
                face_models = (det, rec)
                q_emb = _largest_face_embedding(det, rec, q_rgb)
            except WeightsError as exc:
                faces = Availability(False, str(exc))

        per_ref: list[dict[str, Any]] = []
        best: dict[str, Any] | None = None
        for ref in refs:
            r_rgb, _ = load_rgb(ref.path)
            result = self._align(cv2, sift, q_rgb, q_kp, q_desc, r_rgb, p)
            if face_models is not None:
                r_emb = _largest_face_embedding(face_models[0], face_models[1], r_rgb)
                result["identity_similarity"] = (
                    r6(float(np.dot(q_emb, r_emb))) if q_emb is not None and r_emb is not None else None)
                result["faces_found"] = {"questioned": q_emb is not None, "reference": r_emb is not None}
            result["reference_evidence_id"] = ref.evidence_id
            per_ref.append({k: v for k, v in result.items() if not k.startswith("_")})
            if best is None or result["inlier_count"] > best["inlier_count"]:
                best = result
        assert best is not None

        out = item.workdir
        artefacts: list[Artefact] = []
        if best.get("_diff") is not None:
            diff = best["_diff"]
            save_png(colormap(np.clip(diff / 64.0, 0, 1), "inferno"), out / "aligned_difference.png")
            artefacts.append(Artefact("aligned_difference.png", out / "aligned_difference.png",
                                      ArtefactKind.HEATMAP,
                                      "Absolute difference to the aligned reference (full scale = 64 "
                                      "grey levels; black outside the overlap)"))
            save_png(self._side_by_side(cv2, q_rgb, best["_warped"], diff), out / "side_by_side.png")
            artefacts.append(Artefact("side_by_side.png", out / "side_by_side.png", ArtefactKind.IMAGE,
                                      "Questioned | aligned reference | questioned with changed areas "
                                      "outlined"))

        aligned = best["aligned"]
        ident = best.get("identity_similarity")
        scores = [
            Score("inlier_count", float(best["inlier_count"]), None,
                  "Keypoint matches consistent with one geometric transform. Higher means the "
                  "reference is more clearly the same scene; below the minimum, no alignment is made."),
            Score("inlier_ratio", best["inlier_ratio"], (0, 1),
                  "Share of ratio-test matches that are RANSAC inliers."),
            Score("mean_aligned_difference", best.get("mean_difference"), (0, 255),
                  "Mean absolute difference inside the overlap after alignment (grey levels). "
                  "Low values mean the images are near-identical apart from local changes.", "levels"),
            Score("changed_area_fraction", best.get("changed_fraction"), (0, 1),
                  f"Fraction of the overlap differing by more than {p['change_threshold']} grey "
                  "levels after smoothing: candidate edited regions."),
            Score("identity_similarity", ident, (-1, 1),
                  "ArcFace cosine similarity of the largest face in each image (higher = more "
                  "similar). Null when weights are not installed or no face was found. Not calibrated."),
        ]
        summary = (
            (f"Best reference aligned with {best['inlier_count']} inliers; "
             f"{(best.get('changed_fraction') or 0) * 100:.2f}% of the overlap differs markedly. "
             "See the difference map for where.") if aligned else
            (f"No reliable alignment (best {best['inlier_count']} inliers, minimum "
             f"{p['min_inliers']}): the reference may not show the same scene.")
        )
        if ident is not None:
            summary += f" Face identity similarity {ident:.3f}."
        elif not faces.available:
            summary += " Face identity not computed: face weights not installed."
        return Finding(
            scores=scores, summary=summary, limitations=self.limitations, artefacts=artefacts,
            details={"references": per_ref, "decode": q_info,
                     "questioned_keypoints": len(q_kp), "face_status": faces.reason or "ok"},
            provenance={"weights": face_weights},
        )

    def _align(self, cv2: Any, sift: Any, q_rgb: Array, q_kp: Any, q_desc: Any,
               r_rgb: Array, p: dict[str, Any]) -> dict[str, Any]:
        h, w = q_rgb.shape[:2]
        r_kp, r_desc = sift.detectAndCompute(_gray(r_rgb), None)
        res: dict[str, Any] = {"reference_keypoints": len(r_kp), "inlier_count": 0,
                               "inlier_ratio": 0.0, "aligned": False}
        if q_desc is None or r_desc is None or len(q_kp) < 4 or len(r_kp) < 4:
            return res
        matcher = cv2.BFMatcher(cv2.NORM_L2)
        good = []
        for pair in matcher.knnMatch(r_desc, q_desc, k=2):
            if len(pair) == 2 and pair[0].distance < float(p["ratio"]) * pair[1].distance:
                good.append(pair[0])
        good.sort(key=lambda m: (m.queryIdx, m.trainIdx))
        res["ratio_matches"] = len(good)
        if len(good) < 4:
            return res
        src = np.array([r_kp[m.queryIdx].pt for m in good], dtype=np.float32).reshape(-1, 1, 2)
        dst = np.array([q_kp[m.trainIdx].pt for m in good], dtype=np.float32).reshape(-1, 1, 2)
        hom, mask = cv2.findHomography(src, dst, cv2.RANSAC, float(p["ransac_threshold_px"]),
                                       maxIters=5000, confidence=0.999)
        if hom is None:
            return res
        inliers = int(mask.sum())
        res.update(inlier_count=inliers, inlier_ratio=r6(inliers / len(good)),
                   homography=[[r6(v) for v in row] for row in hom])
        if inliers < int(p["min_inliers"]):
            return res
        warped = cv2.warpPerspective(r_rgb, hom, (w, h), flags=cv2.INTER_LINEAR)
        valid = cv2.warpPerspective(np.ones(r_rgb.shape[:2], np.uint8), hom, (w, h),
                                    flags=cv2.INTER_NEAREST) > 0
        valid = cv2.erode(valid.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        if valid.sum() < 100:
            return res
        q = q_rgb.astype(np.float64)
        r = warped.astype(np.float64)
        for c in range(3):  # match brightness/contrast inside the overlap
            qv, rv = q[..., c][valid], r[..., c][valid]
            qm, qs = float(np.mean(qv)), float(np.std(qv)) + 1e-6
            rm, rs = float(np.mean(rv)), float(np.std(rv)) + 1e-6
            r[..., c] = (r[..., c] - rm) * (qs / rs) + qm
        diff = np.abs(q - r).mean(axis=2)
        diff = cv2.GaussianBlur(diff, (0, 0), 2.0)
        diff[~valid] = 0.0
        changed = (diff > float(p["change_threshold"])) & valid
        res.update(aligned=True, mean_difference=r6(diff[valid].mean()),
                   changed_fraction=r6(changed.sum() / valid.sum()),
                   overlap_fraction=r6(valid.mean()), _diff=diff, _warped=warped,
                   _changed=changed)
        return res

    @staticmethod
    def _side_by_side(cv2: Any, q: Array, warped: Array, diff: Array) -> Array:
        changed = (diff > 25).astype(np.uint8)
        contours, _ = cv2.findContours(changed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        marked = q.copy()
        cv2.drawContours(marked, contours, -1, (255, 0, 0), 2)
        sep = np.full((q.shape[0], 8, 3), 255, np.uint8)
        return np.concatenate([q, sep, warped, sep, marked], axis=1)


MODULE = SourceMatch()
