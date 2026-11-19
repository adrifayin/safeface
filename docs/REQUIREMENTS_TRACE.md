# Requirements traceability (SRS v0.1 / TDD v0.1 → Phase 1 implementation)

Status: **Done** = implemented and tested · **Partial** = implemented with a stated gap ·
**Later** = scheduled for a later phase (not started, per the build plan) · **Doc** = procedure documented, not code.

## Functional requirements

| ID | Requirement (short) | Pri | Status | Where | Tests |
|---|---|---|---|---|---|
| FR-1.1 | Case: case no., FIR, crime head, IO, assigned examiner | M | Done | `api/cases.py`, `db/models.py:Case` | `test_policy_matrix`, `test_full_flow` |
| FR-1.2 | Upload images/video/audio ≤ 4 GB | M | Done (ingest of all listed types; analysis Phase 1 = images) | `services/ingest.py`, `core/filetype.py` | `test_evidence_flow` (415, 413) |
| FR-1.3 | SHA-256 + MD5, read-only original, working copy | M | Done | `services/ingest.py`, `core/storage.py` (object lock) | `test_hashing`, `test_evidence_flow` |
| FR-1.4 | Provenance: URL, platform, device, complainant, collected-by/at, upload method | M | Done | `EvidenceMetadata`, `EvidenceItem` | `test_upload_returns_independent_hashes` |
| FR-1.5 | Chain-of-custody log per item | M | Done | `GET /evidence/{id}/custody` | `test_custody_log_records_actions` |
| FR-1.6 | Re-verify on demand and before every report | M | Done | `services/verification.py`, `api/reports.py` | `test_modified_original_is_detected` |
| FR-1.7 | Attach reference media | M | Done | `reference_for` on upload; `POST /evidence/{id}/references` | `test_full_flow` |
| FR-1.8 | Bulk upload with batch triage | S | Done: many files / a folder's contents at once, per-file progress + hash check, each triaged automatically. Archives (ZIP) are deliberately not unpacked server-side (attack surface) | `CasePage.tsx` UploadPanel | Playwright bulk step |
| FR-2.1 | Metadata: EXIF/XMP/IPTC, software tags, thumbnail, quant tables | M | Done | `modules/image_metadata` | goldens + `test_metadata_*` |
| FR-2.2 | C2PA verification; invisible watermark "where decoders exist" | M | Partial: C2PA done; no offline watermark decoder exists, stated in limitations | `modules/image_c2pa` | `test_c2pa_reports_absence` |
| FR-2.3 | TruFor localization + reliability map | M | Done — runs with the official weights (edited fixture: integrity 0.96, pixel F1 0.94 vs ground truth; original: 0.32) | `modules/image_trufor` | shim tests; real-weights run |
| FR-2.4 | ≥ 2 AI detectors, reported separately | M | Done (UnivFD + NPR; never averaged; "triage indicator") | `modules/image_aigen_*` | determinism, weights tests; NPR verified against real checkpoint |
| FR-2.5 | Source matching: face identity + keypoint alignment + aligned difference | M | Done (ArcFace when weights installed) | `modules/image_source_match` | `test_source_match_localises_the_edit` |
| FR-2.6 | ELA, JPEG ghosts, local noise | M | Done | `modules/image_ela`, `image_noise`, `image_jpeg_ghost` | goldens |
| FR-2.7 | Residual FFT spectrum | S | Done | `image_fft` | golden |
| FR-2.8 | PRNU fingerprint, global PCE + regional map | S | Done | `image_prnu` | synthetic-fingerprint test |
| FR-2.9 | Face-swap detection | S | Done (SBI on images and video) | `video_face_frame_scores` | real checkpoint loads strictly |
| FR-2.10 | Shadow / perspective tools | C | Done (examiner draws lines; vanishing-point / light-source fit) | `image_geometry`, `GeometryTool.tsx` | geometry test |
| FR-3.1 | Container/stream analysis | M | Done (ffprobe + MediaInfo) | `video_container` | media tests |
| FR-3.2 | Keyframes + sampled frames into image detectors | M | Done | `video_aigen`, `_common/media.py` | media tests, real weights |
| FR-3.3 | Face tracks + per-frame face scores on a timeline | M | Done | `video_face_track`, `video_face_frame_scores`, timeline click-to-seek | |
| FR-3.4 | Temporal detection on face tracks | S | Partial: identity drift + SBI flicker; FTCN not integrated (no licence, PyTorch 1.4) | `video_temporal` | |
| FR-3.5 | AV sync | S | Partial: speech-energy vs lip-opening synchrony; no offline lip-reading (VSR) model, so no word-level VSR diff | `video_av_sync` | |
| FR-3.6 | Phoneme–viseme M/B/P | S | Done (Whisper word timings; English + Malayalam bilabials) | `video_phoneme_viseme` | |
| FR-3.7 | rPPG, labelled experimental | C | Done (POS, 3x3 regions) | `video_rppg` | |
| FR-4.1 | Synthetic speech, segment scores | S | Done (AASIST, speech-gated by Silero VAD) | `audio_spoof` | media tests, real weights |
| FR-4.2 | Spectrogram + audio metadata | S | Done | `audio_spectrogram` | golden |
| FR-5.1 | Finding = method, version, params, scores, visual, limitations | M | Done | `modules/base.py`, `workers/tasks.py` | `test_full_flow` |
| FR-5.2 | Dashboard grouped by family | M | Done | `GET /evidence/{id}/findings`, Workbench | `test_full_flow`, Playwright |
| FR-5.3 | Never a single real/fake verdict | M | Done | no combining code exists; notice on every screen/report | `test_full_flow` (forbidden words) |
| FR-5.4 | Notes per finding; conclusion on fixed scale | M | Done | `api/examiner.py` | `test_full_flow` |
| FR-5.5 | Supervisor approval workflow | M | Done (+ separation of duties in API and DB) | `POST /conclusions/{id}/approve` | `test_full_flow`, `test_newer_conclusion_supersedes` |
| FR-5.6 | SWGDE-structured PDF with hashes, environment, versions, limitations, signatures | M | Done | `reports/builder.py`, `templates/report.html.j2` | `test_full_flow` (PDF hash) |
| FR-5.7 | BSA s.63(4) Part A pre-fill | M | Done (fields SafeFace cannot know returned as null) | `GET /cases/{id}/s63-data` | `test_full_flow` |
| FR-5.8 | Re-run past analysis, confirm identical output | S | Done | `POST /findings/{id}/rerun`, `/reproducibility` | `test_rerun_reproduces_scores` |
| FR-6.1 | Users/roles with 2FA | M | Done (Keycloak; read-only mirror in UI) | realm generator, `api/admin.py` | Playwright (TOTP login) |
| FR-6.2 | Tamper-evident audit log | M | Done | `core/audit.py` | `test_audit_chain`, `test_audit_export` |
| FR-6.3 | Model registry: install, version, checksum, enable/disable offline | M | Done (two-person enable/disable) | `modules/weights.py`, `api/admin.py` | `test_weights_and_ml` |
| FR-6.4 | Benchmark runner | S | Done: Administration → Validation (and CLI); results stored in the DB and shown beside scores and in reports. Numbers need the user-supplied test sets in `datasets/` | `services/benchmark.py`, `api/benchmarks.py`, `Validation.tsx` | metric + API tests |
| FR-6.5 | Retention rules with approved deletion | S | Done: close case, disposal request, second supervisor approves; derived files deleted, records kept, originals stay sealed until their lock date | `api/disposals.py`, migration 0003, `Disposal.tsx` | `test_disposal.py` |

## Non-functional requirements

| ID | Status | Notes |
|---|---|---|
| NFR-S1 air-gapped | Done | internal networks; no-egress test; CSP; no CDN; see SECURITY.md §1 |
| NFR-S2 AES-256 at rest, TLS 1.3 | Partial | MinIO SSE on all buckets; TLS 1.3 at the edge; Postgres encrypted volume is a deployment step (documented); per-hop TLS planned |
| NFR-S3 RBAC + case permissions, admins no media | Done | `core/policy.py`; matrix tests |
| NFR-S4 2FA, 15-min idle, lockout | Done | realm config + SPA idle timer |
| NFR-S5 hash-chained, exportable | Done | JSONL export + standalone verifier |
| NFR-S6 weights checksum, refuse modified | Done | `weights.py`; tests incl. post-load tamper |
| NFR-S7 sandboxed workers, no network | Done | hardened containers; magic bytes; timeouts |
| NFR-S8 encrypted backups + restore | Doc | DEPLOYMENT.md |
| NFR-R1 provenance per finding | Done | module/version/weights/params/digest/hardware/runtime |
| NFR-R2 deterministic, tolerance | Done | 1e-6 on CPU, tested; GPU strict mode with recorded fallback |
| NFR-R3 originals never modified | Done | object lock + DB triggers + working copies |
| NFR-R4 validation results per module | Partial | registry field + UI/report display; values pending Phase 4 |
| NFR-P1 Tier 1 < 60 s / image | Expected | classical modules take < 2 s on the fixtures; ML timing depends on GPU — measure on reference server |
| NFR-P3 async queue, progress | Done | Celery cpu/gpu queues; UI polls job status |
| NFR-U1 blur by default | Done | `Reveal` component; greyscale toggle |
| NFR-U2 explanation + limitations beside every score | Done | meaning/range per score; limitations per module |
| NFR-U4 Malayalam labels | Done (first draft) | EN / Malayalam toggle on investigator screens (`lib/i18n.tsx`); needs native-speaker review; the legal caveat is always also shown in English |
| NFR-L1 s.63(4) compatible | Done (data) | |
| NFR-L3 CSAM never used for testing | Done | fixtures are synthetic, generated by `scripts/make_fixtures.py` |
| NFR-L4 SWGDE structure incl. limitations | Done | report template |

## SRS acceptance criteria (§5.3)

| Criterion | Status |
|---|---|
| Upload hash matches `sha256sum` | Done — `test_hash_matches_sha256sum_and_md5sum`, Playwright compares browser hash |
| Modified original detected on re-verification | Done — `test_modified_original_is_detected` |
| TruFor heatmap overlaps edited region on inpainted test set | Partly shown: F1 0.94 on the synthetic fixture with official weights; run `scripts/benchmark.py` on the team test set |
| Source matching difference map highlights edited region | Done — `test_source_match_localises_the_edit` (> 3× contrast inside mask) |
| AI detectors report AUC on Deepfake-Eval-2024 + own set | Pending — Phase 4 benchmark runner |
| No real/fake verdict anywhere | Done |
| Re-run reproduces within tolerance | Done |
| Audit tampering detected | Done (API and standalone verifier) |
| Runs with networking disabled | Done — internal networks + no-egress test |
| Full report with hashes, versions, findings, limitations, signatures | Done |

## Where the documents disagree, and what was done

1. **JPEG ghosts** — SRS FR-2.6 (M) vs build plan/TDD roadmap (Phase 3): followed the build plan.
2. **MinIO KES** — TDD lists a `kes` service; build plan does not: static MinIO KMS key in dev, KES documented for production.
3. **SIFT vs LoFTR** — SIFT implemented (build plan).
4. **image.noise tier** — TDD/prompt Tier 1 (as built); SRS workflow §5.1 mentions noise maps as Tier 2: kept Tier 1 (cheap, automatic).

## Preliminary screening (agreed with the user for Phase 2)

`GET /evidence/{id}/screening` returns "Doubt raised — refer to an examiner", "No doubt raised by the automated checks
that ran" or "Screening incomplete". Each doubt names its check and threshold, and the accuracy caveat always travels
with it. It is not a real/fake verdict (those words are never used; tested), appears in the PDF only as Appendix A, and
the examiner's approved conclusion remains the only opinion in the report.
