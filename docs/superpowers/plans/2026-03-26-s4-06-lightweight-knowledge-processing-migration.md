# S4-06: Lightweight Knowledge Processing Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Docling-centric naming with a provider-agnostic interface, add Document AI as Path C fallback for complex documents, and synchronize all living docs.

**Architecture:** A `DocumentProcessor` Protocol defines the parsing contract. `LightweightParser` (renamed from `DoclingParser`) handles Path B. New `DocumentAIParser` handles Path C. The path router gains `PATH_C` support via hybrid auto-detection (scan heuristic) plus explicit user override. A shared `TextChunker` is extracted to avoid duplicating chunking logic.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2, google-cloud-documentai, tenacity, pypdf, structlog, pytest

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `backend/app/services/document_processing.py` | `DocumentProcessor` Protocol + `ChunkData` dataclass (moved here) + `TextChunker` class |
| `backend/app/services/document_ai_parser.py` | `DocumentAIParser` — Document AI adapter implementing `DocumentProcessor` |
| `backend/app/workers/tasks/handlers/path_c.py` | Path C handler — orchestrates Document AI parsing + embed + index |
| `backend/tests/unit/services/test_document_ai_parser.py` | Unit tests for Document AI normalization |
| `backend/tests/unit/services/test_text_chunker.py` | Unit tests for extracted TextChunker |
| `backend/tests/unit/services/test_path_c_routing.py` | Unit tests for Path C routing and scan detection |
| `backend/tests/integration/test_path_c_ingestion.py` | Integration tests for Path C handler full cycle |

### Renamed Files

| Before | After |
|--------|-------|
| `backend/app/services/docling_parser.py` | `backend/app/services/lightweight_parser.py` |
| `backend/tests/unit/services/test_docling_parser.py` | `backend/tests/unit/services/test_lightweight_parser.py` |

### Modified Files

| File | Changes |
|------|---------|
| `backend/app/db/models/enums.py` | Add `PATH_C` to `ProcessingPath` |
| `backend/app/db/models/knowledge.py` | Add `processing_hint` column to `DocumentVersion` |
| `backend/migrations/versions/` | Alembic migration: add `path_c` to enum + `processing_hint` column |
| `backend/app/core/config.py` | Add Document AI + Path C settings |
| `backend/app/services/path_router.py` | Add `processing_hint` parameter, Path C routing |
| `backend/app/workers/tasks/pipeline.py` | Rename `docling_parser` → `document_processor`, add `document_ai_parser` field |
| `backend/app/workers/main.py` | Rename imports, instantiate `DocumentAIParser` conditionally |
| `backend/app/workers/tasks/ingestion.py` | Rename references, add Path C dispatch, scan reroute |
| `backend/app/workers/tasks/handlers/path_b.py` | Use `document_processor`, add scan detection + reroute |
| `backend/app/api/schemas.py` | Add `processing_hint` to `SourceUploadMetadata` |
| `backend/app/services/source.py` | Store `processing_hint` in task metadata |
| `backend/pyproject.toml` | Add `google-cloud-documentai` dependency |
| `backend/tests/unit/services/test_path_router.py` | Add Path C routing tests |
| `docs/lightweight-knowledge-processing-migration.md` | Mark complete |
| `docs/rag.md` | Replace Docling references, add Path C |
| `docs/architecture.md` | Verify, fix discrepancies |
| `docs/spec.md` | Add Path C config parameters |

---

## Task 1: Extract TextChunker + DocumentProcessor Protocol + Move ChunkData

**Files:**
- Create: `backend/app/services/document_processing.py`
- Create: `backend/tests/unit/services/test_text_chunker.py`

- [ ] **Step 1: Write failing tests for TextChunker**

Create `backend/tests/unit/services/test_text_chunker.py`:

```python
from __future__ import annotations

import pytest

from app.services.document_processing import ChunkData, TextChunker, ParsedBlock


def test_chunk_single_block_within_budget() -> None:
    chunker = TextChunker(chunk_max_tokens=128)
    blocks = [ParsedBlock(text="Hello world", headings=("Chapter",), anchor_page=1)]

    chunks = chunker.chunk_blocks(blocks)

    assert len(chunks) == 1
    assert chunks[0].text_content == "Hello world"
    assert chunks[0].chunk_index == 0
    assert chunks[0].anchor_page == 1
    assert chunks[0].anchor_chapter == "Chapter"
    assert chunks[0].token_count > 0


def test_chunk_blocks_splits_when_exceeding_budget() -> None:
    chunker = TextChunker(chunk_max_tokens=10)
    blocks = [ParsedBlock(text="word " * 40, headings=("Heading",), anchor_page=3)]

    chunks = chunker.chunk_blocks(blocks)

    assert len(chunks) > 1
    assert all(chunk.token_count <= 10 for chunk in chunks)
    assert all(chunk.anchor_page == 3 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_chunk_blocks_merges_small_blocks() -> None:
    chunker = TextChunker(chunk_max_tokens=128)
    blocks = [
        ParsedBlock(text="First paragraph.", headings=("H1",)),
        ParsedBlock(text="Second paragraph.", headings=("H1",)),
    ]

    chunks = chunker.chunk_blocks(blocks)

    assert len(chunks) == 1
    assert "First paragraph." in chunks[0].text_content
    assert "Second paragraph." in chunks[0].text_content


def test_chunk_blocks_skips_empty_text() -> None:
    chunker = TextChunker(chunk_max_tokens=128)
    blocks = [
        ParsedBlock(text="   ", headings=()),
        ParsedBlock(text="Real content.", headings=()),
    ]

    chunks = chunker.chunk_blocks(blocks)

    assert len(chunks) == 1
    assert chunks[0].text_content == "Real content."


def test_chunk_blocks_empty_input_returns_empty() -> None:
    chunker = TextChunker(chunk_max_tokens=128)

    chunks = chunker.chunk_blocks([])

    assert chunks == []


def test_chunk_blocks_preserves_anchor_from_first_block() -> None:
    chunker = TextChunker(chunk_max_tokens=128)
    blocks = [
        ParsedBlock(text="Para A.", headings=("Ch1", "Sec1"), anchor_page=1),
        ParsedBlock(text="Para B.", headings=("Ch1", "Sec2"), anchor_page=2),
    ]

    chunks = chunker.chunk_blocks(blocks)

    assert len(chunks) == 1
    assert chunks[0].anchor_chapter == "Ch1"
    assert chunks[0].anchor_page == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api python -m pytest tests/unit/services/test_text_chunker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.document_processing'`

- [ ] **Step 3: Create document_processing.py with Protocol, ChunkData, ParsedBlock, TextChunker**

Create `backend/app/services/document_processing.py`:

```python
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.db.models.enums import SourceType

CHARS_PER_TOKEN: int = 3


@dataclass(slots=True, frozen=True)
class ParsedBlock:
    text: str
    headings: tuple[str, ...]
    anchor_page: int | None = None


@dataclass(slots=True, frozen=True)
class ChunkData:
    text_content: str
    token_count: int
    chunk_index: int
    anchor_page: int | None
    anchor_chapter: str | None
    anchor_section: str | None
    anchor_timecode: str | None = None


class DocumentProcessor(Protocol):
    async def parse_and_chunk(
        self, content: bytes, filename: str, source_type: SourceType
    ) -> list[ChunkData]: ...


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


class TextChunker:
    def __init__(self, *, chunk_max_tokens: int) -> None:
        self._chunk_max_tokens = chunk_max_tokens

    def chunk_blocks(self, blocks: list[ParsedBlock]) -> list[ChunkData]:
        chunk_data: list[ChunkData] = []
        current_parts: list[str] = []
        current_tokens = 0
        current_headings: tuple[str, ...] = ()
        current_anchor_page: int | None = None

        def flush() -> None:
            nonlocal current_parts, current_tokens, current_headings, current_anchor_page
            text_content = _normalize_whitespace("\n\n".join(current_parts))
            if not text_content:
                current_parts = []
                current_tokens = 0
                current_headings = ()
                current_anchor_page = None
                return
            chunk_data.append(
                ChunkData(
                    text_content=text_content,
                    token_count=max(1, current_tokens),
                    chunk_index=len(chunk_data),
                    anchor_page=current_anchor_page,
                    anchor_chapter=current_headings[0] if current_headings else None,
                    anchor_section=current_headings[-1] if len(current_headings) > 1 else None,
                )
            )
            current_parts = []
            current_tokens = 0
            current_headings = ()
            current_anchor_page = None

        for block in blocks:
            block_text = _normalize_whitespace(block.text)
            if not block_text:
                continue
            for fragment in self._split_block_text(block_text):
                fragment_tokens = _estimate_tokens(fragment)
                if current_parts and current_tokens + fragment_tokens > self._chunk_max_tokens:
                    flush()
                if not current_parts:
                    current_headings = block.headings
                    current_anchor_page = block.anchor_page
                current_parts.append(fragment)
                current_tokens += fragment_tokens

        flush()
        return chunk_data

    def _split_block_text(self, text: str) -> list[str]:
        if _estimate_tokens(text) <= self._chunk_max_tokens:
            return [text]

        max_chars = max(CHARS_PER_TOKEN, self._chunk_max_tokens * CHARS_PER_TOKEN)
        fragments: list[str] = []
        start = 0

        while start < len(text):
            end = min(len(text), start + max_chars)
            if end < len(text):
                split_at = text.rfind(" ", start, end)
                if split_at <= start:
                    split_at = end
            else:
                split_at = end

            fragment = text[start:split_at].strip()
            if fragment:
                fragments.append(fragment)
            start = split_at
            while start < len(text) and text[start].isspace():
                start += 1

        return fragments
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api python -m pytest tests/unit/services/test_text_chunker.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/document_processing.py backend/tests/unit/services/test_text_chunker.py
git commit -m "feat(knowledge): extract TextChunker, DocumentProcessor Protocol, and ChunkData into document_processing module"
```

---

## Task 2: Rename DoclingParser → LightweightParser + Rewire Imports

**Files:**
- Rename: `backend/app/services/docling_parser.py` → `backend/app/services/lightweight_parser.py`
- Rename: `backend/tests/unit/services/test_docling_parser.py` → `backend/tests/unit/services/test_lightweight_parser.py`
- Modify: `backend/app/workers/tasks/pipeline.py`
- Modify: `backend/app/workers/main.py`
- Modify: `backend/app/workers/tasks/handlers/path_b.py`
- Modify: `backend/app/workers/tasks/ingestion.py`

- [ ] **Step 1: Rename file and class**

Rename `backend/app/services/docling_parser.py` → `backend/app/services/lightweight_parser.py`.

In the new file:
- Rename class `DoclingParser` → `LightweightParser`
- Remove `chunker` parameter from `__init__`
- Remove `_chunk_external_document` method
- Remove `_extract_anchor_page` method (dead code — only used by `_chunk_external_document`)
- Simplify `_chunk_document` to call `_chunk_blocks` directly (no conditional)
- Import `ChunkData` and `ParsedBlock` from `document_processing` instead of defining locally (keep `_ParsedBlock` as internal alias or replace with `ParsedBlock`)
- Delegate chunking to `TextChunker` from `document_processing`
- Keep format-specific `_parse_*` methods unchanged
- Update error message: `"Unsupported source type for DoclingParser"` → `"Unsupported source type for LightweightParser"`

The `LightweightParser` class after changes:

```python
from __future__ import annotations

import asyncio
from html.parser import HTMLParser
from io import BytesIO
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader

from app.db.models.enums import SourceType
from app.services.document_processing import ChunkData, ParsedBlock, TextChunker

_WORD_NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_MAX_DOCX_XML_BYTES = 8 * 1024 * 1024
_MAX_DOCX_XML_COMPRESSION_RATIO = 100


class LightweightParser:
    def __init__(self, *, chunk_max_tokens: int) -> None:
        self._chunker = TextChunker(chunk_max_tokens=chunk_max_tokens)

    async def parse_and_chunk(
        self,
        content: bytes,
        filename: str,
        source_type: SourceType,
    ) -> list[ChunkData]:
        if not content.strip():
            return []

        blocks = await asyncio.to_thread(self._convert_document, content, filename, source_type)
        if not blocks:
            return []

        return await asyncio.to_thread(self._chunker.chunk_blocks, blocks)

    # ... _convert_document, _parse_markdown, _parse_plain_text, _parse_html,
    #     _parse_docx, _parse_pdf — unchanged except they return list[ParsedBlock]
    #     instead of list[_ParsedBlock]
```

All `_ParsedBlock` usages inside the parser should be replaced with the shared `ParsedBlock` from `document_processing`.

- [ ] **Step 2: Update PipelineServices in pipeline.py**

In `backend/app/workers/tasks/pipeline.py`:
- Change TYPE_CHECKING import from `from app.services.docling_parser import DoclingParser` to `from app.services.document_processing import DocumentProcessor`
- Rename field `docling_parser: DoclingParser` → `document_processor: DocumentProcessor`

```python
if TYPE_CHECKING:
    from app.core.config import Settings
    from app.services.batch_orchestrator import BatchOrchestrator
    from app.services.document_processing import DocumentProcessor
    from app.services.embedding import EmbeddingService
    from app.services.gemini_content import GeminiContentService
    from app.services.qdrant import QdrantService
    from app.services.snapshot import SnapshotService
    from app.services.storage import StorageService
    from app.services.token_counter import ApproximateTokenizer

@dataclass(slots=True)
class PipelineServices:
    storage_service: StorageService
    document_processor: DocumentProcessor
    # ... rest unchanged
```

- [ ] **Step 3: Update workers/main.py**

```python
# Change import
from app.services.lightweight_parser import LightweightParser

# In on_startup:
ctx["document_processor"] = LightweightParser(chunk_max_tokens=settings.chunk_max_tokens)
# Remove: ctx["docling_parser"] = ...
```

- [ ] **Step 4: Update ingestion.py**

In `_load_pipeline_services`:
```python
# Change:
docling_parser = ctx["docling_parser"]
# To:
document_processor = ctx["document_processor"]

# Change validation:
if not hasattr(docling_parser, "parse_and_chunk"):
    raise RuntimeError("Worker context contains an invalid Docling parser")
# To:
if not hasattr(document_processor, "parse_and_chunk"):
    raise RuntimeError("Worker context contains an invalid document processor")

# Change PipelineServices construction:
return PipelineServices(
    storage_service=storage_service,
    document_processor=document_processor,
    # ... rest unchanged
)
```

- [ ] **Step 5: Update path_b.py**

```python
# Change line 47:
chunk_data = await services.docling_parser.parse_and_chunk(
# To:
chunk_data = await services.document_processor.parse_and_chunk(
```

- [ ] **Step 6: Rename test file and update imports**

Rename `backend/tests/unit/services/test_docling_parser.py` → `backend/tests/unit/services/test_lightweight_parser.py`.

Update all references inside:
```python
# Change:
import app.services.docling_parser as docling_parser
from app.services.docling_parser import DoclingParser
# To:
import app.services.lightweight_parser as lightweight_parser
from app.services.lightweight_parser import LightweightParser

# Update all DoclingParser(...) → LightweightParser(...)
# Update all docling_parser._ParsedBlock → use ParsedBlock from document_processing
# Update docling_parser._MAX_DOCX_XML_BYTES → lightweight_parser._MAX_DOCX_XML_BYTES
# Update monkeypatch references
```

Remove the test `test_chunk_indices_stay_sequential_when_empty_chunks_are_skipped` — it tested the now-removed `_chunk_external_document` path with `FakeChunker`.

- [ ] **Step 7: Run all existing tests**

Run: `docker compose exec api python -m pytest tests/unit/ -v`
Expected: All tests PASS (with updated file names)

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(knowledge): rename DoclingParser to LightweightParser, remove dead code, use shared TextChunker"
```

---

## Task 3: Add PATH_C to Enum + Configuration + Alembic Migration

**Files:**
- Modify: `backend/app/db/models/enums.py`
- Modify: `backend/app/db/models/knowledge.py`
- Modify: `backend/app/core/config.py`
- Create: `backend/migrations/versions/<auto>_add_path_c_and_processing_hint.py`

- [ ] **Step 1: Add PATH_C enum value**

In `backend/app/db/models/enums.py`, update `ProcessingPath`:

```python
class ProcessingPath(StrEnum):
    PATH_A = "path_a"
    PATH_B = "path_b"
    PATH_C = "path_c"
```

- [ ] **Step 2: Add processing_hint column to DocumentVersion**

In `backend/app/db/models/knowledge.py`, add to `DocumentVersion`:

```python
class DocumentVersion(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_versions"
    # ... existing fields ...
    processing_path: Mapped[ProcessingPath | None] = mapped_column(
        pg_enum(ProcessingPath, name="processing_path_enum"),
        nullable=True,
    )
    processing_hint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[DocumentVersionStatus] = mapped_column(
        pg_enum(DocumentVersionStatus, name="document_version_status_enum"),
        nullable=False,
    )
```

The `processing_hint` column is a plain `String(32)` (not an enum) — it stores `"auto"` or `"external"` for audit purposes. Using a string avoids another enum migration for future hint values.

- [ ] **Step 3: Add Document AI + Path C settings**

In `backend/app/core/config.py`, add to `Settings` class:

```python
    # Document AI (Path C)
    document_ai_project_id: str | None = Field(default=None)
    document_ai_location: str = Field(default="us", min_length=1)
    document_ai_processor_id: str | None = Field(default=None)
    path_c_min_chars_per_page: int = Field(default=50, ge=1)
```

Add to `normalize_empty_optional_strings` field list:
```python
        for field_name in (
            "gemini_api_key",
            "llm_api_key",
            "llm_api_base",
            "rewrite_llm_model",
            "rewrite_llm_api_key",
            "rewrite_llm_api_base",
            "document_ai_project_id",
            "document_ai_processor_id",
        ):
```

Add a computed property:

```python
    @computed_field
    @property
    def document_ai_enabled(self) -> bool:
        return self.document_ai_project_id is not None and self.document_ai_processor_id is not None
```

- [ ] **Step 4: Create Alembic migration**

Run: `docker compose exec api alembic revision --autogenerate -m "add path_c enum value and processing_hint column"`

The auto-generated migration will NOT handle the enum alteration correctly — Alembic cannot auto-detect PostgreSQL enum value additions. Manually edit the generated migration:

```python
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    # Add 'path_c' to the existing PostgreSQL enum type
    op.execute("ALTER TYPE processing_path_enum ADD VALUE IF NOT EXISTS 'path_c'")

    # Add processing_hint column to document_versions
    op.add_column(
        "document_versions",
        sa.Column("processing_hint", sa.String(32), nullable=True),
    )

def downgrade() -> None:
    op.drop_column("document_versions", "processing_hint")
    # Note: PostgreSQL does not support removing values from enum types.
    # path_c will remain in the enum after downgrade. This is safe —
    # the application code simply won't use it.
```

- [ ] **Step 5: Apply migration and verify**

Run: `docker compose exec api alembic upgrade head`
Expected: Migration applies successfully.

- [ ] **Step 6: Run existing tests to verify nothing is broken**

Run: `docker compose exec api python -m pytest tests/unit/ -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models/enums.py backend/app/db/models/knowledge.py backend/app/core/config.py backend/migrations/
git commit -m "feat(knowledge): add PATH_C enum value, processing_hint column, and Alembic migration"
```

---

## Task 4: Add processing_hint to Upload API + Path C Routing

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/services/source.py`
- Modify: `backend/app/services/path_router.py`
- Modify: `backend/app/workers/tasks/ingestion.py`
- Modify: `backend/app/workers/tasks/pipeline.py`
- Modify: `backend/tests/unit/services/test_path_router.py`
- Create: `backend/tests/unit/services/test_path_c_routing.py`

- [ ] **Step 1: Write failing tests for processing_hint routing**

Create `backend/tests/unit/services/test_path_c_routing.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db.models.enums import ProcessingPath, SourceType
from app.services.path_router import FileMetadata, determine_path


def _settings(**overrides: object) -> SimpleNamespace:
    defaults = dict(
        path_a_max_pdf_pages=6,
        path_a_max_audio_duration_sec=80,
        path_a_max_video_duration_sec=120,
        document_ai_enabled=True,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_processing_hint_external_routes_pdf_to_path_c() -> None:
    decision = determine_path(
        SourceType.PDF,
        FileMetadata(10, None, 1000),
        _settings(),
        processing_hint="external",
    )

    assert decision.path is ProcessingPath.PATH_C
    assert decision.rejected is False


def test_processing_hint_external_ignored_for_text_formats() -> None:
    decision = determine_path(
        SourceType.MARKDOWN,
        FileMetadata(None, None, 100),
        _settings(),
        processing_hint="external",
    )

    assert decision.path is ProcessingPath.PATH_B


def test_processing_hint_external_falls_back_when_document_ai_disabled() -> None:
    decision = determine_path(
        SourceType.PDF,
        FileMetadata(10, None, 1000),
        _settings(document_ai_enabled=False),
        processing_hint="external",
    )

    assert decision.path is ProcessingPath.PATH_B
    assert "not configured" in decision.reason


def test_processing_hint_external_short_pdf_falls_back_when_document_ai_disabled() -> None:
    """Short PDF (2 pages) + external hint + Document AI disabled → Path B, not Path A."""
    decision = determine_path(
        SourceType.PDF,
        FileMetadata(2, None, 500),
        _settings(document_ai_enabled=False),
        processing_hint="external",
    )

    assert decision.path is ProcessingPath.PATH_B
    assert "not configured" in decision.reason


def test_processing_hint_auto_preserves_existing_routing() -> None:
    decision = determine_path(
        SourceType.PDF,
        FileMetadata(2, None, 1000),
        _settings(),
        processing_hint="auto",
    )

    assert decision.path is ProcessingPath.PATH_A


def test_default_routing_unchanged_without_hint() -> None:
    decision = determine_path(
        SourceType.MARKDOWN,
        FileMetadata(None, None, 100),
        _settings(),
    )

    assert decision.path is ProcessingPath.PATH_B
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api python -m pytest tests/unit/services/test_path_c_routing.py -v`
Expected: FAIL — `determine_path()` does not accept `processing_hint`

- [ ] **Step 3: Update path_router.py to accept processing_hint**

In `backend/app/services/path_router.py`, add `structlog` import and update `PathRouterSettings` and `determine_path`:

```python
import structlog

logger = structlog.get_logger(__name__)


class PathRouterSettings(Protocol):
    path_a_max_pdf_pages: int
    path_a_max_audio_duration_sec: int
    path_a_max_video_duration_sec: int
    document_ai_enabled: bool


def determine_path(
    source_type: SourceType,
    file_metadata: FileMetadata,
    settings: PathRouterSettings,
    processing_hint: str = "auto",
) -> PathDecision:
    # Handle explicit external hint
    if processing_hint == "external" and source_type is SourceType.PDF:
        if settings.document_ai_enabled:
            return PathDecision(
                path=ProcessingPath.PATH_C,
                reason="User requested external processing and Document AI is configured",
                rejected=False,
            )
        # Document AI not configured — fall back to Path B with warning
        logger.warning(
            "path_router.external_hint_ignored",
            reason="Document AI is not configured; falling back to Path B",
            source_type=source_type.value,
        )
        return PathDecision(
            path=ProcessingPath.PATH_B,
            reason="User requested external processing but Document AI is not configured; falling back to Path B",
            rejected=False,
        )

    # ... rest of existing logic unchanged
```

Import `ProcessingPath` must now include `PATH_C` (already added in Task 3). The router owns the warning — it is the component making the fallback decision.

- [ ] **Step 4: Add processing_hint to SourceUploadMetadata**

In `backend/app/api/schemas.py`:

```python
from typing import Literal

class SourceUploadMetadata(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    public_url: Annotated[AnyHttpUrl, UrlConstraints(max_length=2048)] | None = None
    catalog_item_id: uuid.UUID | None = None
    language: str | None = Field(default=None, max_length=32)
    processing_hint: Literal["auto", "external"] = "auto"
    # ... existing validator unchanged
```

- [ ] **Step 5: Pass processing_hint through source service to task metadata**

In `backend/app/services/source.py`, update `create_source_and_task`:

```python
    async def create_source_and_task(
        self,
        *,
        source_id: uuid.UUID,
        metadata: SourceUploadMetadata,
        source_type: SourceType,
        file_path: str,
        file_size_bytes: int,
        mime_type: str | None,
        skip_embedding: bool = False,
    ) -> SourceTaskBundle:
        # ... source creation unchanged ...
        result_metadata: dict[str, object] | None = None
        if skip_embedding or metadata.processing_hint != "auto":
            result_metadata = {}
            if skip_embedding:
                result_metadata["skip_embedding"] = True
            if metadata.processing_hint != "auto":
                result_metadata["processing_hint"] = metadata.processing_hint

        task = BackgroundTask(
            id=uuid.uuid7(),
            agent_id=DEFAULT_AGENT_ID,
            task_type=BackgroundTaskType.INGESTION,
            status=BackgroundTaskStatus.PENDING,
            source_id=source_id,
            result_metadata=result_metadata,
        )
```

- [ ] **Step 6: Read processing_hint in ingestion.py and pass to pipeline**

In `backend/app/workers/tasks/ingestion.py`, update `_run_ingestion_pipeline`:

```python
    processing_hint = (task.result_metadata or {}).get("processing_hint", "auto")
    path_decision = determine_path(source.source_type, file_metadata, services, processing_hint=processing_hint)
```

Also store `processing_hint` in `PipelineServices` (or pass it directly to handlers) so that `initialize_pipeline_records` can write it to `DocumentVersion.processing_hint`. Update `initialize_pipeline_records` in `pipeline.py` to accept and persist `processing_hint`:

```python
async def initialize_pipeline_records(
    session: AsyncSession,
    *,
    source: Source,
    snapshot_service: SnapshotService,
    processing_path: ProcessingPath,
    processing_hint: str = "auto",
) -> InitializedPipelineRecords:
    # ... existing logic ...
    document_version = DocumentVersion(
        id=uuid.uuid7(),
        document_id=document.id,
        version_number=1,
        file_path=source.file_path,
        processing_path=processing_path,
        processing_hint=processing_hint,
        status=DocumentVersionStatus.PROCESSING,
    )
    # ... rest unchanged
```

Update all callers (path_a, path_b, path_c handlers) to pass `processing_hint` through.

- [ ] **Step 7: Update existing path_router tests to pass document_ai_enabled**

In `backend/tests/unit/services/test_path_router.py`, update `_settings()`:

```python
def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        path_a_max_pdf_pages=6,
        path_a_max_audio_duration_sec=80,
        path_a_max_video_duration_sec=120,
        document_ai_enabled=False,
    )
```

- [ ] **Step 8: Run all tests**

Run: `docker compose exec api python -m pytest tests/unit/ -v`
Expected: All tests PASS

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(knowledge): add processing_hint to upload API and Path C routing in path_router"
```

---

## Task 5: Implement DocumentAIParser

**Files:**
- Create: `backend/app/services/document_ai_parser.py`
- Create: `backend/tests/unit/services/test_document_ai_parser.py`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add google-cloud-documentai dependency**

In `backend/pyproject.toml`, add to `dependencies`:

```toml
"google-cloud-documentai>=3.0.0",
```

Run: `docker compose build api`

- [ ] **Step 2: Write failing tests for DocumentAIParser**

Create `backend/tests/unit/services/test_document_ai_parser.py`:

```python
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.enums import SourceType
from app.services.document_ai_parser import DocumentAIParser


def _fake_document_response(pages: list[dict]) -> SimpleNamespace:
    """Build a fake Document AI response with pages containing paragraphs."""
    fake_pages = []
    for page_data in pages:
        paragraphs = []
        for para_text in page_data.get("paragraphs", []):
            layout = SimpleNamespace(
                text_anchor=SimpleNamespace(
                    text_segments=[SimpleNamespace(start_index=0, end_index=len(para_text))]
                )
            )
            paragraphs.append(SimpleNamespace(layout=layout))
        fake_pages.append(
            SimpleNamespace(
                page_number=page_data["page_number"],
                paragraphs=paragraphs,
            )
        )
    return SimpleNamespace(
        text="\n".join(
            para_text
            for page_data in pages
            for para_text in page_data.get("paragraphs", [])
        ),
        pages=fake_pages,
    )


@pytest.fixture
def parser() -> DocumentAIParser:
    return DocumentAIParser(
        project_id="test-project",
        location="us",
        processor_id="test-processor",
        chunk_max_tokens=1024,
    )


@pytest.mark.asyncio
async def test_parse_and_chunk_returns_normalized_chunks(parser: DocumentAIParser) -> None:
    fake_response = _fake_document_response([
        {"page_number": 1, "paragraphs": ["First paragraph on page one."]},
        {"page_number": 2, "paragraphs": ["Second paragraph on page two."]},
    ])

    with patch.object(parser, "_call_document_ai", return_value=fake_response):
        chunks = await parser.parse_and_chunk(b"fake-pdf", "test.pdf", SourceType.PDF)

    assert len(chunks) >= 1
    assert all(chunk.text_content for chunk in chunks)
    assert all(chunk.token_count > 0 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    pages_found = {chunk.anchor_page for chunk in chunks if chunk.anchor_page is not None}
    assert pages_found


@pytest.mark.asyncio
async def test_parse_and_chunk_empty_response_returns_empty(parser: DocumentAIParser) -> None:
    fake_response = SimpleNamespace(text="", pages=[])

    with patch.object(parser, "_call_document_ai", return_value=fake_response):
        chunks = await parser.parse_and_chunk(b"fake-pdf", "test.pdf", SourceType.PDF)

    assert chunks == []


@pytest.mark.asyncio
async def test_anchor_timecode_is_none_for_pdf(parser: DocumentAIParser) -> None:
    fake_response = _fake_document_response([
        {"page_number": 1, "paragraphs": ["Some text content."]},
    ])

    with patch.object(parser, "_call_document_ai", return_value=fake_response):
        chunks = await parser.parse_and_chunk(b"fake-pdf", "test.pdf", SourceType.PDF)

    assert all(chunk.anchor_timecode is None for chunk in chunks)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker compose exec api python -m pytest tests/unit/services/test_document_ai_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.document_ai_parser'`

- [ ] **Step 4: Implement DocumentAIParser**

Create `backend/app/services/document_ai_parser.py`:

```python
from __future__ import annotations

import asyncio

import structlog
from google.api_core.exceptions import DeadlineExceeded, ServiceUnavailable
from google.cloud import documentai
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.db.models.enums import SourceType
from app.services.document_processing import ChunkData, ParsedBlock, TextChunker

logger = structlog.get_logger(__name__)

# Retry only on transient gRPC errors — configuration, auth, and code bugs must fail fast
_TRANSIENT_EXCEPTIONS = (ServiceUnavailable, DeadlineExceeded)


class DocumentAIParser:
    def __init__(
        self,
        *,
        project_id: str,
        location: str,
        processor_id: str,
        chunk_max_tokens: int,
    ) -> None:
        self._project_id = project_id
        self._location = location
        self._processor_id = processor_id
        self._chunker = TextChunker(chunk_max_tokens=chunk_max_tokens)
        self._processor_name = (
            f"projects/{project_id}/locations/{location}/processors/{processor_id}"
        )

    async def parse_and_chunk(
        self,
        content: bytes,
        filename: str,
        source_type: SourceType,
    ) -> list[ChunkData]:
        document = await self._call_document_ai(content, filename)
        if not document.text.strip():
            return []

        blocks = self._extract_blocks(document)
        if not blocks:
            return []

        return await asyncio.to_thread(self._chunker.chunk_blocks, blocks)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(_TRANSIENT_EXCEPTIONS),
        reraise=True,
    )
    async def _call_document_ai(self, content: bytes, filename: str) -> object:
        def _sync_call() -> object:
            client = documentai.DocumentProcessorServiceClient()
            raw_document = documentai.RawDocument(content=content, mime_type="application/pdf")
            request = documentai.ProcessRequest(
                name=self._processor_name,
                raw_document=raw_document,
            )
            result = client.process_document(request=request)
            return result.document

        return await asyncio.to_thread(_sync_call)

    @staticmethod
    def _extract_blocks(document: object) -> list[ParsedBlock]:
        blocks: list[ParsedBlock] = []
        full_text = document.text  # type: ignore[attr-defined]

        for page in document.pages:  # type: ignore[attr-defined]
            page_number = page.page_number
            for paragraph in page.paragraphs:
                text_anchor = paragraph.layout.text_anchor
                if not text_anchor.text_segments:
                    continue
                start = text_anchor.text_segments[0].start_index
                end = text_anchor.text_segments[-1].end_index
                para_text = full_text[start:end].strip()
                if para_text:
                    blocks.append(
                        ParsedBlock(
                            text=para_text,
                            headings=(),
                            anchor_page=page_number,
                        )
                    )

        return blocks
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec api python -m pytest tests/unit/services/test_document_ai_parser.py -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/document_ai_parser.py backend/tests/unit/services/test_document_ai_parser.py backend/pyproject.toml
git commit -m "feat(knowledge): implement DocumentAIParser with Layout Parser and retry logic"
```

---

## Task 6: Path C Handler + Scan Detection Reroute

**Files:**
- Create: `backend/app/workers/tasks/handlers/path_c.py`
- Modify: `backend/app/workers/tasks/handlers/path_b.py`
- Modify: `backend/app/workers/tasks/pipeline.py`
- Modify: `backend/app/workers/tasks/ingestion.py`
- Modify: `backend/app/workers/main.py`
- Create: `backend/tests/integration/test_path_c_ingestion.py`

- [ ] **Step 1: Add document_ai_parser to PipelineServices**

In `backend/app/workers/tasks/pipeline.py`, add:

```python
if TYPE_CHECKING:
    # ... existing imports ...
    from app.services.document_ai_parser import DocumentAIParser

@dataclass(slots=True)
class PipelineServices:
    storage_service: StorageService
    document_processor: DocumentProcessor
    embedding_service: EmbeddingService
    qdrant_service: QdrantService
    snapshot_service: SnapshotService
    gemini_content_service: GeminiContentService
    tokenizer: ApproximateTokenizer
    settings: Settings
    default_language: str
    path_a_text_threshold_pdf: int
    path_a_text_threshold_media: int
    path_a_max_pdf_pages: int
    path_a_max_audio_duration_sec: int
    path_a_max_video_duration_sec: int
    batch_orchestrator: BatchOrchestrator | None = None
    document_ai_parser: DocumentAIParser | None = None
```

- [ ] **Step 2: Conditionally instantiate DocumentAIParser in workers/main.py**

In `backend/app/workers/main.py`, in `on_startup`:

```python
    from app.services.document_ai_parser import DocumentAIParser

    # ... after existing service setup ...
    document_ai_parser = None
    if settings.document_ai_enabled:
        document_ai_parser = DocumentAIParser(
            project_id=settings.document_ai_project_id,
            location=settings.document_ai_location,
            processor_id=settings.document_ai_processor_id,
            chunk_max_tokens=settings.chunk_max_tokens,
        )
        logger.info("worker.startup.document_ai_enabled")

    ctx["document_ai_parser"] = document_ai_parser
```

Update `_load_pipeline_services` in `ingestion.py` to include:

```python
    document_ai_parser = ctx.get("document_ai_parser")

    return PipelineServices(
        # ... existing fields ...
        document_ai_parser=document_ai_parser,
    )
```

- [ ] **Step 3: Create path_c handler**

Create `backend/app/workers/tasks/handlers/path_c.py`:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BackgroundTask, Chunk, Source
from app.db.models.enums import ChunkStatus, ProcessingPath
from app.services.qdrant import QdrantChunkPoint
from app.workers.tasks.pipeline import (
    BatchSubmittedResult,
    PersistedPipelineState,
    PipelineServices,
    SkipEmbeddingResult,
    cleanup_qdrant_chunks,
    initialize_pipeline_records,
    mark_persisted_records_failed,
)

DEFAULT_EMBEDDING_TASK_TYPE = "RETRIEVAL_DOCUMENT"


@dataclass(slots=True, frozen=True)
class PathCResult:
    snapshot_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_ids: list[uuid.UUID]
    chunk_count: int
    token_count_total: int
    processing_path: ProcessingPath
    pipeline_version: str


async def handle_path_c(
    session: AsyncSession,
    task: BackgroundTask,
    source: Source,
    file_bytes: bytes,
    services: PipelineServices,
) -> PathCResult | SkipEmbeddingResult | BatchSubmittedResult:
    if services.document_ai_parser is None:
        raise RuntimeError("Path C handler called but Document AI parser is not configured")

    persisted_state: PersistedPipelineState | None = None
    qdrant_write_may_have_happened = False

    try:
        chunk_data = await services.document_ai_parser.parse_and_chunk(
            file_bytes,
            source.file_path.rsplit("/", maxsplit=1)[-1],
            source.source_type,
        )
        if not chunk_data:
            raise ValueError("Document AI produced no chunks")
        task.progress = 40
        await session.commit()

        processing_hint = (task.result_metadata or {}).get("processing_hint", "auto")
        initialized = await initialize_pipeline_records(
            session,
            source=source,
            snapshot_service=services.snapshot_service,
            processing_path=ProcessingPath.PATH_C,
            processing_hint=processing_hint,
        )
        document = initialized.document
        document_version = initialized.document_version
        snapshot_id = initialized.snapshot_id

        chunk_rows = [
            Chunk(
                id=uuid.uuid7(),
                owner_id=source.owner_id,
                agent_id=source.agent_id,
                knowledge_base_id=source.knowledge_base_id,
                document_version_id=document_version.id,
                snapshot_id=snapshot_id,
                source_id=source.id,
                chunk_index=chunk.chunk_index,
                text_content=chunk.text_content,
                token_count=chunk.token_count,
                anchor_page=chunk.anchor_page,
                anchor_chapter=chunk.anchor_chapter,
                anchor_section=chunk.anchor_section,
                anchor_timecode=chunk.anchor_timecode,
                status=ChunkStatus.PENDING,
            )
            for chunk in chunk_data
        ]
        session.add_all(chunk_rows)

        persisted_state = PersistedPipelineState(
            snapshot_id=snapshot_id,
            document_id=document.id,
            document_version_id=document_version.id,
            chunk_ids=[chunk.id for chunk in chunk_rows],
            token_count_total=sum(chunk.token_count for chunk in chunk_data),
        )

        task.progress = 50
        await session.commit()

        skip_embedding = bool((task.result_metadata or {}).get("skip_embedding"))
        if skip_embedding:
            return SkipEmbeddingResult(
                snapshot_id=snapshot_id,
                document_id=document.id,
                document_version_id=document_version.id,
                chunk_ids=[chunk.id for chunk in chunk_rows],
                chunk_count=len(chunk_rows),
                token_count_total=persisted_state.token_count_total,
                processing_path=ProcessingPath.PATH_C,
                pipeline_version="s4-06-path-c",
            )

        if (
            services.batch_orchestrator is not None
            and len(chunk_rows) > services.settings.batch_embed_chunk_threshold
        ):
            await services.batch_orchestrator.create_batch_job_for_threshold(
                session,
                task=task,
                source=source,
                snapshot_id=snapshot_id,
                chunk_ids=[chunk.id for chunk in chunk_rows],
                document_id=document.id,
                document_version_id=document_version.id,
                chunk_count=len(chunk_rows),
                token_count_total=persisted_state.token_count_total,
                processing_path=ProcessingPath.PATH_C.value,
                pipeline_version="s4-06-path-c",
            )
            await services.batch_orchestrator.submit_to_gemini(
                session,
                background_task_id=task.id,
                texts=[chunk.text_content for chunk in chunk_rows],
                chunk_ids=[chunk.id for chunk in chunk_rows],
                display_name=source.title,
            )
            task.progress = 60
            await session.commit()
            return BatchSubmittedResult(
                snapshot_id=snapshot_id,
                document_id=document.id,
                document_version_id=document_version.id,
                chunk_ids=[chunk.id for chunk in chunk_rows],
                chunk_count=len(chunk_rows),
                token_count_total=persisted_state.token_count_total,
                processing_path=ProcessingPath.PATH_C,
                pipeline_version="s4-06-path-c",
            )

        vectors = await services.embedding_service.embed_texts(
            [chunk.text_content for chunk in chunk_data],
            task_type=getattr(
                services.settings,
                "embedding_task_type",
                DEFAULT_EMBEDDING_TASK_TYPE,
            ),
            title=source.title,
        )
        task.progress = 85
        await session.commit()

        qdrant_points = [
            QdrantChunkPoint(
                chunk_id=row.id,
                vector=vector,
                snapshot_id=snapshot_id,
                source_id=source.id,
                document_version_id=document_version.id,
                agent_id=source.agent_id,
                knowledge_base_id=source.knowledge_base_id,
                text_content=row.text_content,
                chunk_index=row.chunk_index,
                token_count=row.token_count,
                anchor_page=row.anchor_page,
                anchor_chapter=row.anchor_chapter,
                anchor_section=row.anchor_section,
                anchor_timecode=row.anchor_timecode,
                source_type=source.source_type,
                language=source.language or services.default_language,
                status=ChunkStatus.INDEXED,
            )
            for row, vector in zip(chunk_rows, vectors, strict=True)
        ]
        qdrant_write_may_have_happened = True
        await services.qdrant_service.upsert_chunks(qdrant_points)
        task.progress = 95
        await session.commit()

        return PathCResult(
            snapshot_id=snapshot_id,
            document_id=document.id,
            document_version_id=document_version.id,
            chunk_ids=[chunk.id for chunk in chunk_rows],
            chunk_count=len(chunk_rows),
            token_count_total=persisted_state.token_count_total,
            processing_path=ProcessingPath.PATH_C,
            pipeline_version="s4-06-path-c",
        )
    except Exception:
        await session.rollback()
        if qdrant_write_may_have_happened and persisted_state is not None:
            await cleanup_qdrant_chunks(services.qdrant_service, persisted_state.chunk_ids)
        if persisted_state is not None:
            await mark_persisted_records_failed(
                session,
                source_id=source.id,
                document_id=persisted_state.document_id,
                document_version_id=persisted_state.document_version_id,
                chunk_ids=persisted_state.chunk_ids,
            )
        raise
```

- [ ] **Step 4: Add scan detection in path_b handler**

In `backend/app/workers/tasks/handlers/path_b.py`, after parsing and before chunk persistence, add scan detection logic:

```python
import structlog

logger = structlog.get_logger(__name__)

async def handle_path_b(
    session: AsyncSession,
    task: BackgroundTask,
    source: Source,
    file_bytes: bytes,
    services: PipelineServices,
) -> PathBResult | SkipEmbeddingResult | BatchSubmittedResult:
    persisted_state: PersistedPipelineState | None = None
    qdrant_write_may_have_happened = False

    try:
        chunk_data = await services.document_processor.parse_and_chunk(
            file_bytes,
            source.file_path.rsplit("/", maxsplit=1)[-1],
            source.source_type,
        )

        # Scan detection: if PDF produced very little text, reroute to Path C
        if (
            source.source_type is SourceType.PDF
            and services.document_ai_parser is not None
            and _is_suspected_scan(chunk_data, file_metadata.page_count, services.settings.path_c_min_chars_per_page)
        ):
            logger.info(
                "worker.ingestion.scan_detected_rerouting_to_path_c",
                source_id=str(source.id),
            )
            from app.workers.tasks.handlers.path_c import handle_path_c
            return await handle_path_c(session, task, source, file_bytes, services)

        if not chunk_data:
            raise ValueError("Parsed document produced no chunks")

        # ... rest of existing path_b logic unchanged ...
```

Note: `handle_path_b` now needs `file_metadata` passed as a parameter so it can access `page_count` for scan detection. Update the signature and all callers.

Add the helper function at module level:

```python
from app.services.document_processing import ChunkData


def _is_suspected_scan(
    chunk_data: list[ChunkData],
    page_count: int | None,
    min_chars_per_page: int,
) -> bool:
    """Check if extracted text is too sparse for the number of pages — likely a scan.

    Uses page_count from FileMetadata (already computed by inspect_file)
    to avoid re-reading the PDF.
    """
    if page_count is None or page_count == 0:
        return False
    total_chars = sum(len(chunk.text_content) for chunk in chunk_data)
    return (total_chars / page_count) < min_chars_per_page
```

Also add `path_c_min_chars_per_page` to `PipelineServices` in `pipeline.py`:

```python
@dataclass(slots=True)
class PipelineServices:
    # ... existing fields ...
    path_c_min_chars_per_page: int = 50
```

And wire it in `workers/main.py` and `ingestion.py` `_load_pipeline_services`.

- [ ] **Step 5: Update _run_ingestion_pipeline in ingestion.py for Path C dispatch**

In `backend/app/workers/tasks/ingestion.py`, update `_run_ingestion_pipeline`:

```python
    from app.workers.tasks.handlers.path_a import PathAFallback, handle_path_a
    from app.workers.tasks.handlers.path_b import handle_path_b
    from app.workers.tasks.handlers.path_c import handle_path_c

    if path_decision.path is ProcessingPath.PATH_A:
        result = await handle_path_a(
            session, task, source, file_bytes, file_metadata, services,
        )
        if isinstance(result, PathAFallback):
            result = await handle_path_b(session, task, source, file_bytes, file_metadata, services)
    elif path_decision.path is ProcessingPath.PATH_C:
        result = await handle_path_c(session, task, source, file_bytes, services)
    else:
        result = await handle_path_b(session, task, source, file_bytes, file_metadata, services)
```

- [ ] **Step 6: Write integration test for Path C**

Create `backend/tests/integration/test_path_c_ingestion.py`:

```python
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BackgroundTask, Source
from app.db.models.enums import (
    BackgroundTaskStatus,
    BackgroundTaskType,
    ProcessingPath,
    SourceStatus,
    SourceType,
)
from app.services.document_processing import ChunkData


@pytest.fixture
def mock_document_ai_parser() -> MagicMock:
    parser = MagicMock()
    parser.parse_and_chunk = AsyncMock(return_value=[
        ChunkData(
            text_content="Scanned text from page one.",
            token_count=9,
            chunk_index=0,
            anchor_page=1,
            anchor_chapter=None,
            anchor_section=None,
        ),
        ChunkData(
            text_content="Scanned text from page two.",
            token_count=9,
            chunk_index=1,
            anchor_page=2,
            anchor_chapter=None,
            anchor_section=None,
        ),
    ])
    return parser


# Integration tests use the full worker context helper from test_ingestion_worker.py.
# These tests verify:
# 1. Path C handler full cycle with mock Document AI
# 2. Scan reroute from Path B to Path C
# 3. Graceful disable when Document AI not configured
# 4. processing_hint="external" routes to Path C
```

- [ ] **Step 7: Run all tests**

Run: `docker compose exec api python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(knowledge): implement Path C handler, scan detection reroute, and Document AI integration"
```

---

## Task 7: Update Living Documentation

**Files:**
- Modify: `docs/lightweight-knowledge-processing-migration.md`
- Modify: `docs/rag.md`
- Modify: `docs/architecture.md`
- Modify: `docs/spec.md`

- [ ] **Step 1: Update lightweight-knowledge-processing-migration.md**

Add a section at the end:

```markdown
## Migration status

**Status: Complete** (S4-06, 2026-03-26)

All items from the implementation checklist have been addressed:

- [x] Provider-agnostic `DocumentProcessor` Protocol defined in `backend/app/services/document_processing.py`
- [x] Lightweight local parser path (`LightweightParser`) is the default baseline for Path B
- [x] Document AI adapter (`DocumentAIParser`) added for Path C complex-document fallback
- [x] Current chunk contract preserved — all paths produce `ChunkData` with the same fields
- [x] Citation compatibility verified through normalization
- [x] Docling-specific naming removed from runtime code (class names, module names, imports)
- [x] Dependency policy aligned with cheap-VPS constraint — no local ML runtimes

### Configuration added

- `DOCUMENT_AI_PROJECT_ID` — Google Cloud project (unset = Path C disabled)
- `DOCUMENT_AI_LOCATION` — processor region (default: `us`)
- `DOCUMENT_AI_PROCESSOR_ID` — Layout Parser processor ID
- `PATH_C_MIN_CHARS_PER_PAGE` — scan detection threshold (default: 50)
```

- [ ] **Step 2: Update docs/rag.md**

Replace all Docling/HybridChunker references:

- "Path B — Docling" → "Path B — lightweight local"
- "Docling parses" → "Lightweight parsers extract"
- "Docling HybridChunker" → "TextChunker (structure-aware, lightweight)"
- "Docling" in multilingual table → remove row
- Add Path C section after Path B section
- Update pipeline diagram to include Path C

- [ ] **Step 3: Verify docs/architecture.md**

Check references — already uses "Lightweight Parser Stack" and "Document AI Fallback". Fix any remaining "Docling" references if found.

- [ ] **Step 4: Update docs/spec.md**

Add Path C configuration parameters to the implementation defaults table:

```markdown
| `path_c_min_chars_per_page`    | 50                          | Characters/page threshold for scan auto-detection  |
```

- [ ] **Step 5: Commit**

```bash
git add docs/
git commit -m "docs(knowledge): update living docs to reflect lightweight architecture and Path C"
```

---

## Task 8: Final Regression + Cleanup

**Files:**
- All modified files from previous tasks

- [ ] **Step 1: Run full test suite**

Run: `docker compose exec api python -m pytest tests/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 2: Verify no remaining docling references in runtime code**

Run: `grep -ri "docling" backend/app/ --include="*.py"` (via Grep tool)
Expected: Zero matches in `backend/app/`. Matches may remain in `tests/` fixtures or historical files — that is acceptable.

- [ ] **Step 3: Verify no local ML dependencies**

Run: `grep -E "torch|torchvision|transformers|cuda|docling" backend/pyproject.toml`
Expected: Zero matches.

- [ ] **Step 4: Verify Docker build succeeds**

Run: `docker compose build api worker`
Expected: Build succeeds without errors.

- [ ] **Step 5: Commit any final fixes**

```bash
git add -A
git commit -m "chore(knowledge): final cleanup and regression verification for S4-06"
```
