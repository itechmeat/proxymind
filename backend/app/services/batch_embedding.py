from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.db.models.enums import BatchStatus


def _is_retryable_batch_error(error: BaseException) -> bool:
    return isinstance(error, genai_errors.ServerError) or (
        isinstance(error, genai_errors.ClientError) and error.code == 429
    )


def map_gemini_state(state: str | None) -> BatchStatus:
    if state in {
        "JOB_STATE_QUEUED",
        "JOB_STATE_PENDING",
        "JOB_STATE_RUNNING",
        "JOB_STATE_UPDATING",
    }:
        return BatchStatus.PROCESSING
    if state in {"JOB_STATE_SUCCEEDED", "JOB_STATE_PARTIALLY_SUCCEEDED"}:
        return BatchStatus.COMPLETE
    if state in {"JOB_STATE_CANCELLED", "JOB_STATE_CANCELLING"}:
        return BatchStatus.CANCELLED
    if state in {"JOB_STATE_FAILED", "JOB_STATE_EXPIRED"}:
        return BatchStatus.FAILED
    return BatchStatus.PROCESSING


@dataclass(slots=True, frozen=True)
class BatchEmbeddingRequest:
    chunk_id: uuid.UUID
    text: str


@dataclass(slots=True, frozen=True)
class BatchEmbeddingStatus:
    operation_name: str
    status: BatchStatus
    state: str | None
    error_message: str | None
    succeeded_count: int
    failed_count: int
    last_polled_at: datetime


@dataclass(slots=True, frozen=True)
class BatchEmbeddingResultItem:
    index: int
    embedding: list[float] | None
    error_message: str | None


class BatchEmbeddingClient:
    def __init__(
        self,
        *,
        model: str,
        dimensions: int,
        api_key: str | None = None,
        client: genai.Client | None = None,
    ) -> None:
        self._model = model
        self._dimensions = dimensions
        self._api_key = api_key
        self._client = client
        self._client_lock = threading.Lock()

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def create_embedding_batch(
        self,
        requests: Sequence[BatchEmbeddingRequest],
        *,
        display_name: str | None = None,
    ) -> str:
        if not requests:
            raise ValueError("Batch embedding requires at least one request")

        return await asyncio.to_thread(self._create_embedding_batch, list(requests), display_name)

    async def get_batch_status(self, operation_name: str) -> BatchEmbeddingStatus:
        batch_job = await asyncio.to_thread(self._get_batch_job, operation_name)
        state = batch_job.state.value if batch_job.state is not None else None
        stats = batch_job.completion_stats
        return BatchEmbeddingStatus(
            operation_name=operation_name,
            status=map_gemini_state(state),
            state=state,
            error_message=batch_job.error.message if batch_job.error is not None else None,
            succeeded_count=(
                stats.successful_count
                if stats and stats.successful_count is not None
                else 0
            ),
            failed_count=stats.failed_count if stats and stats.failed_count is not None else 0,
            last_polled_at=datetime.now(UTC),
        )

    async def get_batch_results(
        self,
        operation_name: str,
        *,
        expected_count: int,
    ) -> list[BatchEmbeddingResultItem]:
        batch_job = await asyncio.to_thread(self._get_batch_job, operation_name)
        responses = batch_job.dest.inlined_embed_content_responses if batch_job.dest else None
        if responses is None:
            raise ValueError("Gemini batch job returned no inline embedding responses")
        if len(responses) != expected_count:
            raise ValueError(
                "Gemini batch job returned an unexpected number of responses: "
                f"expected {expected_count}, got {len(responses)}"
            )

        items: list[BatchEmbeddingResultItem] = []
        for index, response in enumerate(responses):
            if response.error is not None:
                items.append(
                    BatchEmbeddingResultItem(
                        index=index,
                        embedding=None,
                        error_message=response.error.message,
                    )
                )
                continue

            embedding_response = response.response
            values = (
                list(embedding_response.embedding.values)
                if embedding_response and embedding_response.embedding
                else None
            )
            if values is None:
                items.append(
                    BatchEmbeddingResultItem(
                        index=index,
                        embedding=None,
                        error_message="Missing embedding in Gemini batch response",
                    )
                )
                continue
            if len(values) != self._dimensions:
                raise ValueError(
                    "Gemini batch embedding returned an unexpected dimensionality: "
                    f"expected {self._dimensions}, got {len(values)}"
                )
            items.append(
                BatchEmbeddingResultItem(
                    index=index,
                    embedding=values,
                    error_message=None,
                )
            )
        return items

    @retry(
        retry=retry_if_exception(_is_retryable_batch_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _create_embedding_batch(
        self,
        requests: list[BatchEmbeddingRequest],
        display_name: str | None,
    ) -> str:
        # Gemini batch embeddings currently accept one shared EmbedContentBatch with list contents.
        # The Python SDK surface does not expose per-item custom_id fields, so
        # correlation relies on stored chunk_ids order plus Gemini's documented
        # guarantee that inlined responses preserve input order.
        batch = types.EmbedContentBatch(
            contents=[request.text for request in requests],
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=self._dimensions,
            ),
        )
        batch_job = self._get_client().batches.create_embeddings(
            model=self._model,
            src=types.EmbeddingsBatchJobSource(inlined_requests=batch),
            config=types.CreateEmbeddingsBatchJobConfig(display_name=display_name),
        )
        if not batch_job.name:
            raise ValueError("Gemini batch API returned a batch job without a name")
        return batch_job.name

    @retry(
        retry=retry_if_exception(_is_retryable_batch_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _get_batch_job(self, operation_name: str) -> types.BatchJob:
        return self._get_client().batches.get(name=operation_name)

    def _get_client(self) -> genai.Client:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    if not self._api_key:
                        raise ValueError("GEMINI_API_KEY is required for batch embedding")
                    self._client = genai.Client(api_key=self._api_key)
        return self._client
