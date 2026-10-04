"""Object-storage port (ADR-005): S3 API everywhere, presigned URLs for every download.

``S3ObjectStorage`` is the ONLY file allowed to import boto3 (mirror of the auth module's
Firebase confinement, ADR-011). The sync SDK runs off the event loop via
``asyncio.to_thread``; every SDK error is mapped to ``StorageUnavailableError`` so no
provider detail ever reaches a client or a log (docs/SECURITY.md).
"""

import asyncio
import re
from abc import ABC, abstractmethod
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings
from app.modules.records.errors import StorageUnavailableError

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(filename: str) -> str:
    """ASCII-safe filename for the Content-Disposition of a presigned download.

    The original name is preserved in the DB; this only guards the HTTP header
    (header injection, exotic encodings). Falls back to ``document`` if nothing safe
    remains.
    """
    cleaned = _FILENAME_SAFE.sub("_", filename).strip("._")
    return cleaned or "document"


class ObjectStorage(ABC):
    @abstractmethod
    async def put_object(self, key: str, data: bytes, *, content_type: str) -> None:
        """Store ``data`` under ``key``. Raises ``StorageUnavailableError`` on failure."""

    @abstractmethod
    async def get_object(self, key: str) -> bytes:
        """Retrieve object data by key. Raises ``StorageUnavailableError`` on failure."""

    @abstractmethod
    async def create_download_url(
        self, key: str, *, expires_in_seconds: int, filename: str, content_type: str
    ) -> str:
        """Short-lived presigned GET URL (docs/SECURITY.md: minutes, issued only after
        the authorization check). Raises ``StorageUnavailableError`` on failure."""


class S3ObjectStorage(ObjectStorage):
    """MinIO locally, real S3 in production — identical code path (ADR-005).

    The client is created lazily on first use so the API boots without object storage
    (same posture as the DB engine and the auth provider).
    """

    def __init__(self, settings: Settings) -> None:
        self._endpoint_url = settings.s3_endpoint_url
        self._access_key = settings.s3_access_key
        self._secret_key = settings.s3_secret_key
        self._region = settings.s3_region
        self._bucket = settings.s3_bucket_records
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint_url,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                region_name=self._region,
                # SigV4 is required for presigned URLs against MinIO.
                config=BotoConfig(signature_version="s3v4"),
            )
        return self._client

    async def put_object(self, key: str, data: bytes, *, content_type: str) -> None:
        def _put() -> None:
            self._get_client().put_object(
                Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
            )

        try:
            await asyncio.to_thread(_put)
        except (BotoCoreError, ClientError) as exc:
            raise StorageUnavailableError() from exc

    async def get_object(self, key: str) -> bytes:
        def _get() -> bytes:
            response = self._get_client().get_object(
                Bucket=self._bucket,
                Key=key,
            )
            return response["Body"].read()

        try:
            return await asyncio.to_thread(_get)
        except (BotoCoreError, ClientError) as exc:
            raise StorageUnavailableError() from exc

    async def create_download_url(
        self, key: str, *, expires_in_seconds: int, filename: str, content_type: str
    ) -> str:
        def _presign() -> str:
            url: str = self._get_client().generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    "ResponseContentType": content_type,
                    "ResponseContentDisposition": (
                        f'attachment; filename="{sanitize_filename(filename)}"'
                    ),
                },
                ExpiresIn=expires_in_seconds,
            )
            return url

        try:
            return await asyncio.to_thread(_presign)
        except (BotoCoreError, ClientError) as exc:
            raise StorageUnavailableError() from exc
