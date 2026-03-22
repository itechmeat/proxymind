from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from qdrant_client import models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.db.models.enums import ChunkStatus, SourceType
from app.services.qdrant import (
    BM25_MODEL_NAME,
    BM25_VECTOR_NAME,
    DENSE_VECTOR_NAME,
    PAYLOAD_INDEX_FIELDS,
    CollectionSchemaMismatchError,
    InvalidRetrievedChunkError,
    QdrantChunkPoint,
    QdrantService,
    RetrievedChunk,
)


def _collection_info(
    size: int, *, bm25_modifier: models.Modifier | None = models.Modifier.IDF
) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(
                vectors={DENSE_VECTOR_NAME: SimpleNamespace(size=size)},
                sparse_vectors=(
                    {BM25_VECTOR_NAME: SimpleNamespace(modifier=bm25_modifier)}
                    if bm25_modifier is not None
                    else None
                ),
            )
        )
    )


def _unexpected_response(status_code: int, message: str) -> UnexpectedResponse:
    return UnexpectedResponse(
        status_code=status_code,
        reason_phrase="Error",
        content=f'{{"status":{{"error":"{message}"}}}}'.encode(),
        headers=httpx.Headers(),
    )


def _language_value(value: object) -> object:
    return getattr(value, "value", value)


def _service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    client: SimpleNamespace,
    collection_name: str = "proxymind_chunks",
    embedding_dimensions: int = 3072,
    bm25_language: str = "english",
) -> tuple[QdrantService, Mock]:
    logger = Mock()
    monkeypatch.setattr("app.services.qdrant.structlog.get_logger", lambda *_args: logger)
    return (
        QdrantService(
            client=client,  # type: ignore[arg-type]
            collection_name=collection_name,
            embedding_dimensions=embedding_dimensions,
            bm25_language=bm25_language,
        ),
        logger,
    )


def _assert_scope_filters(
    filters: list[models.FieldCondition],
    *,
    snapshot_id: uuid.UUID,
    agent_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
) -> None:
    assert [(condition.key, condition.match.value) for condition in filters] == [
        ("snapshot_id", str(snapshot_id)),
        ("agent_id", str(agent_id)),
        ("knowledge_base_id", str(knowledge_base_id)),
    ]


@pytest.mark.asyncio
async def test_ensure_collection_creates_named_dense_and_sparse_vectors_and_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=False),
        create_collection=AsyncMock(),
        create_payload_index=AsyncMock(),
    )
    service, logger = _service(
        monkeypatch,
        client=client,
        embedding_dimensions=3072,
        bm25_language="english",
    )

    await service.ensure_collection()

    client.create_collection.assert_awaited_once()
    kwargs = client.create_collection.await_args.kwargs
    assert kwargs["collection_name"] == "proxymind_chunks"
    assert kwargs["vectors_config"][DENSE_VECTOR_NAME].size == 3072
    assert kwargs["vectors_config"][DENSE_VECTOR_NAME].distance is models.Distance.COSINE
    assert (
        kwargs["sparse_vectors_config"][BM25_VECTOR_NAME].modifier is models.Modifier.IDF
    )
    logger.info.assert_called_once_with(
        "qdrant.ensure_collection",
        collection_name="proxymind_chunks",
        bm25_language="english",
    )
    assert client.create_payload_index.await_count == len(PAYLOAD_INDEX_FIELDS)


@pytest.mark.asyncio
async def test_ensure_collection_is_idempotent_for_matching_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        get_collection=AsyncMock(return_value=_collection_info(3072)),
        create_collection=AsyncMock(),
        create_payload_index=AsyncMock(),
    )
    service, logger = _service(monkeypatch, client=client)

    await service.ensure_collection()

    client.create_collection.assert_not_awaited()
    client.get_collection.assert_awaited_once_with("proxymind_chunks")
    logger.warning.assert_not_called()
    assert client.create_payload_index.await_count == len(PAYLOAD_INDEX_FIELDS)


@pytest.mark.asyncio
async def test_ensure_collection_handles_duplicate_create_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=False),
        create_collection=AsyncMock(
            side_effect=_unexpected_response(409, "Collection already exists")
        ),
        get_collection=AsyncMock(return_value=_collection_info(3072)),
        create_payload_index=AsyncMock(),
    )
    service, _logger = _service(monkeypatch, client=client)

    await service.ensure_collection()

    client.create_collection.assert_awaited_once()
    client.get_collection.assert_awaited_once_with("proxymind_chunks")
    assert client.create_payload_index.await_count == len(PAYLOAD_INDEX_FIELDS)


@pytest.mark.asyncio
async def test_ensure_collection_recreates_collection_when_bm25_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(side_effect=[True, True, True]),
        get_collection=AsyncMock(
            side_effect=[
                _collection_info(3072, bm25_modifier=None),
                _collection_info(3072, bm25_modifier=None),
                _collection_info(3072),
            ]
        ),
        delete_collection=AsyncMock(),
        create_collection=AsyncMock(),
        create_payload_index=AsyncMock(),
    )
    service, logger = _service(monkeypatch, client=client)

    await service.ensure_collection()

    logger.warning.assert_called_once()
    client.delete_collection.assert_awaited_once_with("proxymind_chunks")
    client.create_collection.assert_awaited_once()
    create_kwargs = client.create_collection.await_args.kwargs
    assert BM25_VECTOR_NAME in create_kwargs["sparse_vectors_config"]
    assert client.create_payload_index.await_count == len(PAYLOAD_INDEX_FIELDS)


@pytest.mark.asyncio
async def test_ensure_collection_recreates_collection_when_bm25_modifier_is_not_idf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(side_effect=[True, True, True]),
        get_collection=AsyncMock(
            side_effect=[
                _collection_info(3072, bm25_modifier=models.Modifier.NONE),
                _collection_info(3072, bm25_modifier=models.Modifier.NONE),
                _collection_info(3072),
            ]
        ),
        delete_collection=AsyncMock(),
        create_collection=AsyncMock(),
        create_payload_index=AsyncMock(),
    )
    service, logger = _service(monkeypatch, client=client)

    await service.ensure_collection()

    logger.warning.assert_called_once()
    client.delete_collection.assert_awaited_once_with("proxymind_chunks")
    client.create_collection.assert_awaited_once()
    assert client.create_payload_index.await_count == len(PAYLOAD_INDEX_FIELDS)


@pytest.mark.asyncio
async def test_ensure_collection_handles_delete_404_during_recreate_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(side_effect=[True, True, True]),
        get_collection=AsyncMock(
            side_effect=[
                _collection_info(3072, bm25_modifier=None),
                _collection_info(3072, bm25_modifier=None),
                _collection_info(3072),
            ]
        ),
        delete_collection=AsyncMock(
            side_effect=_unexpected_response(404, "Collection doesn't exist")
        ),
        create_collection=AsyncMock(
            side_effect=_unexpected_response(409, "Collection already exists")
        ),
        create_payload_index=AsyncMock(),
    )
    service, _logger = _service(monkeypatch, client=client)

    await service.ensure_collection()

    client.delete_collection.assert_awaited_once_with("proxymind_chunks")
    client.create_collection.assert_awaited_once()
    assert client.create_payload_index.await_count == len(PAYLOAD_INDEX_FIELDS)


@pytest.mark.asyncio
async def test_ensure_collection_handles_create_409_during_recreate_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(side_effect=[True, True, True]),
        get_collection=AsyncMock(
            side_effect=[
                _collection_info(3072, bm25_modifier=None),
                _collection_info(3072, bm25_modifier=None),
                _collection_info(3072),
            ]
        ),
        delete_collection=AsyncMock(),
        create_collection=AsyncMock(
            side_effect=_unexpected_response(409, "Collection already exists")
        ),
        create_payload_index=AsyncMock(),
    )
    service, _logger = _service(monkeypatch, client=client)

    await service.ensure_collection()

    client.delete_collection.assert_awaited_once_with("proxymind_chunks")
    client.create_collection.assert_awaited_once()
    assert client.create_payload_index.await_count == len(PAYLOAD_INDEX_FIELDS)


@pytest.mark.asyncio
async def test_ensure_collection_fails_when_bm25_never_appears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        get_collection=AsyncMock(
            return_value=_collection_info(3072, bm25_modifier=None),
        ),
        delete_collection=AsyncMock(),
        create_collection=AsyncMock(),
        create_payload_index=AsyncMock(),
    )
    service, _logger = _service(monkeypatch, client=client)

    with pytest.raises(
        CollectionSchemaMismatchError,
        match="did not converge",
    ):
        await service.ensure_collection()

    assert client.delete_collection.await_count == 3
    assert client.create_collection.await_count == 3


@pytest.mark.asyncio
async def test_ensure_collection_raises_on_dimension_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        get_collection=AsyncMock(return_value=_collection_info(3072)),
        create_payload_index=AsyncMock(),
    )
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=1024)

    with pytest.raises(CollectionSchemaMismatchError, match="existing=3072, required=1024"):
        await service.ensure_collection()


@pytest.mark.asyncio
async def test_upsert_chunks_sends_dense_and_bm25_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(upsert=AsyncMock())
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)
    point = QdrantChunkPoint(
        chunk_id=uuid.uuid4(),
        vector=[0.1, 0.2, 0.3],
        snapshot_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        text_content="chunk body",
        chunk_index=0,
        token_count=12,
        anchor_page=None,
        anchor_chapter="Chapter",
        anchor_section="Section",
        anchor_timecode=None,
        source_type=SourceType.MARKDOWN,
        language="english",
        status=ChunkStatus.INDEXED,
    )

    await service.upsert_chunks([point])

    client.upsert.assert_awaited_once()
    points = client.upsert.await_args.kwargs["points"]
    assert len(points) == 1
    assert points[0].vector[DENSE_VECTOR_NAME] == [0.1, 0.2, 0.3]
    bm25_document = points[0].vector[BM25_VECTOR_NAME]
    assert isinstance(bm25_document, models.Document)
    assert bm25_document.text == "chunk body"
    assert bm25_document.model == BM25_MODEL_NAME
    assert _language_value(bm25_document.options.language) == "english"
    assert points[0].payload["text_content"] == "chunk body"
    assert points[0].payload["source_type"] == "markdown"


@pytest.mark.asyncio
async def test_upsert_chunks_retries_transient_connection_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        upsert=AsyncMock(
            side_effect=[
                ResponseHandlingException(httpx.ConnectError("boom")),
                None,
            ]
        )
    )
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)
    point = QdrantChunkPoint(
        chunk_id=uuid.uuid4(),
        vector=[0.1, 0.2, 0.3],
        snapshot_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        text_content="chunk body",
        chunk_index=0,
        token_count=12,
        anchor_page=None,
        anchor_chapter=None,
        anchor_section=None,
        anchor_timecode=None,
        source_type=SourceType.MARKDOWN,
        language=None,
        status=ChunkStatus.INDEXED,
    )

    await service.upsert_chunks([point])

    assert client.upsert.await_count == 2


@pytest.mark.asyncio
async def test_delete_chunks_sends_point_ids_to_qdrant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(delete=AsyncMock())
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)
    chunk_ids = [uuid.uuid4(), uuid.uuid4()]

    await service.delete_chunks(chunk_ids)

    client.delete.assert_awaited_once()
    kwargs = client.delete.await_args.kwargs
    assert kwargs["collection_name"] == "proxymind_chunks"
    assert kwargs["wait"] is True
    assert kwargs["points_selector"].points == [str(chunk_id) for chunk_id in chunk_ids]


@pytest.mark.asyncio
async def test_search_builds_dense_query_with_scope_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    source_id = uuid.uuid4()
    client = SimpleNamespace(
        query_points=AsyncMock(
            return_value=SimpleNamespace(
                points=[
                    SimpleNamespace(
                        score=0.91,
                        payload={
                            "chunk_id": str(chunk_id),
                            "source_id": str(source_id),
                            "text_content": "retrieved body",
                            "anchor_page": 7,
                            "anchor_chapter": "Ch. 1",
                            "anchor_section": "Intro",
                            "anchor_timecode": None,
                        },
                    )
                ]
            )
        )
    )
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    results = await service.search(
        vector=[0.1, 0.2, 0.3],
        snapshot_id=snapshot_id,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        limit=5,
        score_threshold=0.5,
    )

    assert results == [
        RetrievedChunk(
            chunk_id=chunk_id,
            source_id=source_id,
            text_content="retrieved body",
            score=0.91,
            anchor_metadata={
                "anchor_page": 7,
                "anchor_chapter": "Ch. 1",
                "anchor_section": "Intro",
                "anchor_timecode": None,
            },
        )
    ]
    kwargs = client.query_points.await_args.kwargs
    assert kwargs["query"] == [0.1, 0.2, 0.3]
    assert kwargs["using"] == DENSE_VECTOR_NAME
    assert kwargs["limit"] == 5
    assert kwargs["score_threshold"] == 0.5
    _assert_scope_filters(
        kwargs["query_filter"].must,
        snapshot_id=snapshot_id,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    )


@pytest.mark.asyncio
async def test_search_omits_score_threshold_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    results = await service.search(
        vector=[0.3, 0.2, 0.1],
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        limit=3,
        score_threshold=None,
    )

    assert results == []
    kwargs = client.query_points.await_args.kwargs
    assert "score_threshold" not in kwargs


@pytest.mark.asyncio
async def test_search_preserves_zero_score_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    await service.search(
        vector=[0.3, 0.2, 0.1],
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        limit=3,
        score_threshold=0.0,
    )

    kwargs = client.query_points.await_args.kwargs
    assert kwargs["score_threshold"] == 0.0


@pytest.mark.asyncio
async def test_search_returns_empty_list_when_qdrant_finds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    results = await service.search(
        vector=[0.9, 0.1, 0.0],
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        limit=2,
    )

    assert results == []


@pytest.mark.asyncio
async def test_search_raises_typed_error_for_invalid_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        query_points=AsyncMock(
            return_value=SimpleNamespace(
                points=[
                    SimpleNamespace(
                        score=0.91,
                        payload={
                            "source_id": str(uuid.uuid4()),
                            "text_content": "retrieved body",
                        },
                    )
                ]
            )
        )
    )
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    with pytest.raises(InvalidRetrievedChunkError, match="chunk_id"):
        await service.search(
            vector=[0.1, 0.2, 0.3],
            snapshot_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            knowledge_base_id=uuid.uuid4(),
            limit=5,
        )


@pytest.mark.asyncio
async def test_keyword_search_builds_bm25_query_with_scope_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    source_id = uuid.uuid4()
    client = SimpleNamespace(
        query_points=AsyncMock(
            return_value=SimpleNamespace(
                points=[
                    SimpleNamespace(
                        score=4.2,
                        payload={
                            "chunk_id": str(chunk_id),
                            "source_id": str(source_id),
                            "text_content": "deployment guide",
                            "anchor_page": 5,
                            "anchor_chapter": "Deploy",
                            "anchor_section": "Checklist",
                            "anchor_timecode": None,
                        },
                    )
                ]
            )
        )
    )
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    results = await service.keyword_search(
        text="deployment",
        snapshot_id=snapshot_id,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        limit=5,
    )

    assert results == [
        RetrievedChunk(
            chunk_id=chunk_id,
            source_id=source_id,
            text_content="deployment guide",
            score=4.2,
            anchor_metadata={
                "anchor_page": 5,
                "anchor_chapter": "Deploy",
                "anchor_section": "Checklist",
                "anchor_timecode": None,
            },
        )
    ]
    kwargs = client.query_points.await_args.kwargs
    assert kwargs["using"] == BM25_VECTOR_NAME
    assert kwargs["limit"] == 5
    assert isinstance(kwargs["query"], models.Document)
    assert kwargs["query"].text == "deployment"
    assert kwargs["query"].model == BM25_MODEL_NAME
    assert _language_value(kwargs["query"].options.language) == "english"
    _assert_scope_filters(
        kwargs["query_filter"].must,
        snapshot_id=snapshot_id,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    )


@pytest.mark.asyncio
async def test_keyword_search_returns_empty_list_when_qdrant_finds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    results = await service.keyword_search(
        text="nothing",
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
    )

    assert results == []


@pytest.mark.asyncio
async def test_keyword_search_retries_transient_connection_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        query_points=AsyncMock(
            side_effect=[
                ResponseHandlingException(httpx.ConnectError("boom")),
                SimpleNamespace(points=[]),
            ]
        )
    )
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    await service.keyword_search(
        text="deployment",
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
    )

    assert client.query_points.await_count == 2
