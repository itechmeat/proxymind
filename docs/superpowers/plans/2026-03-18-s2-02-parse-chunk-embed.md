# S2-02: Parse + Chunk + Embed — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the noop ingestion worker with a real pipeline: download from MinIO → Docling parse → HybridChunker → Gemini Embedding 2 → Qdrant upsert.

**Architecture:** Three new services (DoclingParser, EmbeddingService, QdrantService) called sequentially by the worker task. No abstract orchestrator — the worker task IS the orchestrator. Two transaction boundaries: Tx 1 persists chunks in PG before external calls, Tx 2 finalizes after Qdrant upsert.

**Tech Stack:** Python 3.14, FastAPI, Docling 2.80+, google-genai 1.14+, qdrant-client 1.14+, SQLAlchemy 2.0, Alembic, arq, tenacity, pytest

**Spec:** `docs/superpowers/specs/2026-03-18-s2-02-parse-chunk-embed-design.md`

**Pre-implementation:** Before writing any code, read `docs/development.md` and treat it as binding.

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `backend/app/services/docling_parser.py` | Parse files via Docling + HybridChunker → list of ChunkData |
| `backend/app/services/embedding.py` | Batch embed via Google GenAI SDK with tenacity retry |
| `backend/app/services/qdrant.py` | Qdrant collection management + point upsert |
| `backend/app/services/snapshot.py` | get_or_create_draft snapshot |
| `backend/migrations/versions/004_s2_02_language_and_draft_index.py` | Migration: language column + partial unique index |
| `backend/tests/unit/services/test_docling_parser.py` | DoclingParser unit tests |
| `backend/tests/unit/services/test_embedding.py` | EmbeddingService unit tests |
| `backend/tests/unit/services/test_qdrant.py` | QdrantService unit tests |
| `backend/tests/unit/services/test_storage_download.py` | StorageService.download unit test |
| `backend/tests/integration/test_snapshot.py` | SnapshotService integration tests (needs real PG) |
| `backend/tests/integration/test_qdrant_roundtrip.py` | Real Qdrant integration test |
| `backend/tests/fixtures/sample.md` | Test fixture: MD file with headings |
| `backend/tests/fixtures/sample_small.md` | Test fixture: single-section MD |
| `backend/tests/fixtures/sample.txt` | Test fixture: plain text |

### Modified files

| File | Changes |
|------|---------|
| `backend/pyproject.toml` | Add docling, google-genai, qdrant-client deps |
| `backend/app/core/config.py` | Add embedding/chunking/qdrant settings |
| `backend/app/services/storage.py` | Add `download()` method |
| `backend/app/services/source.py` | Persist `language` from metadata |
| `backend/app/services/__init__.py` | Export new services |
| `backend/app/db/models/knowledge.py` | Add `language` column to Source |
| `backend/app/workers/main.py` | Initialize new services in worker context |
| `backend/app/workers/tasks/ingestion.py` | Replace noop with real pipeline |
| `backend/tests/conftest.py` | Add Qdrant testcontainer fixture |
| `backend/tests/integration/test_ingestion_worker.py` | Update to test real pipeline |

---

## Task 1: Dependencies and Configuration

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/core/config.py`

- [ ] **Step 1: Add new dependencies to pyproject.toml**

Add to `[project.dependencies]`:
```toml
"docling>=2.80.0",
"google-genai>=1.14.0",
"qdrant-client>=1.14.0",
```

- [ ] **Step 2: Install dependencies**

Run: `cd backend && uv sync`
Expected: all packages install without conflict

- [ ] **Step 3: Add new Settings fields to config.py**

Read `backend/app/core/config.py` first. Add these fields to the `Settings` class:

```python
# Embedding (Gemini)
gemini_api_key: str = ""
embedding_model: str = "gemini-embedding-2-preview"
embedding_dimensions: int = 3072
embedding_batch_size: int = 100

# Chunking
chunk_max_tokens: int = 1024

# Qdrant
qdrant_collection: str = "proxymind_chunks"

# Language
bm25_language: str = "english"
```

Note: `gemini_api_key` defaults to empty string for CI (tests mock the SDK). Real deployments MUST set it via `.env`.

- [ ] **Step 4: Ensure env vars are set**

Ensure `GEMINI_API_KEY` is set in your `.env` files (not committed to git).

- [ ] **Step 5: Verify settings load**

Run: `cd backend && python -c "from app.core.config import get_settings; s = get_settings(); print(s.embedding_dimensions, s.qdrant_collection)"`
Expected: `3072 proxymind_chunks`

- [ ] **Step 6: Checkpoint**

All tests pass. Files ready for commit when user requests:
- `backend/pyproject.toml`
- `backend/uv.lock`
- `backend/app/core/config.py`

---

## Task 2: Alembic Migration

**Files:**
- Create: `backend/migrations/versions/004_s2_02_language_and_draft_index.py`
- Modify: `backend/app/db/models/knowledge.py`

- [ ] **Step 1: Add language column to Source model**

Read `backend/app/db/models/knowledge.py`. Add to the `Source` class:

```python
language: Mapped[str | None] = mapped_column(String(32), nullable=True)
```

Place it after `mime_type`.

- [ ] **Step 2: Create Alembic migration**

Run: `cd backend && alembic revision --autogenerate -m "add source language column and draft snapshot unique index"`

- [ ] **Step 3: Edit the generated migration**

The autogenerate will create the `language` column. Manually add the partial unique index:

```python
def upgrade() -> None:
    # ... autogenerated column add ...
    op.create_index(
        "uq_one_draft_per_scope",
        "knowledge_snapshots",
        ["agent_id", "knowledge_base_id"],
        unique=True,
        postgresql_where=text("status = 'draft'"),
    )

def downgrade() -> None:
    op.drop_index("uq_one_draft_per_scope", table_name="knowledge_snapshots")
    # ... autogenerated column drop ...
```

**Note on `owner_id` exclusion:** The tenant-ready fields include `owner_id` (from `TenantMixin`), but it is intentionally excluded from this index. Reasons: (1) `owner_id` is nullable — PG treats NULLs as distinct in unique indexes, so `(NULL, agent_1, kb_1)` and `(NULL, agent_1, kb_1)` would NOT conflict, defeating the purpose. (2) In the current single-instance model, `agent_id` already implies the owner context. (3) If multi-owner support is added later, the index can be recreated with `owner_id` as part of that story.

- [ ] **Step 4: Run migration**

Run: `cd backend && alembic upgrade head`
Expected: migration applies cleanly

- [ ] **Step 5: Verify**

Run: `cd backend && alembic check`
Expected: no pending migrations

- [ ] **Step 6: Checkpoint**

All tests pass. Files ready for commit when user requests:
- `backend/app/db/models/knowledge.py`
- `backend/migrations/versions/004_s2_02_language_and_draft_index.py`

---

## Task 3: StorageService.download()

**Files:**
- Modify: `backend/app/services/storage.py`
- Test: `backend/tests/unit/test_source_validation.py` (or new test file)

- [ ] **Step 1: Write failing test**

Add to existing tests or create `backend/tests/unit/services/test_storage_download.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from app.services.storage import StorageService

@pytest.mark.asyncio
async def test_download_returns_file_bytes():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.read.return_value = b"# Hello World"
    mock_response.close = MagicMock()
    mock_response.release_conn = MagicMock()
    mock_client.get_object.return_value = mock_response

    service = StorageService(client=mock_client, bucket_name="test-bucket")
    result = await service.download("agent/source/file.md")

    assert result == b"# Hello World"
    mock_client.get_object.assert_called_once_with("test-bucket", "agent/source/file.md")
    mock_response.close.assert_called_once()
    mock_response.release_conn.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/services/test_storage_download.py -v`
Expected: FAIL (download method doesn't exist)

- [ ] **Step 3: Implement download method**

Read `backend/app/services/storage.py`. Add the `download` method:

```python
async def download(self, object_key: str) -> bytes:
    response = await asyncio.to_thread(
        self._client.get_object, self.bucket_name, object_key
    )
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()
```

Add `import asyncio` if not already present.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/unit/services/test_storage_download.py -v`
Expected: PASS

- [ ] **Step 5: Checkpoint**

All tests pass. Files ready for commit when user requests:
- `backend/app/services/storage.py`
- `backend/tests/unit/services/test_storage_download.py`

---

## Task 4: DoclingParser

**Files:**
- Create: `backend/app/services/docling_parser.py`
- Create: `backend/tests/unit/services/test_docling_parser.py`
- Create: `backend/tests/fixtures/sample.md`
- Create: `backend/tests/fixtures/sample_small.md`
- Create: `backend/tests/fixtures/sample.txt`

- [ ] **Step 1: Create test fixtures**

`backend/tests/fixtures/sample.md`:
```markdown
# Introduction

This is the first section about artificial intelligence.
It covers the basics of machine learning and neural networks.
The field has grown rapidly in recent years.

## History

The history of AI dates back to the 1950s when Alan Turing
proposed the Turing test. Early AI research focused on
symbolic reasoning and rule-based systems.

## Modern Approaches

Modern AI uses deep learning and transformer architectures.
Large language models have revolutionized natural language processing.
```

`backend/tests/fixtures/sample_small.md`:
```markdown
# Simple Document

A short paragraph with minimal content.
```

`backend/tests/fixtures/sample.txt`:
```text
This is a plain text document without any structure.
It contains multiple sentences that should be chunked based on size.
The chunker should handle plain text gracefully.
```

- [ ] **Step 2: Write failing tests**

Create `backend/tests/unit/services/test_docling_parser.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from app.db.models.enums import SourceType
from app.services.docling_parser import ChunkData, DoclingParser

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def test_chunk_data_has_required_fields():
    chunk = ChunkData(
        text_content="hello",
        token_count=1,
        chunk_index=0,
        anchor_page=None,
        anchor_chapter=None,
        anchor_section="Introduction",
    )
    assert chunk.text_content == "hello"
    assert chunk.anchor_section == "Introduction"


def test_parse_markdown_produces_chunks():
    parser = DoclingParser(chunk_max_tokens=1024)
    content = (FIXTURES / "sample.md").read_bytes()
    chunks = parser.parse_and_chunk(content, "sample.md", SourceType.MARKDOWN)

    assert len(chunks) >= 1
    assert all(isinstance(c, ChunkData) for c in chunks)
    assert all(c.text_content for c in chunks)
    assert chunks[0].chunk_index == 0


def test_parse_markdown_extracts_section_anchors():
    parser = DoclingParser(chunk_max_tokens=1024)
    content = (FIXTURES / "sample.md").read_bytes()
    chunks = parser.parse_and_chunk(content, "sample.md", SourceType.MARKDOWN)

    sections = [c.anchor_section for c in chunks if c.anchor_section]
    assert len(sections) > 0  # At least some chunks have section metadata


def test_parse_txt_produces_chunks():
    parser = DoclingParser(chunk_max_tokens=1024)
    content = (FIXTURES / "sample.txt").read_bytes()
    chunks = parser.parse_and_chunk(content, "sample.txt", SourceType.TXT)

    assert len(chunks) >= 1
    assert all(c.text_content for c in chunks)


def test_parse_small_file_single_chunk():
    parser = DoclingParser(chunk_max_tokens=4096)
    content = (FIXTURES / "sample_small.md").read_bytes()
    chunks = parser.parse_and_chunk(content, "small.md", SourceType.MARKDOWN)

    assert len(chunks) >= 1


def test_parse_empty_content_returns_empty():
    parser = DoclingParser(chunk_max_tokens=1024)
    chunks = parser.parse_and_chunk(b"", "empty.md", SourceType.MARKDOWN)

    assert chunks == []


def test_chunk_indices_are_sequential():
    parser = DoclingParser(chunk_max_tokens=256)  # Small to force multiple chunks
    content = (FIXTURES / "sample.md").read_bytes()
    chunks = parser.parse_and_chunk(content, "sample.md", SourceType.MARKDOWN)

    if len(chunks) > 1:
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/services/test_docling_parser.py -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 4: Implement DoclingParser**

Create `backend/app/services/docling_parser.py`:

```python
from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path

from docling.document_converter import DocumentConverter
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker

from app.db.models.enums import SourceType


@dataclass(frozen=True, slots=True)
class ChunkData:
    text_content: str
    token_count: int
    chunk_index: int
    anchor_page: int | None
    anchor_chapter: str | None
    anchor_section: str | None


_EXTENSION_MAP: dict[SourceType, str] = {
    SourceType.MARKDOWN: ".md",
    SourceType.TXT: ".txt",
}


class DoclingParser:
    def __init__(self, chunk_max_tokens: int = 1024) -> None:
        self._chunk_max_tokens = chunk_max_tokens

    async def parse_and_chunk_async(
        self, file_content: bytes, filename: str, source_type: SourceType
    ) -> list[ChunkData]:
        return await asyncio.to_thread(
            self.parse_and_chunk, file_content, filename, source_type
        )

    def parse_and_chunk(
        self, file_content: bytes, filename: str, source_type: SourceType
    ) -> list[ChunkData]:
        if not file_content:
            return []

        ext = _EXTENSION_MAP.get(source_type, Path(filename).suffix or ".txt")

        with tempfile.NamedTemporaryFile(suffix=ext, delete=True) as tmp:
            tmp.write(file_content)
            tmp.flush()
            tmp_path = Path(tmp.name)

            converter = DocumentConverter()
            result = converter.convert(tmp_path)

        chunker = HybridChunker(max_tokens=self._chunk_max_tokens)
        doc_chunks = list(chunker.chunk(result.document))

        chunks: list[ChunkData] = []
        for idx, chunk in enumerate(doc_chunks):
            text = chunk.text
            if not text or not text.strip():
                continue

            # Extract anchor metadata from chunk headings/metadata
            meta = chunk.meta or {}
            headings = meta.get("headings", [])

            anchor_section = headings[-1] if headings else None
            anchor_chapter = headings[0] if len(headings) > 1 else None
            anchor_page = meta.get("page") if isinstance(meta.get("page"), int) else None

            chunks.append(
                ChunkData(
                    text_content=text.strip(),
                    token_count=len(text.split()),  # Approximate; Docling tokenizer is more precise
                    chunk_index=len(chunks),
                    anchor_page=anchor_page,
                    anchor_chapter=anchor_chapter,
                    anchor_section=anchor_section,
                )
            )

        return chunks
```

**Important:** The exact Docling API (chunk.meta, headings extraction) MUST be verified against the installed Docling version at implementation time. The above is based on Docling 2.x API — read Docling's documentation or source to confirm the `HybridChunker` output format and available metadata fields. Adjust the anchor extraction accordingly.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/services/test_docling_parser.py -v`
Expected: PASS (adjust implementation if Docling API differs)

- [ ] **Step 6: Checkpoint**

All tests pass. Files ready for commit when user requests:
- `backend/app/services/docling_parser.py`
- `backend/tests/unit/services/test_docling_parser.py`
- `backend/tests/fixtures/sample.md`
- `backend/tests/fixtures/sample_small.md`
- `backend/tests/fixtures/sample.txt`

---

## Task 5: EmbeddingService

**Files:**
- Create: `backend/app/services/embedding.py`
- Create: `backend/tests/unit/services/test_embedding.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/services/test_embedding.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.embedding import EmbeddingService


def _make_mock_client(dimensions: int = 3072, num_results: int = 1):
    """Create a mock Google GenAI client that returns fake embeddings."""
    mock_client = MagicMock()

    def mock_embed(*args, **kwargs):
        contents = kwargs.get("contents") or args[1] if len(args) > 1 else []
        n = len(contents) if isinstance(contents, list) else num_results
        embeddings = [MagicMock(values=[0.1] * dimensions) for _ in range(n)]
        return MagicMock(embeddings=embeddings)

    mock_client.models.embed_content = mock_embed
    return mock_client


@pytest.mark.asyncio
async def test_embed_single_text():
    client = _make_mock_client(dimensions=3072, num_results=1)
    service = EmbeddingService(
        client=client, model="test-model", dimensions=3072, batch_size=100
    )
    vectors = await service.embed_texts(["hello world"])

    assert len(vectors) == 1
    assert len(vectors[0]) == 3072


@pytest.mark.asyncio
async def test_embed_batching():
    call_count = 0
    original_embed = None

    client = MagicMock()

    def tracking_embed(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        contents = kwargs.get("contents") or []
        n = len(contents) if isinstance(contents, list) else 1
        embeddings = [MagicMock(values=[0.1] * 10) for _ in range(n)]
        return MagicMock(embeddings=embeddings)

    client.models.embed_content = tracking_embed

    service = EmbeddingService(
        client=client, model="test-model", dimensions=10, batch_size=3
    )
    vectors = await service.embed_texts(["a", "b", "c", "d", "e"])

    assert len(vectors) == 5
    assert call_count == 2  # batch of 3 + batch of 2


@pytest.mark.asyncio
async def test_embed_empty_input():
    client = MagicMock()
    service = EmbeddingService(
        client=client, model="test-model", dimensions=10, batch_size=100
    )
    vectors = await service.embed_texts([])

    assert vectors == []
    client.models.embed_content.assert_not_called()


@pytest.mark.asyncio
async def test_embed_retries_on_transient_error():
    client = MagicMock()
    attempt = 0

    def flaky_embed(*args, **kwargs):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            from google.api_core.exceptions import ServiceUnavailable
            raise ServiceUnavailable("temporary")
        contents = kwargs.get("contents") or []
        n = len(contents) if isinstance(contents, list) else 1
        return MagicMock(embeddings=[MagicMock(values=[0.1] * 10) for _ in range(n)])

    client.models.embed_content = flaky_embed

    service = EmbeddingService(
        client=client, model="test-model", dimensions=10, batch_size=100
    )
    vectors = await service.embed_texts(["test"])

    assert len(vectors) == 1
    assert attempt == 2  # First failed, second succeeded
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/services/test_embedding.py -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Implement EmbeddingService**

Create `backend/app/services/embedding.py`:

```python
from __future__ import annotations

import asyncio

import structlog
from google import genai
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)


class EmbeddingService:
    def __init__(
        self,
        client: genai.Client,
        model: str,
        dimensions: int,
        batch_size: int = 100,
    ) -> None:
        self._client = client
        self._model = model
        self._dimensions = dimensions
        self._batch_size = batch_size

    async def embed_texts(
        self,
        texts: list[str],
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> list[list[float]]:
        if not texts:
            return []

        all_vectors: list[list[float]] = []

        for batch_start in range(0, len(texts), self._batch_size):
            batch = texts[batch_start : batch_start + self._batch_size]
            vectors = await self._embed_batch(batch, task_type)
            all_vectors.extend(vectors)

        return all_vectors

    async def _embed_batch(
        self, texts: list[str], task_type: str
    ) -> list[list[float]]:
        result = await asyncio.to_thread(self._embed_batch_sync, texts, task_type)
        return result

    @retry(
        retry=retry_if_exception_type(Exception),  # Narrow this at implementation time
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _embed_batch_sync(self, texts: list[str], task_type: str) -> list[list[float]]:
        # Verify exact API at implementation time — SDK may have changed
        response = self._client.models.embed_content(
            model=self._model,
            contents=texts,
            config={
                "task_type": task_type,
                "output_dimensionality": self._dimensions,
            },
        )
        return [emb.values for emb in response.embeddings]
```

**Important:** The exact Google GenAI SDK API (`client.models.embed_content` parameters, `config` dict vs keyword args, response shape) MUST be verified at implementation time. Run `python -c "import google.genai; help(google.genai.Client)"` and check the actual method signatures.

Also narrow the tenacity `retry_if_exception_type` to actual transient exceptions from `google.api_core.exceptions` (e.g., `ServiceUnavailable`, `ResourceExhausted`, `TooManyRequests`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/services/test_embedding.py -v`
Expected: PASS (adjust mock structure if GenAI SDK API differs)

- [ ] **Step 5: Checkpoint**

All tests pass. Files ready for commit when user requests:
- `backend/app/services/embedding.py`
- `backend/tests/unit/services/test_embedding.py`

---

## Task 6: QdrantService

**Files:**
- Create: `backend/app/services/qdrant.py`
- Create: `backend/tests/unit/services/test_qdrant.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/services/test_qdrant.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from app.services.qdrant import CollectionSchemaMismatchError, QdrantService


def _make_mock_client(collection_exists: bool = False, existing_size: int = 3072):
    client = AsyncMock()

    if collection_exists:
        collection_info = MagicMock()
        dense_params = MagicMock()
        dense_params.size = existing_size
        collection_info.config.params.vectors = {"dense": dense_params}
        client.get_collection.return_value = collection_info
    else:
        from qdrant_client.http.exceptions import UnexpectedResponse
        client.get_collection.side_effect = UnexpectedResponse(
            status_code=404, reason_phrase="Not found", content=b""
        )

    return client


@pytest.mark.asyncio
async def test_ensure_collection_creates_when_missing():
    client = _make_mock_client(collection_exists=False)
    service = QdrantService(
        client=client, collection_name="test", vector_size=3072
    )
    await service.ensure_collection()

    client.create_collection.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_collection_noop_when_exists_with_matching_schema():
    client = _make_mock_client(collection_exists=True, existing_size=3072)
    service = QdrantService(
        client=client, collection_name="test", vector_size=3072
    )
    await service.ensure_collection()

    client.create_collection.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_collection_raises_on_dimension_mismatch():
    client = _make_mock_client(collection_exists=True, existing_size=3072)
    service = QdrantService(
        client=client, collection_name="test", vector_size=1024
    )

    with pytest.raises(CollectionSchemaMismatchError, match="3072.*1024"):
        await service.ensure_collection()


@pytest.mark.asyncio
async def test_upsert_chunks_calls_client():
    client = AsyncMock()
    service = QdrantService(
        client=client, collection_name="test", vector_size=3072
    )

    points = [
        {
            "id": "abc-123",
            "vector": {"dense": [0.1] * 3072},
            "payload": {"snapshot_id": "snap-1", "text_content": "hello"},
        }
    ]
    await service.upsert_chunks(points)

    client.upsert.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/services/test_qdrant.py -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Implement QdrantService**

Create `backend/app/services/qdrant.py`:

```python
from __future__ import annotations

from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

logger = structlog.get_logger(__name__)


class CollectionSchemaMismatchError(Exception):
    pass


_PAYLOAD_INDEXES: list[tuple[str, PayloadSchemaType]] = [
    ("snapshot_id", PayloadSchemaType.KEYWORD),
    ("agent_id", PayloadSchemaType.KEYWORD),
    ("knowledge_base_id", PayloadSchemaType.KEYWORD),
    ("source_id", PayloadSchemaType.KEYWORD),
    ("status", PayloadSchemaType.KEYWORD),
    ("source_type", PayloadSchemaType.KEYWORD),
    ("language", PayloadSchemaType.KEYWORD),
]


class QdrantService:
    def __init__(
        self,
        client: AsyncQdrantClient,
        collection_name: str,
        vector_size: int,
    ) -> None:
        self._client = client
        self._collection_name = collection_name
        self._vector_size = vector_size

    async def ensure_collection(self) -> None:
        try:
            info = await self._client.get_collection(self._collection_name)
            existing_dense = info.config.params.vectors.get("dense")
            if existing_dense and existing_dense.size != self._vector_size:
                raise CollectionSchemaMismatchError(
                    f"Collection '{self._collection_name}' has dense vector size "
                    f"{existing_dense.size} but settings require {self._vector_size}. "
                    f"Reindex required — delete the collection and re-run ingestion."
                )
            logger.info(
                "qdrant.collection_exists",
                collection=self._collection_name,
                vector_size=self._vector_size,
            )
            return
        except UnexpectedResponse as exc:
            if exc.status_code != 404:
                raise

        await self._client.create_collection(
            collection_name=self._collection_name,
            vectors_config={
                "dense": VectorParams(
                    size=self._vector_size,
                    distance=Distance.COSINE,
                )
            },
        )

        for field_name, schema_type in _PAYLOAD_INDEXES:
            await self._client.create_payload_index(
                collection_name=self._collection_name,
                field_name=field_name,
                field_schema=schema_type,
            )

        logger.info(
            "qdrant.collection_created",
            collection=self._collection_name,
            vector_size=self._vector_size,
            indexes=len(_PAYLOAD_INDEXES),
        )

    async def upsert_chunks(self, points: list[dict[str, Any]]) -> None:
        if not points:
            return

        qdrant_points = [
            PointStruct(
                id=p["id"],
                vector=p["vector"],
                payload=p["payload"],
            )
            for p in points
        ]

        await self._client.upsert(
            collection_name=self._collection_name,
            points=qdrant_points,
        )

        logger.info(
            "qdrant.chunks_upserted",
            collection=self._collection_name,
            count=len(qdrant_points),
        )
```

**Important:** Verify qdrant-client async API at implementation time. The `AsyncQdrantClient` methods, `UnexpectedResponse` import path, and `VectorParams`/`PointStruct` models may have changed. Check `qdrant-client` docs or source.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/services/test_qdrant.py -v`
Expected: PASS

- [ ] **Step 5: Checkpoint**

All tests pass. Files ready for commit when user requests:
- `backend/app/services/qdrant.py`
- `backend/tests/unit/services/test_qdrant.py`

---

## Task 7: SnapshotService

**Files:**
- Create: `backend/app/services/snapshot.py`
- Create: `backend/tests/integration/test_snapshot.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/integration/test_snapshot.py`:

```python
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import KnowledgeSnapshot
from app.db.models.enums import SnapshotStatus
from app.services.snapshot import SnapshotService


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_creates_draft_when_none_exists(
    db_session: AsyncSession,
) -> None:
    service = SnapshotService(db_session)
    snapshot = await service.get_or_create_draft(
        DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
    )

    assert snapshot is not None
    assert snapshot.status is SnapshotStatus.DRAFT
    assert snapshot.agent_id == DEFAULT_AGENT_ID
    assert snapshot.knowledge_base_id == DEFAULT_KNOWLEDGE_BASE_ID
    assert snapshot.name is not None


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_reuses_existing_draft(
    db_session: AsyncSession,
) -> None:
    service = SnapshotService(db_session)
    first = await service.get_or_create_draft(
        DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
    )
    second = await service.get_or_create_draft(
        DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
    )

    assert first.id == second.id


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_different_scope_creates_separate_drafts(
    db_session: AsyncSession,
) -> None:
    other_kb = uuid.uuid7()
    service = SnapshotService(db_session)
    snap_a = await service.get_or_create_draft(
        DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
    )
    snap_b = await service.get_or_create_draft(
        DEFAULT_AGENT_ID, other_kb
    )

    assert snap_a.id != snap_b.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/services/test_snapshot.py -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Implement SnapshotService**

Create `backend/app/services/snapshot.py`:

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeSnapshot
from app.db.models.enums import SnapshotStatus


class SnapshotService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create_draft(
        self,
        agent_id: uuid.UUID,
        knowledge_base_id: uuid.UUID,
    ) -> KnowledgeSnapshot:
        # Try INSERT ON CONFLICT DO NOTHING (uses partial unique index)
        new_id = uuid.uuid7()
        stmt = (
            pg_insert(KnowledgeSnapshot)
            .values(
                id=new_id,
                agent_id=agent_id,
                knowledge_base_id=knowledge_base_id,
                status=SnapshotStatus.DRAFT,
                name=f"Draft {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}",
                chunk_count=0,
            )
            .on_conflict_do_nothing(
                index_elements=["agent_id", "knowledge_base_id"],
                index_where=KnowledgeSnapshot.status == SnapshotStatus.DRAFT,
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

        # SELECT the existing or newly created draft
        query = select(KnowledgeSnapshot).where(
            KnowledgeSnapshot.agent_id == agent_id,
            KnowledgeSnapshot.knowledge_base_id == knowledge_base_id,
            KnowledgeSnapshot.status == SnapshotStatus.DRAFT,
        )
        snapshot = await self._session.scalar(query)
        assert snapshot is not None, "Draft snapshot must exist after INSERT ON CONFLICT"
        return snapshot
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/services/test_snapshot.py -v`
Expected: PASS

Note: These tests use real PG (via conftest.py fixtures). They need the `committed_data_cleanup` fixture and `migrated_database`.

- [ ] **Step 5: Checkpoint**

All tests pass. Files ready for commit when user requests:
- `backend/app/services/snapshot.py`
- `backend/tests/integration/test_snapshot.py`

---

## Task 8: Fix Source Language Persistence

**Files:**
- Modify: `backend/app/services/source.py`
- Modify: `backend/tests/integration/test_source_upload.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/integration/test_source_upload.py` (or appropriate test file):

```python
@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_source_persists_language(api_client, session_factory):
    # Upload with language in metadata
    response = await api_client.post(
        "/api/admin/sources",
        files={"file": ("test.md", b"# Hello", "text/markdown")},
        data={"metadata": '{"title": "Test", "language": "russian"}'},
    )
    assert response.status_code == 202
    source_id = response.json()["source_id"]

    async with session_factory() as session:
        source = await session.get(Source, uuid.UUID(source_id))
    assert source is not None
    assert source.language == "russian"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/integration/test_source_upload.py::test_source_persists_language -v`
Expected: FAIL (language not persisted)

- [ ] **Step 3: Fix source.py to persist language**

Read `backend/app/services/source.py`. Find `create_source_and_task()`. The method already receives the full `metadata` object and unpacks fields into the Source constructor. Simply add `language=metadata.language` to the Source constructor call. No changes to `admin.py` needed — the service contract already passes the full metadata.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/integration/test_source_upload.py::test_source_persists_language -v`
Expected: PASS

- [ ] **Step 5: Checkpoint**

All tests pass. Files ready for commit when user requests:
- `backend/app/services/source.py`
- `backend/tests/integration/test_source_upload.py`

---

## Task 9: Worker Ingestion Pipeline

**Files:**
- Modify: `backend/app/workers/tasks/ingestion.py`
- Modify: `backend/tests/integration/test_ingestion_worker.py`

This is the largest task — replacing `_run_noop_ingestion` with the real pipeline.

- [ ] **Step 1: Update existing tests to expect real behavior**

Read `backend/tests/integration/test_ingestion_worker.py`. The existing tests call `process_ingestion` directly. They need to be updated to:
1. Mock the external services (EmbeddingService, QdrantService) in the worker context
2. Provide a real file in MinIO (or mock StorageService.download)
3. Verify Document, DocumentVersion, Chunk records are created
4. Verify progress tracking

Update `_seed_task` to also put a real file in MinIO or mock the download.

Write new test that verifies the full pipeline creates correct records:

```python
@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_pipeline_creates_document_and_chunks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_task(session_factory)
    mock_storage = SimpleNamespace(download=AsyncMock(return_value=b"# Test\n\nSome content"))
    mock_embedding = SimpleNamespace(
        model="test-model",
        dimensions=3072,
        embed_texts=AsyncMock(return_value=[[0.1] * 3072]),
    )
    mock_qdrant = SimpleNamespace(upsert_chunks=AsyncMock())
    mock_parser = SimpleNamespace(
        parse_and_chunk=AsyncMock(
            return_value=[
                ChunkData(
                    text_content="Some content",
                    token_count=2,
                    chunk_index=0,
                    anchor_page=None,
                    anchor_chapter="Test",
                    anchor_section=None,
                )
            ]
        )
    )

    ctx = {
        "session_factory": session_factory,
        "storage_service": mock_storage,
        "docling_parser": mock_parser,
        "embedding_service": mock_embedding,
        "qdrant_service": mock_qdrant,
        "snapshot_service": SnapshotService(),
    }

    await ingestion.process_ingestion(ctx, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        source = await session.get(Source, source_id)
        # Verify Document, DocumentVersion, Chunks exist
        docs = (await session.execute(
            select(Document).where(Document.source_id == source_id)
        )).scalars().all()

    assert task.status is BackgroundTaskStatus.COMPLETE
    assert task.progress == 100
    assert task.result_metadata is not None
    assert task.result_metadata["chunk_count"] >= 1
    assert task.result_metadata["document_version_id"] is not None
    assert source.status is SourceStatus.READY
    assert len(docs) == 1
    mock_embedding.embed_texts.assert_called_once()
    mock_qdrant.upsert_chunks.assert_called_once()
```

Also add a **failure between Tx 1 and Tx 2** test:

```python
@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_pipeline_failure_marks_records_as_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_task(session_factory)
    mock_storage = SimpleNamespace(download=AsyncMock(return_value=b"# Test\n\nSome content"))
    mock_embedding = SimpleNamespace(
        model="test-model",
        dimensions=3072,
        embed_texts=AsyncMock(side_effect=RuntimeError("Gemini down")),
    )
    mock_qdrant = SimpleNamespace(upsert_chunks=AsyncMock())
    mock_parser = SimpleNamespace(
        parse_and_chunk=AsyncMock(
            return_value=[
                ChunkData(
                    text_content="Some content",
                    token_count=2,
                    chunk_index=0,
                    anchor_page=None,
                    anchor_chapter="Test",
                    anchor_section=None,
                )
            ]
        )
    )

    ctx = {
        "session_factory": session_factory,
        "storage_service": mock_storage,
        "docling_parser": mock_parser,
        "embedding_service": mock_embedding,
        "qdrant_service": mock_qdrant,
        "snapshot_service": SnapshotService(),
    }

    await ingestion.process_ingestion(ctx, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        source = await session.get(Source, source_id)
        # Chunks should exist in PG but be FAILED
        chunks = (await session.execute(
            select(Chunk).join(DocumentVersion).join(Document)
            .where(Document.source_id == source_id)
        )).scalars().all()

    assert task.status is BackgroundTaskStatus.FAILED
    assert source.status is SourceStatus.FAILED
    assert all(c.status is ChunkStatus.FAILED for c in chunks)
    mock_qdrant.upsert_chunks.assert_not_called()  # Never reached Qdrant
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/integration/test_ingestion_worker.py -v`
Expected: FAIL (pipeline not implemented yet)

- [ ] **Step 3: Implement the pipeline**

Replace `_run_noop_ingestion` in `backend/app/workers/tasks/ingestion.py` with `_run_ingestion_pipeline`. The full implementation:

1. Extract services from `ctx`
2. Download file from MinIO via `storage_service.download(source.file_path)`
3. Parse + chunk via `ctx["docling_parser"].parse_and_chunk(...)`
4. **Tx 1**: get_or_create_draft, create Document, create DocumentVersion, bulk insert Chunks (PENDING). Commit.
5. Embed via `embedding_service.embed_texts([c.text_content for c in chunks])`
6. Build Qdrant points with payload. Upsert via `qdrant_service.upsert_chunks(points)`.
7. **Tx 2**: Update chunks → INDEXED, doc_version → READY, doc → READY, source → READY, snapshot.chunk_count += len(chunks), create EmbeddingProfile, task → COMPLETE with result_metadata. Commit.
8. On failure between Tx 1 and Tx 2: mark Document/DocumentVersion/Chunks as FAILED.

**Session management:** Use a single session with explicit `commit()` calls at Tx 1 and Tx 2 boundaries (matching the existing pattern in `_process_task`). The failure handler between Tx 1 and Tx 2 should follow the existing rollback-then-refetch pattern from the current error handler.

**Retry invariant:** A retry ALWAYS means a new upload (new Source + new BackgroundTask + new Document + new DocumentVersion). The worker never re-processes a FAILED task or reuses FAILED Document/DocumentVersion records. Failed records remain in PG as audit trail. This eliminates ambiguity around version numbering, partial state cleanup, and Qdrant idempotency.

Update progress at each stage boundary.

**Key implementation details:**
- DoclingParser is stateless and can be initialized once in worker context
- SnapshotService is stateless and can be initialized once in worker context; its method still receives the per-task DB session
- Use `session.add_all()` for bulk chunk insert
- Build Qdrant point payload per spec D3

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/integration/test_ingestion_worker.py -v`
Expected: PASS

- [ ] **Step 5: Checkpoint**

All tests pass. Files ready for commit when user requests:
- `backend/app/workers/tasks/ingestion.py`
- `backend/tests/integration/test_ingestion_worker.py`

---

## Task 10: Worker Startup — Inject Services

**Files:**
- Modify: `backend/app/workers/main.py`
- Modify: `backend/app/services/__init__.py`

- [ ] **Step 1: Read current worker main.py**

Read `backend/app/workers/main.py` to understand the existing startup/shutdown pattern.

- [ ] **Step 2: Add service initialization to on_startup**

Add to `on_startup`:
1. Load settings
2. Create Minio client → StorageService → `ctx["storage_service"]`
3. Create `AsyncQdrantClient(url=settings.qdrant_url)` → QdrantService → `ctx["qdrant_service"]`
4. Create `google.genai.Client(api_key=settings.gemini_api_key)` → EmbeddingService → `ctx["embedding_service"]`
5. Call `await ctx["qdrant_service"].ensure_collection()`
6. Store `ctx["settings"] = settings`

Add to `on_shutdown`:
1. Close Qdrant client via a `close()` method on QdrantService (add a `async def close(self)` method that wraps `self._client.close()` — don't access `_client` from outside the service)

- [ ] **Step 3: Update services __init__.py**

Export new services from `backend/app/services/__init__.py`.

- [ ] **Step 4: Verify worker starts**

Run: `cd backend && timeout 5 python -m app.workers.run 2>&1 || true`
Expected: Worker attempts to start, connects to services (may fail on missing infra, but import/init works)

- [ ] **Step 5: Checkpoint**

All tests pass. Files ready for commit when user requests:
- `backend/app/workers/main.py`
- `backend/app/services/__init__.py`

---

## Task 11: Integration Tests — Qdrant Round-Trip

**Files:**
- Create: `backend/tests/integration/test_qdrant_roundtrip.py`
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Add Qdrant testcontainer fixture to conftest.py**

Add a Qdrant testcontainer fixture using real Qdrant server. This validates named vectors, payload indexes, and filter behavior at the actual server level (in-memory mode may not fully replicate server behavior for named vectors and payload indexes).

```python
from testcontainers.qdrant import QdrantContainer

@pytest.fixture(scope="session")
def qdrant_url():
    with QdrantContainer("qdrant/qdrant:v1.14.0") as qdrant:
        yield qdrant.get_rest_url()

@pytest_asyncio.fixture
async def qdrant_client(qdrant_url: str):
    from qdrant_client import AsyncQdrantClient
    client = AsyncQdrantClient(url=qdrant_url)
    try:
        yield client
    finally:
        await client.close()
```

Note: If `testcontainers[qdrant]` is not available, fall back to `AsyncQdrantClient(":memory:")` but document the limitation. The real container is preferred per the spec requirement.

Also add `knowledge_snapshots` to `TRUNCATE_TEST_DATA_SQL` in `conftest.py` (currently missing — snapshot tests would leak state between tests).

- [ ] **Step 2: Write Qdrant round-trip test**

Create `backend/tests/integration/test_qdrant_roundtrip.py`:

```python
from __future__ import annotations

import uuid

import pytest
from qdrant_client import AsyncQdrantClient

from app.services.qdrant import CollectionSchemaMismatchError, QdrantService


@pytest.mark.asyncio
async def test_create_collection_and_upsert_and_search(qdrant_client: AsyncQdrantClient):
    service = QdrantService(
        client=qdrant_client, collection_name="test_chunks", vector_size=128
    )
    await service.ensure_collection()

    chunk_id = str(uuid.uuid7())
    snapshot_id = str(uuid.uuid7())

    points = [{
        "id": chunk_id,
        "vector": {"dense": [0.1] * 128},
        "payload": {
            "snapshot_id": snapshot_id,
            "agent_id": "agent-1",
            "knowledge_base_id": "kb-1",
            "source_id": "src-1",
            "text_content": "Test content about AI",
            "status": "indexed",
            "source_type": "markdown",
            "language": "english",
            "chunk_index": 0,
        },
    }]
    await service.upsert_chunks(points)

    # Search with snapshot filter
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    results = await qdrant_client.query_points(
        collection_name="test_chunks",
        query=[0.1] * 128,
        using="dense",
        query_filter=Filter(
            must=[FieldCondition(key="snapshot_id", match=MatchValue(value=snapshot_id))]
        ),
        limit=10,
    )

    assert len(results.points) == 1
    assert results.points[0].payload["text_content"] == "Test content about AI"
    assert results.points[0].payload["snapshot_id"] == snapshot_id


@pytest.mark.asyncio
async def test_dimension_mismatch_raises(qdrant_client: AsyncQdrantClient):
    service_3072 = QdrantService(
        client=qdrant_client, collection_name="test_mismatch", vector_size=3072
    )
    await service_3072.ensure_collection()

    service_1024 = QdrantService(
        client=qdrant_client, collection_name="test_mismatch", vector_size=1024
    )
    with pytest.raises(CollectionSchemaMismatchError, match="3072.*1024"):
        await service_1024.ensure_collection()


@pytest.mark.asyncio
async def test_ensure_collection_idempotent(qdrant_client: AsyncQdrantClient):
    service = QdrantService(
        client=qdrant_client, collection_name="test_idempotent", vector_size=256
    )
    await service.ensure_collection()
    await service.ensure_collection()  # Should not raise

    info = await qdrant_client.get_collection("test_idempotent")
    assert info.config.params.vectors["dense"].size == 256
```

- [ ] **Step 3: Run integration tests**

Run: `cd backend && python -m pytest tests/integration/test_qdrant_roundtrip.py -v`
Expected: PASS

- [ ] **Step 4: Checkpoint**

All tests pass. Files ready for commit when user requests:
- `backend/tests/integration/test_qdrant_roundtrip.py`
- `backend/tests/conftest.py`

---

## Task 12: Run Full CI and Verify

- [ ] **Step 1: Run all tests**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 2: Run linters**

Run: `cd backend && ruff check . && ruff format --check .`
Expected: No issues

- [ ] **Step 3: Docker-compose smoke test (manual)**

```bash
docker-compose up -d
# Wait for services
curl http://localhost:8000/ready
# Upload a file
curl -X POST http://localhost:8000/api/admin/sources \
  -F "file=@backend/tests/fixtures/sample.md" \
  -F 'metadata={"title": "Test Document"}'
# Check task status (use task_id from response)
curl http://localhost:8000/api/admin/tasks/<task_id>
# Verify chunks in Qdrant
curl http://localhost:6333/collections/proxymind_chunks
```

- [ ] **Step 4: Post-implementation self-review**

Re-read `docs/development.md` and verify:
- [ ] No mocks outside `tests/`
- [ ] No fallbacks to stubs or dead code
- [ ] All stubs linked to specific stories
- [ ] Secrets outside code and git
- [ ] Tests cover meaningful behavior

- [ ] **Step 5: Final checkpoint**

All tests pass, lints clean. All files from Tasks 1-11 ready for commit when user requests.

---

## Summary

| Task | What | Key files |
|------|------|-----------|
| 1 | Dependencies + Config | pyproject.toml, config.py |
| 2 | Migration | 004_*.py, knowledge.py |
| 3 | StorageService.download | storage.py |
| 4 | DoclingParser | docling_parser.py |
| 5 | EmbeddingService | embedding.py |
| 6 | QdrantService | qdrant.py |
| 7 | SnapshotService | snapshot.py |
| 8 | Source language fix | source.py, admin.py |
| 9 | Worker pipeline | ingestion.py |
| 10 | Worker startup | main.py |
| 11 | Qdrant integration tests | test_qdrant_roundtrip.py |
| 12 | Full CI + verify | all tests |

**Total: 12 tasks, ~50 steps**
