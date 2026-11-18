"""Create a demo case with non-explicit synthetic images (dev/demo deployments only).

The questioned image is a synthetic street scene in which one building was
removed by inpainting and an object pasted in; the reference is the original
"camera" photo of the same scene, slightly rescaled. No real people, no
explicit content. (For AI-inpainting demos, add consenting team members'
photos edited with a diffusion model — see docs/TESTING.md.)

Runs inside the API image so it uses exactly the production ingest pipeline
(hashing, object lock, custody, audit, Tier 1 triage via Celery):

  docker compose -f infra/docker-compose.yml run --rm \
      -v "$PWD/scripts:/scripts:ro" -v "$PWD/backend/tests/fixtures:/fixtures:ro" \
      api python /scripts/seed_demo.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

sys.path.insert(0, "/app")

from sqlalchemy import select  # noqa: E402

from app.api.deps import CurrentUser  # noqa: E402
from app.api.evidence import _record_ingest  # noqa: E402
from app.api.schemas import EvidenceMetadata  # noqa: E402
from app.core import audit  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.policy import Role  # noqa: E402
from app.core.security import Principal  # noqa: E402
from app.core.storage import get_store  # noqa: E402
from app.db.models import Case, CaseMember, CasePermission, User  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.services.ingest import store_original_stream  # noqa: E402

DEMO_NAMESPACE = uuid.UUID("5afeface-0000-4000-8000-000000000000")
FIXTURES = Path("/fixtures")
CASE_NO = "DEMO/2026/0001"
USERS = {
    "ivan.investigator": ("Ivan Investigator", [Role.INVESTIGATOR], CasePermission.ANALYSE),
    "esha.examiner": ("Esha Examiner", [Role.EXAMINER], CasePermission.ANALYSE),
    "suku.supervisor": ("Suku Supervisor", [Role.SUPERVISOR], CasePermission.APPROVE),
    "sara.supervisor": ("Sara Supervisor", [Role.SUPERVISOR], CasePermission.APPROVE),
    "audrey.auditor": ("Audrey Auditor", [Role.AUDITOR], CasePermission.VIEW),
}


def ensure_user(s, username: str) -> User:  # type: ignore[no-untyped-def]
    sub = str(uuid.uuid5(DEMO_NAMESPACE, username))
    user = s.execute(select(User).where(User.keycloak_sub == sub)).scalar_one_or_none()
    if user is None:
        name, roles, _ = USERS[username]
        user = User(keycloak_sub=sub, username=username, display_name=name, roles=[r.value for r in roles])
        s.add(user)
        s.flush()
    return user


async def chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as fh:
        while block := fh.read(1024 * 1024):
            yield block


async def ingest(case_id: uuid.UUID, me: CurrentUser, path: Path, meta: EvidenceMetadata) -> str:
    stored = await store_original_stream(get_store(), case_id, chunks(path))
    with session_scope() as s:
        result = _record_ingest(s, me, case_id, meta, stored, get_store())
    print(f"  ingested {meta.filename}: sha256 {result.sha256}")
    return str(result.evidence.id)


def main() -> None:
    if get_settings().env == "prod":
        sys.exit("refusing to seed demo data in a production deployment")
    with session_scope() as s:
        if s.execute(select(Case).where(Case.case_no == CASE_NO)).scalar_one_or_none():
            print(f"{CASE_NO} already exists; nothing to do")
            return
        users = {u: ensure_user(s, u) for u in USERS}
        ivan, esha = users["ivan.investigator"], users["esha.examiner"]
        case = Case(case_no=CASE_NO, fir_no="FIR-0042/2026", crime_head="IT Act s.66E / BNS s.336 (demo)",
                    investigating_officer="SI Demo Officer", created_by_id=ivan.id,
                    assigned_examiner_id=esha.id,
                    description="DEMO: questioned street-scene image suspected of being edited; "
                                "complainant supplied the original photograph.")
        s.add(case)
        s.flush()
        for username, (_, _, perm) in USERS.items():
            s.add(CaseMember(case_id=case.id, user_id=users[username].id, permission=perm, added_by_id=ivan.id))
        audit.record(s, "system (seed_demo)", "case.created", "case", case.id, {"case_no": CASE_NO, "demo": True})
        case_id = case.id
        principal = Principal(sub=ivan.keycloak_sub, username=ivan.username, display_name=ivan.display_name,
                              roles=frozenset({Role.INVESTIGATOR}), session_id="seed")
        me = CurrentUser(principal, ivan)

    print(f"created {CASE_NO}")
    qid = asyncio.run(ingest(case_id, me, FIXTURES / "scene_edited.jpg", EvidenceMetadata(
        filename="questioned_street_scene.jpg", kind="questioned", source_platform="Instagram (demo)",
        complainant="Demo Complainant", collected_by="SI Demo Officer", upload_method="seed_demo")))
    asyncio.run(ingest(case_id, me, FIXTURES / "scene_original.jpg", EvidenceMetadata(
        filename="complainant_original.jpg", kind="reference", source_device="Complainant's phone (demo)",
        complainant="Demo Complainant", collected_by="SI Demo Officer", upload_method="seed_demo",
        reference_for=[uuid.UUID(qid)])))
    print("done: Tier 1 triage has been queued for the questioned image")


if __name__ == "__main__":
    main()
