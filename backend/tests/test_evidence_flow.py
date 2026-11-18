"""Ingest, hashing, custody and tamper detection (FR-1.2 – FR-1.6)."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.storage import get_store
from tests.conftest import auth, new_case, upload


def test_upload_returns_independent_hashes(client: TestClient, jpeg_bytes: bytes) -> None:
    case = new_case(client)
    r = upload(client, case["id"], jpeg_bytes, source_platform="WhatsApp",
               source_url="https://example.invalid/post/1", collected_by="SI Test",
               complainant="Complainant A", upload_method="web-upload")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["sha256"] == hashlib.sha256(jpeg_bytes).hexdigest()
    assert body["md5"] == hashlib.md5(jpeg_bytes).hexdigest()
    assert body["size_bytes"] == len(jpeg_bytes)
    ev = body["evidence"]
    assert ev["detected_mime"] == "image/jpeg" and ev["media_type"] == "image"
    assert ev["source_platform"] == "WhatsApp" and ev["complainant"] == "Complainant A"
    assert ev["last_verification"]["ok"] is True
    # The stored original is byte-identical to what was uploaded.
    stored = get_store().get_bytes(get_settings().bucket_originals,
                                   f"cases/{case['id']}/{ev['id']}/original")
    assert stored == jpeg_bytes


def test_rejects_unsupported_type_by_content(client: TestClient) -> None:
    case = new_case(client)
    r = upload(client, case["id"], b"MZ\x90\x00" + b"\x00" * 200, filename="photo.jpg")
    assert r.status_code == 415
    r = upload(client, case["id"], b"", filename="empty.jpg")
    assert r.status_code == 400


def test_rejects_oversize(client: TestClient, jpeg_bytes: bytes, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 1000)
    case = new_case(client)
    r = upload(client, case["id"], jpeg_bytes)
    assert r.status_code == 413


def test_custody_log_records_actions(client: TestClient, jpeg_bytes: bytes) -> None:
    case = new_case(client)
    ev = upload(client, case["id"], jpeg_bytes).json()["evidence"]
    client.get(f"/api/v1/evidence/{ev['id']}/content", headers=auth("esha"))
    client.post(f"/api/v1/evidence/{ev['id']}/verify", headers=auth("esha"))
    actions = [e["action"] for e in client.get(f"/api/v1/evidence/{ev['id']}/custody",
                                               headers=auth("esha")).json()]
    for expected in ("evidence.ingested", "evidence.working_copy_created", "evidence.verified",
                     "evidence.triage_queued", "evidence.viewed"):
        assert expected in actions


def test_modified_original_is_detected(client: TestClient, jpeg_bytes: bytes) -> None:
    case = new_case(client)
    ev = upload(client, case["id"], jpeg_bytes).json()["evidence"]
    key = (get_settings().bucket_originals, f"cases/{case['id']}/{ev['id']}/original")
    store = get_store()
    tampered = bytearray(jpeg_bytes)
    tampered[len(tampered) // 2] ^= 0x01  # flip one bit
    store.objects[key] = bytes(tampered)  # type: ignore[attr-defined]

    r = client.post(f"/api/v1/evidence/{ev['id']}/verify", headers=auth("esha"))
    assert r.status_code == 200
    original = next(v for v in r.json() if v["target"] == "original")
    assert original["ok"] is False
    assert original["computed_sha256"] == hashlib.sha256(tampered).hexdigest()

    # Report generation re-verifies and must refuse.
    r = client.post(f"/api/v1/cases/{case['id']}/reports", headers=auth("esha"))
    assert r.status_code == 409
    actions = [e["action"] for e in client.get(f"/api/v1/evidence/{ev['id']}/custody",
                                               headers=auth("esha")).json()]
    assert "evidence.verification_failed" in actions


def test_tampered_working_copy_refused_by_worker(client: TestClient, jpeg_bytes: bytes) -> None:
    case = new_case(client)
    ev = upload(client, case["id"], jpeg_bytes).json()["evidence"]
    store = get_store()
    for (bucket, key) in list(store.objects):  # type: ignore[attr-defined]
        if bucket == get_settings().bucket_working and f"/{ev['id']}/working/" in key:
            store.objects[(bucket, key)] = b"\xff\xd8\xff" + b"0" * 100  # type: ignore[attr-defined]
    r = client.post(f"/api/v1/evidence/{ev['id']}/analyses", headers=auth("esha"),
                    json={"module_ids": ["integrity.hash"]})
    assert r.status_code == 202
    job = client.get(f"/api/v1/jobs/{r.json()[0]['id']}", headers=auth("esha")).json()
    assert job["status"] == "failed" and "refused" in job["error"]


def test_bad_reference_rejected_before_storage(client: TestClient, jpeg_bytes: bytes) -> None:
    import uuid as _uuid

    case = new_case(client)
    before = len(get_store().objects)  # type: ignore[attr-defined]
    r = upload(client, case["id"], jpeg_bytes, kind="reference", reference_for=[str(_uuid.uuid4())])
    assert r.status_code == 422
    assert len(get_store().objects) == before  # nothing written to write-once storage  # type: ignore[attr-defined]
