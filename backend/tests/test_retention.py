"""7-minute purge of working files, restore from the sealed original, integrity summary."""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.storage import get_store
from app.db.models import EvidenceItem
from app.db.session import session_scope
from app.services.retention import purge_work_files
from tests.conftest import auth, new_case, upload


def test_purge_then_restore(client: TestClient, jpeg_bytes: bytes) -> None:
    case = new_case(client)
    ev = upload(client, case["id"], jpeg_bytes).json()["evidence"]
    s = get_settings()
    store = get_store()
    findings = client.get(f"/api/v1/evidence/{ev['id']}/findings", headers=auth("esha")).json()
    art = next(a for g in findings["groups"] for f in g["findings"] for a in f["artefacts"])

    with session_scope() as db:
        removed = purge_work_files(db, store, db.get(EvidenceItem, ev["id"]), "test")
    assert any(r.startswith("working/") for r in removed) and any(r.startswith("artefacts/") for r in removed)
    # The sealed original is untouched.
    assert store.get_bytes(s.bucket_originals, f"cases/{case['id']}/{ev['id']}/original") == jpeg_bytes

    integ = client.get(f"/api/v1/evidence/{ev['id']}/integrity", headers=auth("esha")).json()
    assert integ["status"] == "verified" and "purged" in integ["working_copy"]
    assert integ["sha256"] == hashlib.sha256(jpeg_bytes).hexdigest()

    r = client.get(f"/api/v1/artefacts/{art['key']}", headers=auth("esha"))
    assert r.status_code == 410 and "7-minute" in r.json()["detail"]

    # Viewing (or analysing) restores the working copy from the sealed original, hash-checked.
    content = client.get(f"/api/v1/evidence/{ev['id']}/content", headers=auth("esha"))
    assert content.status_code == 200 and content.content == jpeg_bytes
    actions = [e["action"] for e in client.get(f"/api/v1/evidence/{ev['id']}/custody", headers=auth("esha")).json()]
    assert "evidence.work_files_purged" in actions and "evidence.working_copy_restored" in actions
    assert client.post(f"/api/v1/evidence/{ev['id']}/browser-wipe", headers=auth("esha"),
                       json={"what": "content"}).status_code == 200
    r = client.post(f"/api/v1/evidence/{ev['id']}/analyses", headers=auth("esha"), json={"module_ids": ["image.ela"]})
    job = client.get(f"/api/v1/jobs/{r.json()[0]['id']}", headers=auth("esha")).json()
    assert job["status"] == "succeeded"

    # A report after purging still generates; purged figures are noted, not silently dropped.
    with session_scope() as db:
        purge_work_files(db, store, db.get(EvidenceItem, ev["id"]), "test")
    html = client.get(f"/api/v1/cases/{case['id']}/report-preview", headers=auth("esha")).text
    assert "7-minute retention period" in html


def test_originals_can_never_be_deleted(jpeg_bytes: bytes) -> None:
    with pytest.raises(PermissionError):
        get_store().delete(get_settings().bucket_originals, "cases/x/y/original")
