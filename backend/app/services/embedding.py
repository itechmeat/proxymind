from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


def _is_retryable_embedding_error(error: BaseException) -> bool:
    return isinstance(error, genai_errors.ServerError) or (
        isinstance(error, genai_errors.ClientError) and error.code == 429
    )


class EmbeddingService:
    def __init__(
        self,
        *,
        model: str,
        dimensions: int,
        batch_size: int,
        api_key: str | None = None,
        client: genai.Client | None = None,
    ) -> None:
        self._model = model
        self._dimensions = dimensions
        self._batch_size = batch_size
        self._api_key = api_key
        self._client = client
        self._client_lock = threading.Lock()

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        task_type: str = "RETRIEVAL_DOCUMENT",
        title: str | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []

        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start : start + self._batch_size])
            response = await asyncio.to_thread(
                self._embed_batch,
                batch,
                task_type,
                title,
            )
            if len(response.embeddings) != len(batch):
                raise ValueError("Embedding API returned an unexpected number of vectors")

            for embedding in response.embeddings:
                values = list(embedding.values)
                if len(values) != self._dimensions:
                    raise ValueError(
                        "Embedding API returned a vector with unexpected dimensionality: "
                        f"expected {self._dimensions}, got {len(values)}"
                    )
                embeddings.append(values)

        return embeddings

    @retry(
        retry=retry_if_exception(_is_retryable_embedding_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _embed_batch(
        self,
        batch: list[str],
        task_type: str,
        title: str | None,
    ) -> types.EmbedContentResponse:
        config = types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=self._dimensions,
            title=title if task_type == "RETRIEVAL_DOCUMENT" else None,
        )
        return self._get_client().models.embed_content(
            model=self._model,
            contents=batch,
            config=config,
        )

    def _get_client(self) -> genai.Client:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    if not self._api_key:
                        raise ValueError("GEMINI_API_KEY is required for embedding generation")
                    self._client = genai.Client(api_key=self._api_key)
        return self._client
