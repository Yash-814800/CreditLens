"""Storage abstraction (CLAUDE.md: files served only through the authenticated
API, never a public URL). LocalStorage is for dev/tests; S3Storage is what
STORAGE_BACKEND=s3 selects in production (Phase 9's EC2 deployment)."""

from __future__ import annotations

import contextlib
import uuid
from pathlib import Path
from typing import Protocol

import boto3
from botocore.exceptions import ClientError

from app.core import paths
from app.core.config import Settings


def object_key(application_id: uuid.UUID, filename_hint: str) -> str:
    """Generated storage key -- never the client-supplied filename (CLAUDE.md
    upload-validation rule: never trust client names)."""
    suffix = Path(filename_hint).suffix.lower()
    return f"applications/{application_id}/{uuid.uuid4()}{suffix}"


class StorageBackend(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def exists(self, key: str) -> bool: ...
    async def delete(self, key: str) -> None: ...


class LocalStorage:
    """Dev-only filesystem storage. Never used when STORAGE_BACKEND=s3."""

    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root) if root is not None else paths.data_dir() / "uploads"
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Reject any key that could escape the storage root (defense in depth --
        # object_key() above only ever generates safe keys, this guards the
        # protocol boundary against a future caller passing one through unchecked).
        resolved = (self._root / key).resolve()
        if not resolved.is_relative_to(self._root.resolve()):
            raise ValueError(f"storage key escapes storage root: {key!r}")
        return resolved

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()


class S3Storage:
    """Private, server-side-encrypted S3 storage. No public URLs are ever
    generated; every read goes through the authenticated API, which streams
    bytes from here directly to the client."""

    def __init__(self, bucket: str, region: str) -> None:
        if not bucket:
            raise ValueError("S3_BUCKET must be set when STORAGE_BACKEND=s3")
        self._bucket = bucket
        self._client = boto3.client("s3", region_name=region)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )

    async def get(self, key: str) -> bytes:
        try:
            obj = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            raise FileNotFoundError(key) from exc
        return obj["Body"].read()

    async def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError:
            return False
        return True

    async def delete(self, key: str) -> None:
        with contextlib.suppress(ClientError):
            self._client.delete_object(Bucket=self._bucket, Key=key)


def build_storage_backend(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "s3":
        return S3Storage(bucket=settings.s3_bucket, region=settings.aws_region)
    return LocalStorage()
