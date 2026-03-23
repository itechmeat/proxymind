## Story

**S3-04: Path A (Gemini native)** — For short PDFs/images/audio/video: Gemini LLM → text_content, Gemini Embedding 2 → vector. Thresholds for switching to Path B.

**Verification:** Upload image → text_content generated → search query finds it.

**Stable behavior requiring test coverage:** Path B ingestion pipeline (existing), hybrid search retrieval, snapshot binding during ingestion.

## Why

The ingestion pipeline currently processes all sources through Docling (Path B), which cannot handle images, audio, or video. Short PDFs are also over-processed — Docling parses and chunks them when a single-chunk Gemini native representation would suffice. Path A enables multimodal knowledge ingestion, a core requirement for a digital twin that learns from podcasts, photos, and short documents.

## What Changes

- New `PathRouter` service decides Path A, Path B, or REJECT based on source type, page count, and media duration
- New `GeminiContentService` extracts text from multimodal files via Gemini LLM GenerateContent
- New `embed_file()` method on `EmbeddingService` generates embeddings directly from files (multimodal)
- New `gemini_file_transfer` helper handles inline vs Files API with polling for video readiness
- Upload endpoint accepts new file types: PNG, JPEG, MP3, WAV, MP4
- Worker refactored: thin orchestrator dispatching to separate Path A and Path B handler modules
- Path A creates a single chunk per file; Path B behavior unchanged
- Threshold-based fallback: if Path A text_content is too long (PDF only), file redirected to Path B
- Audio/video exceeding duration limits are rejected (Docling does not yet support these formats)

## Capabilities

### New Capabilities
- `multimodal-ingestion`: Path A pipeline — Gemini native text extraction, multimodal embedding, single-chunk indexing, path routing logic, threshold fallback, and media file inspection
- `gemini-file-transfer`: Shared helper for inline vs Files API file transfer with upload polling

### Modified Capabilities
- `ingestion-pipeline`: Worker refactored into orchestrator + handler modules (Path A / Path B); cleanup ownership moved to handlers; `PipelineServices` extended with new services
- `source-upload`: Accepts new file extensions (PNG, JPEG, MP3, WAV, MP4) with MIME type mapping

## Impact

- **New files:** `app/services/path_router.py`, `app/services/gemini_content.py`, `app/services/gemini_file_transfer.py`, `app/workers/tasks/handlers/path_a.py`, `app/workers/tasks/handlers/path_b.py`
- **Modified files:** `app/services/storage.py`, `app/services/embedding.py`, `app/services/qdrant.py`, `app/workers/tasks/ingestion.py`, `app/workers/main.py`, `app/core/config.py`
- **New dependencies:** `pypdf` (PDF page counting), `tinytag` (audio/video duration)
- **API:** No new endpoints; existing `POST /api/admin/sources` accepts new file types
- **Qdrant:** New optional payload fields `page_count`, `duration_seconds` for Path A chunks
- **Docs:** `docs/spec.md` and `docs/rag.md` need sync re: audio/video Path B availability
