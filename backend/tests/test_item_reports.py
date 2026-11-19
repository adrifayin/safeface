"""Separate reports per evidence item: scope, versioning, references, refusals."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from tests.conftest import FIXTURES, auth, new_case, upload


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_per_item_reports(client: TestClient, jpeg_bytes: bytes, edited_bytes: bytes) -> None:
    cid = new_case(client)["id"]
    ref_bytes = (FIXTURES / "scene_reference.jpg").read_bytes()
    q1 = upload(client, cid, edited_bytes, filename="first questioned.jpg").json()["evidence"]["id"]
    q2 = upload(client, cid, jpeg_bytes, filename="second.jpg").json()["evidence"]["id"]
    r = upload(client, cid, ref_bytes, filename="ref.jpg", kind="reference", reference_for=[q1])
    assert r.status_code == 201, r.text
    rid = r.json()["evidence"]["id"]

    # One report per questioned item, in one call.
    res = client.post(f"/api/v1/cases/{cid}/reports/per-item", headers=auth("esha"))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["refused"] == []
    by_item = {rep["evidence_id"]: rep for rep in body["generated"]}
    assert set(by_item) == {q1, q2}
    # Item 1's report covers it and its linked reference; item 2's covers only itself.
    assert {h["sha256"] for h in by_item[q1]["evidence_hashes"]} == {_sha(edited_bytes), _sha(ref_bytes)}
    assert {h["sha256"] for h in by_item[q2]["evidence_hashes"]} == {_sha(jpeg_bytes)}
    assert all(rep["version"] == 1 and rep["status"] == "draft" for rep in body["generated"])

    # Versions are per item and independent of the whole-case report.
    one = client.post(f"/api/v1/evidence/{q2}/reports", headers=auth("esha"))
    assert one.status_code == 201, one.text
    assert one.json()["version"] == 2 and one.json()["evidence_id"] == q2
    case_rep = client.post(f"/api/v1/cases/{cid}/reports", headers=auth("esha"))
    assert case_rep.status_code == 201, case_rep.text
    assert case_rep.json()["version"] == 1 and case_rep.json()["evidence_id"] is None

    listed = client.get(f"/api/v1/cases/{cid}/reports", headers=auth("suku")).json()
    assert len(listed) == 4 and listed[0]["evidence_id"] is None

    # The PDF downloads under the item's name and matches its register hash.
    pdf = client.get(f"/api/v1/reports/{by_item[q1]['id']}/pdf", headers=auth("suku"))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert _sha(pdf.content) == by_item[q1]["pdf_sha256"]
    assert 'filename="safeface-report-first_questioned-v1.pdf"' in pdf.headers["content-disposition"]

    # The single-item preview names only its own item.
    html = client.get(f"/api/v1/evidence/{q1}/report-preview", headers=auth("esha")).text
    assert "Single-item report" in html and "first questioned.jpg" in html
    assert "second.jpg" not in html

    # A reference item has no report of its own; outsiders cannot generate one.
    assert client.post(f"/api/v1/evidence/{rid}/reports", headers=auth("esha")).status_code == 400
    assert client.post(f"/api/v1/evidence/{q1}/reports", headers=auth("emil")).status_code == 404
    assert client.get("/api/v1/audit/verify", headers=auth("audrey")).json()["ok"] is True


def test_per_item_reports_need_questioned_items(client: TestClient) -> None:
    cid = new_case(client)["id"]
    assert client.post(f"/api/v1/cases/{cid}/reports/per-item", headers=auth("esha")).status_code == 409
