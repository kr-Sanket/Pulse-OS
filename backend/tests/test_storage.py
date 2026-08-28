"""Object-storage port tests: filename hygiene, the fake, and the S3 adapter with the
SDK fully mocked — tests never contact MinIO/S3 (docs/SYSTEM_ARCHITECTURE.md rule 4)."""

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from app.core.config import Settings
from app.modules.records.errors import StorageUnavailableError
from app.modules.records.fake import FakeObjectStorage
from app.modules.records.storage import S3ObjectStorage, sanitize_filename
from botocore.exceptions import ClientError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("CBC Report (final).pdf", "CBC_Report_final_.pdf"),
        ('bad"quote\r\nheader.pdf', "bad_quote_header.pdf"),
        ("../../etc/passwd", "etc_passwd"),
        ("रक्त-रिपोर्ट.pdf", "-_.pdf"),
        ("", "document"),
        ("...", "document"),
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_fake_storage_stores_and_presigns() -> None:
    async def scenario() -> None:
        storage = FakeObjectStorage()
        await storage.put_object("records/p/r", b"%PDF-", content_type="application/pdf")
        assert storage.objects["records/p/r"].data == b"%PDF-"
        assert storage.objects["records/p/r"].content_type == "application/pdf"

        url = await storage.create_download_url(
            "records/p/r",
            expires_in_seconds=300,
            filename="a b.pdf",
            content_type="application/pdf",
        )
        assert "records/p/r" in url and "expires=300" in url

    asyncio.run(scenario())


def test_fake_storage_failure_injection() -> None:
    async def scenario() -> None:
        storage = FakeObjectStorage()
        storage.storage_error = StorageUnavailableError()
        with pytest.raises(StorageUnavailableError):
            await storage.put_object("k", b"x", content_type="application/pdf")
        with pytest.raises(StorageUnavailableError):
            await storage.create_download_url(
                "k", expires_in_seconds=300, filename="f", content_type="application/pdf"
            )

    asyncio.run(scenario())


def _s3(client: MagicMock) -> S3ObjectStorage:
    storage = S3ObjectStorage(Settings())
    with patch("app.modules.records.storage.boto3") as boto3_mock:
        boto3_mock.client.return_value = client
        # Force lazy init through the mocked SDK.
        storage._get_client()
    return storage


def test_s3_put_object_sends_bucket_key_body_and_content_type() -> None:
    async def scenario() -> None:
        client = MagicMock()
        storage = _s3(client)
        await storage.put_object("records/p/r", b"%PDF-", content_type="application/pdf")
        client.put_object.assert_called_once_with(
            Bucket="pulseos-records",
            Key="records/p/r",
            Body=b"%PDF-",
            ContentType="application/pdf",
        )

    asyncio.run(scenario())


def test_s3_presign_includes_ttl_disposition_and_content_type() -> None:
    async def scenario() -> None:
        client = MagicMock()
        client.generate_presigned_url.return_value = "https://minio/presigned"
        storage = _s3(client)
        url = await storage.create_download_url(
            "records/p/r",
            expires_in_seconds=300,
            filename='CBC "final".pdf',
            content_type="application/pdf",
        )
        assert url == "https://minio/presigned"
        kwargs: dict[str, Any] = client.generate_presigned_url.call_args.kwargs
        assert kwargs["ExpiresIn"] == 300
        params = kwargs["Params"]
        assert params["Bucket"] == "pulseos-records"
        assert params["Key"] == "records/p/r"
        assert params["ResponseContentType"] == "application/pdf"
        # The sanitized name can never break out of the quoted header value.
        assert params["ResponseContentDisposition"] == 'attachment; filename="CBC_final_.pdf"'

    asyncio.run(scenario())


def test_s3_errors_map_to_domain_error_without_sdk_detail() -> None:
    async def scenario() -> None:
        client = MagicMock()
        client.put_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "secret-internal-detail"}}, "PutObject"
        )
        storage = _s3(client)
        with pytest.raises(StorageUnavailableError) as excinfo:
            await storage.put_object("k", b"x", content_type="application/pdf")
        assert "secret-internal-detail" not in str(excinfo.value)

    asyncio.run(scenario())


def test_s3_client_is_created_lazily_and_reused() -> None:
    storage = S3ObjectStorage(Settings())
    assert storage._client is None
    with patch("app.modules.records.storage.boto3") as boto3_mock:
        boto3_mock.client.return_value = MagicMock()
        first = storage._get_client()
        second = storage._get_client()
        assert first is second
        boto3_mock.client.assert_called_once()
