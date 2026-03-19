## Story

**S2-02: Parse + chunk + embed**

Worker picks up the task: Docling parses the file → HybridChunker splits into chunks with anchor metadata → Gemini Embedding 2 generates dense vectors → upsert into Qdrant with payload.

**Verification criteria:** Upload MD file → chunks in PG with metadata; chunks in Qdrant; vector search returns results.

**Test coverage requirement:** All stable behavior (parsing, embedding, Qdrant upsert, snapshot auto-creation, pipeline error handling) must be covered by CI tests before archive.

## Why

S2-01 delivered file upload with a noop ingestion worker. Without real parsing, chunking, and embedding, uploaded documents are dead weight — they exist in storage but cannot be searched or used for RAG. S2-02 is the critical path to a working E2E slice: it turns uploaded files into searchable knowledge.

## What Changes

- Replace noop ingestion (`_run_noop_ingestion`) with a real pipeline: download → parse → chunk → embed → index
- Add Docling integration for structure-aware document parsing (MD/TXT)
- Add Gemini Embedding 2 client via Google GenAI SDK for dense vector generation
- Add Qdrant client for vector collection management and chunk upsert
- Add auto-draft snapshot creation (get_or_create_draft) for chunk tagging
- Add `StorageService.download()` for file retrieval from MinIO
- Add `language` column to `sources` table + partial unique index on draft snapshots
- Add new configuration settings (embedding dimensions, batch size, chunk tokens, Qdrant collection)
- Create Document + DocumentVersion + Chunk records during ingestion
- Create EmbeddingProfile records for pipeline audit trail

## Capabilities

### New Capabilities

- `ingestion-pipeline`: Document parsing (Docling), structure-aware chunking (HybridChunker), embedding generation (Gemini Embedding 2), and vector indexing (Qdrant). Covers Path B processing, batch embedding, tenacity retry, and all-or-nothing error handling.
- `vector-storage`: Qdrant collection management with named dense vectors, payload indexes, dimension mismatch detection, and point upsert. Forward-compatible for S3-02 sparse vectors.
- `snapshot-draft`: Auto-creation of draft knowledge snapshots during ingestion. Race-condition safe via partial unique index. Foundation for S2-03 snapshot lifecycle.

### Modified Capabilities

- `source-upload`: Persist `language` field from upload metadata (currently accepted but silently dropped). Add migration for `language` column.

## Impact

- **New dependencies:** docling ≥ 2.80.0, google-genai ≥ 1.14.0, qdrant-client ≥ 1.14.0
- **New services:** DoclingParser, EmbeddingService, QdrantService, SnapshotService
- **Modified services:** StorageService (add download), SourceService (persist language)
- **Database:** Migration 004 — `sources.language` column + `uq_one_draft_per_scope` partial unique index
- **Worker:** New service initialization in startup, real pipeline replacing noop
- **Configuration:** 7 new Settings fields (gemini_api_key, embedding_model, embedding_dimensions, chunk_max_tokens, qdrant_collection, bm25_language, embedding_batch_size)
- **Environment:** GEMINI_API_KEY required for real Gemini calls (empty for CI — tests mock the SDK)
