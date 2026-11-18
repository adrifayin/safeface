"""FR-6.5 disposal requests (two-person approved deletion of a closed case's derived data).

Revision ID: 0003_disposal
Revises: 0002_security
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings

revision = "0003_disposal"
down_revision = "0002_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "disposal_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("authority", sa.String(length=512), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_disposal_requests_case_id"), "disposal_requests", ["case_id"], unique=False)
    role = get_settings().app_db_role
    op.execute("REVOKE ALL ON disposal_requests FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT, UPDATE (status, decided_by_id, decided_at, result) ON disposal_requests TO {role}")
    op.execute("""
        CREATE TRIGGER disposal_requests_no_delete BEFORE DELETE ON disposal_requests
        FOR EACH ROW EXECUTE FUNCTION safeface_refuse_change();
    """)


def downgrade() -> None:
    raise RuntimeError("disposal records are part of the evidence trail and are not removed")
