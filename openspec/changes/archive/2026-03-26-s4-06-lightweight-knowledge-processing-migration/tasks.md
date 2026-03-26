## 1. Extract TextChunker + DocumentProcessor Protocol

- [x] 1.1 Create `backend/app/services/document_processing.py` with `ParsedBlock` dataclass, `ChunkData` dataclass, `DocumentProcessor` Protocol, `TextChunker` class (extracted from `DoclingParser._chunk_blocks`), and helper functions (`_normalize_whitespace`, `_estimate_tokens`)
- [x] 1.2 Create `backend/tests/unit/services/test_text_chunker.py` with unit tests: single block within budget, split on exceeding budget, merge small blocks, skip empty text, empty input, anchor preservation from first block
- [x] 1.3 Run tests via `docker compose exec api python -m pytest tests/unit/services/test_text_chunker.py -v` — all PASS

## 2. Rename DoclingParser → LightweightParser + Rewire Imports

- [x] 2.1 Rename `backend/app/services/docling_parser.py` → `backend/app/services/lightweight_parser.py`, rename class `DoclingParser` → `LightweightParser`, import `ChunkData`/`ParsedBlock`/`TextChunker` from `document_processing`, delegate chunking to `TextChunker`, replace internal `_ParsedBlock` with shared `ParsedBlock`
- [x] 2.2 Remove dead code: `_chunk_external_document()` method, `chunker` parameter from `__init__`, `_extract_anchor_page()` method, conditional in `_chunk_document`
- [x] 2.3 Update `backend/app/workers/tasks/pipeline.py`: change TYPE_CHECKING import to `DocumentProcessor`, rename field `docling_parser` → `document_processor` (type: `DocumentProcessor`)
- [x] 2.4 Update `backend/app/workers/main.py`: change import to `LightweightParser`, rename ctx key `"docling_parser"` → `"document_processor"`
- [x] 2.5 Update `backend/app/workers/tasks/ingestion.py`: rename `ctx["docling_parser"]` → `ctx["document_processor"]`, update validation message
- [x] 2.6 Update `backend/app/workers/tasks/handlers/path_b.py`: change `services.docling_parser` → `services.document_processor`
- [x] 2.7 Rename `backend/tests/unit/services/test_docling_parser.py` → `test_lightweight_parser.py`, update all imports and class references, remove test for `_chunk_external_document` (`test_chunk_indices_stay_sequential_when_empty_chunks_are_skipped`)
- [x] 2.8 Run full unit test suite via `docker compose exec api python -m pytest tests/unit/ -v` — all PASS

## 3. Add PATH_C Enum + Configuration + Alembic Migration

- [x] 3.1 Add `PATH_C = "path_c"` to `ProcessingPath` in `backend/app/db/models/enums.py`
- [x] 3.2 Add `processing_hint` column (`String(32)`, nullable) to `DocumentVersion` in `backend/app/db/models/knowledge.py`
- [x] 3.3 Add Document AI settings to `backend/app/core/config.py`: `document_ai_project_id`, `document_ai_location`, `document_ai_processor_id`, `path_c_min_chars_per_page`, computed `document_ai_enabled` property, update `normalize_empty_optional_strings`. Add a `model_validator` that raises `ValueError` if `document_ai_project_id` is set but `document_ai_processor_id` is not (partial config = startup error)
- [x] 3.4 Create Alembic migration: `ALTER TYPE processing_path_enum ADD VALUE IF NOT EXISTS 'path_c'` + `ADD COLUMN processing_hint String(32) NULLABLE` on `document_versions`
- [x] 3.5 Apply migration via `docker compose exec api alembic upgrade head` and verify
- [x] 3.6 Run unit tests — all PASS

## 4. Add processing_hint to Upload API + Path C Routing

- [x] 4.1 Add `processing_hint: Literal["auto", "external"] = "auto"` to `SourceUploadMetadata` in `backend/app/api/schemas.py`
- [x] 4.2 Update `backend/app/services/source.py` `create_source_and_task` to store `processing_hint` in `task.result_metadata` when not `"auto"`
- [x] 4.3 Update `backend/app/services/path_router.py`: add `document_ai_enabled` to `PathRouterSettings` Protocol, add `processing_hint` parameter to `determine_path()`, handle `external` + enabled → PATH_C, handle `external` + disabled → PATH_B + warning (router logs via structlog)
- [x] 4.4 Update `backend/app/workers/tasks/ingestion.py` `_run_ingestion_pipeline`: read `processing_hint` from `task.result_metadata`, pass to `determine_path()`
- [x] 4.5 Update `initialize_pipeline_records` in `pipeline.py` to accept and persist `processing_hint` on `DocumentVersion`
- [x] 4.6 Update existing `backend/tests/unit/services/test_path_router.py`: add `document_ai_enabled=False` to `_settings()`
- [x] 4.7 Create `backend/tests/unit/services/test_path_c_routing.py` with tests: external→PATH_C, external ignored for text formats, external falls back when disabled (long PDF), external falls back when disabled (short PDF), auto preserves existing routing, default unchanged
- [x] 4.8 Run unit tests — all PASS

## 5. Implement DocumentAIParser

- [x] 5.1 Add `google-cloud-documentai>=3.0.0` to `backend/pyproject.toml` dependencies
- [x] 5.2 Create `backend/app/services/document_ai_parser.py`: `DocumentAIParser` class implementing `DocumentProcessor` Protocol, uses `documentai.DocumentProcessorServiceClient`, `TextChunker` for chunking, retry via tenacity (3 attempts, exp backoff 1-8s, only `ServiceUnavailable`/`DeadlineExceeded`), extracts paragraphs per page into `ParsedBlock` list
- [x] 5.3 Create `backend/tests/unit/services/test_document_ai_parser.py`: normalized chunks from fake response, empty response returns empty, anchor_timecode is None for PDF
- [x] 5.4 Rebuild Docker image via `docker compose build api` to include new dependency
- [x] 5.5 Run unit tests — all PASS

## 6. Path C Handler + Scan Detection Reroute

- [x] 6.1 Add `document_ai_parser: DocumentAIParser | None = None` and `path_c_min_chars_per_page: int = 50` to `PipelineServices` in `pipeline.py`
- [x] 6.2 Conditionally instantiate `DocumentAIParser` in `backend/app/workers/main.py` `on_startup` when `settings.document_ai_enabled`, store in ctx
- [x] 6.3 Update `_load_pipeline_services` in `ingestion.py` to wire `document_ai_parser` and `path_c_min_chars_per_page`
- [x] 6.4 Create `backend/app/workers/tasks/handlers/path_c.py`: `handle_path_c()` following path_b pattern — call `DocumentAIParser.parse_and_chunk`, persist chunks, embed (interactive or batch), upsert to Qdrant, `processing_path=PATH_C`, `pipeline_version="s4-06-path-c"`, pass `processing_hint` to `initialize_pipeline_records`
- [x] 6.5 Add scan detection to `path_b.py`: `_is_suspected_scan(chunk_data, page_count, min_chars_per_page)` using `page_count` from `FileMetadata` (no re-reading PDF), reroute to `handle_path_c` if suspected scan and Document AI is configured
- [x] 6.6 Update `handle_path_b` signature to accept `file_metadata: FileMetadata` for scan detection
- [x] 6.7 Update `_run_ingestion_pipeline` in `ingestion.py`: add Path C dispatch (`path_decision.path is ProcessingPath.PATH_C → handle_path_c`), pass `file_metadata` to `handle_path_b` calls
- [x] 6.8 Create `backend/tests/integration/test_path_c_ingestion.py`: Path C full cycle (mock Document AI + mock Embedding), scan reroute from Path B, graceful disable, processing_hint="external" routes to Path C
- [ ] 6.9 Run full test suite — all PASS

## 7. Update Living Documentation

- [x] 7.1 Update `docs/lightweight-knowledge-processing-migration.md`: add "Migration status: Complete" section with implementation details and configuration added
- [x] 7.2 Update `docs/rag.md`: replace all Docling/HybridChunker references, "Path B — Docling" → "Path B — lightweight local", add Path C section, update multilingual table, update pipeline diagrams
- [x] 7.3 Verify `docs/architecture.md` — already references "Lightweight Parser Stack" and "Document AI Fallback", fix any remaining Docling references
- [x] 7.4 Update `docs/spec.md` — add `path_c_min_chars_per_page` to implementation defaults table if not present

## 8. Final Regression + Cleanup

- [ ] 8.1 Run full test suite via `docker compose exec api python -m pytest tests/ -v --tb=short` — all PASS
- [x] 8.2 Verify zero "docling" references in runtime code: grep `backend/app/` for "docling" — zero matches
- [x] 8.3 Verify no local ML dependencies in `pyproject.toml`: no torch, torchvision, transformers, cuda, docling
- [x] 8.4 Verify Docker build succeeds: `docker compose build api worker`
