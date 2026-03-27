from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai.errors import ClientError, ServerError
from tenacity import wait_none

from app.services.embedding import EmbeddingService
from app.services.gemini_file_transfer import PreparedFilePart


class FakeModels:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def embed_content(self, *, model: str, contents: list[object], config: object) -> object:
        self.calls.append(
            {
                "model": model,
                "contents": list(contents),
                "config": config,
            }
        )
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _response(*vectors: list[float]) -> object:
    return SimpleNamespace(
        embeddings=[SimpleNamespace(values=value) for value in vectors],
    )


@pytest.mark.asyncio
async def test_embed_texts_single_batch_returns_vectors() -> None:
    models = FakeModels([_response([0.1, 0.2], [0.3, 0.4])])
    service = EmbeddingService(
        model="gemini-embedding-2-preview",
        dimensions=2,
        batch_size=100,
        client=SimpleNamespace(models=models),  # type: ignore[arg-type]
    )

    embeddings = await service.embed_texts(["one", "two"])

    assert embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert len(models.calls) == 1
    assert models.calls[0]["contents"] == ["one", "two"]


@pytest.mark.asyncio
async def test_embed_texts_batches_requests_and_preserves_order() -> None:
    models = FakeModels(
        [
            _response([1.0, 1.1], [2.0, 2.1]),
            _response([3.0, 3.1]),
        ]
    )
    service = EmbeddingService(
        model="gemini-embedding-2-preview",
        dimensions=2,
        batch_size=2,
        client=SimpleNamespace(models=models),  # type: ignore[arg-type]
    )

    embeddings = await service.embed_texts(["a", "b", "c"])

    assert embeddings == [[1.0, 1.1], [2.0, 2.1], [3.0, 3.1]]
    assert [call["contents"] for call in models.calls] == [["a", "b"], ["c"]]


@pytest.mark.asyncio
async def test_embed_texts_returns_empty_list_for_empty_input() -> None:
    models = FakeModels([])
    service = EmbeddingService(
        model="gemini-embedding-2-preview",
        dimensions=2,
        batch_size=2,
        client=SimpleNamespace(models=models),  # type: ignore[arg-type]
    )

    embeddings = await service.embed_texts([])

    assert embeddings == []
    assert models.calls == []


@pytest.mark.asyncio
async def test_embed_texts_retries_transient_errors() -> None:
    models = FakeModels(
        [
            ServerError(503, {"error": {"message": "temporary", "status": "UNAVAILABLE"}}, None),
            _response([0.1, 0.2]),
        ]
    )
    service = EmbeddingService(
        model="gemini-embedding-2-preview",
        dimensions=2,
        batch_size=2,
        client=SimpleNamespace(models=models),  # type: ignore[arg-type]
    )
    service._embed_batch.retry.wait = wait_none()

    embeddings = await service.embed_texts(["retry me"])

    assert embeddings == [[0.1, 0.2]]
    assert len(models.calls) == 2


@pytest.mark.asyncio
async def test_embed_texts_raises_after_retries_exhausted() -> None:
    rate_limit_error = ClientError(
        429,
        {"error": {"message": "rate limited", "status": "RESOURCE_EXHAUSTED"}},
        None,
    )
    models = FakeModels([rate_limit_error, rate_limit_error, rate_limit_error])
    service = EmbeddingService(
        model="gemini-embedding-2-preview",
        dimensions=2,
        batch_size=2,
        client=SimpleNamespace(models=models),  # type: ignore[arg-type]
    )
    service._embed_batch.retry.wait = wait_none()

    with pytest.raises(ClientError):
        await service.embed_texts(["retry me"])

    assert len(models.calls) == 3


@pytest.mark.asyncio
async def test_embed_file_uses_prepare_file_part_and_returns_single_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = FakeModels([_response([0.1, 0.2])])
    cleanup_calls: list[str | None] = []

    async def fake_prepare_file_part(*args, **kwargs) -> PreparedFilePart:
        return PreparedFilePart(part="file-part", uploaded_file_name="files/123")  # type: ignore[arg-type]

    async def fake_cleanup_uploaded_file(_client, file_name: str | None) -> None:
        cleanup_calls.append(file_name)

    monkeypatch.setattr("app.services.embedding.prepare_file_part", fake_prepare_file_part)
    monkeypatch.setattr("app.services.embedding.cleanup_uploaded_file", fake_cleanup_uploaded_file)
    service = EmbeddingService(
        model="gemini-embedding-2-preview",
        dimensions=2,
        batch_size=2,
        client=SimpleNamespace(models=models),  # type: ignore[arg-type]
    )

    vector = await service.embed_file(b"image-bytes", "image/png")

    assert vector == [0.1, 0.2]
    assert models.calls[0]["contents"] == ["file-part"]
    assert models.calls[0]["config"].task_type == "RETRIEVAL_DOCUMENT"
    assert models.calls[0]["config"].output_dimensionality == 2
    assert models.calls[0]["config"].mime_type == "image/png"
    assert cleanup_calls == ["files/123"]
