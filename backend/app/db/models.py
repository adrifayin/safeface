"""Database schema (SQLAlchemy 2 declarative models).

Immutability is enforced in the database itself, not just here: the migration
grants the runtime role INSERT/SELECT only on evidence, findings, notes,
verifications and audit tables, and installs triggers that refuse UPDATE and
DELETE (see ``migrations/versions/0001_initial.py``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.timeutil import utcnow


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}  # noqa: RUF012 - SQLAlchemy API


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# --- Enumerations (stored as plain strings for readability in dumps) ---------


class CasePermission(StrEnum):
    VIEW = "view"
    ANALYSE = "analyse"
    APPROVE = "approve"


class EvidenceKind(StrEnum):
    QUESTIONED = "questioned"
    REFERENCE = "reference"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class ConclusionScale(StrEnum):
    """Fixed conclusion scale (SRS FR-5.4). Order matters for display."""

    STRONG_MANIPULATION = "strong_support_manipulation"
    MODERATE_MANIPULATION = "moderate_support_manipulation"
    INCONCLUSIVE = "inconclusive"
    MODERATE_AUTHENTIC = "moderate_support_authentic"
    STRONG_AUTHENTIC = "strong_support_authentic"


CONCLUSION_LABELS: dict[str, str] = {
    ConclusionScale.STRONG_MANIPULATION: "Strong support for manipulation",
    ConclusionScale.MODERATE_MANIPULATION: "Moderate support for manipulation",
    ConclusionScale.INCONCLUSIVE: "Inconclusive",
    ConclusionScale.MODERATE_AUTHENTIC: "Moderate support for authenticity",
    ConclusionScale.STRONG_AUTHENTIC: "Strong support for authenticity",
}


# --- People and cases --------------------------------------------------------


class User(Base):
    """Local mirror of a Keycloak user, refreshed from the token on each request."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    keycloak_sub: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    roles: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = _ts()
    last_seen_at: Mapped[datetime] = _ts()


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    case_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    fir_no: Mapped[str | None] = mapped_column(String(64))
    crime_head: Mapped[str] = mapped_column(String(255), nullable=False)
    investigating_officer: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_examiner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _ts()

    members: Mapped[list[CaseMember]] = relationship(back_populates="case")
    evidence: Mapped[list[EvidenceItem]] = relationship(
        back_populates="case", order_by="EvidenceItem.ingested_at"
    )


class CaseMember(Base):
    __tablename__ = "case_members"

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    permission: Mapped[str] = mapped_column(String(16), nullable=False)
    added_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    added_at: Mapped[datetime] = _ts()

    case: Mapped[Case] = relationship(back_populates="members")
    user: Mapped[User] = relationship(foreign_keys=[user_id])


# --- Evidence ----------------------------------------------------------------


class EvidenceItem(Base):
    """One ingested file. Rows are immutable once written (DB-enforced)."""

    __tablename__ = "evidence_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    detected_mime: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    md5: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_version_id: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(Text)
    source_platform: Mapped[str | None] = mapped_column(String(255))
    source_device: Mapped[str | None] = mapped_column(String(512))
    complainant: Mapped[str | None] = mapped_column(String(255))
    collected_by: Mapped[str | None] = mapped_column(String(255))
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    upload_method: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    ingested_at: Mapped[datetime] = _ts()

    case: Mapped[Case] = relationship(back_populates="evidence")
    working_copies: Mapped[list[WorkingCopyRow]] = relationship(back_populates="evidence")


class EvidenceReference(Base):
    """Links a reference item to the questioned item it should be compared with."""

    __tablename__ = "evidence_references"

    questioned_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_items.id"), primary_key=True
    )
    reference_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_items.id"), primary_key=True
    )
    linked_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    linked_at: Mapped[datetime] = _ts()


class HashVerification(Base):
    """Result of one re-hash of a stored original (append-only)."""

    __tablename__ = "hash_verifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_items.id"), nullable=False, index=True
    )
    target: Mapped[str] = mapped_column(String(64), nullable=False)  # "original" or "working:<id>"
    computed_sha256: Mapped[str | None] = mapped_column(String(64))
    computed_md5: Mapped[str | None] = mapped_column(String(32))
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    verified_at: Mapped[datetime] = _ts()


class WorkingCopyRow(Base):
    __tablename__ = "working_copies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_items.id"), nullable=False, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    derived_from: Mapped[str | None] = mapped_column(String(255))  # e.g. "frame:120"
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    md5: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = _ts()

    evidence: Mapped[EvidenceItem] = relationship(back_populates="working_copies")


# --- Analysis ----------------------------------------------------------------


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_items.id"), nullable=False, index=True
    )
    module_id: Mapped[str] = mapped_column(String(64), nullable=False)
    module_version: Mapped[str] = mapped_column(String(32), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    reference_ids: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    queue: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=JobStatus.QUEUED)
    requested_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    rerun_of_finding_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("findings.id"))
    queued_at: Mapped[datetime] = _ts()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class FindingRow(Base):
    """The output of one module on one item. Immutable (DB-enforced)."""

    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", use_alter=True), unique=True, nullable=False
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_items.id"), nullable=False, index=True
    )
    module_id: Mapped[str] = mapped_column(String(64), nullable=False)
    module_version: Mapped[str] = mapped_column(String(32), nullable=False)
    family: Mapped[str] = mapped_column(String(32), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    scores: Mapped[list[Any]] = mapped_column(nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    artefacts: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    limitations: Mapped[str] = mapped_column(Text, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = _ts()


# --- Examiner work -----------------------------------------------------------


class ExaminerNote(Base):
    __tablename__ = "examiner_notes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_items.id"), nullable=False, index=True
    )
    finding_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("findings.id"))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _ts()

    author: Mapped[User] = relationship()


class Conclusion(Base):
    """Examiner's conclusion for one item. Approval may be set exactly once."""

    __tablename__ = "conclusions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_items.id"), nullable=False, index=True
    )
    scale_value: Mapped[str] = mapped_column(String(48), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_comment: Mapped[str | None] = mapped_column(Text)

    author: Mapped[User] = relationship(foreign_keys=[author_id])
    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_id])


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("case_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # draft | final
    pdf_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    pdf_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_hashes: Mapped[list[Any]] = mapped_column(nullable=False)
    generated_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    signed_by: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    generated_at: Mapped[datetime] = _ts()


# --- Model registry ----------------------------------------------------------


class ModelRegistryEntry(Base):
    """One weights file known to the deployment, synced from models/registry.yaml."""

    __tablename__ = "model_registry"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    module_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    weights_path: Mapped[str] = mapped_column(String(512), nullable=False)
    weights_sha256: Mapped[str | None] = mapped_column(String(64))
    licence: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    validation_summary: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    synced_at: Mapped[datetime] = _ts()


class ModelRegistryChange(Base):
    """Two-person rule: an admin requests enable/disable, a supervisor approves."""

    __tablename__ = "model_registry_changes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(ForeignKey("model_registry.name"), nullable=False)
    enabled_requested: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    requested_at: Mapped[datetime] = _ts()
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- Audit -------------------------------------------------------------------


class AuditLog(Base):
    """Append-only hash chain. ``seq`` is assigned under an advisory lock."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_target", "target_type", "target_id"),)

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
