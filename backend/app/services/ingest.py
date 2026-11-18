"""Evidence ingest (SRS FR-1.2 – FR-1.5).

The upload body is streamed: each chunk is hashed (SHA-256 + MD5) and sent to
the object-locked originals bucket as a multipart upload, so the API never
holds a whole file in memory or on disk. The file type is decided from the
first bytes (magic numbers) before anything is stored, and the stream is cut
off as soon as it exceeds 4 GiB.

After upload the stored original is read back and re-hashed, so the recorded
hashes describe what is actually in storage, not just what was received.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.filetype import SNIFF_BYTES, DetectedType, detect
from app.core.hashing import Digests, StreamHasher
from app.core.storage import ObjectStore, original_key


@dataclass(frozen=True)
class StoredOriginal:
    evidence_id: uuid.UUID
    storage_key: str
    version_id: str | None
    detected: DetectedType
    digests: Digests


async def store_original_stream(
    store: ObjectStore, case_id: uuid.UUID, chunks: AsyncIterator[bytes]
) -> StoredOriginal:
    settings = get_settings()
    evidence_id = uuid.uuid4()
    key = original_key(case_id, evidence_id)
    bucket = settings.bucket_originals
    hasher = StreamHasher()
    buffer = bytearray()
    detected: DetectedType | None = None
    upload_id: str | None = None
    etags: list[str] = []

    async def flush(final: bool) -> None:
        nonlocal buffer
        assert upload_id is not None
        while len(buffer) >= settings.upload_part_bytes or (final and buffer):
            part = bytes(buffer[: settings.upload_part_bytes])
            del buffer[: len(part)]
            etag = await run_in_threadpool(
                store.upload_part, bucket, key, upload_id, len(etags) + 1, part
            )
            etags.append(etag)

    try:
        async for chunk in chunks:
            if not chunk:
                continue
            hasher.update(chunk)
            if hasher.size > settings.max_upload_bytes:
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file exceeds the 4 GiB limit"
                )
            buffer.extend(chunk)
            if detected is None and len(buffer) >= SNIFF_BYTES:
                detected = _require_supported(bytes(buffer[:SNIFF_BYTES]))
                upload_id = await run_in_threadpool(
                    store.start_multipart, bucket, key, detected.mime
                )
            if upload_id is not None:
                await flush(final=False)
        if detected is None:
            if not buffer:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty upload")
            detected = _require_supported(bytes(buffer))
            upload_id = await run_in_threadpool(store.start_multipart, bucket, key, detected.mime)
        await flush(final=True)
        assert upload_id is not None
        version_id = await run_in_threadpool(store.complete_multipart, bucket, key, upload_id, etags)
    except BaseException:
        if upload_id is not None:
            await run_in_threadpool(store.abort_multipart, bucket, key, upload_id)
        raise

    return StoredOriginal(evidence_id, key, version_id, detected, hasher.result())


def _require_supported(head: bytes) -> DetectedType:
    detected = detect(head)
    if detected is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "unsupported file type (checked by content, not file name). Accepted: JPEG, PNG, "
            "HEIC, WEBP, MP4, MOV, MKV, WEBM, WAV, MP3, M4A, OGG",
        )
    return detected
