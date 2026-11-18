"""End-to-end: upload -> triage -> Tier 2 -> notes -> conclusion -> approval -> PDF."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from tests.conftest import auth, new_case, upload

FORBIDDEN_VERDICT_WORDS = ("verdict: fake", "verdict: real", "is fake", "is real", "deepfake detected")


def test_full_flow(client: TestClient, jpeg_bytes: bytes, edited_bytes: bytes) -> None:
    case = new_case(client)
    cid = case["id"]

    # 1. Investigator uploads questioned image and the victim's original as reference.
    q = upload(client, cid, edited_bytes, filename="questioned.jpg", source_platform="Instagram")
    assert q.status_code == 201, q.text
    qid = q.json()["evidence"]["id"]
    assert q.json()["triage_job_ids"], "Tier 1 triage must be queued automatically"
    ref = upload(client, cid, jpeg_bytes, filename="victim_original.jpg", kind="reference",
                 reference_for=[qid])
    assert ref.status_code == 201, ref.text
    rid = ref.json()["evidence"]["id"]

    # 2. Triage findings exist, grouped by family in the defined order, never merged.
    f = client.get(f"/api/v1/evidence/{qid}/findings", headers=auth("esha"))
    assert f.status_code == 200, f.text
    body = f.json()
    families = [g["family"] for g in body["groups"]]
    order = ["INTEGRITY", "PROVENANCE", "COMPARISON", "CLASSICAL", "AI_DETECTOR"]
    assert families == sorted(families, key=order.index)
    modules = {x["module_id"] for g in body["groups"] for x in g["findings"]}
    assert {"integrity.hash", "image.ela", "image.noise"} <= modules
    assert "indicators, not determinations" in body["notice"]
    for job in body["jobs"]:
        assert job["status"] in ("succeeded", "unavailable"), job
    for g in body["groups"]:
        for finding in g["findings"]:
            assert finding["limitations"]
            assert finding["provenance"]["module_version"] == finding["module_version"]
            assert finding["provenance"]["input"]["sha256"] == hashlib.sha256(edited_bytes).hexdigest()
            assert "container_image_digest" in finding["provenance"]["environment"]

    # 3. Examiner runs Tier 2 source matching against the linked reference.
    r = client.post(f"/api/v1/evidence/{qid}/analyses", headers=auth("esha"),
                    json={"module_ids": ["image.source_match"]})
    assert r.status_code == 202, r.text
    job = client.get(f"/api/v1/jobs/{r.json()[0]['id']}", headers=auth("esha")).json()
    assert job["status"] == "succeeded", job
    assert job["reference_ids"] == [rid]

    findings = client.get(f"/api/v1/evidence/{qid}/findings", headers=auth("esha")).json()
    ela = next(x for g in findings["groups"] for x in g["findings"] if x["module_id"] == "image.ela")
    art = ela["artefacts"][0]
    img = client.get(f"/api/v1/artefacts/{art['key']}", headers=auth("esha"))
    assert img.status_code == 200 and img.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert hashlib.sha256(img.content).hexdigest() == art["sha256"]
    assert client.get(f"/api/v1/artefacts/{art['key']}", headers=auth("emil")).status_code == 404

    # 4. Notes and conclusion.
    r = client.post(f"/api/v1/evidence/{qid}/notes", headers=auth("esha"),
                    json={"text": "ELA shows a region of uniform error near the centre.",
                          "finding_id": ela["id"]})
    assert r.status_code == 201
    r = client.post(f"/api/v1/evidence/{qid}/conclusion", headers=auth("esha"), json={
        "scale_value": "moderate_support_manipulation",
        "rationale": "Aligned difference with the reference shows two localised changes; "
                     "noise and ELA maps are consistent with that region.",
    })
    assert r.status_code == 201, r.text
    conclusion = r.json()

    # A draft report can be produced before approval.
    draft = client.post(f"/api/v1/cases/{cid}/reports", headers=auth("esha"))
    assert draft.status_code == 201, draft.text
    assert draft.json()["status"] == "draft"

    # 5. Separation of duties and approval.
    assert client.post(f"/api/v1/conclusions/{conclusion['id']}/approve", headers=auth("esha"),
                       json={}).status_code == 403
    pending_r = client.get("/api/v1/approvals/pending", headers=auth("suku"))
    assert pending_r.status_code == 200, pending_r.text
    pending = pending_r.json()
    assert any(p["id"] == conclusion["id"] for p in pending)
    r = client.post(f"/api/v1/conclusions/{conclusion['id']}/approve", headers=auth("suku"),
                    json={"comment": "Reviewed."})
    assert r.status_code == 200, r.text
    assert r.json()["approved_by_name"]
    assert client.post(f"/api/v1/conclusions/{conclusion['id']}/approve", headers=auth("suku"),
                       json={}).status_code == 409

    # 6. Final report; its hash verifies independently.
    rep = client.post(f"/api/v1/cases/{cid}/reports", headers=auth("esha"))
    assert rep.status_code == 201, rep.text
    report = rep.json()
    assert report["status"] == "final" and report["version"] == 2
    assert {h["sha256"] for h in report["evidence_hashes"]} == {
        hashlib.sha256(edited_bytes).hexdigest(), hashlib.sha256(jpeg_bytes).hexdigest()}
    pdf = client.get(f"/api/v1/reports/{report['id']}/pdf", headers=auth("suku"))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert hashlib.sha256(pdf.content).hexdigest() == report["pdf_sha256"]
    assert pdf.headers["x-safeface-pdf-sha256"] == report["pdf_sha256"]

    # 7. No automatic verdict anywhere in the report text.
    html = client.get(f"/api/v1/cases/{cid}/report-preview", headers=auth("esha")).text.lower()
    assert "indicators, not determinations" in html
    for word in FORBIDDEN_VERDICT_WORDS:
        assert word not in html

    # 8. s.63(4) data and audit chain.
    s63 = client.get(f"/api/v1/cases/{cid}/s63-data", headers=auth("esha")).json()
    assert {r["hash_values"][0]["value"] for r in s63["records"]} == {
        hashlib.sha256(edited_bytes).hexdigest(), hashlib.sha256(jpeg_bytes).hexdigest()}
    assert client.get("/api/v1/audit/verify", headers=auth("audrey")).json()["ok"] is True


def test_newer_conclusion_supersedes(client: TestClient, edited_bytes: bytes) -> None:
    case = new_case(client)
    qid = upload(client, case["id"], edited_bytes).json()["evidence"]["id"]
    first = client.post(f"/api/v1/evidence/{qid}/conclusion", headers=auth("esha"),
                        json={"scale_value": "inconclusive", "rationale": "Initial view, pending Tier 2."}).json()
    client.post(f"/api/v1/evidence/{qid}/conclusion", headers=auth("esha"),
                json={"scale_value": "moderate_support_manipulation", "rationale": "After Tier 2 analysis."})
    r = client.post(f"/api/v1/conclusions/{first['id']}/approve", headers=auth("suku"), json={})
    assert r.status_code == 409


def test_rerun_reproduces_scores(client: TestClient, jpeg_bytes: bytes) -> None:
    case = new_case(client)
    qid = upload(client, case["id"], jpeg_bytes).json()["evidence"]["id"]
    findings = client.get(f"/api/v1/evidence/{qid}/findings", headers=auth("esha")).json()
    ela = next(x for g in findings["groups"] for x in g["findings"] if x["module_id"] == "image.ela")
    r = client.post(f"/api/v1/findings/{ela['id']}/rerun", headers=auth("esha"))
    assert r.status_code == 202, r.text
    rep = client.get(f"/api/v1/findings/{ela['id']}/reproducibility", headers=auth("esha")).json()
    assert rep["reruns"] and all(x["reproduced"] for x in rep["reruns"]), rep
