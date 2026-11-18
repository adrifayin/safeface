"""Least-privilege grants for the runtime role, and immutability triggers.

Two independent layers protect evidence and the audit trail:

1. Privileges: the runtime role (``safeface_app``) has only SELECT and INSERT
   on evidence, hashes, findings, notes, reports and audit_log. It has no
   UPDATE or DELETE on them at all, and only column-level UPDATE elsewhere.
2. Triggers: UPDATE, DELETE and TRUNCATE on those tables raise an exception
   for every role, including the schema owner, unless a superuser explicitly
   disables the trigger (which the hash-chained audit log would then expose).

Conclusions may be updated exactly once, to record approval, and never by
their own author (separation of duties, enforced here as well as in the API).

Revision ID: 0002_security
Revises: 0001_initial
"""

from __future__ import annotations

import re

from alembic import op

from app.core.config import get_settings

revision = "0002_security"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

GRANTS: dict[str, str] = {
    "users": "SELECT, INSERT, UPDATE (username, display_name, roles, unit, active, last_seen_at)",
    "cases": "SELECT, INSERT, UPDATE (status, assigned_examiner_id, description)",
    "case_members": "SELECT, INSERT, UPDATE (permission)",
    "evidence_items": "SELECT, INSERT",
    "evidence_references": "SELECT, INSERT",
    "hash_verifications": "SELECT, INSERT",
    "working_copies": "SELECT, INSERT",
    "jobs": "SELECT, INSERT, UPDATE (status, started_at, finished_at, error)",
    "findings": "SELECT, INSERT",
    "examiner_notes": "SELECT, INSERT",
    "conclusions": "SELECT, INSERT, UPDATE (approved_by_id, approved_at, approval_comment)",
    "reports": "SELECT, INSERT",
    "model_registry": (
        "SELECT, INSERT, UPDATE (module_id, version, weights_path, weights_sha256, licence, "
        "source, validation_summary, enabled, synced_at)"
    ),
    "model_registry_changes": "SELECT, INSERT, UPDATE (status, decided_by_id, decided_at)",
    "audit_log": "SELECT, INSERT",
}

APPEND_ONLY = [
    "audit_log", "evidence_items", "evidence_references", "hash_verifications",
    "working_copies", "findings", "examiner_notes", "reports",
]


def _role() -> str:
    role = get_settings().app_db_role
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError("invalid app role name")
    return role


def upgrade() -> None:
    role = _role()
    for table, privileges in GRANTS.items():
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
        op.execute(f"GRANT {privileges} ON {table} TO {role}")

    op.execute("""
        CREATE FUNCTION safeface_refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'SafeFace: % on % is not permitted (append-only table)',
                TG_OP, TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
        END $$;
    """)
    for table in APPEND_ONLY:
        op.execute(f"""
            CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION safeface_refuse_change();
        """)
        op.execute(f"""
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION safeface_refuse_change();
        """)

    op.execute("""
        CREATE FUNCTION safeface_conclusion_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'SafeFace: conclusions cannot be deleted'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF OLD.approved_at IS NOT NULL THEN
                RAISE EXCEPTION 'SafeFace: an approved conclusion is immutable'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF (NEW.id, NEW.evidence_id, NEW.scale_value, NEW.rationale, NEW.author_id, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.evidence_id, OLD.scale_value, OLD.rationale, OLD.author_id, OLD.created_at) THEN
                RAISE EXCEPTION 'SafeFace: only approval fields of a conclusion may change'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF NEW.approved_by_id IS NULL OR NEW.approved_at IS NULL THEN
                RAISE EXCEPTION 'SafeFace: approval requires approver and time'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF NEW.approved_by_id = OLD.author_id THEN
                RAISE EXCEPTION 'SafeFace: separation of duties - author cannot approve'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER conclusions_guard BEFORE UPDATE OR DELETE ON conclusions
        FOR EACH ROW EXECUTE FUNCTION safeface_conclusion_guard();
    """)
    op.execute("""
        CREATE TRIGGER conclusions_no_truncate BEFORE TRUNCATE ON conclusions
        FOR EACH STATEMENT EXECUTE FUNCTION safeface_refuse_change();
    """)


def downgrade() -> None:
    raise RuntimeError("security migration is not reversible on an evidence database")
