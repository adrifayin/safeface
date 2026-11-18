"""Role / case-permission matrix, tested both on the policy table and over HTTP."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.policy import ROLE_ACTIONS, Action, Role, is_allowed
from app.db.models import CasePermission
from tests.conftest import auth, make_token, new_case, upload, user_id

R = Role


def roles(*r: Role) -> frozenset[Role]:
    return frozenset(r)


# (role, action, membership, expected)
MATRIX = [
    (R.INVESTIGATOR, Action.CASE_CREATE, None, True),
    (R.INVESTIGATOR, Action.EVIDENCE_UPLOAD, CasePermission.ANALYSE, True),
    (R.INVESTIGATOR, Action.EVIDENCE_UPLOAD, CasePermission.VIEW, False),
    (R.INVESTIGATOR, Action.EVIDENCE_UPLOAD, None, False),
    (R.INVESTIGATOR, Action.ANALYSIS_TIER1, CasePermission.ANALYSE, True),
    (R.INVESTIGATOR, Action.ANALYSIS_TIER2, CasePermission.ANALYSE, False),
    (R.INVESTIGATOR, Action.CONCLUSION_WRITE, CasePermission.ANALYSE, False),
    (R.INVESTIGATOR, Action.EVIDENCE_VERIFY, CasePermission.ANALYSE, False),
    (R.EXAMINER, Action.ANALYSIS_TIER2, CasePermission.ANALYSE, True),
    (R.EXAMINER, Action.CONCLUSION_WRITE, CasePermission.ANALYSE, True),
    (R.EXAMINER, Action.CONCLUSION_WRITE, CasePermission.VIEW, False),
    (R.EXAMINER, Action.CONCLUSION_APPROVE, CasePermission.APPROVE, False),
    (R.EXAMINER, Action.REPORT_GENERATE, CasePermission.ANALYSE, True),
    (R.EXAMINER, Action.AUDIT_VERIFY, None, False),
    (R.SUPERVISOR, Action.CONCLUSION_APPROVE, CasePermission.APPROVE, True),
    (R.SUPERVISOR, Action.CONCLUSION_APPROVE, CasePermission.ANALYSE, False),
    (R.SUPERVISOR, Action.CASE_LIST_ALL, None, True),
    (R.SUPERVISOR, Action.EVIDENCE_VIEW, None, False),
    (R.SUPERVISOR, Action.AUDIT_VERIFY, None, True),
    (R.ADMIN, Action.EVIDENCE_VIEW, CasePermission.APPROVE, False),
    (R.ADMIN, Action.CASE_VIEW, CasePermission.VIEW, False),
    (R.ADMIN, Action.MODELS_REQUEST_CHANGE, None, True),
    (R.ADMIN, Action.MODELS_APPROVE_CHANGE, None, False),
    (R.AUDITOR, Action.AUDIT_VERIFY, None, True),
    (R.AUDITOR, Action.REPORT_VIEW, CasePermission.VIEW, True),
    (R.AUDITOR, Action.EVIDENCE_VIEW, CasePermission.VIEW, False),
    (R.AUDITOR, Action.EVIDENCE_UPLOAD, CasePermission.ANALYSE, False),
]


@pytest.mark.parametrize(("role", "action", "member", "expected"), MATRIX)
def test_policy_matrix(role: Role, action: Action, member: CasePermission | None, expected: bool) -> None:
    assert is_allowed(roles(role), action, member) is expected


def test_admin_has_no_case_actions() -> None:
    from app.core.policy import CASE_PERMISSION_NEEDED

    assert all(CASE_PERMISSION_NEEDED[a] is None for a in ROLE_ACTIONS[R.ADMIN])


# --- HTTP -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def setup(client: TestClient) -> dict[str, str]:
    from tests.conftest import FIXTURES

    case = new_case(client)
    r = upload(client, case["id"], (FIXTURES / "scene_original.jpg").read_bytes())
    assert r.status_code == 201, r.text
    return {"case": case["id"], "evidence": r.json()["evidence"]["id"]}


def test_unauthenticated_rejected(client: TestClient, setup: dict[str, str]) -> None:
    assert client.get(f"/api/v1/cases/{setup['case']}").status_code == 401
    bad = {"Authorization": "Bearer not-a-token"}
    assert client.get(f"/api/v1/cases/{setup['case']}", headers=bad).status_code == 401


def test_expired_and_wrong_audience_rejected(client: TestClient) -> None:
    expired = make_token("ivan", exp=1, iat=0)
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    wrong_aud = make_token("ivan", aud="other-api")
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {wrong_aud}"}).status_code == 401
    wrong_iss = make_token("ivan", iss="https://evil.example/realms/x")
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {wrong_iss}"}).status_code == 401


def test_token_without_role_rejected(client: TestClient) -> None:
    tok = make_token("nobody", roles=["offline_access"])
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_non_member_cannot_see_case(client: TestClient, setup: dict[str, str]) -> None:
    # emil is an examiner but not a member of this case.
    assert client.get(f"/api/v1/cases/{setup['case']}", headers=auth("emil")).status_code == 404
    assert client.get(f"/api/v1/evidence/{setup['evidence']}/findings",
                      headers=auth("emil")).status_code == 404
    assert client.get(f"/api/v1/evidence/{setup['evidence']}/content",
                      headers=auth("emil")).status_code == 404


def test_admin_never_sees_media(client: TestClient, setup: dict[str, str]) -> None:
    for path in (f"/cases/{setup['case']}", f"/evidence/{setup['evidence']}/content",
                 f"/evidence/{setup['evidence']}/findings"):
        assert client.get(f"/api/v1{path}", headers=auth("adam")).status_code in (403, 404)
    r = client.post(f"/api/v1/cases/{setup['case']}/members", headers=auth("suku"),
                    json={"user_id": user_id(client, "adam"), "permission": "view"})
    assert r.status_code == 422


def test_auditor_member_sees_case_but_not_media(client: TestClient, setup: dict[str, str]) -> None:
    r = client.post(f"/api/v1/cases/{setup['case']}/members", headers=auth("suku"),
                    json={"user_id": user_id(client, "audrey"), "permission": "view"})
    assert r.status_code == 201
    assert client.get(f"/api/v1/cases/{setup['case']}", headers=auth("audrey")).status_code == 200
    assert client.get(f"/api/v1/evidence/{setup['evidence']}/content",
                      headers=auth("audrey")).status_code == 403
    assert client.get(f"/api/v1/cases/{setup['case']}/reports", headers=auth("audrey")).status_code == 200


def test_investigator_cannot_run_tier2_or_conclude(client: TestClient, setup: dict[str, str]) -> None:
    r = client.post(f"/api/v1/evidence/{setup['evidence']}/analyses", headers=auth("ivan"),
                    json={"module_ids": ["image.source_match"]})
    assert r.status_code in (403, 422)
    r = client.post(f"/api/v1/evidence/{setup['evidence']}/conclusion", headers=auth("ivan"),
                    json={"scale_value": "inconclusive", "rationale": "x" * 30})
    assert r.status_code == 403


def test_only_supervisor_and_auditor_verify_audit(client: TestClient) -> None:
    for user, code in (("ivan", 403), ("esha", 403), ("adam", 403), ("suku", 200), ("audrey", 200)):
        assert client.get("/api/v1/audit/verify", headers=auth(user)).status_code == code, user


def test_member_assignment_requires_supervisor(client: TestClient, setup: dict[str, str]) -> None:
    r = client.post(f"/api/v1/cases/{setup['case']}/members", headers=auth("esha"),
                    json={"user_id": user_id(client, "emil"), "permission": "analyse"})
    assert r.status_code == 403
