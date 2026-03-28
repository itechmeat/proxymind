from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.api.admin_eval import router as eval_router
from app.services.qdrant import RetrievedChunk

TEST_ADMIN_KEY = "test-admin-key"
SOURCE_ID = uuid.uuid4()
CHUNK_ID = uuid.uuid4()
SNAPSHOT_ID = uuid.uuid4()


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(eval_router)
    app.state.settings = SimpleNamespace(admin_api_key=TEST_ADMIN_KEY)
    app.state.retrieval_service = SimpleNamespace(search=AsyncMock(return_value=[]))
    return app


def _make_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=CHUNK_ID,
        source_id=SOURCE_ID,
        text_content="This is chunk text about refund policy",
        score=0.92,
        anchor_metadata={"anchor_page": 1},
    )


@pytest_asyncio.fixture
async def client() -> httpx.AsyncClient:
    app = _make_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_retrieve_success_returns_expected_shape(client: httpx.AsyncClient) -> None:
    client._transport.app.state.retrieval_service.search = AsyncMock(return_value=[_make_chunk()])

    response = await client.post(
        "/api/admin/eval/retrieve",
        headers={"Authorization": f"Bearer {TEST_ADMIN_KEY}"},
        json={"query": "refund policy", "snapshot_id": str(SNAPSHOT_ID)},
    )

    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"chunks", "timing_ms"}
    assert len(data["chunks"]) == 1
    assert set(data["chunks"][0].keys()) == {"chunk_id", "source_id", "score", "text", "rank"}
    assert data["chunks"][0]["chunk_id"] == str(CHUNK_ID)
    assert data["chunks"][0]["source_id"] == str(SOURCE_ID)
    assert data["chunks"][0]["text"] == "This is chunk text about refund policy"
    assert data["chunks"][0]["rank"] == 1
    assert data["chunks"][0]["score"] == 0.92
    client._transport.app.state.retrieval_service.search.assert_awaited_once_with(
        "refund policy",
        snapshot_id=SNAPSHOT_ID,
        top_n=5,
    )


@pytest.mark.asyncio
async def test_retrieve_custom_top_n(client: httpx.AsyncClient) -> None:
    client._transport.app.state.retrieval_service.search = AsyncMock(return_value=[_make_chunk()])

    response = await client.post(
        "/api/admin/eval/retrieve",
        headers={"Authorization": f"Bearer {TEST_ADMIN_KEY}"},
        json={"query": "q", "snapshot_id": str(SNAPSHOT_ID), "top_n": 10},
    )

    assert response.status_code == 200
    client._transport.app.state.retrieval_service.search.assert_awaited_once_with(
        "q",
        snapshot_id=SNAPSHOT_ID,
        top_n=10,
    )


@pytest.mark.asyncio
async def test_retrieve_empty_results_are_valid(client: httpx.AsyncClient) -> None:
    client._transport.app.state.retrieval_service.search = AsyncMock(return_value=[])

    response = await client.post(
        "/api/admin/eval/retrieve",
        headers={"Authorization": f"Bearer {TEST_ADMIN_KEY}"},
        json={"query": "refund", "snapshot_id": str(SNAPSHOT_ID)},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["chunks"] == []
    assert isinstance(data["timing_ms"], float)


@pytest.mark.asyncio
async def test_retrieve_returns_fewer_chunks_than_requested(client: httpx.AsyncClient) -> None:
    client._transport.app.state.retrieval_service.search = AsyncMock(
        return_value=[_make_chunk(), _make_chunk(), _make_chunk()]
    )

    response = await client.post(
        "/api/admin/eval/retrieve",
        headers={"Authorization": f"Bearer {TEST_ADMIN_KEY}"},
        json={"query": "refund", "snapshot_id": str(SNAPSHOT_ID), "top_n": 10},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["chunks"]) == 3
    assert [chunk["rank"] for chunk in data["chunks"]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_retrieve_maps_search_failures_to_json_500(client: httpx.AsyncClient) -> None:
    client._transport.app.state.retrieval_service.search = AsyncMock(
        side_effect=RuntimeError("retrieval failed")
    )

    response = await client.post(
        "/api/admin/eval/retrieve",
        headers={"Authorization": f"Bearer {TEST_ADMIN_KEY}"},
        json={"query": "refund", "snapshot_id": str(SNAPSHOT_ID)},
    )

    assert response.status_code == 500
    assert response.json() == {"error": "retrieval failed"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"snapshot_id": str(SNAPSHOT_ID)},
        {"query": "", "snapshot_id": str(SNAPSHOT_ID)},
    ],
)
async def test_retrieve_rejects_missing_or_empty_query(
    client: httpx.AsyncClient,
    payload: dict[str, object],
) -> None:
    response = await client.post(
        "/api/admin/eval/retrieve",
        headers={"Authorization": f"Bearer {TEST_ADMIN_KEY}"},
        json=payload,
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_retrieve_rejects_invalid_snapshot_id(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/admin/eval/retrieve",
        headers={"Authorization": f"Bearer {TEST_ADMIN_KEY}"},
        json={"query": "refund", "snapshot_id": "not-a-uuid"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("top_n", [0, 51])
async def test_retrieve_rejects_out_of_range_top_n(client: httpx.AsyncClient, top_n: int) -> None:
    response = await client.post(
        "/api/admin/eval/retrieve",
        headers={"Authorization": f"Bearer {TEST_ADMIN_KEY}"},
        json={"query": "refund", "snapshot_id": str(SNAPSHOT_ID), "top_n": top_n},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_retrieve_requires_bearer_auth(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/admin/eval/retrieve",
        json={"query": "refund", "snapshot_id": str(SNAPSHOT_ID)},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_retrieve_rejects_invalid_bearer_token(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/admin/eval/retrieve",
        headers={"Authorization": "Bearer wrong-key"},
        json={"query": "refund", "snapshot_id": str(SNAPSHOT_ID)},
    )

    assert response.status_code == 401
