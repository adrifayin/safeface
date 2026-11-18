# SafeFace Forensic Workbench — Phase 1 (Image MVP)

On-premise, air-gapped web application that helps trained police examiners
decide whether an image was created or manipulated with AI, and produces a
court-ready, SWGDE-structured report. **It never issues a real/fake verdict:**
each analysis module is an independent indicator with stated limitations;
the examiner concludes and a supervisor approves.

Source requirements: `../SafeFace Forensic Workbench Software Requirements Specification.pdf`,
`../SafeFace Forensic Workbench Technical Design Document.pdf`. Traceability: `docs/REQUIREMENTS_TRACE.md`.

## Quick start (development / demo)

Prerequisites: Docker with Compose v2 (NVIDIA Container Toolkit optional), Python 3.11+ on the host for the two setup scripts.

```sh
python scripts/init_secrets.py --host localhost --port 8443 --demo   # infra/.env, Keycloak realm, demo users
docker build --target api -t safeface/api:dev backend
docker run --rm -v "$PWD/infra/certs:/certs" -w /certs --user root safeface/api:dev python gen_dev_certs.py --host localhost
cd infra && docker compose --env-file .env up -d --build        # add -f docker-compose.gpu.yml for the GPU worker
docker compose --env-file .env run --rm -v "$PWD/../scripts:/scripts:ro" \
    -v "$PWD/../backend/tests/fixtures:/fixtures:ro" api python /scripts/seed_demo.py
```

Open https://localhost:8443 (trust `infra/certs/out/ca.crt`, or accept the warning in dev).
Demo users, passwords and TOTP secrets are in `infra/demo-credentials.txt`
(add the `totp_base32` value to any authenticator app).

Model weights are not included (licences, size). Until an admin installs them
(`scripts/fetch_models.md`), TruFor, UnivFD, NPR and face identity show as
**unavailable** with the reason; all other modules work.

## Tests

```sh
docker compose -f infra/docker-compose.test.yml run --rm tests           # backend: pytest against real Postgres, no network
cd frontend && npm ci --ignore-scripts && npx playwright install chromium && npx playwright test   # needs the stack running
```

## Layout

```
backend/app/api       FastAPI routers (/api/v1)          backend/app/modules   one package per analysis module
backend/app/core      config, JWT, policy, audit chain,   backend/app/reports   Jinja2 template + WeasyPrint builder
                      hashing, storage, file types        backend/app/workers   Celery app + job execution
backend/app/db        models + Alembic migrations         backend/tests         pytest suite, fixtures, goldens
frontend/             React + TS + Vite SPA, Playwright   infra/                compose, nginx, MinIO build, certs, Postgres roles
models/registry.yaml  weights registry (SHA-256)          scripts/              secrets, seed, fixtures, audit verifier, bundle, Trivy
docs/                 security, deployment, licences, testing, traceability
```

## Adding an analysis module

Create `backend/app/modules/<name>/__init__.py` exposing `MODULE`, an object
satisfying `AnalysisModule` (`app/modules/base.py`): id, version, family,
media types, tier, GPU/reference needs, fixed limitations text, required
weights, default parameters, `availability()` and `run(item, refs, params) -> Finding`.
No core code changes are needed: the registry discovers it, the API lists it,
the workbench shows it in its family, and reports include it.
