# S3-04: Path A (Gemini Native) — Design Spec

## Overview

Enable multimodal source ingestion via Gemini native pipeline for short PDFs, images, audio, and video. Path A creates a single chunk per file using Gemini LLM for text extraction and Gemini Embedding 2 for multimodal embedding directly from the file.

### Supported Formats (Path A)

| Format | Extensions | Limit |
|--------|-----------|-------|
| PDF | `.pdf` | ≤ 6 pages |
| Image | `.png`, `.jpeg`, `.jpg` | Any (within upload size limit) |
| Audio | `.mp3`, `.wav` | ≤ 80 seconds |
| Video | `.mp4` | ≤ 120 seconds |

### Core Flow

```
Upload → SeaweedFS → Worker → PathRouter decides A, B, or REJECT
  Path A: Gemini LLM (text_content) → threshold check → Gemini Embedding 2 (from file) → 1 chunk → Qdrant
  Path B: (existing) Docling → HybridChunker → Gemini Embedding 2 (from text) → N chunks → Qdrant
  REJECT: audio/video exceeding duration limits → task FAILED (Path B not available for these formats)
```

**Threshold fallback:** If Path A `text_content` exceeds a token threshold (`path_a_text_threshold_pdf`=2000, `path_a_text_threshold_media`=500): for **PDF**, the file is redirected to Path B; for **audio/video**, the task fails (Docling does not yet support these formats). This is an optimistic approach — Gemini LLM is called first, and fallback is expected to be rare given conservative thresholds.

---

## Decision Log

All decisions were made during brainstorming with rationale captured below.

### D1: Format scope — Full set (PDF + images + audio + video)

**Chosen:** Implement all formats from spec in a single story.

**Why:** The architectural difference between formats is minimal — all go through the same flow (Gemini LLM → text + Gemini Embedding 2 → vector). The primary work is routing logic and the Gemini API client, which are shared across all formats. Differences are limited to extraction prompts and limit validation.

**Rejected alternatives:**
- (B) PDF + images + audio only — covers 90%+ use cases but leaves spec incomplete.
- (C) PDF + images only — audio is important for digital twin (podcasts, interviews).

### D2: Gemini API client — Separate `GeminiContentService` via `google.genai` SDK

**Chosen:** New service `app/services/gemini_content.py` using the same `google.genai` SDK already in the project.

**Why:**
- Text extraction is tied to the Gemini ecosystem (same provider as embeddings) — LiteLLM abstraction is unnecessary overhead here.
- `google.genai` SDK is already in the project and proven for embeddings.
- Separate service respects SRP and OCP from `docs/development.md`.
- Multimodal file input via `google.genai` is documented and stable.

**Rejected alternatives:**
- (B) LiteLLM — good for text chat but less reliable for multimodal file processing. Additional abstraction layer with no benefit since provider switching is not planned for this pipeline.
- (C) Extend EmbeddingService — violates SRP (embedding ≠ text extraction).

### D3: File transfer strategy — Hybrid (inline < 10 MB, Files API ≥ 10 MB)

**Chosen:** Inline data for files under 10 MB, Gemini Files API for larger files.

**Why:**
- Images and short PDFs are almost always < 10 MB → inline is simpler and faster (single API call, no state, no cleanup).
- Audio ≤ 80s MP3 is typically 1–5 MB → inline.
- Video ≤ 120s MP4 can be 10–50 MB → needs Files API.
- 10 MB threshold is conservative, well within the ~20 MB inline limit.
- Two code paths are isolated inside the service — external API is identical.

**Rejected alternatives:**
- (A) Inline only — risky for video files near the 20 MB inline limit.
- (B) Files API only — works for all sizes but adds unnecessary latency and complexity for small files (90% of cases).

### D4: Routing logic — Separate `PathRouter` service

**Chosen:** New service `app/services/path_router.py` with a pure function `determine_path()`.

**Why:**
- `docs/development.md` explicitly requires OCP: "When adding a new ingestion path, create a new handler; do not branch inside the existing one."
- Routing logic contains non-trivial decisions: format checks, size/duration limits, PDF page counting. This deserves isolation.
- Pure function → 100% unit-testable without worker infrastructure.
- Current `ingestion.py` is already ~300 lines — adding routing logic would push it over the limit.

**Rejected alternatives:**
- (B) Method inside worker task — violates file size guideline, harder to test.
- (C) Inside DoclingParser — violates SRP (parser should not decide pipeline routing).

### D5: PDF page counting — `pypdf`

**Chosen:** `pypdf` for counting PDF pages in PathRouter.

**Why:** Lightweight pure Python library. Single line of code for page count. No need to fully parse the document — just metadata. No system-level dependencies.

### D6: Audio/video duration — `tinytag`

**Chosen:** `tinytag` for reading media file duration.

**Why:**
- Pure Python, no system-level dependencies (no FFmpeg, no libmediainfo).
- Supports all required formats: MP3, WAV, MP4.
- Reads only metadata headers — instant, does not decode media.
- Minimal footprint (~100 KB).

**Rejected alternatives:**
- (A) `ffprobe` — accurate but requires FFmpeg in Docker image (size increase).
- (B) `mutagen` — does not reliably support video (MP4).
- (C) `pymediainfo` — requires libmediainfo system library.

### D7: Threshold fallback — Optimistic Path A

**Chosen:** Call Gemini LLM first, check token count after, fallback to Path B if exceeded.

**Why:**
- Directly implements the spec from `docs/rag.md`.
- Fallback is expected to be rare — thresholds are chosen conservatively.
- Cost of a wasted Gemini LLM call on fallback is fractions of a cent.
- KISS — one linear flow with a single branch point.

**Important caveat — audio/video fallback:** Docling does not currently support audio or video parsing (audio via `asr` extra is planned for later stages per `docs/rag.md`). Therefore, threshold fallback to Path B is only applicable to PDF. For AUDIO and VIDEO source types, if `text_content` exceeds the media threshold, the task is marked FAILED with a descriptive error (the file is too content-dense for single-chunk indexing, and no structural parser is available yet). This will be resolved when Docling audio support is implemented.

**Rejected alternatives:**
- (B) Pre-check heuristic — unreliable without parsing the file. "Chicken and egg" problem.
- (C) Save text_content on fallback — over-engineering. Docling generates its own text.

### D8: Embedding strategy — Multimodal embed from file

**Chosen:** Pass the original file to Gemini Embedding 2, not the extracted text_content.

**Why:**
- This is the core value of Path A — native multimodal embeddings.
- For images, text description loses visual information that the embedding model can capture directly.
- All Gemini Embedding 2 outputs (from files and from text) live in the same vector space — retrieval works uniformly.
- If we embed from text_content instead, Path A loses its purpose (could just use Docling).

**Rejected alternatives:**
- (B) Embed from text_content — simpler but defeats the purpose of Path A.
- (C) Both embeddings — over-engineering for v1.

### D9: Upload endpoint — Extend existing

**Chosen:** Add new extensions to `ALLOWED_SOURCE_EXTENSIONS` in the existing `POST /api/admin/sources`.

**Why:**
- KISS — one endpoint for all source types.
- Separation of concerns: API accepts files → worker processes. Business logic (Path A/B routing) belongs in the worker.
- Unified API is simpler for the frontend and documentation.

**Rejected alternatives:**
- (B) Separate `/api/admin/sources/media` — breaks API uniformity, forces frontend to choose endpoint.
- (C) Pre-upload validation of duration — YAGNI at API level; `upload_max_file_size_mb` already guards against oversized files.

### D10: Extraction prompts — Constants in service module

**Chosen:** `EXTRACTION_PROMPTS: dict[SourceType, str]` as constants at the top of `GeminiContentService`.

**Why:**
- Four prompts totaling ~20–30 lines. A separate file is over-engineering.
- Prompts are part of extraction business logic, not user configuration. They change with the code.
- Follows existing project pattern (`ALLOWED_SOURCE_EXTENSIONS` in `storage.py`).

**Rejected alternatives:**
- (B) Separate prompts file — unnecessary for 4 short prompts.
- (C) Configuration/disk files — prompts are not user-configurable; they must be versioned with code.

### D11: Token counting — Existing HuggingFaceTokenizer

**Chosen:** Reuse the `HuggingFaceTokenizer` already used in Docling HybridChunker.

**Why:**
- Already in the project, tested, zero additional dependencies.
- For threshold decisions, ±15% accuracy is sufficient — thresholds are empirically tuned via evals.
- Local and fast — no network call needed.
- Works correctly for multilingual text (unlike `len/4` heuristic).

**Rejected alternatives:**
- (A) Gemini count_tokens API — accurate but requires a network call for a threshold check.
- (C) `len(text) / 4` heuristic — unreliable for non-Latin languages (product is multilingual).

### D12: Anchor metadata — Minimal reliable data

**Chosen:** Only metadata extractable from file headers/metadata, no Gemini-enriched content.

| Source Type | anchor_page | anchor_chapter | anchor_section | anchor_timecode |
|-------------|-------------|----------------|----------------|-----------------|
| PDF | `1` (int, first page) | None | None | None |
| IMAGE | None | None | None | None |
| AUDIO | None | None | None | `"0:00-{duration}"` |
| VIDEO | None | None | None | `"0:00-{duration}"` |

Note: `anchor_page` is `int | None` in the existing `Chunk` model and `QdrantChunkPoint`. For Path A PDFs, we store `1` (the starting page). The total page count is available in the `page_count` payload field (see Section 6) and can be used by the citation builder to render "pp. 1–6" if needed.

**Why:**
- KISS + YAGNI — for v1, file-level citations are sufficient for Path A single-chunk files.
- ID3 tags are often empty or unreliable.
- Gemini-enriched metadata is planned as chunk enrichment in S9-01 — not mixed into this story.

### D13: Worker architecture — Orchestrator + separate handler modules

**Chosen:** `process_ingestion` as thin orchestrator dispatching to `handlers/path_a.py` and `handlers/path_b.py`.

**Why:**
- `docs/development.md` literally states: "When adding a new ingestion path, create a new handler; do not branch inside the existing one."
- Each handler is isolated and independently testable.
- Existing Path B logic is extracted as a refactoring (per development.md principle 5: "refactoring is normal work").
- Orchestrator stays thin: download → route → dispatch → finalize.

### D14: Testing strategy — Unit + Integration

**Chosen:** Unit tests with mocked Gemini + integration tests with real Qdrant in Docker.

**Why:**
- PathRouter: parametrized unit tests — pure function, no mocks needed.
- Path A handler: unit tests with mocked GeminiContentService — verifies orchestration.
- Integration: real Qdrant (already in CI Docker) — verifies multimodal chunk upsert/retrieval.
- CLAUDE.md requires: "review stable implemented behavior and ensure it is covered by tests."

---

## New Components

### `app/services/path_router.py` — PathRouter

Two responsibilities: file inspection and path routing.

**File inspection** (uses external libraries):

```
inspect_file(file_bytes, source_type) → FileMetadata
```

- `FileMetadata`: dataclass with `page_count: int | None`, `duration_seconds: float | None`, `file_size_bytes: int`
- Uses `pypdf` for PDF page counting, `tinytag` for audio/video duration
- Returns `None` for fields that don't apply to the source type
- On inspection failure (corrupt file, unreadable metadata): returns `None` for the failed field — the router treats missing metadata as "cannot confirm Path A eligibility" and defaults to Path B (or FAILED for audio/video, see D7 caveat)

**Path routing** (pure function, no I/O):

```
determine_path(source_type, file_metadata: FileMetadata) → PathDecision
```

- `PathDecision`: dataclass with `path: ProcessingPath | None`, `reason: str`, `rejected: bool`, plus metadata
- Routing rules:
  - `IMAGE` → always Path A
  - `PDF` → Path A if page_count ≤ 6, else Path B
  - `AUDIO` → Path A if duration ≤ 80s; **rejected** if over limit (Docling audio support pending)
  - `VIDEO` → Path A if duration ≤ 120s; **rejected** if over limit (Docling video support pending)
  - `MARKDOWN / TXT / DOCX / HTML` → always Path B
- `determine_path()` is a pure function — 100% unit-testable without mocks
- `inspect_file()` is tested separately with real file fixtures

### `app/services/gemini_content.py` — GeminiContentService

Text extraction from multimodal files via Gemini LLM GenerateContent.

- Constructor: `google.genai.Client`, configurable model name
- Method: `extract_text_content(file_bytes, mime_type, source_type) → str`
- File transfer: `types.Part.from_bytes()` for inline (< 10 MB), Files API with `_wait_until_active()` polling for ≥ 10 MB (required for video processing)
- Per-modality prompts as module-level constants (language-neutral: "preserve the original language" — per CLAUDE.md multilingual policy)
- Retry: exponential backoff via tenacity (3 attempts)

### `app/services/embedding.py` — EmbeddingService extension

New method for multimodal file embedding. Verified: Python GenAI SDK `models.embed_content()` accepts `types.Part` objects with binary data via `types.Part.from_bytes()`.

- Method: `embed_file(file_bytes, mime_type, task_type="RETRIEVAL_DOCUMENT") → list[float]`
- Same google.genai client, model, dimensions as text embedding
- File transfer: same hybrid strategy (inline < 10 MB, Files API ≥ 10 MB) via `types.Part.from_bytes()` / Files API
- Shared file transfer helper: `app/services/gemini_file_transfer.py` — extracted for reuse between `GeminiContentService` and `EmbeddingService`. Includes `_wait_until_active()` polling for Files API uploads

---

## Worker Architecture

### Orchestrator: `app/workers/tasks/ingestion.py`

Refactored to thin orchestrator:

1. Download file from SeaweedFS (existing)
2. `PathRouter.determine_path()` — routing decision (NEW)
3. Dispatch to `handle_path_a()` or `handle_path_b()` (NEW)
4. Finalize records, update snapshot (existing)

### `app/workers/tasks/handlers/path_a.py`

Path A handler flow:

1. `GeminiContentService.extract_text_content()` → text_content
2. Count tokens via HuggingFaceTokenizer (`count_tokens()`)
3. If tokens > threshold:
   - **PDF**: return fallback signal → orchestrator dispatches to Path B
   - **Audio/Video**: raise error → task FAILED (Path B not available for these formats)
4. If tokens ≤ threshold:
   - `EmbeddingService.embed_file()` → dense vector from original file
   - Build BM25 sparse vector from text_content
   - Create single Chunk record in PG
   - Upsert to Qdrant (dense + bm25 named vectors + payload)
5. Create EmbeddingProfile (pipeline_version: "s3-04-path-a")

### `app/workers/tasks/handlers/path_b.py`

Existing Path B logic extracted from `process_ingestion`. No behavioral changes — pure refactoring.

---

## Upload & Storage Changes

### `app/services/storage.py`

- Extend `ALLOWED_SOURCE_EXTENSIONS`: `.png`, `.jpeg`, `.jpg`, `.mp3`, `.wav`, `.mp4`
- Extend extension → SourceType mapping: IMAGE, AUDIO, VIDEO
- MIME type mapping: `.png→image/png`, `.jpeg/.jpg→image/jpeg`, `.mp3→audio/mpeg`, `.wav→audio/wav`, `.mp4→video/mp4`

### `app/api/admin.py`

No structural changes. New extensions are picked up automatically via updated `ALLOWED_SOURCE_EXTENSIONS`.

---

## Configuration

New settings in `app/core/config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `path_a_text_threshold_pdf` | 2000 | Token threshold for PDF: Path A → Path B fallback |
| `path_a_text_threshold_media` | 500 | Token threshold for media: Path A → Path B fallback |
| `path_a_max_pdf_pages` | 6 | Max PDF pages for Path A eligibility |
| `path_a_max_audio_duration_sec` | 80 | Max audio duration (seconds) for Path A |
| `path_a_max_video_duration_sec` | 120 | Max video duration (seconds) for Path A |
| `gemini_content_model` | `"gemini-2.5-flash"` | Gemini model for text extraction |
| `gemini_file_upload_threshold_bytes` | 10485760 | Inline vs Files API threshold (10 MB) |

All thresholds are configurable and refined via evals. Settings follow the existing convention: snake_case field names map to uppercase env vars (e.g., `gemini_content_model` → `GEMINI_CONTENT_MODEL`).

---

## Dependencies

### New Python packages

| Package | Purpose | Size impact |
|---------|---------|-------------|
| `pypdf` | PDF page counting (PathRouter) | ~3 MB, pure Python |
| `tinytag` | Audio/video duration (PathRouter) | ~100 KB, pure Python |

Both are pure Python — no system-level dependencies. Docker image size impact is minimal.

### Existing packages (no new installs)

- `google-genai` — GeminiContentService + EmbeddingService.embed_file()
- `tenacity` — retry logic
- `qdrant-client` — upsert with multimodal embeddings

---

## Data Flow

```
                         +-------------------+
                         |  Upload Endpoint  |
                         |  (admin.py)       |
                         +---------+---------+
                                   | file -> SeaweedFS, metadata -> PG, task -> Redis
                                   v
                         +-------------------+
                         |  Worker           |
                         |  (orchestrator)   |
                         +---------+---------+
                                   | download file
                                   v
                         +-------------------+
                         |  PathRouter       |
                         |  determine_path() |
                         +-----+-------+-----+
                      Path A   |       |  Path B
                               v       v
                 +-----------------+  +------------------+
                 |  Path A Handler |  |  Path B Handler  |
                 |                 |  |  (existing logic) |
                 +------+----------+  +------------------+
                        |
               +--------+--------+
               v                 v
      +--------------+  +------------------+
      | Gemini LLM   |  | Token count      |
      | GenerateContent| | (HuggingFace    |
      | -> text_content| |  tokenizer)     |
      +--------------+  +--------+---------+
                                 |
                        +--------+--------+
                        | > threshold?    |
                        +---+--------+----+
                       No   |        |  Yes
                            v        v
                   +-----------+  +------------------+
                   | Embed file|  | PDF: Fallback    |
                   | (multi-   |  | -> Path B Handler|
                   |  modal)   |  | Audio/Video:     |
                   |           |  | -> FAILED (no    |
                   |           |  |  parser yet)     |
                   +-----------+  +------------------+
                   | + BM25    |
                   +-----+-----+
                         v
                   +-----------+
                   | 1 Chunk:  |
                   | PG+Qdrant |
                   | dense+bm25|
                   +-----------+
```

---

## Testing Strategy

### Unit tests (CI, no external dependencies)

1. **PathRouter** (`tests/unit/test_path_router.py`)
   - Parametrized: every source type x size/pages/duration -> expected path
   - Edge cases: exactly at thresholds (6 pages, 80s, 120s)
   - Always Path B: MARKDOWN, TXT, DOCX, HTML
   - pypdf/tinytag failures -> fallback to Path B

2. **Path A handler** (`tests/unit/test_path_a_handler.py`)
   - Mock GeminiContentService + EmbeddingService
   - Happy path: text_content under threshold -> single chunk created
   - Threshold fallback: text_content over threshold -> returns fallback signal
   - Error handling: Gemini API failure -> task marked FAILED

3. **GeminiContentService** (`tests/unit/test_gemini_content.py`)
   - Mock google.genai.Client
   - Correct prompt selected per source type
   - File size < 10 MB -> inline path
   - File size >= 10 MB -> Files API path (upload + cleanup)

4. **EmbeddingService.embed_file** (`tests/unit/test_embedding_file.py`)
   - Mock genai client
   - Correct task type and dimensions passed
   - Inline vs Files API threshold

### Integration tests (CI, real Qdrant in Docker)

5. **Path A end-to-end** (`tests/integration/test_path_a_ingestion.py`)
   - Mock only Gemini (fixed text_content + embedding vector)
   - Real Qdrant: upsert Path A chunk -> hybrid search retrieves it
   - Verify payload: text_content, anchor metadata, source_type, processing_path
   - Verify dense + bm25 vectors both present and searchable

---

## Error Handling

Consistent with existing Path B error handling pattern.

| Error | Behavior |
|-------|----------|
| Gemini LLM GenerateContent fails | Retry 3x (tenacity) -> mark task FAILED |
| Gemini Embedding 2 embed_file fails | Retry 3x -> mark task FAILED |
| Files API upload fails | Retry 3x -> mark task FAILED |
| Token count exceeds threshold (PDF) | Not an error — fallback to Path B |
| Token count exceeds threshold (audio/video) | Mark task FAILED — Docling does not yet support audio/video parsing |
| Audio/video over duration limit (router) | Rejected by PathRouter — mark task FAILED (no Path B available) |
| pypdf can't read PDF | Log warning -> fallback to Path B (let Docling try) |
| tinytag can't read duration | Log warning -> default to Path A (assume within limit; if text_content is too long, threshold check catches it) |
| Qdrant upsert fails | Handler cleans up its own points -> mark task FAILED |

**Key principle:** PathRouter failures for text formats (can't count pages) result in conservative fallback to Path B. For audio/video, duration-gate failures default to Path A (threshold check is the safety net). Audio/video exceeding duration limits are rejected outright — Path B is not available for these formats.

---

## Out of Scope

- Gemini Batch API for Path A (planned in S3-06)
- Chunk enrichment with LLM-generated metadata (planned in S9-01)
- Audio transcription via Deepgram (later phases)
- Parent-child chunking for Path A chunks (planned in S9-02)
- Extended audio/video formats beyond MP3/WAV/MP4
