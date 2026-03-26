## Story

**S4-06: Lightweight knowledge processing migration** (Phase 4 — Dialog Expansion)

**Verification criteria** (from `docs/plan.md`):
- Docling and local ML stacks are absent from runtime dependencies
- Supported text-centric formats still ingest successfully through the lightweight path
- Complex documents route through the external fallback
- Qdrant payloads and citations remain compatible

**Test coverage requirement** (Phase 4, outside Phase 1): All stable behavior introduced by this story — provider-agnostic interface, Path C routing, scan detection, Document AI normalization, graceful disable — MUST be covered by CI tests before archive.

## Why

The codebase has already migrated away from Docling at the implementation level — `DoclingParser` does not import or use Docling, and no Docling dependency exists in `pyproject.toml`. However, the naming, interface design, and documentation still reference Docling, and the canonical architecture calls for an external Document AI fallback (Path C) that has not been implemented. This story closes the gap between the actual lightweight implementation and the target architecture described in `docs/lightweight-knowledge-processing-migration.md`.

## What Changes

- **Rename `DoclingParser` → `LightweightParser`** and extract a provider-agnostic `DocumentProcessor` Protocol with a shared `TextChunker`.
- **Add `DocumentAIParser`** — a new adapter for Google Cloud Document AI (Layout Parser) implementing the same Protocol, with retry logic (tenacity) for transient gRPC errors.
- **Add Path C routing** — hybrid auto-detection (scan heuristic: low chars/page from pypdf) plus explicit user override via `processing_hint` field on upload.
- **Add `PATH_C` to `ProcessingPath` enum** — requires Alembic migration (`ALTER TYPE processing_path_enum ADD VALUE`).
- **Add `processing_hint` column to `DocumentVersion`** — nullable `String(32)` for audit, via the same Alembic migration.
- **Add `google-cloud-documentai` dependency** — lightweight gRPC client, no ML runtime.
- **Graceful disable** — if Document AI is not configured (no `DOCUMENT_AI_PROJECT_ID`), Path C is unavailable; documents that would qualify fall back to Path B with a warning. Warning ownership: the router logs for explicit hint fallback, the path_b handler logs for scan auto-detection fallback.
- **Remove dead code** — `_chunk_external_document()`, unused `chunker` parameter, `_extract_anchor_page()`.
- **Update living documentation** — `docs/rag.md`, `docs/lightweight-knowledge-processing-migration.md`, verify `docs/architecture.md` and `docs/spec.md`. Archived specs and completed story descriptions are NOT modified.

## Capabilities

### New Capabilities
- `document-ai-fallback`: External Document AI adapter (Path C) for complex documents — scanned PDFs, complex tables, layout-heavy documents. Includes routing, scan detection, graceful disable, and retry logic.

### Modified Capabilities
- `ingestion-pipeline`: Path routing gains `PATH_C` + `processing_hint` parameter. `DoclingParser` renamed to `LightweightParser`. Dead code removed. Shared `TextChunker` extracted.
- `multi-format-parsing`: All references to Docling class/module names replaced with lightweight parser equivalents. `DocumentProcessor` Protocol introduced as the parsing contract.
- `source-upload`: Upload API gains optional `processing_hint` field (`"auto"` | `"external"`).

## Impact

- **Backend services**: `docling_parser.py` renamed, `path_router.py` extended, new `document_ai_parser.py` and `path_c.py` handler, `pipeline.py` and `ingestion.py` updated.
- **Database**: Alembic migration for `processing_path_enum` (add `path_c`) and `document_versions.processing_hint` column.
- **API**: `POST /api/admin/sources` metadata schema gains optional `processing_hint` field. Fully backward-compatible (defaults to `"auto"`).
- **Dependencies**: `google-cloud-documentai` added to `pyproject.toml`. No local ML runtimes.
- **Configuration**: New `.env` variables — `DOCUMENT_AI_PROJECT_ID`, `DOCUMENT_AI_LOCATION`, `DOCUMENT_AI_PROCESSOR_ID`, `PATH_C_MIN_CHARS_PER_PAGE`.
- **Documentation**: `docs/rag.md`, `docs/lightweight-knowledge-processing-migration.md` updated. `docs/architecture.md` and `docs/spec.md` verified.
