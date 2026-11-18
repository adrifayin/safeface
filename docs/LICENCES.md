# Licences of third-party models and tools

> **Production warning.** TruFor and several research checkpoints are
> licensed for **non-commercial / non-profit research only**. They are
> acceptable for the academic prototype; operational police use requires
> licence clearance from the rights holders or retraining on cleared data
> (SRS §2.4, TDD §3.5).

| Component | Used by | Licence | Shipped in repo? | Notes |
|---|---|---|---|---|
| TruFor code (GRIP-UNINA) | `image.trufor` | GRIP-UNINA licence: "informational and nonprofit purposes" only; keep notices; cite authors | **No** — admin installs pinned `git archive` | Commit `ae54475`. Results made public must cite Guillaro et al., CVPR 2023. |
| TruFor weights | `image.trufor` | Same GRIP-UNINA licence | No | Downloaded from grip.unina.it. |
| CLIP ViT-L/14 weights (OpenAI) | `image.aigen.univfd` | MIT | No (900 MB) | Architecture re-implemented in `app/modules/_vendor/clip_visual.py` with the MIT notice. |
| UnivFD linear probe | `image.aigen.univfd` | MIT (WisconsinAIVision) | No | Commit `030495a`. |
| NPR weights + reference code | `image.aigen.npr` | **No licence file** in the upstream repository (commit `781ced3`) — treat as *all rights reserved* | No | Our network is an independent re-implementation from the paper. Obtain the authors' permission before operational use. |
| InsightFace `buffalo_l` (det_10g, w600k_r50) | `image.source_match` | InsightFace pretrained models: non-commercial research only | No | Code (`insightface` package) is MIT; the models are not. |
| SBI weights (FF++ c23) | `video.face_frame_scores`, `video.temporal` | SBI licence: **academic / non-profit non-commercial research only** | No | Official checkpoint from the authors' Google Drive. |
| EfficientNet-PyTorch (architecture) | SBI | Apache-2.0 | Yes, `_vendor/efficientnet/` (download code removed) | Commit 7e8b0d3. |
| AASIST code + weights | `audio.spoof` | MIT (NAVER Corp.) | Code vendored (`_vendor/aasist.py`); weights not shipped | Commit a04c986. |
| Whisper small (CTranslate2) | `video.phoneme_viseme` | MIT (OpenAI weights; Systran conversion) | No | Loaded from a local directory only. |
| faster-whisper (+ bundled Silero VAD) | speech modules | MIT | pip, pinned | VAD model ships inside the package. |
| InsightFace 2d106det | `video.av_sync`, `video.phoneme_viseme` | InsightFace models: non-commercial research only | No | From `buffalo_l`. |
| FTCN | — | No licence file upstream | **Not integrated** | `video.temporal` uses an identity-drift method instead. |
| FFmpeg / MediaInfo | video/audio modules | LGPL/GPL (Debian builds) / BSD-2 | Debian packages in worker image | |
| ExifTool | `image.metadata` | Perl Artistic / GPL | Debian package in worker image | |
| c2patool | `image.c2pa` | MIT / Apache-2.0 | Release binary, SHA-256 pinned in Dockerfile | v0.27.22 |
| MinIO | storage | AGPL-3.0 | Built from source tag in `infra/minio/` | Unmodified; network use by police staff only. Review AGPL obligations for any modification. |
| Keycloak | identity | Apache-2.0 | Official image | |
| PostgreSQL 16 | data | PostgreSQL licence | Official image | |
| Redis 7.4 | job queue | RSALv2 / SSPLv1 (dual) since 7.4 | Official image | Internal, unmodified use is permitted by both licences; have legal confirm, or pin Redis 7.2.x (BSD-3). |
| OpenSeadragon, Plotly.js, React, Radix, Tailwind, shadcn/ui pattern | frontend | BSD-3 / MIT | npm, locked | |

When a model's licence changes, or a cleared/retrained checkpoint replaces a
research one, update `models/registry.yaml` (`licence:`) — the value is shown
on the Model registry page and recorded in every finding's provenance.
