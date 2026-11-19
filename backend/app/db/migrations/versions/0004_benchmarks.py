"""Phase 4 benchmark runs started from the Administration screen.

Revision ID: 0004_benchmarks
Revises: 0003_disposal
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings

revision = "0004_benchmarks"
down_revision = "0003_disposal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "benchmark_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.String(length=64), nullable=False),
        sa.Column("dataset", sa.String(length=255), nullable=False),
        sa.Column("robustness", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    role = get_settings().app_db_role
    op.execute("REVOKE ALL ON benchmark_runs FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT, UPDATE (status, finished_at, results, error) ON benchmark_runs TO {role}")
    op.execute("""
        CREATE TRIGGER benchmark_runs_no_delete BEFORE DELETE ON benchmark_runs
        FOR EACH ROW EXECUTE FUNCTION safeface_refuse_change();
    """)


def downgrade() -> None:
    raise RuntimeError("validation records are not removed")
