# S4-06: Lightweight Knowledge Processing Migration — Design Spec

## Overview

Replace the remaining Docling-centric naming and architecture with a clean, provider-agnostic document processing interface. Add Google Cloud Document AI as an external fallback (Path C) for complex documents. Update all living documentation to reflect the actual lightweight architecture.

### Current State

The codebase has already migrated away from Docling at the implementation level:

- `DoclingParser` is a self-contained lightweight parser — it does NOT import or use Docling
- Lightweight parsers for MD, TXT, HTML, DOCX, PDF (via pypdf) are fully implemented
- Path A (Gemini native) and Path B (lightweight local) are operational
- No Docling dependency exists in `pyproject.toml`
- No Document AI integration exists

### What S4-06 Delivers

1. **Provider-agnostic `DocumentProcessor` Protocol** with two implementations
2. **`DocumentAIParser`** — Path C adapter for complex documents (scanned PDFs, complex layout)
3. **Path C routing** — hybrid auto-detection + user override
4. **Cleanup** — remove all misleading Docling references from code
5. **Documentation sync** — update living docs to match actual architecture

## Section 1: Provider-Agnostic Interface + Cleanup

### Protocol

New file: `backend/app/services/document_processing.py`

```python
class DocumentProcessor(Protocol):
    async def parse_and_chunk(
        self, content: bytes, filename: str, source_type: SourceType
    ) -> list[ChunkData]: ...
```

### Renames

| Before | After |
|--------|-------|
| `services/docling_parser.py` | `services/lightweight_parser.py` |
| class `DoclingParser` | class `LightweightParser` |
| `PipelineServices.docling_parser` | `PipelineServices.document_processor` (type: `DocumentProcessor`) |

### Dead Code Removal

- Remove `_chunk_external_document()` method — never used, no external chunker is ever passed
- Remove `chunker` parameter from `LightweightParser.__init__()` — dead extension point

### Affected Files

- `backend/app/services/docling_parser.py` — rename file + class
- `backend/app/workers/main.py` — update import + instantiation
- `backend/app/workers/tasks/pipeline.py` — update `PipelineServices` field name + type
- `backend/app/workers/tasks/handlers/path_b.py` — update field access
- `backend/app/workers/tasks/ingestion.py` — update references
- All test files referencing `docling_parser` or `DoclingParser`

### Design Decision: Why Protocol, not ABC

**Question:** How should the provider-agnostic document processing interface be structured?

**Options considered:**
- **(A) Python Protocol** — structural subtyping, single `parse_and_chunk` method. Two implementations: `LightweightParser`, `DocumentAIParser`. Router selects the processor. Testable, extensible, minimal code.
- **(B) Single class with internal routing** — one `DocumentProcessor` with `_parse_local()` and `_parse_document_ai()`. Fewer files, but violates SRP, harder to test, grows with each new provider.
- **(C) Strategy pattern via composition** — `IngestionPipeline` accepts `{PathType: DocumentProcessor}` dict. Maximum flexibility, but YAGNI for 2-3 strategies.

**Chosen: A.** Minimally sufficient abstraction. Protocol is a standard Python pattern (5 lines of code). Two classes behind one interface. Router selects. Not over-engineering, but gives testability and extensibility. Option C is YAGNI — a strategy registry is justified at 5+ providers, not at 2.

## Section 2: Document AI Adapter

### New File

`backend/app/services/document_ai_parser.py`

### Class: `DocumentAIParser`

Implements `DocumentProcessor` Protocol.

### Dependency

`google-cloud-documentai` — lightweight gRPC client, no ML runtime. Added to `pyproject.toml`.

### Processing Flow

1. Receive `content: bytes` + `filename` + `source_type`
2. Send document to Google Cloud Document AI (Layout Parser processor)
3. Receive structured response: pages, blocks, paragraphs, tables, reading order
4. Extract text with anchor metadata (page numbers, detected headings)
5. Pass extracted text blocks through the shared `TextChunker` (extracted from `LightweightParser._chunk_blocks`)
6. Return `list[ChunkData]` — same contract as all other paths

### Chunking Reuse

Extract `_chunk_blocks` from `DoclingParser` into a standalone `TextChunker` class (or module-level function) that both `LightweightParser` and `DocumentAIParser` use. Currently `_chunk_blocks` is a private method — extracting it is minimal refactoring within the scope of this story.

### Retry Policy

`tenacity` — 3 attempts, exponential backoff 1s -> 2s -> 8s, retry on transient gRPC errors (`ServiceUnavailable`, `DeadlineExceeded`). On exhaustion — raise exception, ingestion task transitions to `failed`.

### Configuration (.env)

| Variable | Description | Default |
|----------|-------------|---------|
| `DOCUMENT_AI_PROJECT_ID` | Google Cloud project ID | — (unset = Path C disabled) |
| `DOCUMENT_AI_LOCATION` | Processor location | `us` |
| `DOCUMENT_AI_PROCESSOR_ID` | Layout Parser processor ID | — (required if project is set) |

### Graceful Disable

If `DOCUMENT_AI_PROJECT_ID` is not set, Path C is unavailable. The router never selects Path C. Documents that would qualify for Path C are processed via Path B (best-effort) with a warning logged. This preserves the cheap-VPS-first constraint: the base installation works without Google Cloud entirely.

### Design Decision: Graceful Disable vs Fail Policy

**Distinction:** "Retry + fail" applies when Document AI IS configured but fails to respond. "Graceful disable" applies when Document AI is NOT configured at all. These are different situations:

- Document AI not configured → Path C disabled, Path B used, warning logged. Not an error.
- Document AI configured but unresponsive → retry 3x, then fail the task. This is an error.

### Design Decision: Document AI Processor Type

**Question:** Which Google Cloud Document AI processor type to use?

**Options considered:**
- **(A) Document OCR** — basic OCR only
- **(B) Layout Parser** — structural analysis + OCR + tables + reading order
- **(C) Form Parser** — optimized for forms and key-value extraction

**Chosen: B (Layout Parser).** It covers OCR, tables, and reading order in a single call — the most versatile processor for ProxyMind's use cases (scanned PDFs, complex layout). Form Parser is too specialized. Document OCR lacks structural analysis.

## Section 3: Path C Routing

### Changes to `path_router.py`

Current `determine_path()` returns `PATH_A`, `PATH_B`, or `REJECTED`. Add `PATH_C`.

New enum value: `ProcessingPath.PATH_C`

### Two Triggers for Path C

#### 1. Auto-detection (scan heuristic for PDF)

After Path B is selected for a PDF and pypdf extracts text:
- If average characters per page < `path_c_min_chars_per_page` threshold → suspected scan → Path C
- This check happens in the path_b handler, not in the router, because the router works pre-parse (on metadata only), while text scarcity is visible only after pypdf extraction attempt

#### 2. Explicit override (user)

New optional parameter in `POST /api/admin/sources`: `processing_hint`
- `"auto"` (default) — normal routing
- `"external"` — router returns PATH_C for supported formats (PDF) **if Document AI is configured**
- If `processing_hint="external"` but Document AI is disabled → router falls back to PATH_B and logs a warning. The router owns the warning because the router is where the decision happens.
- For non-PDF formats, the hint is ignored (DOCX/HTML/MD/TXT always use Path B)

### Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `path_c_min_chars_per_page` | 50 | Characters/page threshold for scan auto-detection |

### Routing Flow

```
Upload PDF
  |-- processing_hint="external"
  |    |-- Document AI configured --> PATH_C
  |    +-- Document AI NOT configured --> PATH_B + warning (router logs)
  |-- pages <= 6, no hint --> PATH_A (unchanged)
  +-- pages > 6 or fallback --> PATH_B
       +-- pypdf extraction
            |-- chars/page >= 50 --> continue PATH_B
            +-- chars/page < 50 --> reroute PATH_C (if configured)
                                     +-- if not configured --> PATH_B + warning
```

### Admin API Changes

`POST /api/admin/sources` — add optional field to request schema:

```python
processing_hint: Literal["auto", "external"] = "auto"
```

Stored in `document_versions` for audit (which hint was provided).

### Design Decision: How to Detect Document Complexity

**Question:** How should the system determine that a document is "complex" and requires Path C (Document AI)?

**Options considered:**
- **(A) Automatic detection via heuristics** — check if pypdf extracts little/no text (chars per page < threshold). Works out of the box. Downside: heuristics can misfire; complex tables/layout impossible to detect reliably without ML.
- **(B) Explicit flag at upload time (user-specified)** — user passes `processing_path: "external"`. No false positives. Downside: requires knowledge of document content, breaks "just upload" UX.
- **(C) Hybrid: auto-detection + override** — Path B by default, auto-detect scans via "low text" heuristic, user can explicitly set `force_external_processing: true` at upload.

**Chosen: C (hybrid).** Auto-detect covers 80% of cases (scans). Override closes edge cases (complex tables, poor layout) that cannot be detected automatically without ML. Matches "local-first, external-on-complexity" principle and KISS.

## Section 4: Path C Handler

### New File

`backend/app/workers/tasks/handlers/path_c.py`

Follows the same pattern as existing `path_a.py` and `path_b.py`.

### `handle_path_c()` Flow

1. Download file from SeaweedFS
2. Call `DocumentAIParser.parse_and_chunk(content, filename, source_type)` → `list[ChunkData]`
3. Save chunks to PostgreSQL (status: `PENDING`)
4. Generate embeddings:
   - If chunks <= `batch_embed_chunk_threshold` (50) → interactive Gemini Embedding API
   - If chunks > 50 → Gemini Batch Embedding API (via `BatchOrchestrator`)
5. Upsert into Qdrant with `snapshot_id` of current draft
6. Update chunk statuses → `INDEXED`
7. Set `DocumentVersion.processing_path` → `"path_c"`

### Shared Embedding + Indexing Logic

Steps 3–6 are identical to the path_b handler. Extract a shared function `embed_and_index_chunks(chunks, ...)` that both path_b and path_c call. This is natural refactoring within scope: path_b already contains this logic, we extract it to avoid duplication.

### Reroute from path_b

When path_b handler detects a scan — average characters per page < `path_c_min_chars_per_page` after pypdf extraction (see Section 3, trigger 1) — it delegates to path_c handler instead of processing itself. If Document AI is not configured, path_b continues with a warning logged.

### `DocumentVersion.processing_path`

Currently stored as a PostgreSQL native enum (`processing_path_enum`) with values `path_a` and `path_b`. Adding `path_c` requires an Alembic migration with `ALTER TYPE processing_path_enum ADD VALUE 'path_c'`.

### `DocumentVersion.processing_hint`

New nullable string column storing the user-provided `processing_hint` value (`"auto"` or `"external"`) for audit purposes. Added via the same Alembic migration. This ensures that the routing decision can be traced back to the user's intent.

## Section 5: Testing

### CI Tests (Deterministic, No External APIs)

#### Unit Tests

- **`DocumentAIParser`** — mock gRPC client, verify normalization of Document AI response → `list[ChunkData]`. All anchor fields correct, `token_count` computed, `chunk_index` sequential.
- **`TextChunker`** (extracted `_chunk_blocks`) — standalone tests: oversized blocks, empty text, merge of small blocks, anchor metadata preservation.
- **`path_router`** — new cases: `processing_hint="external"` → PATH_C; hint with unconfigured Document AI → PATH_B + warning.
- **Scan detection heuristic** — PDF with low text → PATH_C, PDF with normal text → PATH_B.

#### Integration Tests

- **Path C handler full cycle** — mock Document AI + mock Embedding → chunks in PostgreSQL + valid Qdrant payload.
- **Reroute from path_b to path_c** — mock pypdf returns low text → switches to path_c handler.
- **Graceful disable** — Document AI not configured, scan PDF → path_b with warning, task not failed.
- **Retry behavior** — first 2 Document AI calls → transient error, third → success.
- **Upload API** — `processing_hint` field accepted, stored, passed to worker.

#### Regression Tests

- All existing path_a and path_b tests continue to pass after renames.
- Chunk contract unchanged — existing assertions on `ChunkData` fields remain valid.
- Qdrant payload schema unchanged.

### Evals (Separate, Do Not Block CI)

- Real scanned PDF through Document AI → text extraction quality.
- Citation accuracy comparison: path_b vs path_c on complex documents.

## Section 6: Documentation Updates

### Living Docs — Update

| Document | Changes |
|----------|---------|
| `docs/lightweight-knowledge-processing-migration.md` | Mark migration as complete. Update checklist with actual implementation details. Add final state after S4-06. |
| `docs/rag.md` | Replace all Docling/HybridChunker references. "Path B — Docling" → "Path B — lightweight local". Add Path C section. Update multilingual table (remove Docling row). Update pipeline diagrams. |
| `docs/architecture.md` | Verify — already references "Lightweight Parser Stack" and "Document AI Fallback". Fix any remaining discrepancies. |
| `docs/spec.md` | Verify — already contains "Lightweight parser stack" and "Google Cloud Document AI". Add Path C configuration parameters to defaults table if appropriate. |

### Preserved (History)

- Archived OpenSpec specs in `docs/superpowers/specs/` — NOT modified
- Completed story descriptions in `docs/plan.md` (S2-02, S3-01, etc.) — NOT modified
- Past commits and their messages — NOT modified

### Principle

Living docs reflect the current state of the system. Historical artifacts preserve the context of decisions at the time they were made.

## Chunk Contract Validation

All three paths MUST produce `ChunkData` with the same fields:

```python
@dataclass(slots=True, frozen=True)
class ChunkData:
    text_content: str
    token_count: int
    chunk_index: int
    anchor_page: int | None
    anchor_chapter: str | None
    anchor_section: str | None
    anchor_timecode: str | None = None
```

Provider-specific response shapes MUST NOT leak into domain models or retrieval logic. The `DocumentAIParser` normalizes Document AI's structured output into this contract before returning.

## Configuration Summary

### New .env Variables

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DOCUMENT_AI_PROJECT_ID` | — | No | Google Cloud project. Unset = Path C disabled |
| `DOCUMENT_AI_LOCATION` | `us` | No | Document AI processor region |
| `DOCUMENT_AI_PROCESSOR_ID` | — | Conditional | Required if `DOCUMENT_AI_PROJECT_ID` is set |
| `PATH_C_MIN_CHARS_PER_PAGE` | `50` | No | Scan detection threshold |

### New Dependency

| Package | Role | Weight |
|---------|------|--------|
| `google-cloud-documentai` | Document AI gRPC client | Lightweight (no ML runtime) |

## Out of Scope

- Path C for non-PDF formats (DOCX/HTML already parse well locally)
- Auto-provisioning of Document AI processors
- Vertex AI Search / Vertex AI RAG Engine integration
- Changes to archived specs or completed story descriptions
