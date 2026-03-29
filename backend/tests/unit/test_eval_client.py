from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from evals.config import EvalConfig
from evals.models import GenerationResult, RetrievalResult


@pytest.fixture
def config() -> EvalConfig:
    return EvalConfig(base_url="http://localhost:8000", admin_key="test-key")


@pytest.mark.asyncio
async def test_retrieve_success(config: EvalConfig) -> None:
    from evals.client import EvalClient

    snapshot_id = uuid.uuid4()
    chunk_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "chunks": [
            {
                "chunk_id": chunk_id,
                "source_id": source_id,
                "score": 0.9,
                "text": "chunk text",
                "rank": 1,
            }
        ],
        "timing_ms": 50.0,
    }
    response.raise_for_status.return_value = None

    http_client = AsyncMock()
    http_client.post.return_value = response

    client = EvalClient(config=config, http_client=http_client)
    result = await client.retrieve("test query", snapshot_id=snapshot_id, top_n=5)

    assert isinstance(result, RetrievalResult)
    assert len(result.chunks) == 1
    assert result.chunks[0].rank == 1
    http_client.post.assert_awaited_once_with(
        "http://localhost:8000/api/admin/eval/retrieve",
        json={"query": "test query", "snapshot_id": str(snapshot_id), "top_n": 5},
        headers={"Authorization": "Bearer test-key"},
    )


@pytest.mark.asyncio
async def test_retrieve_api_error(config: EvalConfig) -> None:
    from evals.client import EvalClient, EvalClientError

    response = Mock()
    response.raise_for_status.side_effect = Exception("500 Server Error")
    http_client = AsyncMock()
    http_client.post.return_value = response

    client = EvalClient(config=config, http_client=http_client)
    with pytest.raises(EvalClientError):
        await client.retrieve("q", snapshot_id=uuid.uuid4(), top_n=5)


@pytest.mark.asyncio
async def test_retrieve_invalid_payload_error_is_wrapped(config: EvalConfig) -> None:
    from evals.client import EvalClient, EvalClientError

    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"timing_ms": 50.0}

    http_client = AsyncMock()
    http_client.post.return_value = response

    client = EvalClient(config=config, http_client=http_client)
    with pytest.raises(EvalClientError, match="Eval API request failed"):
        await client.retrieve("q", snapshot_id=uuid.uuid4(), top_n=5)


@pytest.mark.asyncio
async def test_generate_success(config: EvalConfig) -> None:
    from evals.client import EvalClient

    snapshot_id = uuid.uuid4()
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "answer": "The answer is X.",
        "citations": [],
        "retrieved_chunks": [],
        "rewritten_query": "What is X?",
        "timing_ms": 50.0,
        "model": "test-model",
    }
    response.raise_for_status.return_value = None

    http_client = AsyncMock()
    http_client.post.return_value = response

    client = EvalClient(config=config, http_client=http_client)
    result = await client.generate("test query", snapshot_id=snapshot_id)

    assert isinstance(result, GenerationResult)
    assert result.answer == "The answer is X."
    http_client.post.assert_awaited_once_with(
        "http://localhost:8000/api/admin/eval/generate",
        json={"query": "test query", "snapshot_id": str(snapshot_id)},
        headers={"Authorization": "Bearer test-key"},
    )


@pytest.mark.asyncio
async def test_generate_error_wrapped(config: EvalConfig) -> None:
    from evals.client import EvalClient, EvalClientError

    response = Mock()
    response.raise_for_status.side_effect = Exception("500 Server Error")
    http_client = AsyncMock()
    http_client.post.return_value = response

    client = EvalClient(config=config, http_client=http_client)
    with pytest.raises(EvalClientError, match="Eval generate request failed"):
        await client.generate("q", snapshot_id=uuid.uuid4())
