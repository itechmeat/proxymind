## Story

**S3-01: More formats (PDF, DOCX, HTML)** — Phase 3: Knowledge Expansion.

Verification criteria from `docs/plan.md`:
- Upload PDF → chunks with page numbers
- Upload DOCX → chunks with headings
- Upload HTML → chunks with heading anchors
- PDF/DOCX/HTML can be uploaded and parsed correctly

Stable behavior to cover with tests: PDF/DOCX/HTML parsing, anchor metadata extraction per format, file extension validation, upload endpoint acceptance of new formats.

## Why

The ingestion pipeline currently accepts only Markdown and TXT files. This blocks the primary use case of digital twins — uploading books (PDF), articles (DOCX), and saved web pages (HTML) as knowledge sources. Extending format support is the first story of the Knowledge Expansion phase and unblocks all subsequent stories (BM25 sparse vectors, hybrid retrieval, Path A, batch API) which assume multi-format content.

## What Changes

- Accept `.pdf`, `.docx`, `.html`, `.htm` file extensions in the upload endpoint
- Extend `DoclingParser` to configure `DocumentConverter` with `InputFormat.PDF`, `InputFormat.DOCX`, `InputFormat.HTML`
- Extract anchor metadata per format: `anchor_page` from PDF provenance, `anchor_chapter`/`anchor_section` from headings in all formats
- Raise `upload_max_file_size_mb` default from 50 to 100 MB to accommodate PDF books
- Corrupt/malformed files: parser raises exception, worker marks task as FAILED
- Add static test fixtures (sample.pdf, sample.docx, sample.html) and comprehensive unit + integration tests
- Add worker smoke coverage for the real `DoclingParser`: HTML success path in the worker plus corrupt PDF failure contract in the worker

## Capabilities

### New Capabilities

- `multi-format-parsing`: PDF, DOCX, and HTML document parsing via Docling with structure-aware chunking and per-format anchor metadata extraction.

### Modified Capabilities

- `source-upload`: Accept new file extensions (.pdf, .docx, .html, .htm) in validation and type mapping. Raise upload size limit to 100 MB.
- `ingestion-pipeline`: No new worker logic. The existing worker already catches parser exceptions and marks the task as FAILED; this story adds parser coverage and worker contract tests for the new formats.

## Impact

- **Code**: `services/storage.py` (extension mapping), `services/docling_parser.py` (multi-format converter), `core/config.py` (size limit)
- **Dependencies**: No dependency change is required in the current locked environment; apply-time verification MUST confirm that the installed Docling build already supports PDF/DOCX/HTML parsing before adding extras.
- **Tests**: New unit tests for each format, updated integration tests, HTML worker smoke success coverage, and corrupt PDF worker failure-contract coverage
- **API**: No API contract changes — existing `POST /api/admin/sources` accepts new extensions transparently
- **Data model**: No schema changes — `SourceType` enum already includes PDF, DOCX, HTML

> **Security note:** S3-01 adds ingestion support for HTML/PDF/DOCX only. It does **not** introduce public serving of raw uploaded files. Any future endpoint that serves uploaded HTML back to browsers MUST use a safe delivery strategy such as `Content-Disposition: attachment` or a segregated domain with restrictive headers.
