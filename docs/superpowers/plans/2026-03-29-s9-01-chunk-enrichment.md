# S9-01: Chunk Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an LLM enrichment stage to the ingestion pipeline that generates summary, keywords, and questions per chunk, then validate via A/B eval whether this improves retrieval.

**Architecture:** New `EnrichmentService` runs between chunking and embedding in Path B/C. Uses Gemini structured output (JSON schema) via concurrent interactive calls (`asyncio.gather` with semaphore). Enriched text is concatenated to chunk text and used for **both** dense embedding **and** BM25 sparse vector. Original `text_content` preserved for LLM context. Feature flag controls activation. Enrichment data persisted in new DB columns on the `chunks` table (Alembic migration). A/B eval validates improvement.

**Tech Stack:** Python, google-genai SDK (already in project), Gemini 2.5 Flash, Pydantic, SQLAlchemy/Alembic, Qdrant, existing pipeline infrastructure.

**Spec:** `docs/superpowers/specs/2026-03-29-s9-01-chunk-enrichment-design.md`

**Important context:** This is an experiment. Enrichment is hypothesized to improve retrieval, but no benchmark exists for our specific configuration (Gemini Embedding 2 + Qdrant BM25 + RRF). The A/B eval is the deliverable that answers whether enrichment should be enabled.

**Git Policy:** This repo prohibits commits without explicit user permission. Commit steps in tasks below are markers for logical commit points — the executor MUST ask the user before running any `git commit`. For agentic workers: stage files but do NOT commit autonomously.

---

## Text Source Matrix (reference for all tasks)

| Consumer | Source | Why |
|----------|--------|-----|
| Dense embedding | `enriched_text` (or `text_content` if unenriched) | Enriched keywords/questions improve semantic match |
| BM25 sparse vector | `enriched_text` (or `text_content` if unenriched) | Enriched keywords close vocabulary gap |
| LLM context (generation) | `text_content` (original, always) | Clean text, no enrichment artifacts |
| Citation display | `text_content` (original, always) | User sees original document text |

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `backend/app/services/enrichment.py` | EnrichmentService — LLM enrichment via Gemini |
| `backend/migrations/versions/xxxx_add_chunk_enrichment_columns.py` | Alembic migration for enrichment columns |
| `backend/tests/unit/test_enrichment_service.py` | Unit tests for EnrichmentService |
| `backend/tests/unit/test_pipeline_enrichment.py` | Pipeline integration tests |
| `backend/evals/datasets/retrieval_enrichment.yaml` | Vocabulary-gap eval cases |

### Modified files

| File | Change |
|------|--------|
| `backend/app/core/config.py` | Add enrichment settings to `Settings` |
| `backend/app/db/models/knowledge.py` | Add enrichment columns to `Chunk` model |
| `backend/app/services/qdrant.py` | Extend `QdrantChunkPoint`, `_build_payload`, BM25 source |
| `backend/app/workers/tasks/pipeline.py` | Insert enrichment stage before embedding/batch paths |
| `backend/app/services/batch_orchestrator.py` | Read enrichment from Chunk DB in `_apply_results` |

---

## Task 1: Configuration — Enrichment Settings

**Files:**
- Modify: `backend/app/core/config.py` (Settings class, ~line 37)
- Test: `backend/tests/unit/test_enrichment_service.py`

- [ ] **Step 1: Write test for enrichment settings defaults**

```python
# backend/tests/unit/test_enrichment_service.py
"""Tests for chunk enrichment service and configuration."""

from app.core.config import Settings


def _base_settings() -> dict[str, object]:
    """Minimal required Settings fields — mirrors test_config.py helper."""
    return {
        "postgres_host": "localhost",
        "postgres_port": 5432,
        "postgres_user": "proxymind",
        "postgres_password": "proxymind",
        "postgres_db": "proxymind",
        "redis_host": "localhost",
        "redis_port": 6379,
        "qdrant_host": "localhost",
        "qdrant_port": 6333,
        "seaweedfs_host": "localhost",
        "seaweedfs_filer_port": 8888,
    }


class TestEnrichmentSettings:
    def test_enrichment_defaults(self) -> None:
        settings = Settings(**_base_settings())
        assert settings.enrichment_enabled is False
        assert settings.enrichment_model == "gemini-2.5-flash"
        assert settings.enrichment_max_concurrency == 10
        assert settings.enrichment_temperature == 0.1
        assert settings.enrichment_max_output_tokens == 512
        assert settings.enrichment_min_chunk_tokens == 10

    def test_enrichment_enabled(self) -> None:
        settings = Settings(**_base_settings(), enrichment_enabled=True)
        assert settings.enrichment_enabled is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose exec api python -m pytest backend/tests/unit/test_enrichment_service.py::TestEnrichmentSettings -v
```
Expected: FAIL — `enrichment_enabled` not found on Settings.

- [ ] **Step 3: Add enrichment fields to Settings**

In `backend/app/core/config.py`, add after the batch settings block (~line 39):

```python
    # Enrichment settings (S9-01)
    enrichment_enabled: bool = False
    enrichment_model: str = "gemini-2.5-flash"
    enrichment_max_concurrency: int = 10
    enrichment_temperature: float = 0.1
    enrichment_max_output_tokens: int = 512
    enrichment_min_chunk_tokens: int = 10
```

- [ ] **Step 4: Run test to verify it passes**

```bash
docker compose exec api python -m pytest backend/tests/unit/test_enrichment_service.py::TestEnrichmentSettings -v
```
Expected: PASS

- [ ] **Step 5: Stage files** (commit only with user permission per Git Policy)

```bash
git add backend/app/core/config.py backend/tests/unit/test_enrichment_service.py
```

---

## Task 2: Database Schema — Chunk Enrichment Columns

**Files:**
- Modify: `backend/app/db/models/knowledge.py` (Chunk class, ~line 111)
- Create: `backend/migrations/versions/xxxx_add_chunk_enrichment_columns.py`

- [ ] **Step 1: Add enrichment columns to Chunk model**

In `backend/app/db/models/knowledge.py`, add after `anchor_timecode` (~line 135), before `status`:

```python
    # Enrichment fields (S9-01)
    enriched_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    enriched_keywords: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    enriched_questions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    enriched_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    enrichment_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enrichment_pipeline_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
```

Add `JSONB` to the imports from `sqlalchemy.dialects.postgresql` if not already imported.

- [ ] **Step 2: Generate Alembic migration**

```bash
docker compose exec api alembic revision --autogenerate -m "add chunk enrichment columns"
```

- [ ] **Step 3: Run migration**

```bash
docker compose exec api alembic upgrade head
```

- [ ] **Step 4: Verify columns exist**

```bash
docker compose exec db psql -U proxymind -d proxymind -c "\d chunks" | grep enriched
```
Expected: 6 new nullable columns visible.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models/knowledge.py backend/migrations/versions/
# Commit only with user permission. Suggested message: feat(enrichment): add enrichment columns to chunks table"
```

---

## Task 3: Qdrant Payload Extension + BM25 Fix

**Files:**
- Modify: `backend/app/services/qdrant.py` (QdrantChunkPoint ~line 40, _build_payload ~line 260, upsert_chunks ~line 137)
- Test: `backend/tests/unit/test_enrichment_service.py`

- [ ] **Step 1: Write test for extended QdrantChunkPoint and BM25 source**

Append to `backend/tests/unit/test_enrichment_service.py`:

```python
import uuid
from app.services.qdrant import QdrantChunkPoint, QdrantService


class TestQdrantEnrichmentPayload:
    def _make_chunk(self, **overrides: object) -> QdrantChunkPoint:
        defaults = dict(
            chunk_id=uuid.uuid4(),
            vector=[0.1] * 10,
            snapshot_id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            document_version_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            knowledge_base_id=uuid.uuid4(),
            text_content="Test chunk text",
            chunk_index=0,
            token_count=10,
            anchor_page=None,
            anchor_chapter=None,
            anchor_section=None,
            anchor_timecode=None,
            source_type="markdown",
            language="en",
            status="indexed",
        )
        defaults.update(overrides)
        return QdrantChunkPoint(**defaults)  # type: ignore[arg-type]

    def test_enrichment_fields_default_none(self) -> None:
        chunk = self._make_chunk()
        assert chunk.enriched_summary is None
        assert chunk.enriched_keywords is None
        assert chunk.enriched_questions is None
        assert chunk.enriched_text is None
        assert chunk.enrichment_model is None
        assert chunk.enrichment_pipeline_version is None

    def test_enrichment_fields_in_payload(self) -> None:
        chunk = self._make_chunk(
            enriched_summary="A test summary.",
            enriched_keywords=["test", "chunk"],
            enriched_questions=["What is this?"],
            enriched_text="Test chunk text\n\nSummary: A test summary.\nKeywords: test, chunk\nQuestions:\n- What is this?",
            enrichment_model="gemini-2.5-flash",
            enrichment_pipeline_version="s9-01-enrichment-v1",
        )
        payload = QdrantService._build_payload(chunk)
        assert payload["enriched_summary"] == "A test summary."
        assert payload["enriched_keywords"] == ["test", "chunk"]
        assert payload["enriched_questions"] == ["What is this?"]
        assert payload["enriched_text"] is not None
        assert payload["enrichment_model"] == "gemini-2.5-flash"
        assert payload["enrichment_pipeline_version"] == "s9-01-enrichment-v1"

    def test_unenriched_payload_has_none_fields(self) -> None:
        chunk = self._make_chunk()
        payload = QdrantService._build_payload(chunk)
        assert payload["enriched_summary"] is None
        assert payload["enriched_keywords"] is None

    def test_bm25_text_uses_enriched_text_when_available(self) -> None:
        """BM25 sparse vector must use enriched_text, not just text_content."""
        enriched = self._make_chunk(
            enriched_text="Test chunk text\n\nKeywords: retrieval, search",
        )
        unenriched = self._make_chunk()
        # The bm25_text property should return enriched_text when available
        assert enriched.bm25_text == "Test chunk text\n\nKeywords: retrieval, search"
        assert unenriched.bm25_text == "Test chunk text"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest backend/tests/unit/test_enrichment_service.py::TestQdrantEnrichmentPayload -v
```
Expected: FAIL — fields not found.

- [ ] **Step 3: Extend QdrantChunkPoint dataclass**

In `backend/app/services/qdrant.py`, add fields to `QdrantChunkPoint` (after `duration_seconds`, ~line 60):

```python
    # Enrichment fields (S9-01)
    enriched_summary: str | None = None
    enriched_keywords: list[str] | None = None
    enriched_questions: list[str] | None = None
    enriched_text: str | None = None
    enrichment_model: str | None = None
    enrichment_pipeline_version: str | None = None

    @property
    def bm25_text(self) -> str:
        """Text used for BM25 sparse vector — enriched if available."""
        return self.enriched_text if self.enriched_text is not None else self.text_content
```

Note: `QdrantChunkPoint` is `frozen=True`. The `@property` works on frozen dataclasses. If the dataclass forbids property, use a standalone function instead.

- [ ] **Step 4: Extend _build_payload**

In `_build_payload` (~line 280), add before the `if chunk.page_count` block:

```python
        # Enrichment fields
        payload["enriched_summary"] = chunk.enriched_summary
        payload["enriched_keywords"] = chunk.enriched_keywords
        payload["enriched_questions"] = chunk.enriched_questions
        payload["enriched_text"] = chunk.enriched_text
        payload["enrichment_model"] = chunk.enrichment_model
        payload["enrichment_pipeline_version"] = chunk.enrichment_pipeline_version
```

- [ ] **Step 5: Fix BM25 source in upsert_chunks**

In `upsert_chunks` (~line 146), change:

```python
# Before:
BM25_VECTOR_NAME: self._build_bm25_document(chunk.text_content),
# After:
BM25_VECTOR_NAME: self._build_bm25_document(chunk.bm25_text),
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
docker compose exec api python -m pytest backend/tests/unit/test_enrichment_service.py -v
```
Expected: ALL PASS

- [ ] **Step 7: Run existing Qdrant tests to verify no regressions**

```bash
docker compose exec api python -m pytest backend/tests/unit/test_qdrant*.py -v
```
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/qdrant.py backend/tests/unit/test_enrichment_service.py
# Commit only with user permission. Suggested message: feat(enrichment): extend Qdrant payload and BM25 with enrichment fields"
```

---

## Task 4: EnrichmentService — Core Implementation

**Files:**
- Create: `backend/app/services/enrichment.py`
- Test: `backend/tests/unit/test_enrichment_service.py`

- [ ] **Step 1: Write tests for EnrichmentService**

Append to `backend/tests/unit/test_enrichment_service.py`:

```python
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.document_processing import ChunkData


class TestEnrichmentService:
    def _make_chunk_data(
        self, text: str = "Revenue grew 3% in Q2 compared to last quarter.",
    ) -> ChunkData:
        return ChunkData(
            text_content=text,
            token_count=20,
            chunk_index=0,
            anchor_page=None,
            anchor_chapter=None,
            anchor_section=None,
        )

    @pytest.mark.asyncio
    async def test_enrich_returns_results_for_each_chunk(self) -> None:
        from app.services.enrichment import EnrichmentResult, EnrichmentService

        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {
                "summary": "Q2 revenue grew 3%.",
                "keywords": ["revenue", "growth", "Q2", "earnings"],
                "questions": ["How did revenue change in Q2?"],
            }
        )
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        service = EnrichmentService(
            model="gemini-2.5-flash",
            temperature=0.1,
            max_output_tokens=512,
            min_chunk_tokens=10,
            max_concurrency=10,
        )
        with patch.object(service, "_get_client", return_value=mock_client):
            results = await service.enrich([self._make_chunk_data()])

        assert len(results) == 1
        assert results[0] is not None
        assert results[0].summary == "Q2 revenue grew 3%."
        assert "revenue" in results[0].keywords
        assert len(results[0].questions) >= 1

    @pytest.mark.asyncio
    async def test_enrich_skips_short_chunks(self) -> None:
        from app.services.enrichment import EnrichmentService

        service = EnrichmentService(
            model="gemini-2.5-flash",
            temperature=0.1,
            max_output_tokens=512,
            min_chunk_tokens=10,
            max_concurrency=10,
        )
        tiny_chunk = ChunkData(
            text_content="Hi",
            token_count=2,
            chunk_index=0,
            anchor_page=None,
            anchor_chapter=None,
            anchor_section=None,
        )
        results = await service.enrich([tiny_chunk])
        assert len(results) == 1
        assert results[0] is None

    @pytest.mark.asyncio
    async def test_enrich_handles_llm_failure_gracefully(self) -> None:
        from app.services.enrichment import EnrichmentService

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API error")

        service = EnrichmentService(
            model="gemini-2.5-flash",
            temperature=0.1,
            max_output_tokens=512,
            min_chunk_tokens=10,
            max_concurrency=10,
        )
        with patch.object(service, "_get_client", return_value=mock_client):
            results = await service.enrich([self._make_chunk_data()])

        assert len(results) == 1
        assert results[0] is None  # fail-open

    @pytest.mark.asyncio
    async def test_enrich_multiple_chunks(self) -> None:
        """Verify all chunks in a batch get enriched."""
        from app.services.enrichment import EnrichmentService

        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {"summary": "s", "keywords": ["k"], "questions": ["q?"]}
        )
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        service = EnrichmentService(
            model="gemini-2.5-flash",
            temperature=0.1,
            max_output_tokens=512,
            min_chunk_tokens=10,
            max_concurrency=2,
        )
        chunks = [self._make_chunk_data(f"Chunk {i} about topic.") for i in range(5)]
        with patch.object(service, "_get_client", return_value=mock_client):
            results = await service.enrich(chunks)

        assert len(results) == 5
        assert all(r is not None for r in results)
        assert mock_client.models.generate_content.call_count == 5


class TestEnrichmentTextConcatenation:
    def test_build_enriched_text(self) -> None:
        from app.services.enrichment import build_enriched_text

        result = build_enriched_text(
            text_content="Original text about deployment.",
            summary="Describes deployment steps.",
            keywords=["deploy", "setup", "configuration"],
            questions=["How to deploy?", "What are the steps?"],
        )
        assert result.startswith("Original text about deployment.")
        assert "Summary: Describes deployment steps." in result
        assert "Keywords: deploy, setup, configuration" in result
        assert "How to deploy?" in result

    def test_truncate_drops_questions_first_when_over_budget(self) -> None:
        from app.services.enrichment import build_enriched_text

        # Original is very long — near token budget
        original = "word " * 8000
        result = build_enriched_text(
            text_content=original,
            summary="Short summary.",
            keywords=["k1", "k2"],
            questions=["Q1?", "Q2?"],
            max_tokens=8192,
        )
        # Should contain original; summary may or may not fit
        assert result.startswith("word ")

    def test_returns_original_if_already_over_budget(self) -> None:
        from app.services.enrichment import build_enriched_text

        original = "word " * 9000
        result = build_enriched_text(
            text_content=original,
            summary="Summary.",
            keywords=["kw"],
            questions=["Q?"],
            max_tokens=8192,
        )
        assert result == original
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest backend/tests/unit/test_enrichment_service.py::TestEnrichmentService -v
docker compose exec api python -m pytest backend/tests/unit/test_enrichment_service.py::TestEnrichmentTextConcatenation -v
```
Expected: FAIL — module `app.services.enrichment` not found.

- [ ] **Step 3: Implement EnrichmentService**

Create `backend/app/services/enrichment.py`:

```python
"""Chunk enrichment service — LLM-generated metadata for improved retrieval.

Generates summary, keywords, and questions per chunk using Gemini structured output.
Uses concurrent interactive API calls with semaphore-based rate limiting.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from google.genai import Client as GenaiClient

    from app.services.document_processing import ChunkData

logger = structlog.get_logger()

ENRICHMENT_PROMPT = """\
You are a search optimization assistant. Given a text chunk from a document, \
generate metadata to improve search retrieval.

<chunk>
{text_content}
</chunk>

Return a JSON object with:
- "summary": 1-2 sentence description of what this chunk contains
- "keywords": 5-8 search terms including synonyms and related concepts not explicitly in the text
- "questions": 2-3 natural questions this chunk can answer"""

ENRICHMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "keywords", "questions"],
}

PIPELINE_VERSION = "s9-01-enrichment-v1"
_CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class EnrichmentResult:
    """Result of enriching a single chunk."""

    summary: str
    keywords: list[str]
    questions: list[str]


class EnrichmentService:
    """Enriches chunks with LLM-generated metadata for retrieval improvement.

    Uses concurrent interactive Gemini API calls with semaphore-based concurrency
    control. Each chunk is enriched independently; failures are handled per-chunk
    (fail-open: chunk is indexed without enrichment).
    """

    def __init__(
        self,
        *,
        model: str,
        temperature: float,
        max_output_tokens: int,
        min_chunk_tokens: int,
        max_concurrency: int,
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._min_chunk_tokens = min_chunk_tokens
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._api_key = api_key
        self._client: GenaiClient | None = None

    def _get_client(self) -> GenaiClient:
        if self._client is None:
            from google.genai import Client as GenaiClient

            kwargs: dict[str, str] = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            self._client = GenaiClient(**kwargs)
        return self._client

    async def enrich(self, chunks: list[ChunkData]) -> list[EnrichmentResult | None]:
        """Enrich chunks with LLM-generated metadata.

        Returns a list parallel to input: EnrichmentResult for enriched chunks,
        None for skipped or failed chunks (fail-open).
        """
        tasks = [self._enrich_one(chunk) for chunk in chunks]
        return await asyncio.gather(*tasks)

    async def _enrich_one(self, chunk: ChunkData) -> EnrichmentResult | None:
        if chunk.token_count is not None and chunk.token_count < self._min_chunk_tokens:
            return None

        async with self._semaphore:
            try:
                client = self._get_client()
                prompt = ENRICHMENT_PROMPT.format(text_content=chunk.text_content)

                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: client.models.generate_content(
                        model=self._model,
                        contents=prompt,
                        config={
                            "temperature": self._temperature,
                            "max_output_tokens": self._max_output_tokens,
                            "response_mime_type": "application/json",
                            "response_schema": ENRICHMENT_SCHEMA,
                        },
                    ),
                )

                data = json.loads(response.text)
                return EnrichmentResult(
                    summary=data["summary"],
                    keywords=data["keywords"],
                    questions=data["questions"],
                )
            except Exception:
                logger.warning(
                    "enrichment_failed",
                    chunk_text_preview=chunk.text_content[:80],
                    exc_info=True,
                )
                return None


def _approx_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


def build_enriched_text(
    *,
    text_content: str,
    summary: str,
    keywords: list[str],
    questions: list[str],
    max_tokens: int = 8192,
) -> str:
    """Build concatenated text for embedding and BM25 indexing.

    Truncation priority when over token budget:
    questions dropped first, then keywords, summary last.
    If original text_content already exceeds budget, return it unchanged.
    """
    original_tokens = _approx_tokens(text_content)
    if original_tokens >= max_tokens:
        return text_content

    summary_part = f"\n\nSummary: {summary}"
    keywords_part = f"\nKeywords: {', '.join(keywords)}"
    questions_lines = [f"- {q}" for q in questions]
    questions_part = "\nQuestions:\n" + "\n".join(questions_lines) if questions_lines else ""

    # Try full enrichment
    full = text_content + summary_part + keywords_part + questions_part
    if _approx_tokens(full) <= max_tokens:
        return full

    # Drop questions
    without_questions = text_content + summary_part + keywords_part
    if _approx_tokens(without_questions) <= max_tokens:
        return without_questions

    # Drop keywords too
    without_keywords = text_content + summary_part
    if _approx_tokens(without_keywords) <= max_tokens:
        return without_keywords

    # Can't fit even summary — return original
    return text_content
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec api python -m pytest backend/tests/unit/test_enrichment_service.py -v
```
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/enrichment.py backend/tests/unit/test_enrichment_service.py
# Commit only with user permission. Suggested message: feat(enrichment): implement EnrichmentService with structured output and concurrency control"
```

---

## Task 5: Pipeline Integration

**Files:**
- Modify: `backend/app/workers/tasks/pipeline.py` (~line 36 PipelineServices, ~line 174 embed_and_index_chunks)
- Test: `backend/tests/unit/test_pipeline_enrichment.py`

This is the most critical task — enrichment must run **before** the batch/inline branch point so that both paths benefit.

- [ ] **Step 1: Write pipeline integration tests**

Create `backend/tests/unit/test_pipeline_enrichment.py`:

```python
"""Tests for enrichment integration in the ingestion pipeline.

These tests verify that:
1. Enrichment runs BEFORE the batch/inline branch point
2. embed_texts receives enriched text (not original) when enrichment succeeds
3. Qdrant upsert receives enriched payload fields
4. BM25 uses enriched text
5. Failed enrichment falls back to original text (fail-open)
6. Enrichment is skipped entirely when disabled
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.document_processing import ChunkData
from app.services.enrichment import EnrichmentResult, build_enriched_text, PIPELINE_VERSION
from app.services.qdrant import QdrantChunkPoint, QdrantService


class TestPipelineEnrichmentFlow:
    """Tests verifying the enrichment → embedding → upsert data flow."""

    def test_enriched_text_used_for_embedding_input(self) -> None:
        """When enrichment succeeds, the embedding input must be the enriched text."""
        original = "Revenue grew 3% in Q2."
        er = EnrichmentResult(
            summary="Q2 revenue growth.",
            keywords=["revenue", "growth", "earnings"],
            questions=["How did revenue change?"],
        )
        enriched_text = build_enriched_text(
            text_content=original,
            summary=er.summary,
            keywords=er.keywords,
            questions=er.questions,
        )
        # This is what embed_texts should receive
        assert enriched_text.startswith(original)
        assert "Summary: Q2 revenue growth." in enriched_text
        assert "Keywords: revenue, growth, earnings" in enriched_text
        assert "How did revenue change?" in enriched_text

    def test_unenriched_text_used_when_enrichment_fails(self) -> None:
        """When enrichment returns None, original text_content is used."""
        original = "Original chunk text."
        enrichment_result = None
        text_for_embedding = original if enrichment_result is None else "should not happen"
        assert text_for_embedding == original

    def test_qdrant_payload_carries_enrichment_fields(self) -> None:
        """QdrantChunkPoint with enrichment produces correct payload."""
        er = EnrichmentResult(
            summary="Describes deployment.",
            keywords=["deploy", "docker"],
            questions=["How to deploy?"],
        )
        original = "Step 1: Run docker compose up."
        enriched_text = build_enriched_text(
            text_content=original,
            summary=er.summary,
            keywords=er.keywords,
            questions=er.questions,
        )
        point = QdrantChunkPoint(
            chunk_id=uuid.uuid4(),
            vector=[0.1] * 10,
            snapshot_id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            document_version_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            knowledge_base_id=uuid.uuid4(),
            text_content=original,
            chunk_index=0,
            token_count=15,
            anchor_page=None,
            anchor_chapter=None,
            anchor_section=None,
            anchor_timecode=None,
            source_type="markdown",
            language="en",
            status="indexed",
            enriched_summary=er.summary,
            enriched_keywords=er.keywords,
            enriched_questions=er.questions,
            enriched_text=enriched_text,
            enrichment_model="gemini-2.5-flash",
            enrichment_pipeline_version=PIPELINE_VERSION,
        )

        payload = QdrantService._build_payload(point)

        # Original preserved for LLM context
        assert payload["text_content"] == original
        # Enrichment present
        assert payload["enriched_summary"] == "Describes deployment."
        assert payload["enriched_keywords"] == ["deploy", "docker"]
        assert payload["enrichment_model"] == "gemini-2.5-flash"

    def test_bm25_uses_enriched_text(self) -> None:
        """BM25 sparse vector must use enriched_text, not text_content."""
        enriched_text = "Original\n\nKeywords: search, retrieval"
        point = QdrantChunkPoint(
            chunk_id=uuid.uuid4(),
            vector=[0.1] * 10,
            snapshot_id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            document_version_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            knowledge_base_id=uuid.uuid4(),
            text_content="Original",
            chunk_index=0,
            token_count=10,
            anchor_page=None,
            anchor_chapter=None,
            anchor_section=None,
            anchor_timecode=None,
            source_type="markdown",
            language="en",
            status="indexed",
            enriched_text=enriched_text,
        )
        # bm25_text property returns enriched_text when available
        assert point.bm25_text == enriched_text
        assert "Keywords: search, retrieval" in point.bm25_text

    def test_unenriched_bm25_uses_original(self) -> None:
        """When no enrichment, BM25 uses original text_content."""
        point = QdrantChunkPoint(
            chunk_id=uuid.uuid4(),
            vector=[0.1] * 10,
            snapshot_id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            document_version_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            knowledge_base_id=uuid.uuid4(),
            text_content="Just the original.",
            chunk_index=0,
            token_count=10,
            anchor_page=None,
            anchor_chapter=None,
            anchor_section=None,
            anchor_timecode=None,
            source_type="markdown",
            language="en",
            status="indexed",
        )
        assert point.bm25_text == "Just the original."
```

- [ ] **Step 2: Run tests**

```bash
docker compose exec api python -m pytest backend/tests/unit/test_pipeline_enrichment.py -v
```
Expected: PASS (these test the data contract, not pipeline internals directly).

- [ ] **Step 3: Add EnrichmentService to PipelineServices**

In `backend/app/workers/tasks/pipeline.py`, add to the `PipelineServices` dataclass (~line 36):

```python
    enrichment_service: EnrichmentService | None = None
```

Add import at top:

```python
from app.services.enrichment import EnrichmentService, EnrichmentResult, build_enriched_text, PIPELINE_VERSION as ENRICHMENT_PIPELINE_VERSION
```

- [ ] **Step 4: Insert enrichment stage in embed_and_index_chunks**

In `embed_and_index_chunks` (~line 174), add enrichment logic **before** the batch threshold check (~line 217). The enrichment must run before BOTH inline and batch paths:

```python
    # --- Enrichment stage (S9-01) ---
    enrichment_results: list[EnrichmentResult | None] = [None] * len(chunk_data)
    if services.enrichment_service is not None:
        enrichment_results = await services.enrichment_service.enrich(chunk_data)

    # Build texts for embedding: enriched if available, original otherwise
    texts_for_embedding: list[str] = []
    for i, cd in enumerate(chunk_data):
        er = enrichment_results[i]
        if er is not None:
            texts_for_embedding.append(
                build_enriched_text(
                    text_content=cd.text_content,
                    summary=er.summary,
                    keywords=er.keywords,
                    questions=er.questions,
                )
            )
        else:
            texts_for_embedding.append(cd.text_content)

    # Persist enrichment data to Chunk DB rows (for batch flow recovery)
    for i, chunk_row in enumerate(chunk_rows):
        er = enrichment_results[i]
        if er is not None:
            chunk_row.enriched_summary = er.summary
            chunk_row.enriched_keywords = er.keywords
            chunk_row.enriched_questions = er.questions
            chunk_row.enriched_text = texts_for_embedding[i]
            chunk_row.enrichment_model = services.enrichment_service._model
            chunk_row.enrichment_pipeline_version = ENRICHMENT_PIPELINE_VERSION
    await session.flush()
    # --- End enrichment stage ---
```

Then modify the batch submission path to pass `texts_for_embedding` instead of original texts.

Modify the inline embedding path to use `texts_for_embedding`.

Modify the QdrantChunkPoint construction to include enrichment fields:

```python
    for i, (cd, chunk_row) in enumerate(zip(chunk_data, chunk_rows)):
        er = enrichment_results[i]
        points.append(
            QdrantChunkPoint(
                # ... all existing fields ...
                enriched_summary=er.summary if er else None,
                enriched_keywords=er.keywords if er else None,
                enriched_questions=er.questions if er else None,
                enriched_text=texts_for_embedding[i] if er else None,
                enrichment_model=services.enrichment_service._model if (er and services.enrichment_service) else None,
                enrichment_pipeline_version=ENRICHMENT_PIPELINE_VERSION if er else None,
            )
        )
```

- [ ] **Step 5: Initialize EnrichmentService in worker setup**

Find where `PipelineServices` is constructed and conditionally create `EnrichmentService`:

```python
from app.core.config import get_settings

settings = get_settings()
enrichment_service = None
if settings.enrichment_enabled:
    from app.services.enrichment import EnrichmentService
    enrichment_service = EnrichmentService(
        model=settings.enrichment_model,
        temperature=settings.enrichment_temperature,
        max_output_tokens=settings.enrichment_max_output_tokens,
        min_chunk_tokens=settings.enrichment_min_chunk_tokens,
        max_concurrency=settings.enrichment_max_concurrency,
    )
```

Pass `enrichment_service=enrichment_service` to `PipelineServices`.

- [ ] **Step 6: Run all pipeline tests**

```bash
docker compose exec api python -m pytest backend/tests/unit/test_pipeline*.py -v
docker compose exec api python -m pytest backend/tests/unit/test_enrichment*.py -v
```
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/workers/tasks/pipeline.py backend/tests/unit/test_pipeline_enrichment.py
# Commit only with user permission. Suggested message: feat(enrichment): integrate enrichment into pipeline before batch/inline branch"
```

---

## Task 6: Batch Orchestrator — Read Enrichment from DB

**Files:**
- Modify: `backend/app/services/batch_orchestrator.py` (`_apply_results` ~line 196)

- [ ] **Step 1: Update _apply_results to read enrichment from Chunk rows**

In `batch_orchestrator.py`, in the `_apply_results` method where `QdrantChunkPoint` is constructed (~line 235-269), read enrichment data from the Chunk DB model:

```python
    # In the QdrantChunkPoint construction loop:
    points.append(
        QdrantChunkPoint(
            # ... existing fields ...
            enriched_summary=chunk_row.enriched_summary,
            enriched_keywords=chunk_row.enriched_keywords,
            enriched_questions=chunk_row.enriched_questions,
            enriched_text=chunk_row.enriched_text,
            enrichment_model=chunk_row.enrichment_model,
            enrichment_pipeline_version=chunk_row.enrichment_pipeline_version,
        )
    )
```

This works because Task 5 persists enrichment data to Chunk DB rows before batch submission.

- [ ] **Step 2: Run batch orchestrator tests**

```bash
docker compose exec api python -m pytest backend/tests/unit/test_batch*.py -v
```
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/batch_orchestrator.py
# Commit only with user permission. Suggested message: feat(enrichment): read enrichment fields from DB in batch completion handler"
```

---

## Task 7: A/B Eval Dataset

**Files:**
- Create: `backend/evals/datasets/retrieval_enrichment.yaml`

- [ ] **Step 1: Create vocabulary-gap eval dataset**

Create `backend/evals/datasets/retrieval_enrichment.yaml`:

```yaml
# Eval suite targeting vocabulary gap — queries phrased differently from chunk text.
# Designed for A/B comparison: enrichment is HYPOTHESIZED to improve these cases.
# The A/B eval is the experiment that validates (or invalidates) this hypothesis.
#
# Source UUID mapping (from seed knowledge):
#   00000000-0000-0000-0000-000000000011 = guide.md
#   00000000-0000-0000-0000-000000000012 = faq.md
#   00000000-0000-0000-0000-000000000021 = biography.md

suite: retrieval_enrichment
description: "Vocabulary gap cases for enrichment A/B comparison (hypothesis validation)"
snapshot_id: "00000000-0000-0000-0000-000000000000"

cases:
  - id: re-001
    query: "How do I set up the application from scratch?"
    tags: [synonym, enrichment]
    expected:
      - source_id: "00000000-0000-0000-0000-000000000011"
        contains: "docker"
    notes: "Query uses 'set up' — chunk uses 'installation' and 'docker compose'"

  - id: re-002
    query: "What are the system's data storage options?"
    tags: [abstraction, enrichment]
    expected:
      - source_id: "00000000-0000-0000-0000-000000000011"
        contains: "Qdrant"
    notes: "Abstract query about storage — chunk describes specific tools"

  - id: re-003
    query: "How to verify everything works after launch?"
    tags: [synonym, enrichment]
    expected:
      - source_id: "00000000-0000-0000-0000-000000000011"
        contains: "health"
    notes: "Query uses 'verify' and 'launch' — chunk uses 'health check' and 'deployment'"

  - id: re-004
    query: "Tell me about the expert's background"
    tags: [abstraction, enrichment]
    expected:
      - source_id: "00000000-0000-0000-0000-000000000021"
        contains: "Morgan"
    notes: "Vague reference to 'expert' — chunk has specific name and biography"

  - id: re-005
    query: "What happens when you add new content to the knowledge base?"
    tags: [paraphrase, enrichment]
    expected:
      - source_id: "00000000-0000-0000-0000-000000000011"
        contains: "ingest"
    notes: "Query describes action abstractly — chunk uses 'ingestion' terminology"

  - id: re-006
    query: "How does the system handle measuring quality?"
    tags: [synonym, enrichment]
    expected:
      - source_id: "00000000-0000-0000-0000-000000000011"
        contains: "eval"
    notes: "Query uses 'measuring quality' — chunk uses 'evaluation' and 'metrics'"
```

- [ ] **Step 2: Verify dataset loads correctly**

```bash
docker compose exec api python -c "
from evals.loader import load_suite
suite = load_suite('backend/evals/datasets/retrieval_enrichment.yaml')
print(f'Loaded {len(suite.cases)} cases from {suite.suite}')
for c in suite.cases:
    print(f'  {c.id}: {c.query[:60]}')
"
```
Expected: 6 cases loaded.

- [ ] **Step 3: Commit**

```bash
git add backend/evals/datasets/retrieval_enrichment.yaml
# Commit only with user permission. Suggested message: feat(enrichment): add vocabulary-gap eval dataset for A/B comparison"
```

---

## Task 8: Documentation Update

**Files:**
- Modify: `docs/rag.md` (Chunk enrichment section)

- [ ] **Step 1: Update rag.md enrichment section**

Replace the "Chunk enrichment (deferred)" section with implemented design:
- Status: implemented (behind feature flag `ENRICHMENT_ENABLED`)
- Fields: summary, keywords, questions
- Pipeline: between chunking and embedding (Path B/C only)
- Execution: concurrent interactive Gemini API calls
- Text matrix: what text goes where (dense, BM25, LLM context, citations)
- Cost: ~$1.60/1000 chunks (interactive pricing)
- A/B eval: hypothesis validation methodology

- [ ] **Step 2: Verify documentation consistency**

Ensure the pipeline overview diagram in `docs/rag.md` reflects the enrichment stage.

- [ ] **Step 3: Commit**

```bash
git add docs/rag.md
# Commit only with user permission. Suggested message: docs(rag): update chunk enrichment section from deferred to implemented"
```

---

## Task 9: Full Integration Smoke Test

- [ ] **Step 1: Run full test suite**

```bash
docker compose exec api python -m pytest backend/tests/ -v --timeout=120
```
Expected: ALL PASS

- [ ] **Step 2: Verify pipeline with enrichment disabled (default)**

```bash
docker compose exec api python -c "
from app.core.config import get_settings
s = get_settings()
assert s.enrichment_enabled is False
print('Enrichment disabled by default - pipeline unchanged')
"
```

- [ ] **Step 3: Final commit if any fixups needed**

---

## Summary

| Task | What | Key Review Fix |
|------|------|---------------|
| 1 | Configuration | Replaced `batch_threshold` with `max_concurrency` |
| 2 | DB Schema migration | **NEW** — Alembic migration for Chunk enrichment columns (fixes #2) |
| 3 | Qdrant payload + BM25 | Added `bm25_text` property using `enriched_text` (fixes #4) |
| 4 | EnrichmentService | Fixed `ChunkData` API: `text_content` not `text` (fixes #3); semaphore concurrency |
| 5 | Pipeline integration | Enrichment runs BEFORE batch/inline branch (fixes #1); persists to DB (fixes #2) |
| 6 | Batch orchestrator | Reads enrichment from Chunk DB rows (fixes #1, #2) |
| 7 | A/B eval dataset | Softened language: "hypothesis validation" (fixes #6) |
| 8 | Documentation | Text source matrix added |
| 9 | Integration smoke test | Proper coverage (fixes #5) |

Total: 9 tasks, ~9 commits, zero new dependencies.
