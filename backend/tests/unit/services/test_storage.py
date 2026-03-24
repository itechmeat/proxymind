from __future__ import annotations

import httpx
import pytest

from app.services.storage import StorageService


@pytest.mark.asyncio
async def test_ensure_storage_root_posts_directory_root() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/sources/"
        return httpx.Response(201)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://storage.local",
    ) as client:
        service = StorageService(client, "/sources/")
        await service.ensure_storage_root()


@pytest.mark.asyncio
async def test_ensure_storage_root_accepts_existing_directory() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/sources/"
        return httpx.Response(409, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://storage.local",
    ) as client:
        service = StorageService(client, "/sources/")
        await service.ensure_storage_root()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_path", "object_key", "expected_path"),
    [
        ("sources", "agent/source/doc.md", "/sources/agent/source/doc.md"),
        ("/sources", "agent/source/doc.md", "/sources/agent/source/doc.md"),
        ("sources/", "/agent/source/doc.md", "/sources/agent/source/doc.md"),
        ("/sources/", "/agent/source/doc.md", "/sources/agent/source/doc.md"),
    ],
)
async def test_upload_normalizes_base_path_and_object_key(
    base_path: str,
    object_key: str,
    expected_path: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == expected_path
        return httpx.Response(201)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://storage.local",
    ) as client:
        service = StorageService(client, base_path)
        await service.upload(object_key, b"payload", "text/markdown")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_path", "object_key", "expected_path"),
    [
        ("/", "", "/"),
        ("/", "file.txt", "/file.txt"),
        ("/", "/file.txt", "/file.txt"),
    ],
)
async def test_build_url_root_base_path_no_double_slash(
    base_path: str,
    object_key: str,
    expected_path: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == expected_path
        return httpx.Response(200, content=b"ok")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://storage.local",
    ) as client:
        service = StorageService(client, base_path)
        if object_key:
            await service.download(object_key)
        else:
            await service.ensure_storage_root()


@pytest.mark.asyncio
async def test_upload_posts_multipart_content_to_filer_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/sources/agent/source/doc.md"
        assert request.headers["content-type"].startswith("multipart/form-data;")
        return httpx.Response(201)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://storage.local",
    ) as client:
        service = StorageService(client, "sources")
        await service.upload("agent/source/doc.md", b"payload", "text/markdown")


@pytest.mark.asyncio
async def test_upload_propagates_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://storage.local",
    ) as client:
        service = StorageService(client, "sources")
        with pytest.raises(httpx.HTTPStatusError):
            await service.upload("agent/source/doc.md", b"payload", "text/markdown")


@pytest.mark.asyncio
async def test_download_returns_file_bytes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/sources/agent/source/doc.md"
        return httpx.Response(200, content=b"payload")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://storage.local",
    ) as client:
        service = StorageService(client, "sources")
        content = await service.download("agent/source/doc.md")

    assert content == b"payload"


@pytest.mark.asyncio
async def test_delete_uses_filer_delete_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/sources/agent/source/doc.md"
        return httpx.Response(204)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://storage.local",
    ) as client:
        service = StorageService(client, "sources")
        await service.delete("agent/source/doc.md")


@pytest.mark.asyncio
async def test_download_propagates_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://storage.local",
    ) as client:
        service = StorageService(client, "sources")
        with pytest.raises(httpx.HTTPStatusError):
            await service.download("missing.md")
