"""Access-control policy: the single source of truth for who may do what.

A request is allowed only if BOTH hold:

1. one of the caller's Keycloak roles grants the action (``ROLE_ACTIONS``); and
2. for case-scoped actions, the caller is a member of the case with at least
   the permission in ``CASE_PERMISSION_NEEDED``.

Notable rules from the SRS/TDD:
- Administrators have no case-scoped actions at all, so they can never see
  case media (NFR-S3).
- Auditors are read-only: audit log, plus reports of cases they are members of.
- Supervisors can list all cases and assign members, but must still be a
  member (``approve``) of a case to see its media or approve conclusions.
- Separation of duties (an author may not approve their own conclusion) is
  enforced in the approval route, because it depends on the row, not the role.
"""

from __future__ import annotations

from enum import StrEnum

from app.db.models import CasePermission


class Role(StrEnum):
    INVESTIGATOR = "investigator"
    EXAMINER = "examiner"
    SUPERVISOR = "supervisor"
    ADMIN = "admin"
    AUDITOR = "auditor"


class Action(StrEnum):
    CASE_CREATE = "case.create"
    CASE_LIST_ALL = "case.list_all"
    CASE_ASSIGN = "case.assign"
    CASE_VIEW = "case.view"
    CASE_CLOSE = "case.close"
    CASE_DISPOSE = "case.dispose"
    EVIDENCE_UPLOAD = "evidence.upload"
    EVIDENCE_VIEW = "evidence.view"
    EVIDENCE_VERIFY = "evidence.verify"
    ANALYSIS_TIER1 = "analysis.tier1"
    ANALYSIS_TIER2 = "analysis.tier2"
    NOTE_WRITE = "note.write"
    CONCLUSION_WRITE = "conclusion.write"
    CONCLUSION_APPROVE = "conclusion.approve"
    REPORT_GENERATE = "report.generate"
    REPORT_VIEW = "report.view"
    S63_VIEW = "s63.view"
    AUDIT_VIEW = "audit.view"
    AUDIT_VERIFY = "audit.verify"
    MODULES_VIEW = "modules.view"
    ADMIN_USERS = "admin.users"
    MODELS_VIEW = "models.view"
    MODELS_REQUEST_CHANGE = "models.request_change"
    MODELS_APPROVE_CHANGE = "models.approve_change"
    BENCHMARK_RUN = "benchmark.run"


A = Action

_CASE_WORKER = {
    A.CASE_VIEW, A.EVIDENCE_VIEW, A.REPORT_VIEW, A.MODULES_VIEW, A.MODELS_VIEW,
}

ROLE_ACTIONS: dict[Role, frozenset[Action]] = {
    Role.INVESTIGATOR: frozenset(
        _CASE_WORKER | {A.CASE_CREATE, A.EVIDENCE_UPLOAD, A.ANALYSIS_TIER1}
    ),
    Role.EXAMINER: frozenset(
        _CASE_WORKER
        | {
            A.CASE_CREATE, A.EVIDENCE_UPLOAD, A.EVIDENCE_VERIFY, A.ANALYSIS_TIER1,
            A.ANALYSIS_TIER2, A.NOTE_WRITE, A.CONCLUSION_WRITE, A.REPORT_GENERATE, A.S63_VIEW,
        }
    ),
    Role.SUPERVISOR: frozenset(
        _CASE_WORKER
        | {
            A.CASE_CREATE, A.CASE_LIST_ALL, A.CASE_ASSIGN, A.CASE_CLOSE, A.CASE_DISPOSE, A.EVIDENCE_VERIFY,
            A.CONCLUSION_APPROVE, A.AUDIT_VIEW, A.AUDIT_VERIFY, A.MODELS_APPROVE_CHANGE, A.BENCHMARK_RUN,
        }
    ),
    Role.ADMIN: frozenset(
        {A.MODULES_VIEW, A.MODELS_VIEW, A.ADMIN_USERS, A.MODELS_REQUEST_CHANGE, A.BENCHMARK_RUN}
    ),
    Role.AUDITOR: frozenset(
        {A.CASE_VIEW, A.REPORT_VIEW, A.AUDIT_VIEW, A.AUDIT_VERIFY, A.MODULES_VIEW, A.MODELS_VIEW}
    ),
}

_RANK = {CasePermission.VIEW: 1, CasePermission.ANALYSE: 2, CasePermission.APPROVE: 3}

# ``None`` means the action is not scoped to a case.
CASE_PERMISSION_NEEDED: dict[Action, CasePermission | None] = {
    A.CASE_CREATE: None,
    A.CASE_LIST_ALL: None,
    A.CASE_ASSIGN: None,
    A.CASE_VIEW: CasePermission.VIEW,
    A.CASE_CLOSE: None,
    A.CASE_DISPOSE: None,
    A.EVIDENCE_UPLOAD: CasePermission.ANALYSE,
    A.EVIDENCE_VIEW: CasePermission.VIEW,
    A.EVIDENCE_VERIFY: CasePermission.VIEW,
    A.ANALYSIS_TIER1: CasePermission.ANALYSE,
    A.ANALYSIS_TIER2: CasePermission.ANALYSE,
    A.NOTE_WRITE: CasePermission.ANALYSE,
    A.CONCLUSION_WRITE: CasePermission.ANALYSE,
    A.CONCLUSION_APPROVE: CasePermission.APPROVE,
    A.REPORT_GENERATE: CasePermission.ANALYSE,
    A.REPORT_VIEW: CasePermission.VIEW,
    A.S63_VIEW: CasePermission.ANALYSE,
    A.AUDIT_VIEW: None,
    A.AUDIT_VERIFY: None,
    A.MODULES_VIEW: None,
    A.ADMIN_USERS: None,
    A.MODELS_VIEW: None,
    A.MODELS_REQUEST_CHANGE: None,
    A.MODELS_APPROVE_CHANGE: None,
    A.BENCHMARK_RUN: None,
}

# Auditors may see case metadata and reports, never evidence media.
_MEDIA_ACTIONS = {A.EVIDENCE_VIEW}


def role_allows(roles: frozenset[Role], action: Action) -> bool:
    return any(action in ROLE_ACTIONS.get(role, frozenset()) for role in roles)


def is_allowed(
    roles: frozenset[Role], action: Action, membership: CasePermission | str | None
) -> bool:
    """Decide one request. ``membership`` is the caller's case permission, if any."""
    if not role_allows(roles, action):
        return False
    needed = CASE_PERMISSION_NEEDED[action]
    if needed is None:
        return True
    if membership is None:
        return False
    if action in _MEDIA_ACTIONS and roles <= {Role.AUDITOR, Role.ADMIN}:
        return False
    return _RANK[CasePermission(membership)] >= _RANK[needed]


def default_membership(roles: frozenset[Role]) -> CasePermission:
    """Permission given to a user who creates a case or is assigned to it."""
    if Role.SUPERVISOR in roles:
        return CasePermission.APPROVE
    if roles & {Role.EXAMINER, Role.INVESTIGATOR}:
        return CasePermission.ANALYSE
    return CasePermission.VIEW
