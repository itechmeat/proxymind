from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from qdrant_client import models

from app.services.sparse_providers import (
    Bm25SparseProvider,
    ExternalBgeM3SparseProvider,
    SparseProviderMetadata,
    build_sparse_provider,
)


@pytest.mark.asyncio
async def test_bm25_provider_builds_qdrant_document() -> None:
    provider = Bm25SparseProvider(language="english")

    result = await provider.build_document_representation("hello world")

    assert isinstance(result, models.Document)
    assert result.model == "Qdrant/bm25"
    assert result.text == "hello world"


@pytest.mark.asyncio
async def test_bge_m3_provider_posts_texts_to_external_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://sparse/sparse/queries"
        assert request.url.path == "/sparse/queries"
        assert request.content == b'{"text":"hello"}'
        return httpx.Response(200, json={"indices": [1], "values": [0.5]})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = ExternalBgeM3SparseProvider(base_url="http://sparse/", client=client)
        result = await provider.build_query_representation("hello")

    assert result.indices == [1]
    assert result.values == [0.5]


@pytest.mark.asyncio
async def test_bge_m3_provider_preserves_base_url_path_prefix_for_owned_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://sparse/api/sparse/queries"
        assert request.url.path == "/api/sparse/queries"
        return httpx.Response(200, json={"indices": [1], "values": [0.5]})

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def build_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        return original_async_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr("app.services.sparse_providers.httpx.AsyncClient", build_client)

    provider = ExternalBgeM3SparseProvider(base_url="http://sparse/api")
    try:
        result = await provider.build_query_representation("hello")
    finally:
        await provider.aclose()

    assert result.indices == [1]
    assert result.values == [0.5]


@pytest.mark.asyncio
async def test_bge_m3_provider_rejects_invalid_payload() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"indices": [1], "values": [0.5, 0.7]})
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://sparse") as client:
        provider = ExternalBgeM3SparseProvider(base_url="http://sparse", client=client)
        with pytest.raises(ValueError, match="same length"):
            await provider.build_document_representation("hello")


@pytest.mark.asyncio
async def test_bge_m3_provider_rejects_non_numeric_sparse_payload() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"indices": ["bad"], "values": [0.5]})
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://sparse") as client:
        provider = ExternalBgeM3SparseProvider(base_url="http://sparse", client=client)
        with pytest.raises(ValueError, match="non-negative integers"):
            await provider.build_document_representation("hello")


@pytest.mark.asyncio
async def test_bge_m3_provider_rejects_non_finite_sparse_values() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=b'{"indices": [1], "values": [Infinity]}',
            headers={"content-type": "application/json"},
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://sparse") as client:
        provider = ExternalBgeM3SparseProvider(base_url="http://sparse", client=client)
        with pytest.raises(ValueError, match="finite numeric items"):
            await provider.build_document_representation("hello")


def test_build_sparse_provider_returns_bm25_provider_by_default() -> None:
    settings = SimpleNamespace(
        sparse_backend="bm25",
        bm25_language="english",
        bge_m3_provider_url=None,
        bge_m3_model_name="bge-m3",
        bge_m3_timeout_seconds=10.0,
    )

    provider = build_sparse_provider(settings)

    assert provider.metadata == SparseProviderMetadata(
        backend="bm25",
        model_name="Qdrant/bm25",
        contract_version="v1",
    )


def test_build_sparse_provider_returns_external_provider() -> None:
    settings = SimpleNamespace(
        sparse_backend="bge_m3",
        bm25_language="english",
        bge_m3_provider_url="http://sparse",
        bge_m3_model_name="bge-m3-large",
        bge_m3_timeout_seconds=4.0,
    )

    provider = build_sparse_provider(settings)

    assert provider.metadata == SparseProviderMetadata(
        backend="bge_m3",
        model_name="bge-m3-large",
        contract_version="v1",
    )
