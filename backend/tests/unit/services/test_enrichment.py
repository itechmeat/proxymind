from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.document_processing import ChunkData
from app.services.enrichment import (
    EnrichmentResult,
    EnrichmentService,
    _estimate_tokens,
    build_enriched_text,
)


def _chunk(text: str = "Revenue grew 3% in Q2 compared to last quarter.", *, token_count: int = 20) -> ChunkData:
    return ChunkData(
        text_content=text,
        token_count=token_count,
        chunk_index=0,
        anchor_page=None,
        anchor_chapter=None,
        anchor_section=None,
    )


def _response(*, summary: str = "Q2 revenue grew 3%.") -> SimpleNamespace:
    return SimpleNamespace(
        text=json.dumps(
            {
                "summary": summary,
                "keywords": ["revenue", "growth", "q2"],
                "questions": ["How did revenue change in Q2?"],
            }
        )
    )


@pytest.mark.asyncio
async def test_enrich_returns_structured_results() -> None:
    client = MagicMock()
    client.models.generate_content.return_value = _response()
    service = EnrichmentService(
        model="gemini-2.5-flash",
        temperature=0.1,
        max_output_tokens=512,
        min_chunk_tokens=10,
        max_concurrency=2,
        client=client,
    )

    results = await service.enrich([_chunk()])

    assert results == [
        EnrichmentResult(
            summary="Q2 revenue grew 3%.",
            keywords=["revenue", "growth", "q2"],
            questions=["How did revenue change in Q2?"],
        )
    ]
    client.models.generate_content.assert_called_once()


@pytest.mark.asyncio
async def test_enrich_skips_small_chunks_without_api_call() -> None:
    client = MagicMock()
    service = EnrichmentService(
        model="gemini-2.5-flash",
        temperature=0.1,
        max_output_tokens=512,
        min_chunk_tokens=10,
        max_concurrency=2,
        client=client,
    )

    results = await service.enrich([_chunk("tiny", token_count=2)])

    assert results == [None]
    client.models.generate_content.assert_not_called()


@pytest.mark.asyncio
async def test_enrich_skips_small_chunks_when_token_count_is_missing() -> None:
    client = MagicMock()
    service = EnrichmentService(
        model="gemini-2.5-flash",
        temperature=0.1,
        max_output_tokens=512,
        min_chunk_tokens=10,
        max_concurrency=2,
        client=client,
    )

    results = await service.enrich(
        [SimpleNamespace(text_content="tiny", token_count=None, chunk_index=0)]
    )

    assert results == [None]
    client.models.generate_content.assert_not_called()


@pytest.mark.asyncio
async def test_enrich_fails_open_when_text_content_is_missing() -> None:
    client = MagicMock()
    service = EnrichmentService(
        model="gemini-2.5-flash",
        temperature=0.1,
        max_output_tokens=512,
        min_chunk_tokens=1,
        max_concurrency=2,
        client=client,
    )

    results = await service.enrich([SimpleNamespace(token_count=20, chunk_index=0)])

    assert results == [None]
    client.models.generate_content.assert_not_called()


@pytest.mark.asyncio
async def test_enrich_fails_open_per_chunk() -> None:
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("boom")
    service = EnrichmentService(
        model="gemini-2.5-flash",
        temperature=0.1,
        max_output_tokens=512,
        min_chunk_tokens=10,
        max_concurrency=2,
        client=client,
    )

    results = await service.enrich([_chunk()])

    assert results == [None]


@pytest.mark.asyncio
async def test_enrich_fails_open_when_all_chunks_fail() -> None:
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("boom")
    service = EnrichmentService(
        model="gemini-2.5-flash",
        temperature=0.1,
        max_output_tokens=512,
        min_chunk_tokens=1,
        max_concurrency=2,
        client=client,
    )

    results = await service.enrich([_chunk("first"), _chunk("second")])

    assert results == [None, None]


@pytest.mark.asyncio
async def test_enrich_fails_open_when_structured_fields_are_blank() -> None:
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(
        text=json.dumps(
            {
                "summary": "   ",
                "keywords": ["   ", "retrieval"],
                "questions": ["   "],
            }
        )
    )
    service = EnrichmentService(
        model="gemini-2.5-flash",
        temperature=0.1,
        max_output_tokens=512,
        min_chunk_tokens=10,
        max_concurrency=2,
        client=client,
    )

    results = await service.enrich([_chunk()])

    assert results == [None]


@pytest.mark.asyncio
async def test_enrich_respects_max_concurrency() -> None:
    service = EnrichmentService(
        model="gemini-2.5-flash",
        temperature=0.1,
        max_output_tokens=512,
        min_chunk_tokens=1,
        max_concurrency=2,
        client=MagicMock(),
    )
    in_flight = 0
    max_in_flight = 0
    lock = threading.Lock()
    entered = threading.Event()
    release = threading.Event()

    def fake_generate_content(_text: str) -> SimpleNamespace:
        nonlocal in_flight, max_in_flight
        with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            if in_flight == 2:
                entered.set()
        release.wait(timeout=1)
        with lock:
            in_flight -= 1
        return _response(summary="ok")

    service._generate_content = fake_generate_content  # type: ignore[method-assign]

    task = asyncio.create_task(service.enrich([_chunk("a"), _chunk("b"), _chunk("c")]))
    assert await asyncio.to_thread(entered.wait, 1)
    with lock:
        assert in_flight == 2
        assert max_in_flight == 2
    release.set()
    await task

    assert max_in_flight == 2


def test_build_enriched_text_formats_all_sections() -> None:
    result = build_enriched_text(
        text_content="Original text.",
        summary="Deployment steps.",
        keywords=["deploy", "setup"],
        questions=["How do I deploy?"],
    )

    assert result.startswith("Original text.")
    assert "Summary: Deployment steps." in result
    assert "Keywords: deploy, setup" in result
    assert "Questions:\n- How do I deploy?" in result


def test_build_enriched_text_drops_questions_before_keywords() -> None:
    result = build_enriched_text(
        text_content="x" * 23920,
        summary="summary",
        keywords=["keyword-one", "keyword-two"],
        questions=["Question one?", "Question two?"],
        max_tokens=8001,
    )

    assert "Summary: summary" in result
    assert "Keywords: keyword-one, keyword-two" in result
    assert "Questions:" not in result


def test_build_enriched_text_truncates_summary_last() -> None:
    result = build_enriched_text(
        text_content="x" * 24560,
        summary="summary-" * 40,
        keywords=["keyword-one", "keyword-two"],
        questions=["Question one?", "Question two?"],
        max_tokens=8192,
    )

    assert result.startswith("x" * 20)
    assert "Questions:" not in result
    assert "Keywords:" not in result
    assert "Summary:" in result
    assert len(result) < len("x" * 24560 + "summary-" * 40)


def test_build_enriched_text_summary_fits_exact_budget() -> None:
    max_tokens = 20
    result = build_enriched_text(
        text_content="x" * 40,
        summary="summary-" * 40,
        keywords=["keyword-one", "keyword-two"],
        questions=["Question one?", "Question two?"],
        max_tokens=max_tokens,
    )

    assert "Summary:" in result
    assert _estimate_tokens(result) <= max_tokens


def test_build_enriched_text_returns_original_when_source_is_over_budget() -> None:
    original = "x" * 25000
    result = build_enriched_text(
        text_content=original,
        summary="summary",
        keywords=["keyword"],
        questions=["question?"],
        max_tokens=8192,
    )

    assert result == original
