"""FR-6.5: closure and two-person approved disposal of a case's derived data."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.storage import get_store
from tests.conftest import auth, new_case, upload


def test_close_and_dispose(client: TestClient, jpeg_bytes: bytes) -> None:
    case = new_case(client)
    cid = case["id"]
    ev = upload(client, cid, jpeg_bytes).json()["evidence"]

    # Disposal needs a closed case; only supervisors may close.
    body = {"reason": "Retention period ended for this closed matter.", "authority": "Retention order 12/2026"}
    assert client.post(f"/api/v1/cases/{cid}/disposals", headers=auth("suku"), json=body).status_code == 409
    assert client.post(f"/api/v1/cases/{cid}/close", headers=auth("esha")).status_code == 403
    assert client.post(f"/api/v1/cases/{cid}/close", headers=auth("suku")).status_code == 200

    # A closed case accepts no new evidence or analyses.
    assert upload(client, cid, jpeg_bytes).status_code == 409
    r = client.post(f"/api/v1/evidence/{ev['id']}/analyses", headers=auth("esha"), json={"module_ids": ["image.ela"]})
    assert r.status_code == 409

    req = client.post(f"/api/v1/cases/{cid}/disposals", headers=auth("suku"), json=body)
    assert req.status_code == 201, req.text
    rid = req.json()["id"]
    # Two-person rule: the requester cannot approve; investigators cannot either.
    assert client.post(f"/api/v1/disposals/{rid}/approve", headers=auth("suku")).status_code == 403
    assert client.post(f"/api/v1/disposals/{rid}/approve", headers=auth("ivan")).status_code == 403
    done = client.post(f"/api/v1/disposals/{rid}/approve", headers=auth("sara"))
    assert done.status_code == 200, done.text
    result = done.json()
    assert result["status"] == "approved" and result["result"]["derived_objects_deleted"] >= 1

    s = get_settings()
    store = get_store()
    # Original untouched (write-once); working copy gone; media no longer served.
    assert store.get_bytes(s.bucket_originals, f"cases/{cid}/{ev['id']}/original") == jpeg_bytes
    assert client.get(f"/api/v1/evidence/{ev['id']}/content", headers=auth("esha")).status_code == 410
    # Records remain: hashes and the audit trail.
    assert client.get(f"/api/v1/evidence/{ev['id']}", headers=auth("esha")).json()["sha256"] == ev["sha256"]
    entries = client.get(f"/api/v1/audit/entries?target_id={cid}&limit=1000", headers=auth("audrey")).json()
    actions = {e["action"] for e in entries}
    assert {"case.closed", "case.disposal_requested", "case.disposal_approved"} <= actions
    assert client.get("/api/v1/audit/verify", headers=auth("audrey")).json()["ok"]
