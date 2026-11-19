"""Request and response bodies (Pydantic v2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.db.models import CasePermission, ConclusionScale, EvidenceKind


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- users ---------------------------------------------------------------------


class UserOut(Out):
    id: uuid.UUID
    username: str
    display_name: str
    roles: list[str]
    unit: str | None = None
    active: bool
    last_seen_at: datetime


# --- cases ---------------------------------------------------------------------


class CaseCreate(BaseModel):
    case_no: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9/_.\-]+$")
    fir_no: str | None = Field(default=None, max_length=64)
    crime_head: str = Field(min_length=1, max_length=255)
    investigating_officer: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    assigned_examiner_id: uuid.UUID | None = None


class MemberAdd(BaseModel):
    user_id: uuid.UUID
    permission: CasePermission


class MemberOut(Out):
    user_id: uuid.UUID
    permission: str
    added_at: datetime
    username: str = ""
    display_name: str = ""


class EvidenceOut(Out):
    id: uuid.UUID
    case_id: uuid.UUID
    kind: str
    media_type: str
    detected_mime: str
    original_filename: str
    size_bytes: int
    sha256: str
    md5: str
    source_url: str | None
    source_platform: str | None
    source_device: str | None
    complainant: str | None
    collected_by: str | None
    collected_at: datetime | None
    upload_method: str
    ingested_at: datetime
    reference_ids: list[uuid.UUID] = []
    questioned_ids: list[uuid.UUID] = []
    last_verification: dict[str, Any] | None = None


class CaseOut(Out):
    id: uuid.UUID
    case_no: str
    fir_no: str | None
    crime_head: str
    investigating_officer: str
    description: str | None
    status: str
    created_at: datetime
    created_by_id: uuid.UUID
    assigned_examiner_id: uuid.UUID | None
    my_permission: str | None = None


class CaseDetail(CaseOut):
    evidence: list[EvidenceOut] = []
    members: list[MemberOut] = []


# --- evidence ------------------------------------------------------------------


class EvidenceMetadata(BaseModel):
    """Sent base64url-encoded in the ``X-SafeFace-Metadata`` upload header."""

    filename: str = Field(min_length=1, max_length=512)
    kind: EvidenceKind = EvidenceKind.QUESTIONED
    source_url: HttpUrl | None = None
    source_platform: str | None = Field(default=None, max_length=255)
    source_device: str | None = Field(default=None, max_length=512)
    complainant: str | None = Field(default=None, max_length=255)
    collected_by: str | None = Field(default=None, max_length=255)
    collected_at: datetime | None = None
    upload_method: str = Field(default="web-upload", max_length=64)
    # For reference items: questioned item(s) this reference belongs to.
    reference_for: list[uuid.UUID] = []


class UploadResult(BaseModel):
    evidence: EvidenceOut
    sha256: str
    md5: str
    size_bytes: int
    triage_job_ids: list[uuid.UUID]


class ReferenceLink(BaseModel):
    reference_ids: list[uuid.UUID] = Field(min_length=1)


class VerificationOut(Out):
    id: uuid.UUID
    evidence_id: uuid.UUID
    target: str
    computed_sha256: str | None
    computed_md5: str | None
    ok: bool
    reason: str
    actor: str
    verified_at: datetime


class CustodyEntry(BaseModel):
    seq: int
    ts: datetime
    actor: str
    action: str
    details: dict[str, Any]
    entry_hash: str


# --- analyses ------------------------------------------------------------------


class AnalysisRequest(BaseModel):
    module_ids: list[str] = Field(min_length=1)
    params: dict[str, dict[str, Any]] = {}
    reference_ids: list[uuid.UUID] = []


class JobOut(Out):
    id: uuid.UUID
    evidence_id: uuid.UUID
    module_id: str
    module_version: str
    params: dict[str, Any]
    reference_ids: list[Any]
    queue: str
    status: str
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    rerun_of_finding_id: uuid.UUID | None = None


class FindingOut(Out):
    id: uuid.UUID
    job_id: uuid.UUID
    evidence_id: uuid.UUID
    module_id: str
    module_version: str
    family: str
    tier: int
    scores: list[dict[str, Any]]
    summary: str
    details: dict[str, Any]
    artefacts: list[dict[str, Any]]
    limitations: str
    provenance: dict[str, Any]
    created_at: datetime
    module_name: str = ""
    triage_indicator: bool = False


class FamilyGroup(BaseModel):
    family: str
    label: str
    findings: list[FindingOut]


class FindingsResponse(BaseModel):
    evidence_id: uuid.UUID
    groups: list[FamilyGroup]
    jobs: list[JobOut]
    notice: str


# --- examiner work -------------------------------------------------------------


class NoteCreate(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    finding_id: uuid.UUID | None = None


class NoteOut(Out):
    id: uuid.UUID
    evidence_id: uuid.UUID
    finding_id: uuid.UUID | None
    author_id: uuid.UUID
    author_name: str = ""
    text: str
    created_at: datetime


class ConclusionCreate(BaseModel):
    scale_value: ConclusionScale
    rationale: str = Field(min_length=20, max_length=20000)


class ConclusionApprove(BaseModel):
    comment: str | None = Field(default=None, max_length=5000)


class ConclusionOut(Out):
    id: uuid.UUID
    evidence_id: uuid.UUID
    scale_value: str
    scale_label: str = ""
    rationale: str
    author_id: uuid.UUID
    author_name: str = ""
    created_at: datetime
    approved_by_id: uuid.UUID | None
    approved_by_name: str | None = None
    approved_at: datetime | None
    approval_comment: str | None
    case_id: uuid.UUID | None = None
    case_no: str | None = None
    evidence_filename: str | None = None


# --- reports -------------------------------------------------------------------


class ReportOut(Out):
    id: uuid.UUID
    case_id: uuid.UUID
    evidence_id: uuid.UUID | None = None  # None = whole-case report
    version: int
    status: str
    pdf_sha256: str
    evidence_hashes: list[Any]
    generated_by_id: uuid.UUID
    signed_by: list[Any]
    generated_at: datetime


class PerItemReportsOut(BaseModel):
    generated: list[ReportOut]
    refused: list[dict[str, Any]]


# --- modules and registry ------------------------------------------------------


class ModuleOut(BaseModel):
    id: str
    version: str
    name: str
    description: str
    family: str
    family_label: str
    media_types: list[str]
    tier: int
    requires_gpu: bool
    requires_reference: bool
    limitations: str
    triage_indicator: bool
    available: bool
    unavailable_reason: str
    default_params: dict[str, Any]
    validation: list[dict[str, Any]]


class RegistryOut(Out):
    name: str
    module_id: str
    version: str
    weights_path: str
    weights_sha256: str | None
    licence: str
    source: str | None
    validation_summary: dict[str, Any]
    enabled: bool
    installed: bool = False
    status: str = ""


class RegistryChangeCreate(BaseModel):
    enabled: bool
    reason: str = Field(min_length=10, max_length=2000)


class RegistryChangeOut(Out):
    id: uuid.UUID
    name: str
    enabled_requested: bool
    reason: str
    requested_by_id: uuid.UUID
    requested_at: datetime
    status: str
    decided_by_id: uuid.UUID | None
    decided_at: datetime | None


# --- audit ---------------------------------------------------------------------


class AuditEntryOut(Out):
    seq: int
    ts: datetime
    actor: str
    action: str
    target_type: str
    target_id: str
    details: dict[str, Any]
    prev_hash: str
    entry_hash: str


class AuditVerifyOut(BaseModel):
    ok: bool
    entries_checked: int
    head_seq: int
    head_hash: str
    first_bad_seq: int | None
    problem: str | None
    verified_at: datetime
