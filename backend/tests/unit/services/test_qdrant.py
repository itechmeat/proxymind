from __future__ import annotations

import uuid
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from qdrant_client import models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from tenacity import wait_none

from app.db.models.enums import ChunkStatus, SourceType
from app.services.qdrant import (
    BM25_MODEL_NAME,
    BM25_VECTOR_NAME,
    DENSE_VECTOR_NAME,
    PAYLOAD_INDEX_FIELDS,
    PREFETCH_MULTIPLIER,
    RRF_K,
    CollectionSchemaMismatchError,
    InvalidRetrievedChunkError,
    QdrantChunkPoint,
    QdrantService,
    RetrievedChunk,
)
from app.services.sparse_providers import SparseProviderMetadata


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


def _bm25_document(text: str, *, language: str = "english") -> models.Document:
    return models.Document(
        text=text,
        model=BM25_MODEL_NAME,
        options=models.Bm25Config(language=language),
    )


def _sparse_provider(
    *,
    backend: str = "bm25",
    model_name: str = BM25_MODEL_NAME,
    contract_version: str = "v1",
    language: str = "english",
    document_representation: models.Document | models.SparseVector | None = None,
    query_representation: models.Document | models.SparseVector | None = None,
) -> SimpleNamespace:
    async def _build_document(text: str) -> models.Document | models.SparseVector:
        if document_representation is not None:
            return document_representation
        return _bm25_document(text, language=language)

    async def _build_query(text: str) -> models.Document | models.SparseVector:
        if query_representation is not None:
            return query_representation
        if backend == "bm25":
            return _bm25_document(text, language=language)
        return models.SparseVector(indices=[1], values=[1.0])

    return SimpleNamespace(
        metadata=SparseProviderMetadata(
            backend=backend,
            model_name=model_name,
            contract_version=contract_version,
        ),
        build_document_representation=AsyncMock(side_effect=_build_document),
        build_query_representation=AsyncMock(side_effect=_build_query),
        aclose=AsyncMock(),
    )


def _scroll_result(*, payload: dict[str, object] | None = None) -> tuple[list[SimpleNamespace], None]:
    if payload is None:
        return ([], None)
    return ([SimpleNamespace(payload=payload)], None)


def _scroll_page(
    *payloads: dict[str, object],
    offset: Any | None = None,
) -> tuple[list[SimpleNamespace], Any | None]:
    return ([SimpleNamespace(payload=payload) for payload in payloads], offset)


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
    sparse_provider: SimpleNamespace | None = None,
) -> tuple[QdrantService, Mock]:
    logger = Mock()
    monkeypatch.setattr("app.services.qdrant.structlog.get_logger", lambda *_args: logger)
    return (
        QdrantService(
            client=client,  # type: ignore[arg-type]
            collection_name=collection_name,
            embedding_dimensions=embedding_dimensions,
            sparse_provider=sparse_provider or _sparse_provider(language=bm25_language),
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


def _point(
    *,
    chunk_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    agent_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    vector: list[float],
    text_content: str,
) -> QdrantChunkPoint:
    return QdrantChunkPoint(
        chunk_id=chunk_id,
        vector=vector,
        snapshot_id=snapshot_id,
        source_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        text_content=text_content,
        chunk_index=0,
        token_count=12,
        anchor_page=None,
        anchor_chapter=None,
        anchor_section=None,
        anchor_timecode=None,
        source_type=SourceType.MARKDOWN,
        language="english",
        status=ChunkStatus.INDEXED,
    )


@pytest.mark.asyncio
async def test_ensure_collection_creates_named_dense_and_sparse_vectors_and_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=False),
        create_collection=AsyncMock(),
        get_collection=AsyncMock(return_value=_collection_info(3072)),
        scroll=AsyncMock(return_value=_scroll_result()),
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
        sparse_backend="bm25",
        sparse_model=BM25_MODEL_NAME,
        sparse_contract_version="v1",
    )
    assert client.create_payload_index.await_count == len(PAYLOAD_INDEX_FIELDS)


@pytest.mark.asyncio
async def test_ensure_collection_is_idempotent_for_matching_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        get_collection=AsyncMock(return_value=_collection_info(3072)),
        scroll=AsyncMock(return_value=_scroll_result()),
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
        scroll=AsyncMock(return_value=_scroll_result()),
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
        scroll=AsyncMock(return_value=_scroll_result()),
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
        scroll=AsyncMock(return_value=_scroll_result()),
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
        scroll=AsyncMock(return_value=_scroll_result()),
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
        scroll=AsyncMock(return_value=_scroll_result()),
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
        scroll=AsyncMock(return_value=_scroll_result()),
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
        scroll=AsyncMock(return_value=_scroll_result()),
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
    assert points[0].payload["sparse_backend"] == "bm25"
    assert points[0].payload["sparse_model"] == BM25_MODEL_NAME


@pytest.mark.asyncio
async def test_upsert_chunks_sends_external_sparse_vectors_and_contract_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sparse_vector = models.SparseVector(indices=[1, 3], values=[0.25, 0.75])
    provider = _sparse_provider(
        backend="bge_m3",
        model_name="bge-m3",
        document_representation=sparse_vector,
        query_representation=models.SparseVector(indices=[2], values=[1.0]),
    )
    client = SimpleNamespace(upsert=AsyncMock())
    service, _logger = _service(
        monkeypatch,
        client=client,
        embedding_dimensions=3,
        sparse_provider=provider,
    )
    point = _point(
        chunk_id=uuid.uuid4(),
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        vector=[0.1, 0.2, 0.3],
        text_content="chunk body",
    )

    await service.upsert_chunks([point])

    provider.build_document_representation.assert_awaited_once_with("chunk body")
    points = client.upsert.await_args.kwargs["points"]
    assert points[0].vector[BM25_VECTOR_NAME] == sparse_vector
    assert points[0].payload["sparse_backend"] == "bge_m3"
    assert points[0].payload["sparse_model"] == "bge-m3"
    assert points[0].payload["sparse_contract_version"] == "v1"


def test_qdrant_chunk_point_bm25_text_prefers_enriched_text() -> None:
    point = QdrantChunkPoint(
        chunk_id=uuid.uuid4(),
        vector=[0.1, 0.2, 0.3],
        snapshot_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        text_content="original",
        chunk_index=0,
        token_count=12,
        anchor_page=None,
        anchor_chapter=None,
        anchor_section=None,
        anchor_timecode=None,
        source_type=SourceType.MARKDOWN,
        language="english",
        status=ChunkStatus.INDEXED,
        enriched_text="original\n\nKeywords: search, retrieval",
    )

    assert point.bm25_text == "original\n\nKeywords: search, retrieval"


def test_build_payload_includes_enrichment_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point = QdrantChunkPoint(
        chunk_id=uuid.uuid4(),
        vector=[0.1, 0.2, 0.3],
        snapshot_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        text_content="original",
        chunk_index=0,
        token_count=12,
        anchor_page=None,
        anchor_chapter=None,
        anchor_section=None,
        anchor_timecode=None,
        source_type=SourceType.MARKDOWN,
        language="english",
        status=ChunkStatus.INDEXED,
        enriched_summary="summary",
        enriched_keywords=["keyword"],
        enriched_questions=["question?"],
        enriched_text="original\n\nSummary: summary",
        enrichment_model="gemini-2.5-flash",
        enrichment_pipeline_version="s9-01-enrichment-v1",
    )

    service, _logger = _service(
        monkeypatch,
        client=SimpleNamespace(),
        embedding_dimensions=3,
    )

    payload = service._build_payload(point)

    assert payload["enriched_summary"] == "summary"
    assert payload["enriched_keywords"] == ["keyword"]
    assert payload["enriched_questions"] == ["question?"]
    assert payload["enriched_text"] == "original\n\nSummary: summary"
    assert payload["enrichment_model"] == "gemini-2.5-flash"
    assert payload["enrichment_pipeline_version"] == "s9-01-enrichment-v1"
    assert payload["source_type"] == SourceType.MARKDOWN.value
    assert payload["sparse_backend"] == "bm25"
    assert payload["sparse_model"] == BM25_MODEL_NAME
    assert payload["sparse_contract_version"] == "v1"


@pytest.mark.asyncio
async def test_upsert_chunks_only_includes_optional_media_payload_when_present(
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
        anchor_page=1,
        anchor_chapter=None,
        anchor_section=None,
        anchor_timecode=None,
        source_type=SourceType.PDF,
        language="english",
        status=ChunkStatus.INDEXED,
        page_count=4,
        duration_seconds=None,
    )

    await service.upsert_chunks([point])

    payload = client.upsert.await_args.kwargs["points"][0].payload
    assert payload["page_count"] == 4
    assert "duration_seconds" not in payload


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
    service._upsert_points.retry.wait = wait_none()
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
async def test_dense_search_builds_dense_query_with_scope_filters(
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

    results = await service.dense_search(
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
async def test_dense_search_omits_score_threshold_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    results = await service.dense_search(
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


def test_build_payload_includes_parent_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _logger = _service(
        monkeypatch,
        client=SimpleNamespace(),
        embedding_dimensions=3,
    )
    point = replace(
        _point(
            chunk_id=uuid.uuid4(),
            snapshot_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            knowledge_base_id=uuid.uuid4(),
            vector=[1.0, 0.0, 0.0],
            text_content="child text",
        ),
        parent_id=uuid.uuid4(),
        parent_text_content="parent text",
        parent_token_count=90,
        parent_anchor_chapter="Chapter 1",
        parent_anchor_section="Section A",
    )

    payload = service._build_payload(point)

    assert payload["parent_text_content"] == "parent text"
    assert payload["parent_anchor_section"] == "Section A"


@pytest.mark.asyncio
async def test_dense_search_returns_parent_metadata_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunk_id = uuid.uuid4()
    source_id = uuid.uuid4()
    parent_id = uuid.uuid4()
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
                            "parent_id": str(parent_id),
                            "parent_text_content": "parent body",
                            "parent_token_count": 120,
                            "parent_anchor_page": 1,
                            "parent_anchor_chapter": "Parent Chapter",
                            "parent_anchor_section": "Parent Section",
                            "parent_anchor_timecode": None,
                        },
                    )
                ]
            )
        )
    )
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    results = await service.dense_search(
        vector=[0.1, 0.2, 0.3],
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        limit=5,
    )

    assert results[0].parent_id == parent_id
    assert results[0].parent_text_content == "parent body"
    assert results[0].parent_anchor_metadata == {
        "anchor_page": 1,
        "anchor_chapter": "Parent Chapter",
        "anchor_section": "Parent Section",
        "anchor_timecode": None,
    }


@pytest.mark.asyncio
async def test_dense_search_preserves_zero_score_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    await service.dense_search(
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
async def test_dense_search_returns_empty_list_when_qdrant_finds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    results = await service.dense_search(
        vector=[0.9, 0.1, 0.0],
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        limit=2,
    )

    assert results == []


@pytest.mark.asyncio
async def test_dense_search_raises_typed_error_for_invalid_payload(
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
        await service.dense_search(
            vector=[0.1, 0.2, 0.3],
            snapshot_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            knowledge_base_id=uuid.uuid4(),
            limit=5,
        )


@pytest.mark.asyncio
async def test_hybrid_search_builds_correct_prefetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    results = await service.hybrid_search(
        text="deployment",
        vector=[0.1, 0.2, 0.3],
        snapshot_id=snapshot_id,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        limit=5,
        score_threshold=0.4,
    )

    assert results == []
    kwargs = client.query_points.await_args.kwargs
    assert kwargs["collection_name"] == "proxymind_chunks"
    assert kwargs["limit"] == 5
    assert kwargs["with_payload"] is True
    prefetch = kwargs["prefetch"]
    assert len(prefetch) == 2

    dense_prefetch, sparse_prefetch = prefetch
    assert dense_prefetch.query == [0.1, 0.2, 0.3]
    assert dense_prefetch.using == DENSE_VECTOR_NAME
    assert dense_prefetch.limit == 5 * PREFETCH_MULTIPLIER
    assert dense_prefetch.score_threshold == 0.4
    assert dense_prefetch.filter is not None
    _assert_scope_filters(
        dense_prefetch.filter.must,
        snapshot_id=snapshot_id,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    )

    assert sparse_prefetch.using == BM25_VECTOR_NAME
    assert sparse_prefetch.limit == 5 * PREFETCH_MULTIPLIER
    assert sparse_prefetch.score_threshold is None
    assert isinstance(sparse_prefetch.query, models.Document)
    assert sparse_prefetch.query.text == "deployment"
    assert sparse_prefetch.query.model == BM25_MODEL_NAME
    assert _language_value(sparse_prefetch.query.options.language) == "english"
    assert sparse_prefetch.filter is not None
    _assert_scope_filters(
        sparse_prefetch.filter.must,
        snapshot_id=snapshot_id,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    )


@pytest.mark.asyncio
async def test_hybrid_search_builds_sparse_vector_prefetch_for_bge_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sparse_query = models.SparseVector(indices=[7], values=[0.9])
    provider = _sparse_provider(
        backend="bge_m3",
        model_name="bge-m3",
        document_representation=models.SparseVector(indices=[1], values=[1.0]),
        query_representation=sparse_query,
    )
    client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
    service, _logger = _service(
        monkeypatch,
        client=client,
        embedding_dimensions=3,
        sparse_provider=provider,
    )

    await service.hybrid_search(
        text="deployment",
        vector=[0.1, 0.2, 0.3],
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        limit=5,
    )

    provider.build_query_representation.assert_awaited_once_with("deployment")
    sparse_prefetch = client.query_points.await_args.kwargs["prefetch"][1]
    assert sparse_prefetch.using == BM25_VECTOR_NAME
    assert sparse_prefetch.query == sparse_query


@pytest.mark.asyncio
async def test_hybrid_search_uses_rrf_query_with_explicit_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    await service.hybrid_search(
        text="deployment",
        vector=[0.1, 0.2, 0.3],
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        limit=5,
    )

    query = client.query_points.await_args.kwargs["query"]
    assert isinstance(query, models.RrfQuery)
    assert query.rrf.k == RRF_K


@pytest.mark.asyncio
async def test_hybrid_search_applies_score_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    await service.hybrid_search(
        text="deployment",
        vector=[0.1, 0.2, 0.3],
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        limit=5,
        score_threshold=None,
    )

    dense_prefetch = client.query_points.await_args.kwargs["prefetch"][0]
    assert dense_prefetch.score_threshold is None

    await service.hybrid_search(
        text="deployment",
        vector=[0.1, 0.2, 0.3],
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        limit=5,
        score_threshold=0.0,
    )

    dense_prefetch = client.query_points.await_args.kwargs["prefetch"][0]
    assert dense_prefetch.score_threshold == 0.0


@pytest.mark.asyncio
async def test_hybrid_search_respects_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    await service.hybrid_search(
        text="deployment",
        vector=[0.1, 0.2, 0.3],
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        limit=7,
    )

    kwargs = client.query_points.await_args.kwargs
    assert kwargs["limit"] == 7
    dense_prefetch, sparse_prefetch = kwargs["prefetch"]
    assert dense_prefetch.limit == 7 * PREFETCH_MULTIPLIER
    assert sparse_prefetch.limit == 7 * PREFETCH_MULTIPLIER


@pytest.mark.asyncio
async def test_hybrid_search_applies_scope_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    await service.hybrid_search(
        text="deployment",
        vector=[0.1, 0.2, 0.3],
        snapshot_id=snapshot_id,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        limit=5,
    )

    kwargs = client.query_points.await_args.kwargs
    _assert_scope_filters(
        kwargs["query_filter"].must,
        snapshot_id=snapshot_id,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    )


@pytest.mark.asyncio
async def test_hybrid_search_retries_on_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunk_id = uuid.uuid4()
    source_id = uuid.uuid4()
    client = SimpleNamespace(
        query_points=AsyncMock(
            side_effect=[
                ResponseHandlingException(httpx.ConnectError("boom")),
                SimpleNamespace(
                    points=[
                        SimpleNamespace(
                            score=0.25,
                            payload={
                                "chunk_id": str(chunk_id),
                                "source_id": str(source_id),
                                "text_content": "deployment guide",
                                "anchor_page": None,
                                "anchor_chapter": None,
                                "anchor_section": None,
                                "anchor_timecode": None,
                            },
                        )
                    ]
                ),
            ]
        )
    )
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)
    service._search_points.retry.wait = wait_none()

    results = await service.hybrid_search(
        text="deployment",
        vector=[0.1, 0.2, 0.3],
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        limit=5,
    )

    assert client.query_points.await_count == 2
    assert results == [
        RetrievedChunk(
            chunk_id=chunk_id,
            source_id=source_id,
            text_content="deployment guide",
            score=0.25,
            anchor_metadata={
                "anchor_page": None,
                "anchor_chapter": None,
                "anchor_section": None,
                "anchor_timecode": None,
            },
        )
    ]


@pytest.mark.asyncio
async def test_hybrid_search_zero_limit_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(query_points=AsyncMock())
    service, _logger = _service(monkeypatch, client=client, embedding_dimensions=3)

    results = await service.hybrid_search(
        text="deployment",
        vector=[0.1, 0.2, 0.3],
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        limit=0,
    )

    assert results == []
    client.query_points.assert_not_awaited()


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
async def test_keyword_search_builds_sparse_vector_query_for_bge_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sparse_query = models.SparseVector(indices=[11], values=[0.42])
    provider = _sparse_provider(
        backend="bge_m3",
        model_name="bge-m3",
        document_representation=models.SparseVector(indices=[1], values=[1.0]),
        query_representation=sparse_query,
    )
    client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
    service, _logger = _service(
        monkeypatch,
        client=client,
        embedding_dimensions=3,
        sparse_provider=provider,
    )

    await service.keyword_search(
        text="deployment",
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        limit=5,
    )

    provider.build_query_representation.assert_awaited_once_with("deployment")
    kwargs = client.query_points.await_args.kwargs
    assert kwargs["query"] == sparse_query
    assert kwargs["using"] == BM25_VECTOR_NAME


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
    service._search_points.retry.wait = wait_none()

    await service.keyword_search(
        text="deployment",
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
    )

    assert client.query_points.await_count == 2


@pytest.mark.asyncio
async def test_ensure_collection_requires_explicit_reindex_for_bge_without_payload_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _sparse_provider(
        backend="bge_m3",
        model_name="bge-m3",
        document_representation=models.SparseVector(indices=[1], values=[1.0]),
        query_representation=models.SparseVector(indices=[2], values=[1.0]),
    )
    collection_info = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(
                vectors={DENSE_VECTOR_NAME: SimpleNamespace(size=3072)},
                sparse_vectors={BM25_VECTOR_NAME: SimpleNamespace(modifier=None)},
            )
        )
    )
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        get_collection=AsyncMock(return_value=collection_info),
        scroll=AsyncMock(return_value=_scroll_result(payload={})),
        create_payload_index=AsyncMock(),
    )
    service, _logger = _service(
        monkeypatch,
        client=client,
        sparse_provider=provider,
    )

    with pytest.raises(
        CollectionSchemaMismatchError,
        match="compatibility could not be proven",
    ):
        await service.ensure_collection()


@pytest.mark.asyncio
async def test_ensure_collection_rejects_mixed_sparse_contract_metadata_across_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        get_collection=AsyncMock(return_value=_collection_info(3072)),
        scroll=AsyncMock(
            side_effect=[
                _scroll_page(
                    {
                        "sparse_backend": "bm25",
                        "sparse_model": BM25_MODEL_NAME,
                        "sparse_contract_version": "v1",
                    },
                    offset="next-page",
                ),
                _scroll_page(
                    {
                        "sparse_backend": "bge_m3",
                        "sparse_model": "bge-m3",
                        "sparse_contract_version": "v1",
                    }
                ),
            ]
        ),
        create_payload_index=AsyncMock(),
    )
    service, _logger = _service(monkeypatch, client=client)

    with pytest.raises(
        CollectionSchemaMismatchError,
        match="mismatch detected across indexed payload metadata",
    ):
        await service.ensure_collection()

    assert client.scroll.await_count == 2


@pytest.mark.asyncio
async def test_ensure_collection_rejects_mixed_legacy_and_annotated_sparse_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        get_collection=AsyncMock(return_value=_collection_info(3072)),
        scroll=AsyncMock(
            return_value=_scroll_page(
                {},
                {
                    "sparse_backend": "bm25",
                    "sparse_model": BM25_MODEL_NAME,
                    "sparse_contract_version": "v1",
                },
            )
        ),
        create_payload_index=AsyncMock(),
    )
    service, _logger = _service(monkeypatch, client=client)

    with pytest.raises(
        CollectionSchemaMismatchError,
        match="mixed legacy/annotated state",
    ):
        await service.ensure_collection()


@pytest.mark.asyncio
async def test_close_closes_qdrant_client_even_when_sparse_provider_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _sparse_provider()
    provider.aclose = AsyncMock(side_effect=RuntimeError("sparse close failed"))
    client = SimpleNamespace(close=AsyncMock())
    service, _logger = _service(
        monkeypatch,
        client=client,
        sparse_provider=provider,
    )

    with pytest.raises(ExceptionGroup, match="Failed to close Qdrant service resources") as error:
        await service.close()

    client.close.assert_awaited_once()
    assert len(error.value.exceptions) == 1
    assert str(error.value.exceptions[0]) == "sparse close failed"


@pytest.mark.asyncio
async def test_close_reports_both_resource_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _sparse_provider()
    provider.aclose = AsyncMock(side_effect=RuntimeError("sparse close failed"))
    client = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("client close failed")))
    service, _logger = _service(
        monkeypatch,
        client=client,
        sparse_provider=provider,
    )

    with pytest.raises(ExceptionGroup, match="Failed to close Qdrant service resources") as error:
        await service.close()

    assert [str(item) for item in error.value.exceptions] == [
        "sparse close failed",
        "client close failed",
    ]
