from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.db.models.enums import BatchStatus
from app.services.batch_embedding import (
    BatchEmbeddingClient,
    BatchEmbeddingRequest,
    map_gemini_state,
)


class FakeBatches:
    def __init__(self, *, create_response: object, get_responses: list[object]) -> None:
        self._create_response = create_response
        self._get_responses = list(get_responses)
        self.create_calls: list[dict[str, object]] = []
        self.get_calls: list[str] = []

    def create_embeddings(self, *, model: str, src: object, config: object) -> object:
        self.create_calls.append({"model": model, "src": src, "config": config})
        if isinstance(self._create_response, Exception):
            raise self._create_response
        return self._create_response

    def get(self, *, name: str, config: object | None = None) -> object:
        self.get_calls.append(name)
        response = self._get_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _batch_job(
    *,
    state: str,
    responses: list[object] | None = None,
    error_message: str | None = None,
    include_completion_stats: bool = True,
):
    return SimpleNamespace(
        name="batches/123",
        state=SimpleNamespace(value=state),
        error=SimpleNamespace(message=error_message) if error_message else None,
        completion_stats=(
            SimpleNamespace(successful_count=1, failed_count=0)
            if include_completion_stats
            else None
        ),
        dest=SimpleNamespace(inlined_embed_content_responses=responses),
    )


@pytest.mark.asyncio
async def test_create_embedding_batch_returns_operation_name() -> None:
    batches = FakeBatches(create_response=SimpleNamespace(name="batches/123"), get_responses=[])
    client = BatchEmbeddingClient(
        model="gemini-embedding-2-preview",
        dimensions=2,
        embedding_task_type="CLASSIFICATION",
        client=SimpleNamespace(batches=batches),  # type: ignore[arg-type]
    )

    operation_name = await client.create_embedding_batch(
        [BatchEmbeddingRequest(chunk_id=uuid.uuid7(), text="hello")]
    )

    assert operation_name == "batches/123"
    assert batches.create_calls[0]["model"] == "gemini-embedding-2-preview"
    batch_src = batches.create_calls[0]["src"]
    assert batch_src.inlined_requests.config.task_type == "CLASSIFICATION"


@pytest.mark.asyncio
async def test_get_batch_status_maps_gemini_state() -> None:
    batches = FakeBatches(
        create_response=SimpleNamespace(name="batches/123"),
        get_responses=[_batch_job(state="JOB_STATE_RUNNING", include_completion_stats=False)],
    )
    client = BatchEmbeddingClient(
        model="gemini-embedding-2-preview",
        dimensions=2,
        client=SimpleNamespace(batches=batches),  # type: ignore[arg-type]
    )

    status = await client.get_batch_status("batches/123")

    assert status.status is BatchStatus.PROCESSING
    assert status.operation_name == "batches/123"
    assert status.succeeded_count == 0
    assert status.failed_count == 0


@pytest.mark.asyncio
async def test_get_batch_results_validates_response_count_and_dimensions() -> None:
    responses = [
        SimpleNamespace(
            response=SimpleNamespace(embedding=SimpleNamespace(values=[0.1, 0.2])),
            error=None,
        ),
        SimpleNamespace(response=None, error=SimpleNamespace(message="bad row")),
    ]
    batches = FakeBatches(
        create_response=SimpleNamespace(name="batches/123"),
        get_responses=[_batch_job(state="JOB_STATE_SUCCEEDED", responses=responses)],
    )
    client = BatchEmbeddingClient(
        model="gemini-embedding-2-preview",
        dimensions=2,
        client=SimpleNamespace(batches=batches),  # type: ignore[arg-type]
    )

    items = await client.get_batch_results("batches/123", expected_count=2)

    assert items[0].embedding == [0.1, 0.2]
    assert items[0].error_message is None
    assert items[1].embedding is None
    assert items[1].error_message == "bad row"


def test_map_gemini_state_covers_expected_values() -> None:
    assert map_gemini_state(None) is BatchStatus.PROCESSING
    assert map_gemini_state("JOB_STATE_UNSPECIFIED") is BatchStatus.PROCESSING
    assert map_gemini_state("JOB_STATE_PENDING") is BatchStatus.PROCESSING
    assert map_gemini_state("JOB_STATE_PAUSED") is BatchStatus.PROCESSING
    assert map_gemini_state("JOB_STATE_RUNNING") is BatchStatus.PROCESSING
    assert map_gemini_state("JOB_STATE_SUCCEEDED") is BatchStatus.COMPLETE
    assert map_gemini_state("JOB_STATE_FAILED") is BatchStatus.FAILED
    assert map_gemini_state("JOB_STATE_EXPIRED") is BatchStatus.FAILED
    assert map_gemini_state("JOB_STATE_CANCELLED") is BatchStatus.CANCELLED
