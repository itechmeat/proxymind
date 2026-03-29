from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

import app.api.admin_eval as admin_eval_module
from app.api.dependencies import get_context_assembler
from app.api.admin_eval import router as eval_router
from app.db.session import get_session
from app.services.llm_types import LLMResponse
from app.services.query_rewrite import RewriteResult
from app.services.qdrant import RetrievedChunk

TEST_ADMIN_KEY = "test-admin-key"
SOURCE_ID = uuid.uuid4()
CHUNK_ID = uuid.uuid4()
SNAPSHOT_ID = uuid.uuid4()


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(eval_router)
    app.state.settings = SimpleNamespace(
        admin_api_key=TEST_ADMIN_KEY,
        retrieval_top_n=5,
        min_retrieved_chunks=1,
        max_citations_per_response=5,
        llm_model="openai/gpt-4o",
    )
    app.state.retrieval_service = SimpleNamespace(search=AsyncMock(return_value=[]))
    app.state.query_rewrite_service = SimpleNamespace(
        rewrite=AsyncMock(
            return_value=RewriteResult(
                query="refund policy",
                is_rewritten=False,
                original_query="refund policy",
            )
        )
    )
    app.state.llm_service = SimpleNamespace(
        complete=AsyncMock(
            return_value=LLMResponse(
                content="Assistant answer [source:1]",
                model_name="openai/gpt-4o",
                token_count_prompt=10,
                token_count_completion=5,
            )
        )
    )
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
async def app() -> FastAPI:
    app = _make_app()
    app.dependency_overrides[get_context_assembler] = lambda: SimpleNamespace(
        assemble=lambda **kwargs: SimpleNamespace(
            messages=[{"role": "user", "content": "assembled prompt"}],
            retrieval_chunks_used=1,
            catalog_items_used=[],
            included_promotions=[],
        )
    )
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    return app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_retrieve_success_returns_expected_shape(
    client: httpx.AsyncClient,
    app: FastAPI,
) -> None:
    app.state.retrieval_service.search = AsyncMock(return_value=[_make_chunk()])

    response = await client.post(
        "/api/admin/eval/retrieve",
        headers={"Authorization": f"Bearer {TEST_ADMIN_KEY}"},
        json={"query": "  refund policy  ", "snapshot_id": str(SNAPSHOT_ID)},
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
    app.state.retrieval_service.search.assert_awaited_once_with(
        "refund policy",
        snapshot_id=SNAPSHOT_ID,
        top_n=5,
    )


@pytest.mark.asyncio
async def test_retrieve_custom_top_n(client: httpx.AsyncClient, app: FastAPI) -> None:
    app.state.retrieval_service.search = AsyncMock(return_value=[_make_chunk()])

    response = await client.post(
        "/api/admin/eval/retrieve",
        headers={"Authorization": f"Bearer {TEST_ADMIN_KEY}"},
        json={"query": "q", "snapshot_id": str(SNAPSHOT_ID), "top_n": 10},
    )

    assert response.status_code == 200
    app.state.retrieval_service.search.assert_awaited_once_with(
        "q",
        snapshot_id=SNAPSHOT_ID,
        top_n=10,
    )


@pytest.mark.asyncio
async def test_retrieve_empty_results_are_valid(client: httpx.AsyncClient, app: FastAPI) -> None:
    app.state.retrieval_service.search = AsyncMock(return_value=[])

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
async def test_retrieve_returns_fewer_chunks_than_requested(
    client: httpx.AsyncClient,
    app: FastAPI,
) -> None:
    app.state.retrieval_service.search = AsyncMock(
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
async def test_retrieve_maps_search_failures_to_json_500(
    client: httpx.AsyncClient,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger_spy = Mock()
    monkeypatch.setattr(admin_eval_module.logger, "exception", logger_spy)
    app.state.retrieval_service.search = AsyncMock(
        side_effect=RuntimeError("retrieval failed")
    )

    response = await client.post(
        "/api/admin/eval/retrieve",
        headers={"Authorization": f"Bearer {TEST_ADMIN_KEY}"},
        json={"query": "refund", "snapshot_id": str(SNAPSHOT_ID)},
    )

    assert response.status_code == 500
    assert response.json() == {"error": "Internal server error"}
    logger_spy.assert_called_once()
    assert logger_spy.call_args.args[0] == "Eval retrieve failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"snapshot_id": str(SNAPSHOT_ID)},
        {"query": "", "snapshot_id": str(SNAPSHOT_ID)},
        {"query": "   ", "snapshot_id": str(SNAPSHOT_ID)},
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


@pytest.mark.asyncio
async def test_generate_success_returns_expected_shape(
    client: httpx.AsyncClient,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.state.retrieval_service.search = AsyncMock(return_value=[_make_chunk()])
    app.state.query_rewrite_service.rewrite = AsyncMock(
        return_value=RewriteResult(
            query="refund policy",
            is_rewritten=True,
            original_query="refunds?",
        )
    )
    monkeypatch.setattr(admin_eval_module, "load_source_map", AsyncMock(return_value={}))

    response = await client.post(
        "/api/admin/eval/generate",
        headers={"Authorization": f"Bearer {TEST_ADMIN_KEY}"},
        json={"query": "  refunds?  ", "snapshot_id": str(SNAPSHOT_ID)},
    )

    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {
        "answer",
        "citations",
        "retrieved_chunks",
        "rewritten_query",
        "timing_ms",
        "model",
    }
    assert data["answer"] == "Assistant answer [source:1]"
    assert data["rewritten_query"] == "refund policy"
    assert data["model"] == "openai/gpt-4o"
    assert len(data["retrieved_chunks"]) == 1
    app.state.retrieval_service.search.assert_awaited_once_with(
        "refund policy",
        snapshot_id=SNAPSHOT_ID,
        top_n=5,
    )


@pytest.mark.asyncio
async def test_generate_returns_refusal_when_not_enough_chunks(
    client: httpx.AsyncClient,
    app: FastAPI,
) -> None:
    app.state.retrieval_service.search = AsyncMock(return_value=[])

    response = await client.post(
        "/api/admin/eval/generate",
        headers={"Authorization": f"Bearer {TEST_ADMIN_KEY}"},
        json={"query": "refund", "snapshot_id": str(SNAPSHOT_ID)},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["retrieved_chunks"] == []
    assert data["citations"] == []
    assert isinstance(data["answer"], str)


@pytest.mark.asyncio
async def test_generate_maps_failures_to_json_500(
    client: httpx.AsyncClient,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger_spy = Mock()
    monkeypatch.setattr(admin_eval_module.logger, "exception", logger_spy)
    app.state.query_rewrite_service.rewrite = AsyncMock(side_effect=RuntimeError("rewrite failed"))

    response = await client.post(
        "/api/admin/eval/generate",
        headers={"Authorization": f"Bearer {TEST_ADMIN_KEY}"},
        json={"query": "refund", "snapshot_id": str(SNAPSHOT_ID)},
    )

    assert response.status_code == 500
    assert response.json() == {"error": "Internal server error"}
    logger_spy.assert_called_once()
    assert logger_spy.call_args.args[0] == "Eval generate failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"snapshot_id": str(SNAPSHOT_ID)},
        {"query": "", "snapshot_id": str(SNAPSHOT_ID)},
        {"query": "   ", "snapshot_id": str(SNAPSHOT_ID)},
    ],
)
async def test_generate_rejects_missing_or_empty_query(
    client: httpx.AsyncClient,
    payload: dict[str, object],
) -> None:
    response = await client.post(
        "/api/admin/eval/generate",
        headers={"Authorization": f"Bearer {TEST_ADMIN_KEY}"},
        json=payload,
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_generate_requires_bearer_auth(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/admin/eval/generate",
        json={"query": "refund", "snapshot_id": str(SNAPSHOT_ID)},
    )

    assert response.status_code == 401
