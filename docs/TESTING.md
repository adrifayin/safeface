# Testing

## Backend (pytest)

`docker compose -f infra/docker-compose.test.yml run --rm tests`

Runs inside the worker image (same libraries as production) against a real
PostgreSQL 16 on an `internal: true` network, so grants, triggers and the
no-egress check are real. Object storage is in-memory (it allows tampering,
which the tamper tests need); Celery runs eagerly; a local RSA key stands in
for Keycloak.

| Area | Tests |
|---|---|
| Hashing = `sha256sum`/`md5sum`, chunking invariance, known vectors | `test_hashing.py` |
| Modified original / working copy detected; report refused | `test_evidence_flow.py` |
| Role × case-permission matrix (policy table + HTTP), token validation | `test_policy_matrix.py` |
| DB role cannot UPDATE/DELETE evidence hashes or audit; triggers block owner | `test_db_privileges.py` |
| Audit chain tamper detection (in-memory + real DB), standalone verifier | `test_audit_chain.py`, `test_audit_export.py` |
| Module goldens on fixtures (tolerance 1e-6), heatmap geometry, localisation | `test_modules_classical.py` + `tests/golden/` |
| Deterministic re-runs within 1e-6 on CPU | `test_deterministic_reruns`, ML tests |
| Weights: missing / unverified / modified / traversal / disabled / pickle | `test_weights_and_ml.py` |
| Air-gap: no internet route, no download calls, no CDN docs | `test_air_gap.py` |
| Full flow upload → triage → Tier 2 → conclusion → approval → PDF | `test_full_flow.py` |

Golden files are regenerated only deliberately:
`docker compose -f infra/docker-compose.test.yml run --rm -e SAFEFACE_UPDATE_GOLDENS=1 tests pytest tests/test_modules_classical.py`
then review the diff — a changed golden means analysis output changed, which
requires a module version bump.

Optional: verify the NPR re-implementation against the authors' checkpoint
by mounting it and setting `SAFEFACE_REAL_NPR=/path/NPR.pth`.

## Frontend end-to-end (Playwright)

With the stack running and demo users (`init_secrets.py --demo`):
`cd frontend && npx playwright install chromium && npx playwright test`.
The test signs in through Keycloak with password + TOTP for four roles and
walks the Phase 1 acceptance path, finishing with an independent SHA-256 of
the downloaded PDF.

## Fixtures

`scripts/make_fixtures.py` draws synthetic street scenes (no people, nothing
explicit): an original "camera" JPEG with EXIF, a rescaled reference, and an
edited version (object pasted, building removed by inpainting) with its
ground-truth mask. For realistic AI-inpainting evaluation, the team test set
(TDD §6.1: consenting team members' photos with non-explicit diffusion edits
and messaging-app round-trips) is used in Phase 4 and is not stored in git.
