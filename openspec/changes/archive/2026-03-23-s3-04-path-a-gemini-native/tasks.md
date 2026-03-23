## 1. Dependencies and Configuration

- [x] 1.1 Add `pypdf` and `tinytag` to `backend/pyproject.toml`, lock and verify imports
- [x] 1.2 Add Path A configuration settings to `backend/app/core/config.py` (thresholds, model, file upload threshold) with tests

## 2. Storage Extensions

- [x] 2.1 Extend `ALLOWED_SOURCE_EXTENSIONS` and `SOURCE_TYPE_BY_EXTENSION` in `backend/app/services/storage.py` for media types (PNG, JPEG, MP3, WAV, MP4)
- [x] 2.2 Add `MIME_TYPE_BY_EXTENSION` mapping to `backend/app/services/storage.py` with tests

## 3. PathRouter Service

- [x] 3.1 Implement `FileMetadata` dataclass, `PathDecision` dataclass (with `rejected` flag), and `inspect_file()` in `backend/app/services/path_router.py`
- [x] 3.2 Implement `determine_path()` pure function with all routing rules (Path A / Path B / REJECT) and configurable thresholds
- [x] 3.3 Write parametrized unit tests for `determine_path()` covering all source types, boundary values, rejection cases, and custom thresholds
- [x] 3.4 Write unit tests for `inspect_file()` with real PDF fixtures, corrupt files, and image/audio edge cases

## 4. Gemini File Transfer Helper

- [x] 4.1 Implement `PreparedFilePart` dataclass, `prepare_file_part()` (inline via `Part.from_bytes` / Files API), `_wait_until_active()` polling, and `cleanup_uploaded_file()` in `backend/app/services/gemini_file_transfer.py`
- [x] 4.2 Write unit tests for inline vs Files API threshold, polling behavior, and cleanup

## 5. GeminiContentService

- [x] 5.1 Implement `GeminiContentService` with per-modality `EXTRACTION_PROMPTS`, `extract_text_content()`, retry logic, and file transfer integration in `backend/app/services/gemini_content.py`
- [x] 5.2 Write unit tests: prompt selection per source type, language-neutrality check, inline and Files API paths, retry on retryable errors

## 6. EmbeddingService Extension

- [x] 6.1 Add `embed_file()` method to `backend/app/services/embedding.py` using `gemini_file_transfer` helper, with retry and dimension validation
- [x] 6.2 Write unit tests for `embed_file()`: correct task type, dimensions, inline vs Files API, and verify existing `embed_texts()` tests still pass

## 7. Worker Refactoring — Path B Extraction

- [x] 7.1 Create `backend/app/workers/tasks/handlers/__init__.py` and extract Path B logic into `backend/app/workers/tasks/handlers/path_b.py` with cleanup ownership (try/except + `mark_persisted_records_failed`)
- [x] 7.2 Rename `_mark_persisted_records_failed` to `mark_persisted_records_failed` in `ingestion.py` (make importable by handlers)
- [x] 7.3 Refactor `_run_ingestion_pipeline` in `ingestion.py` to call `handle_path_b()` instead of inline logic; snapshot management stays in orchestrator
- [x] 7.4 Run full test suite to verify zero regressions from refactoring

## 8. Path A Handler

- [x] 8.1 Implement `PathAResult`, `PathAFallback` dataclasses and `handle_path_a()` in `backend/app/workers/tasks/handlers/path_a.py` with threshold fallback, anchor metadata, cleanup ownership, and Qdrant upsert
- [x] 8.2 Extend `QdrantChunkPoint` with optional `page_count` and `duration_seconds` fields; add them to inline payload dict in `upsert_chunks()` (only when non-None)
- [x] 8.3 Write unit tests: happy path (image), image skips threshold check (no fallback regardless of token count), threshold fallback (PDF), audio threshold raises, Gemini failure propagation, Qdrant failure triggers cleanup

## 9. Orchestrator Wiring

- [x] 9.1 Extend `PipelineServices` with `gemini_content_service`, `tokenizer`, and Path A config; add fail-fast validation in `_load_pipeline_services`
- [x] 9.2 Update `_run_ingestion_pipeline` to use PathRouter (inspect → determine → reject or dispatch) and handle `PathAFallback` → Path B
- [x] 9.3 Parameterize `_finalize_pipeline_success` to accept `processing_path` and `pipeline_version` from handler results
- [x] 9.4 Initialize `GeminiContentService` and `HuggingFaceTokenizer` in `backend/app/workers/main.py` on_startup

## 10. Integration Tests

- [x] 10.1 Write worker-level integration test: image happy path (real PG + Qdrant, mocked Gemini) — verify Source READY, Task COMPLETE, 1 Chunk, PATH_A, pipeline_version, hybrid search finds chunk
- [x] 10.2 Write worker-level integration test: PDF threshold fallback (mock Gemini returns >2000 tokens for 3-page PDF) — verify fallback to Path B with multiple chunks
- [x] 10.3 Write worker-level integration test: audio/video rejection (duration > limit) — verify Task FAILED with descriptive error

## 11. Documentation Sync

- [x] 11.1 Update `docs/spec.md` and `docs/rag.md` to clarify audio/video Path B availability (currently unavailable, Docling ASR pending)

## 12. Real-Provider Eval (non-CI, manual)

- [ ] 12.1 Run a smoke test with real Gemini API: upload a small PNG image, verify text_content is generated and chunk is searchable
- [ ] 12.2 Run a smoke test with real Gemini API: upload a short MP3 audio (<80s), verify transcription and embedding
- [ ] 12.3 Run a smoke test with real Gemini API: upload a 3-page PDF, verify Path A single-chunk indexing
- [ ] 12.4 Document eval results (text quality, embedding search accuracy) in a brief note — this informs future threshold tuning

## 13. Final Verification

- [x] 13.1 Run full test suite (`uv run pytest -v`) — all tests pass
- [x] 13.2 Run linter (`uv run ruff check app/ tests/`) — no errors
- [x] 13.3 Verify all installed package versions are at or above minimums in `docs/spec.md`
