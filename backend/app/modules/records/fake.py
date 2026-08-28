"""In-memory object storage for tests and credential-free local development.

Fake implementations of external ports are first-class citizens
(docs/SYSTEM_ARCHITECTURE.md rule 4): tests must never contact MinIO/S3.
"""

from dataclasses import dataclass

from app.modules.records.errors import StorageUnavailableError
from app.modules.records.storage import ObjectStorage, sanitize_filename


@dataclass(frozen=True, slots=True)
class StoredObject:
    data: bytes
    content_type: str


class FakeObjectStorage(ObjectStorage):
    """Dict-backed storage; download URLs are inert but structurally realistic."""

    def __init__(self) -> None:
        #: Objects by key — assert on this.
        self.objects: dict[str, StoredObject] = {}
        #: Set to make every operation raise (storage-down tests).
        self.storage_error: StorageUnavailableError | None = None

    async def put_object(self, key: str, data: bytes, *, content_type: str) -> None:
        if self.storage_error is not None:
            raise self.storage_error
        self.objects[key] = StoredObject(data=data, content_type=content_type)

    async def create_download_url(
        self, key: str, *, expires_in_seconds: int, filename: str, content_type: str
    ) -> str:
        if self.storage_error is not None:
            raise self.storage_error
        return (
            f"https://fake-storage.local/{key}"
            f"?expires={expires_in_seconds}&filename={sanitize_filename(filename)}"
        )
