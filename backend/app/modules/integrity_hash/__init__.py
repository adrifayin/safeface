"""integrity.hash: confirm the analysed bytes are identical to the ingested original."""

from __future__ import annotations

from typing import Any

from app.core.hashing import hash_file
from app.modules.base import (
    Availability,
    Family,
    Finding,
    MediaType,
    ModuleBase,
    Score,
    WorkingCopy,
)


class IntegrityHash(ModuleBase):
    id = "integrity.hash"
    version = "1.0.0"
    name = "Hash verification"
    description = "SHA-256 and MD5 of the working copy compared with the hashes recorded at ingest."
    family = Family.INTEGRITY
    media_types = {MediaType.IMAGE, MediaType.VIDEO, MediaType.AUDIO}  # noqa: RUF012
    tier = 1

    def screen(self, scores: dict[str, float | None], details: dict[str, Any]) -> str | None:
        if scores.get("sha256_match") == 0:
            return "The analysed copy does not match the ingest hash (integrity failure)"
        return None
    headline = ("sha256_match", None)
    question = ""  # shown in the integrity panel, not as a manipulation question
    plain = 'Is the file analysed exactly the file that was received? (1 = yes)'
    limitations = (
        "A matching hash proves only that the analysed file is bit-for-bit identical to the file "
        "received at ingest. It says nothing about whether the content itself is authentic, nor "
        "about what happened to the file before it was collected."
    )

    def availability(self) -> Availability:
        return Availability(True)

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding:
        self.merged_params(params)
        digests = hash_file(item.path)
        sha_ok = digests.sha256 == item.original_sha256
        md5_ok = digests.md5 == item.original_md5
        status = "verified" if sha_ok and md5_ok else "MISMATCH"
        return Finding(
            scores=[
                Score("sha256_match", 1.0 if sha_ok else 0.0, (0, 1),
                      "1 = SHA-256 of the analysed copy equals the ingest SHA-256; 0 = differs."),
                Score("md5_match", 1.0 if md5_ok else 0.0, (0, 1),
                      "1 = MD5 equals the ingest MD5; 0 = differs. MD5 is recorded for legacy "
                      "compatibility; SHA-256 is authoritative."),
                Score("size_bytes", float(digests.size), None, "File size in bytes.", "bytes"),
            ],
            summary=f"Hash verification {status}: SHA-256 {digests.sha256}.",
            limitations=self.limitations,
            details={
                "computed": {"sha256": digests.sha256, "md5": digests.md5, "size": digests.size},
                "recorded_at_ingest": {"sha256": item.original_sha256, "md5": item.original_md5},
                "status": status,
            },
        )


MODULE = IntegrityHash()
