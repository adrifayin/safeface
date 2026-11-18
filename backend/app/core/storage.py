"""Object storage (MinIO via the S3 API).

Buckets:
- ``evidence-originals``: object lock (COMPLIANCE by default) + versioning. An
  original can never be overwritten or deleted during its retention period,
  not even by the MinIO root user.
- ``working``, ``artefacts``, ``reports``: ordinary buckets.

Every bucket gets default server-side encryption (SSE-S3, AES-256), backed by
the MinIO KMS key configured in ``infra/.env``.

``MemoryStore`` implements the same interface for unit tests; it deliberately
allows overwriting so tests can simulate tampering with an original.
"""

from __future__ import annotations

import base64
import hashlib
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from app.core.config import Settings, get_settings

READ_CHUNK = 1024 * 1024


class ObjectStore(Protocol):
    def ensure_buckets(self) -> None: ...
    def start_multipart(self, bucket: str, key: str, content_type: str) -> str: ...
    def upload_part(self, bucket: str, key: str, upload_id: str, number: int, data: bytes) -> str: ...
    def complete_multipart(
        self, bucket: str, key: str, upload_id: str, etags: list[str]
    ) -> str | None: ...
    def abort_multipart(self, bucket: str, key: str, upload_id: str) -> None: ...
    def put_bytes(self, bucket: str, key: str, data: bytes, content_type: str) -> None: ...
    def get_bytes(self, bucket: str, key: str) -> bytes: ...
    def iter_object(self, bucket: str, key: str, version_id: str | None = None) -> Iterator[bytes]: ...
    def download_to(self, bucket: str, key: str, path: Path) -> None: ...
    def copy(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> None: ...
    def exists(self, bucket: str, key: str) -> bool: ...
    def delete(self, bucket: str, key: str) -> None: ...
    def retention(self, bucket: str, key: str, version_id: str | None) -> dict[str, str] | None: ...


def _md5_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.md5(data, usedforsecurity=False).digest()).decode()


class S3Store:
    """MinIO/S3 implementation using boto3."""

    def __init__(self, settings: Settings) -> None:
        import boto3
        from botocore.config import Config

        self._settings = settings
        self._s3: Any = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    # --- bootstrap -------------------------------------------------------------

    def ensure_buckets(self) -> None:
        s = self._settings
        existing = {b["Name"] for b in self._s3.list_buckets().get("Buckets", [])}
        if s.bucket_originals not in existing:
            self._s3.create_bucket(Bucket=s.bucket_originals, ObjectLockEnabledForBucket=True)
        self._s3.put_object_lock_configuration(
            Bucket=s.bucket_originals,
            ObjectLockConfiguration={
                "ObjectLockEnabled": "Enabled",
                "Rule": {
                    "DefaultRetention": {"Mode": s.object_lock_mode, "Days": s.object_lock_days}
                },
            },
        )
        for bucket in (s.bucket_working, s.bucket_artefacts, s.bucket_reports):
            if bucket not in existing:
                self._s3.create_bucket(Bucket=bucket)
        for bucket in (s.bucket_originals, s.bucket_working, s.bucket_artefacts, s.bucket_reports):
            self._s3.put_bucket_encryption(
                Bucket=bucket,
                ServerSideEncryptionConfiguration={
                    "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
                },
            )

    # --- writes ------------------------------------------------------------------

    def start_multipart(self, bucket: str, key: str, content_type: str) -> str:
        resp = self._s3.create_multipart_upload(
            Bucket=bucket, Key=key, ContentType=content_type, ServerSideEncryption="AES256"
        )
        return str(resp["UploadId"])

    def upload_part(self, bucket: str, key: str, upload_id: str, number: int, data: bytes) -> str:
        # Content-MD5 is required by S3 for object-locked buckets.
        resp = self._s3.upload_part(
            Bucket=bucket, Key=key, UploadId=upload_id, PartNumber=number, Body=data,
            ContentMD5=_md5_b64(data),
        )
        return str(resp["ETag"])

    def complete_multipart(
        self, bucket: str, key: str, upload_id: str, etags: list[str]
    ) -> str | None:
        resp = self._s3.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=upload_id,
            MultipartUpload={"Parts": [{"ETag": e, "PartNumber": i + 1} for i, e in enumerate(etags)]},
        )
        version = resp.get("VersionId")
        return str(version) if version else None

    def abort_multipart(self, bucket: str, key: str, upload_id: str) -> None:
        self._s3.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)

    def put_bytes(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self._s3.put_object(
            Bucket=bucket, Key=key, Body=data, ContentType=content_type,
            ContentMD5=_md5_b64(data), ServerSideEncryption="AES256",
        )

    def copy(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> None:
        # Server-side copy; originals are limited to 4 GiB, below the 5 GiB copy limit.
        self._s3.copy_object(
            Bucket=dst_bucket, Key=dst_key, CopySource={"Bucket": src_bucket, "Key": src_key},
            ServerSideEncryption="AES256",
        )

    # --- reads -------------------------------------------------------------------

    def get_bytes(self, bucket: str, key: str) -> bytes:
        return bytes(self._s3.get_object(Bucket=bucket, Key=key)["Body"].read())

    def iter_object(self, bucket: str, key: str, version_id: str | None = None) -> Iterator[bytes]:
        kwargs: dict[str, str] = {"Bucket": bucket, "Key": key}
        if version_id:
            kwargs["VersionId"] = version_id
        body = self._s3.get_object(**kwargs)["Body"]
        try:
            yield from body.iter_chunks(READ_CHUNK)
        finally:
            body.close()

    def download_to(self, bucket: str, key: str, path: Path) -> None:
        with path.open("wb") as fh:
            for chunk in self.iter_object(bucket, key):
                fh.write(chunk)

    def exists(self, bucket: str, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._s3.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError:
            return False

    def delete(self, bucket: str, key: str) -> None:
        if bucket == self._settings.bucket_originals:
            raise PermissionError("originals are never deleted by the application")
        self._s3.delete_object(Bucket=bucket, Key=key)

    def retention(self, bucket: str, key: str, version_id: str | None) -> dict[str, str] | None:
        from botocore.exceptions import ClientError

        kwargs: dict[str, str] = {"Bucket": bucket, "Key": key}
        if version_id:
            kwargs["VersionId"] = version_id
        try:
            r = self._s3.get_object_retention(**kwargs)["Retention"]
            return {"mode": str(r["Mode"]), "retain_until": r["RetainUntilDate"].isoformat()}
        except ClientError:
            return None


@dataclass
class MemoryStore:
    """In-process store for tests. NOT immutable: tests use it to simulate tampering."""

    objects: dict[tuple[str, str], bytes] = field(default_factory=dict)
    _parts: dict[str, dict[int, bytes]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def ensure_buckets(self) -> None:
        return None

    def start_multipart(self, bucket: str, key: str, content_type: str) -> str:
        upload_id = f"{bucket}/{key}/{len(self._parts)}"
        self._parts[upload_id] = {}
        return upload_id

    def upload_part(self, bucket: str, key: str, upload_id: str, number: int, data: bytes) -> str:
        self._parts[upload_id][number] = data
        return hashlib.md5(data, usedforsecurity=False).hexdigest()

    def complete_multipart(
        self, bucket: str, key: str, upload_id: str, etags: list[str]
    ) -> str | None:
        parts = self._parts.pop(upload_id)
        self.objects[(bucket, key)] = b"".join(parts[i] for i in sorted(parts))
        return "v1"

    def abort_multipart(self, bucket: str, key: str, upload_id: str) -> None:
        self._parts.pop(upload_id, None)

    def put_bytes(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        with self._lock:
            self.objects[(bucket, key)] = data

    def get_bytes(self, bucket: str, key: str) -> bytes:
        try:
            return self.objects[(bucket, key)]
        except KeyError as exc:
            raise FileNotFoundError(f"{bucket}/{key}") from exc

    def iter_object(self, bucket: str, key: str, version_id: str | None = None) -> Iterator[bytes]:
        data = self.get_bytes(bucket, key)
        for i in range(0, len(data), READ_CHUNK):
            yield data[i : i + READ_CHUNK]

    def download_to(self, bucket: str, key: str, path: Path) -> None:
        path.write_bytes(self.get_bytes(bucket, key))

    def copy(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> None:
        self.objects[(dst_bucket, dst_key)] = self.get_bytes(src_bucket, src_key)

    def exists(self, bucket: str, key: str) -> bool:
        return (bucket, key) in self.objects

    def delete(self, bucket: str, key: str) -> None:
        if bucket == get_settings().bucket_originals:
            raise PermissionError("originals are never deleted by the application")
        self.objects.pop((bucket, key), None)

    def retention(self, bucket: str, key: str, version_id: str | None) -> dict[str, str] | None:
        return {"mode": "TEST (in-memory store)", "retain_until": "n/a"} if (bucket, key) in self.objects else None


_memory_store = MemoryStore()


@lru_cache
def _s3_store() -> S3Store:
    return S3Store(get_settings())


def get_store() -> ObjectStore:
    if get_settings().storage_backend == "memory":
        return _memory_store
    return _s3_store()


def original_key(case_id: object, evidence_id: object) -> str:
    """Storage keys never contain user-supplied filenames."""
    return f"cases/{case_id}/{evidence_id}/original"


def working_key(case_id: object, evidence_id: object, copy_id: object) -> str:
    return f"cases/{case_id}/{evidence_id}/working/{copy_id}"


def artefact_key(case_id: object, evidence_id: object, finding_id: object, name: str) -> str:
    return f"{case_id}/{evidence_id}/{finding_id}/{name}"
