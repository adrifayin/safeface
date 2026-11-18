"""Hash re-verification of stored originals and working copies (SRS FR-1.6)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import get_settings
from app.core.hashing import hash_chunks
from app.core.storage import ObjectStore
from app.db.models import EvidenceItem, HashVerification, WorkingCopyRow


def verify_item(
    session: Session, store: ObjectStore, item: EvidenceItem, actor: str, reason: str
) -> list[HashVerification]:
    """Re-hash the original (exact stored version) and its working copies.

    Returns the verification rows written. A missing object counts as a failure.
    """
    settings = get_settings()
    results: list[HashVerification] = []

    def check(target: str, bucket: str, key: str, version: str | None, sha: str, md5: str) -> None:
        try:
            digests = hash_chunks(store.iter_object(bucket, key, version))
            ok = digests.sha256 == sha and digests.md5 == md5
            row = HashVerification(
                evidence_id=item.id, target=target, computed_sha256=digests.sha256,
                computed_md5=digests.md5, ok=ok, reason=reason, actor=actor,
            )
        except Exception:  # noqa: BLE001 - missing/unreadable object is a failed check
            row = HashVerification(
                evidence_id=item.id, target=target, computed_sha256=None, computed_md5=None,
                ok=False, reason=reason, actor=actor,
            )
        session.add(row)
        results.append(row)

    check("original", settings.bucket_originals, item.storage_key, item.storage_version_id,
          item.sha256, item.md5)
    copies = session.execute(
        select(WorkingCopyRow).where(
            WorkingCopyRow.evidence_id == item.id, WorkingCopyRow.derived_from.is_(None)
        )
    ).scalars()
    for wc in copies:
        check(f"working:{wc.id}", settings.bucket_working, wc.storage_key, None, wc.sha256, wc.md5)
    session.flush()

    all_ok = all(r.ok for r in results)
    audit.record(
        session, actor, "evidence.verified" if all_ok else "evidence.verification_failed",
        "evidence", item.id,
        {
            "reason": reason,
            "expected_sha256": item.sha256,
            "results": [
                {"target": r.target, "ok": r.ok, "computed_sha256": r.computed_sha256}
                for r in results
            ],
        },
    )
    return results


def latest_verification(session: Session, evidence_id: object) -> HashVerification | None:
    return session.execute(
        select(HashVerification)
        .where(HashVerification.evidence_id == evidence_id, HashVerification.target == "original")
        .order_by(HashVerification.verified_at.desc())
        .limit(1)
    ).scalar_one_or_none()
