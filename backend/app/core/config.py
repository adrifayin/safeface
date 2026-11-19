"""Application configuration, read from ``SAFEFACE_*`` environment variables.

Nothing here has a network default outside the Docker internal network: the
system is designed to run air-gapped.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

FOUR_GIB = 4 * 1024**3


class Settings(BaseSettings):
    """All runtime settings. Secrets come from the environment (``infra/.env``)."""

    model_config = SettingsConfigDict(env_prefix="SAFEFACE_", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"

    # --- Database -------------------------------------------------------------
    # Runtime role: INSERT/SELECT only on audit_log and evidence tables.
    database_url: str = "postgresql+psycopg://safeface_app:change-me@postgres:5432/safeface"
    # Owner role: used only by the one-shot migration job.
    database_owner_url: str = ""
    app_db_role: str = "safeface_app"

    # --- Job queue ------------------------------------------------------------
    redis_url: str = "redis://redis:6379/0"
    celery_eager: bool = False
    worker_queue: str = ""  # set on worker containers: "cpu" or "gpu"
    job_soft_time_limit_s: int = 840
    job_time_limit_s: int = 900

    # --- Object storage (MinIO) ----------------------------------------------
    storage_backend: Literal["s3", "memory"] = "s3"
    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    bucket_originals: str = "evidence-originals"
    bucket_working: str = "working"
    bucket_artefacts: str = "artefacts"
    bucket_reports: str = "reports"
    object_lock_mode: Literal["COMPLIANCE", "GOVERNANCE"] = "COMPLIANCE"
    object_lock_days: int = Field(default=1, ge=1)
    upload_part_bytes: int = 16 * 1024 * 1024
    max_upload_bytes: int = FOUR_GIB

    # --- Identity (Keycloak OIDC) --------------------------------------------
    oidc_issuer: str = "https://localhost:8443/auth/realms/safeface"
    oidc_jwks_url: str = "http://keycloak:8080/auth/realms/safeface/protocol/openid-connect/certs"
    oidc_jwks_file: str = ""  # tests: a static JWKS JSON file instead of the URL
    oidc_audience: str = "safeface-api"
    oidc_client_id: str = "safeface-web"
    # Require an OTP authentication method reference in the token (needs the
    # Keycloak AMR mapper; see docs/SECURITY.md).
    require_amr_otp: bool = False

    # --- Analysis -------------------------------------------------------------
    models_dir: str = "/models"
    work_dir: str = "/work"
    datasets_dir: str = "/datasets"  # Phase 4 test sets, mounted read-only
    seed: int = 0
    # Working copies and figures/heatmaps are purged this long after the last analysis of an item
    # (agreed with the user: 7 minutes). The sealed original, hashes, scores and reports are never
    # purged. 0 disables purging.
    work_retention_seconds: int = 420

    # --- Provenance -----------------------------------------------------------
    image_digest: str = "unknown (dev build)"
    deployment_name: str = "SafeFace dev deployment"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (cached)."""
    return Settings()
