"""Per-evidence reports: a report may cover one questioned item instead of the whole case.

``evidence_id`` NULL = whole-case report (versioned per case, as before);
non-NULL = single-item report (versioned per item).

Revision ID: 0005_item_reports
Revises: 0004_benchmarks
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_item_reports"
down_revision = "0004_benchmarks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("evidence_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("reports_evidence_id_fkey", "reports", "evidence_items", ["evidence_id"], ["id"])
    op.create_index("ix_reports_evidence_id", "reports", ["evidence_id"])
    op.drop_constraint("reports_case_id_version_key", "reports", type_="unique")
    op.create_index("uq_reports_case_version", "reports", ["case_id", "version"], unique=True,
                    postgresql_where=sa.text("evidence_id IS NULL"))
    op.create_index("uq_reports_item_version", "reports", ["evidence_id", "version"], unique=True,
                    postgresql_where=sa.text("evidence_id IS NOT NULL"))


def downgrade() -> None:
    raise RuntimeError("report records are not removed")
