"""image.metadata: EXIF/XMP/IPTC/PNG metadata, thumbnail and JPEG quantization checks.

Metadata is read with ExifTool. Checks performed (SRS FR-2.1):
- editing-software and AI-generator signatures in software/creator tags,
  IPTC DigitalSourceType and Stable-Diffusion-style PNG "parameters" text;
- camera fields that an unedited camera photo normally has but this file lacks;
- embedded EXIF thumbnail compared with the main image (aspect and content);
- JPEG quantization tables: count, whether they are the standard IJG tables,
  and the nearest IJG quality.
"""

from __future__ import annotations

import io
import json
import shutil
from typing import Any

import numpy as np
from PIL import Image

from app.modules._common.imaging import load_rgb, open_image, r6, run_tool
from app.modules.base import Availability, Family, Finding, ModuleBase, Score, WorkingCopy

EDITORS = [
    "photoshop", "gimp", "lightroom", "snapseed", "picsart", "canva", "affinity", "pixelmator",
    "facetune", "meitu", "faceapp", "remini", "paint.net", "krita", "darktable", "capture one",
    "photopea", "fotor", "luminar", "inshot", "vsco", "polarr", "photodirector", "beautyplus",
]
AI_GENERATORS = [
    "midjourney", "dall-e", "dall·e", "dalle", "stable diffusion", "stablediffusion", "comfyui",
    "automatic1111", "invokeai", "firefly", "imagen", "novelai", "leonardo", "ideogram",
    "flux", "sdxl", "openai", "gemini", "grok", "runway", "playground ai", "nightcafe",
]
SOFTWARE_TAGS = ["Software", "CreatorTool", "ProcessingSoftware", "HistorySoftwareAgent",
                 "Creator", "Generator", "Producer", "ApplicationRecordVersion", "Comment"]
CAMERA_FIELDS = ["Make", "Model", "DateTimeOriginal", "ExposureTime", "FNumber", "ISO", "FocalLength"]

# IJG (libjpeg) standard tables, natural (row-major) order.
IJG_LUMA = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57,
            69, 56, 14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64,
            81, 104, 113, 92, 49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99]
IJG_CHROMA = ([17, 18, 24, 47] + [99] * 4 + [18, 21, 26, 66] + [99] * 4 + [24, 26, 56] + [99] * 5
              + [47, 66] + [99] * 6 + [99] * 32)
ZIGZAG = [0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27,
          20, 13, 6, 7, 14, 21, 28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58,
          59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63]
_EXCLUDED_GROUPS = ("System", "ExifTool", "SourceFile")


def ijg_table(base: list[int], quality: int) -> list[int]:
    scale = 5000 // quality if quality < 50 else 200 - 2 * quality
    return [min(255, max(1, (v * scale + 50) // 100)) for v in base]


def estimate_quality(table: list[int], base: list[int]) -> tuple[int, bool, float]:
    """Nearest IJG quality, whether it is an exact match, and mean abs deviation."""
    best = (0, False, float("inf"))
    zig = [table[ZIGZAG.index(i)] for i in range(64)]  # in case the table is zigzag-ordered
    for q in range(1, 101):
        ref = ijg_table(base, q)
        for t in (table, zig):
            dev = float(np.mean(np.abs(np.array(t) - np.array(ref))))
            if dev < best[2]:
                best = (q, dev == 0.0, dev)
    return best


class Metadata(ModuleBase):
    id = "image.metadata"
    version = "1.0.0"
    name = "Metadata, thumbnail and quantization tables"
    description = (
        "ExifTool extraction of EXIF/XMP/IPTC/PNG metadata; software and AI-generator signatures; "
        "missing camera fields; EXIF thumbnail vs main image; JPEG quantization table analysis."
    )
    family = Family.PROVENANCE
    tier = 1

    def screen(self, scores: dict[str, float | None], details: dict[str, Any]) -> str | None:
        if scores.get("ai_generator_tag") == 1:
            return "Metadata names an AI image generator or declares AI-generated content"
        if scores.get("editing_software_tag") == 1:
            return "Metadata shows the file was written by image-editing software"
        return None
    headline = ("anomaly_count", None)
    plain = 'Looks at hidden file information (camera, software, AI-tool tags).'
    limitations = (
        "Metadata is easily stripped, edited or forged, and almost all social-media and messaging "
        "platforms remove it. Absence of metadata or of camera fields proves nothing; presence of "
        "an editing-software tag shows only that the file passed through that software, not what "
        "was changed. Quantization tables identify the last encoder, not the content's history."
    )

    def availability(self) -> Availability:
        if shutil.which("exiftool") is None:
            return Availability(False, "ExifTool is not installed in the worker image")
        return Availability(True)

    def _exiftool(self, path: Any) -> dict[str, Any]:
        res = run_tool(["exiftool", "-json", "-G1", "-a", "-n", "-api", "largefilesupport=1", str(path)],
                       timeout=60)
        if res.returncode not in (0, 1):
            raise RuntimeError(f"exiftool failed: {res.stderr.decode(errors='replace')[:300]}")
        data: list[dict[str, Any]] = json.loads(res.stdout.decode("utf-8", errors="replace") or "[{}]")
        return data[0] if data else {}

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        self.merged_params(params)
        raw = self._exiftool(item.path)
        table = {k: (str(v)[:500]) for k, v in sorted(raw.items())
                 if not k.startswith(_EXCLUDED_GROUPS)}
        by_name: dict[str, list[str]] = {}
        for k, v in raw.items():
            by_name.setdefault(k.split(":")[-1], []).append(str(v))

        anomalies: list[dict[str, str]] = []
        software_values = [(t, v) for t in SOFTWARE_TAGS for v in by_name.get(t, [])]
        editing = [(t, v) for t, v in software_values if any(e in v.lower() for e in EDITORS)]
        ai = [(t, v) for t, v in software_values if any(g in v.lower() for g in AI_GENERATORS)]
        for t, v in editing:
            anomalies.append({"check": "editing_software", "tag": t, "value": v,
                              "explanation": "The file was written by image-editing software."})
        for t, v in ai:
            anomalies.append({"check": "ai_generator_tag", "tag": t, "value": v,
                              "explanation": "A software tag names an AI image generator."})
        dst = " ".join(by_name.get("DigitalSourceType", []))
        if "trainedalgorithmicmedia" in dst.lower().replace(" ", ""):
            ai.append(("DigitalSourceType", dst))
            anomalies.append({"check": "iptc_digital_source_type", "tag": "DigitalSourceType", "value": dst,
                              "explanation": "IPTC metadata declares the image as generated by a "
                                             "trained algorithm (AI)."})
        params_text = " ".join(by_name.get("Parameters", []))
        if "steps:" in params_text.lower() and "sampler" in params_text.lower():
            ai.append(("Parameters", params_text[:200]))
            anomalies.append({"check": "diffusion_parameters", "tag": "PNG:Parameters",
                              "value": params_text[:200],
                              "explanation": "PNG text chunk matches the format written by Stable "
                                             "Diffusion front-ends (prompt, steps, sampler)."})
        missing = [f for f in CAMERA_FIELDS if f not in by_name]
        if missing:
            anomalies.append({"check": "missing_camera_fields", "tag": ", ".join(missing), "value": "",
                              "explanation": "Fields a camera normally writes are absent (common "
                                             "after editing or platform re-encoding)."})
        dto, mod = by_name.get("DateTimeOriginal", [None])[0], by_name.get("ModifyDate", [None])[0]
        if dto and mod and dto != mod:
            anomalies.append({"check": "modify_after_capture", "tag": "ModifyDate", "value": f"{dto} -> {mod}",
                              "explanation": "The file was modified after the recorded capture time."})

        thumb = self._thumbnail_check(item, anomalies)
        quant = self._quantization(item)
        if quant.get("tables") and not quant.get("standard_ijg", True):
            anomalies.append({"check": "nonstandard_quantization", "tag": "DQT", "value": "",
                              "explanation": "Quantization tables are not the standard IJG tables "
                                             "(typical of camera firmware or some editors/platforms)."})

        scores = [
            Score("anomaly_count", float(len(anomalies)), None,
                  "Number of metadata observations listed below (not a measure of manipulation)."),
            Score("editing_software_tag", 1.0 if editing else 0.0, (0, 1),
                  "1 = a software tag names image-editing software."),
            Score("ai_generator_tag", 1.0 if ai else 0.0, (0, 1),
                  "1 = metadata names an AI generator or declares AI-generated content."),
            Score("missing_camera_fields", float(len(missing)), (0, len(CAMERA_FIELDS)),
                  f"How many of {len(CAMERA_FIELDS)} typical camera fields are absent."),
            Score("thumbnail_mean_abs_diff", thumb, (0, 255),
                  "Mean absolute difference between the EXIF thumbnail and the downscaled image "
                  "(grey levels). Large values mean the thumbnail shows different content; null = "
                  "no thumbnail.", "levels"),
            Score("jpeg_quality_estimate", float(quant["luma_quality"]) if quant.get("luma_quality") else None,
                  (1, 100), "Nearest IJG quality of the luminance quantization table (null = not JPEG)."),
        ]
        summary = (f"{len(anomalies)} metadata observation(s): "
                   + ("; ".join(a["check"] for a in anomalies) if anomalies else "none")
                   + f". Software tags: {', '.join(v for _, v in software_values) or 'none'}.")
        return Finding(scores=scores, summary=summary, limitations=self.limitations,
                       details={"anomalies": anomalies, "metadata": table, "quantization": quant},
                       provenance={"tools": {"exiftool": self._exiftool_version()}})

    def _exiftool_version(self) -> str:
        res = run_tool(["exiftool", "-ver"], timeout=10)
        return res.stdout.decode().strip()

    def _thumbnail_check(self, item: WorkingCopy, anomalies: list[dict[str, str]]) -> float | None:
        res = run_tool(["exiftool", "-b", "-ThumbnailImage", str(item.path)], timeout=60)
        if not res.stdout:
            return None
        try:
            thumb = Image.open(io.BytesIO(res.stdout)).convert("L")
        except Exception:  # noqa: BLE001 - a corrupt thumbnail is itself an observation
            anomalies.append({"check": "thumbnail_unreadable", "tag": "ThumbnailImage", "value": "",
                              "explanation": "An embedded thumbnail exists but cannot be decoded."})
            return None
        rgb, _ = load_rgb(item.path)
        main = Image.fromarray(rgb).convert("L")
        tw, th = thumb.size
        aspect_diff = abs(tw / th - main.width / main.height) / (main.width / main.height)
        if aspect_diff > 0.03:
            anomalies.append({"check": "thumbnail_aspect_mismatch", "tag": "ThumbnailImage",
                              "value": f"{tw}x{th} vs {main.width}x{main.height}",
                              "explanation": "Thumbnail aspect ratio differs from the image (cropped "
                                             "after the thumbnail was written?)."})
        small = np.asarray(main.resize((tw, th), Image.Resampling.BILINEAR), dtype=np.float64)
        mad = r6(np.mean(np.abs(small - np.asarray(thumb, dtype=np.float64))))
        if mad > 20:
            anomalies.append({"check": "thumbnail_content_mismatch", "tag": "ThumbnailImage",
                              "value": f"mean abs diff {mad:.1f}",
                              "explanation": "Thumbnail content differs from the main image "
                                             "(the image may have been edited without updating it)."})
        return mad

    def _quantization(self, item: WorkingCopy) -> dict[str, Any]:
        img = open_image(item.path)
        tables = getattr(img, "quantization", None)
        if not tables:
            return {"tables": 0}
        out: dict[str, Any] = {"tables": len(tables), "raw": {str(k): list(v) for k, v in tables.items()}}
        luma = list(tables[0])
        q, exact, dev = estimate_quality(luma, IJG_LUMA)
        out.update(luma_quality=q, luma_exact_ijg=exact, luma_mean_deviation=r6(dev))
        standard = exact
        if 1 in tables:
            cq, cexact, cdev = estimate_quality(list(tables[1]), IJG_CHROMA)
            out.update(chroma_quality=cq, chroma_exact_ijg=cexact, chroma_mean_deviation=r6(cdev))
            standard = standard and cexact
        out["standard_ijg"] = standard
        return out


MODULE = Metadata()
