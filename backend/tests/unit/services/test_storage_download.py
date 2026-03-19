from __future__ import annotations

import pytest

from app.services.storage import StorageService


@pytest.mark.asyncio
async def test_download_returns_file_bytes() -> None:
    class FakeResponse:
        def __init__(self) -> None:
            self.closed = False
            self.released = False

        def read(self) -> bytes:
            return b"payload"

        def close(self) -> None:
            self.closed = True

        def release_conn(self) -> None:
            self.released = True

    response = FakeResponse()

    class FakeClient:
        def get_object(self, bucket_name: str, object_key: str) -> FakeResponse:
            assert bucket_name == "sources"
            assert object_key == "agent/source/doc.md"
            return response

    service = StorageService(FakeClient(), "sources")  # type: ignore[arg-type]

    content = await service.download("agent/source/doc.md")

    assert content == b"payload"
    assert response.closed is True
    assert response.released is True


@pytest.mark.asyncio
async def test_download_propagates_client_errors() -> None:
    class FakeClient:
        def get_object(self, bucket_name: str, object_key: str) -> bytes:
            raise FileNotFoundError(object_key)

    service = StorageService(FakeClient(), "sources")  # type: ignore[arg-type]

    with pytest.raises(FileNotFoundError, match="missing.md"):
        await service.download("missing.md")
