from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.dependencies import get_chat_service, get_conversation_memory_service


def test_get_conversation_memory_service_returns_none_when_unconfigured() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    assert get_conversation_memory_service(request) is None


@pytest.mark.asyncio
async def test_get_chat_service_uses_deduplicated_summary_job_id() -> None:
    arq_pool = SimpleNamespace(
        enqueue_job=AsyncMock(return_value=SimpleNamespace(job_id="summary:session-123"))
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                arq_pool=arq_pool,
                settings=SimpleNamespace(
                    min_retrieved_chunks=1,
                    max_citations_per_response=5,
                ),
            )
        )
    )

    service = get_chat_service(
        request=request,
        session=SimpleNamespace(),
        snapshot_service=SimpleNamespace(),
        retrieval_service=SimpleNamespace(),
        llm_service=SimpleNamespace(),
        query_rewrite_service=SimpleNamespace(),
        context_assembler=SimpleNamespace(),
        conversation_memory_service=SimpleNamespace(),
        audit_service=SimpleNamespace(),
    )

    assert service._summary_enqueuer is not None

    await service._summary_enqueuer("session-123", "window-456")

    arq_pool.enqueue_job.assert_awaited_once_with(
        "generate_session_summary",
        "session-123",
        "window-456",
        _job_id="summary:session-123",
    )


@pytest.mark.asyncio
async def test_get_chat_service_treats_duplicate_summary_job_as_best_effort() -> None:
    arq_pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=None))
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                arq_pool=arq_pool,
                settings=SimpleNamespace(
                    min_retrieved_chunks=1,
                    max_citations_per_response=5,
                ),
            )
        )
    )

    service = get_chat_service(
        request=request,
        session=SimpleNamespace(),
        snapshot_service=SimpleNamespace(),
        retrieval_service=SimpleNamespace(),
        llm_service=SimpleNamespace(),
        query_rewrite_service=SimpleNamespace(),
        context_assembler=SimpleNamespace(),
        conversation_memory_service=SimpleNamespace(),
        audit_service=SimpleNamespace(),
    )

    assert service._summary_enqueuer is not None

    await service._summary_enqueuer("session-123", None)

    arq_pool.enqueue_job.assert_awaited_once_with(
        "generate_session_summary",
        "session-123",
        None,
        _job_id="summary:session-123",
    )


@pytest.mark.asyncio
async def test_get_chat_service_propagates_correlation_id_to_summary_job() -> None:
    arq_pool = SimpleNamespace(
        enqueue_job=AsyncMock(return_value=SimpleNamespace(job_id="summary:session-123"))
    )
    request = SimpleNamespace(
        state=SimpleNamespace(correlation_id="corr-123"),
        app=SimpleNamespace(
            state=SimpleNamespace(
                arq_pool=arq_pool,
                settings=SimpleNamespace(
                    min_retrieved_chunks=1,
                    max_citations_per_response=5,
                ),
            )
        ),
    )

    service = get_chat_service(
        request=request,
        session=SimpleNamespace(),
        snapshot_service=SimpleNamespace(),
        retrieval_service=SimpleNamespace(),
        llm_service=SimpleNamespace(),
        query_rewrite_service=SimpleNamespace(),
        context_assembler=SimpleNamespace(),
        conversation_memory_service=SimpleNamespace(),
        audit_service=SimpleNamespace(),
    )

    assert service._summary_enqueuer is not None

    await service._summary_enqueuer("session-123", "window-456")

    arq_pool.enqueue_job.assert_awaited_once_with(
        "generate_session_summary",
        "session-123",
        "window-456",
        _job_id="summary:session-123",
        correlation_id="corr-123",
    )
