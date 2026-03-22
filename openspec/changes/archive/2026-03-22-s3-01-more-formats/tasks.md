## 0. Preflight

- [x] 0.1 Read `docs/development.md` — binding implementation standard
- [x] 0.2 Read the design spec `docs/superpowers/specs/2026-03-22-s3-01-more-formats-design.md`
- [x] 0.3 Run `find-skills` discovery for Docling, FastAPI, pytest, PDF parsing, SQLAlchemy — install any relevant skills into the project
- [x] 0.4 Verify dependency versions meet `docs/spec.md` minimums: `uv run python -c "import docling; print(docling.__version__)"`

## 1. Storage Validation (extension mapping)

- [x] 1.1 Update unit tests in `tests/unit/test_source_validation.py`: parametrize `.pdf`, `.docx`, `.html`, `.htm` as accepted; `.xlsx`, `.png`, `.csv`, `.zip` as rejected; add type mapping tests for all new extensions
- [x] 1.2 Run tests — verify they fail (red)
- [x] 1.3 Update `app/services/storage.py`: add `.pdf`, `.docx`, `.html`, `.htm` to `ALLOWED_SOURCE_EXTENSIONS` and `SOURCE_TYPE_BY_EXTENSION`
- [x] 1.4 Run tests — verify they pass (green)
- [x] 1.5 Propose commit: `feat(storage): accept PDF, DOCX, HTML, HTM file extensions (S3-01)`

## 2. Test Fixtures

- [x] 2.1 Create `tests/fixtures/sample.html` — static HTML with `<h1>`–`<h3>`, `<p>`, `<table>`, `<ul>`
- [x] 2.2 Generate `tests/fixtures/sample.pdf` — 2 pages, headings, table, paragraphs (ephemeral `uv run --with reportlab`, delete generator script after)
- [x] 2.3 Generate `tests/fixtures/sample.docx` — H1/H2 headings, paragraphs, list, table (ephemeral `uv run --with python-docx`, delete generator script after)
- [x] 2.4 Verify all three fixtures exist with reasonable sizes
- [x] 2.5 Propose commit: `test: add PDF, DOCX, HTML test fixtures (S3-01)`

## 3. DoclingParser Multi-Format Support

- [x] 3.1 Write failing unit test: PDF → chunks with `anchor_page` populated
- [x] 3.2 Write failing unit test: DOCX → chunks with `anchor_chapter` from headings
- [x] 3.3 Write failing unit test: HTML → chunks with `anchor_chapter` from `<h1>`–`<h6>`
- [x] 3.4 Write failing unit test: PDF table content appears in chunk text
- [x] 3.5 Write failing unit test: unsupported `SourceType.AUDIO` → `ValueError`
- [x] 3.6 Write failing unit test: corrupt PDF (`b"not-a-real-pdf"`) → raises exception
- [x] 3.7 Run all new tests — confirm they fail (red)
- [x] 3.8 Update `DocumentConverter` in `docling_parser.py:37` to `allowed_formats=[InputFormat.MD, InputFormat.PDF, InputFormat.DOCX, InputFormat.HTML]`
- [x] 3.9 Add module-level `_SOURCE_TYPE_TO_INPUT_FORMAT` mapping and extend `_convert_document` for PDF/DOCX/HTML via `DocumentStream`
- [x] 3.10 If Docling needs PDF extras: `uv add 'docling[pdf]'`
- [x] 3.11 Run all parser tests — verify they pass (green), including existing MD/TXT tests
- [x] 3.12 Propose commit: `feat(parser): extend DoclingParser for PDF, DOCX, HTML formats (S3-01)`

## 4. Upload Size Limit

- [x] 4.1 Change `upload_max_file_size_mb` default from 50 to 100 in `app/core/config.py:46`
- [x] 4.2 Align test fixture default in `tests/conftest.py:198` (50 → 100)
- [x] 4.3 Run existing oversized file test — verify it still passes
- [x] 4.4 Propose commit: `feat(config): raise upload_max_file_size_mb default to 100 (S3-01)`

## 5. Integration Tests

- [x] 5.1 Extend parametrized upload test to include `report.pdf`, `document.docx`, `page.html`, `page.htm`
- [x] 5.2 Update rejection test to use `.xlsx` instead of `.pdf`
- [x] 5.3 Run integration tests — verify all pass
- [x] 5.4 Propose commit: `test(upload): extend integration tests for PDF, DOCX, HTML uploads (S3-01)`

## 6. Worker Smoke Tests

- [x] 6.1 Add smoke test: upload HTML → `process_ingestion` with real `DoclingParser` (mocked embedding/qdrant) → verify task completes with `chunk_count > 0`
- [x] 6.2 Add integration test for corrupt file contract: upload corrupt PDF → `process_ingestion` with real `DoclingParser` → verify task and source are FAILED
- [x] 6.3 Run both smoke tests — verify they pass
- [x] 6.4 Propose commit: `test(worker): add smoke tests — real parser for HTML and corrupt file contract (S3-01)`

## 7. Final Verification

- [x] 7.1 Run full test suite: `uv run python -m pytest tests/ -v --tb=short`
- [x] 7.2 Run linter: `uv run ruff check app/ tests/`
- [x] 7.3 Verify dependency versions against `docs/spec.md` minimums
- [x] 7.4 Re-read `docs/development.md` and self-review the implementation against its checklist
- [x] 7.5 Confirm pre-code read (Task 0) and post-code self-review (this step) were both completed
