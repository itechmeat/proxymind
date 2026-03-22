# S3-01: More Formats (PDF, DOCX, HTML) — Design Spec

## Story

> Extend Docling parsing: PDF with tables and structure, DOCX, HTML. Anchor metadata for each format (page, chapter, section).

**Outcome:** PDF/DOCX/HTML can be uploaded and parsed correctly.
**Verification:** upload PDF → chunks with page numbers; upload DOCX → chunks with headings; upload HTML → chunks with heading anchors.

## Design Decisions

### D1: Single DocumentConverter with multiple formats

**Decision:** Use one `DocumentConverter` instance configured with all supported formats: `[InputFormat.MD, InputFormat.PDF, InputFormat.DOCX, InputFormat.HTML]`. Docling auto-detects the format by content and applies the correct parser.

**Why:** Docling v2.80+ handles format routing internally. Format-specific options (e.g., OCR for scanned PDFs, `TableFormerMode.ACCURATE`) are YAGNI for this story — S3-01 targets structured digital documents, not scanned images. A single converter follows KISS and avoids a factory/mapping layer. If format-specific configuration is needed later (driven by evals), it can be added without changing the public interface.

**Rejected:** Per-format converter factory — adds complexity with no current benefit.

### D2: Current anchor fields are sufficient

**Decision:** Keep the existing four anchor fields: `anchor_page`, `anchor_chapter`, `anchor_section`, `anchor_timecode`. No new fields.

| Format | `anchor_page` | `anchor_chapter` | `anchor_section` | `anchor_timecode` |
|--------|:---:|:---:|:---:|:---:|
| PDF | Yes (provenance) | Yes (headings) | Yes (sub-headings) | No |
| DOCX | No | Yes (heading styles) | Yes (sub-headings) | No |
| HTML | No | Yes (`<h1>`–`<h6>`) | Yes | No |
| MD | No | Yes (`#`–`######`) | Yes | No |
| TXT | No | No | No | No |

**Why:** Tables in PDF are extracted by Docling as Markdown text within the chunk body — no separate `anchor_table_index` needed. The citation builder uses page + chapter/section to form references, which is sufficient for all three new formats. Adding fields for niche metadata is YAGNI; evals (S8-02) will reveal if more granularity is needed.

**Rejected:** New anchor fields (table index, paragraph number) — premature without eval data.

### D3: Raise upload size limit to 100 MB

**Decision:** Change `upload_max_file_size_mb` default from 50 to 100 MB. Single limit for all formats.

**Why:** Typical digital twin sources (books, articles, reports) in PDF can reach 50–100 MB with embedded images. A 50 MB limit would block legitimate use cases. Per-format limits add configuration complexity with no clear benefit — the user can always override via `.env`. 100 MB covers 95%+ of realistic content while remaining safe for worker processing.

**Rejected:** Per-format limits — unnecessary complexity. Keeping 50 MB — too restrictive for PDF books.

### D4: Docling default table handling

**Decision:** Use Docling's default table extraction. Do not enable `TableFormerMode.ACCURATE`.

**Why:** Docling's default table parser already achieves 97.9% accuracy on benchmarks. `ACCURATE` mode is ~2x slower and requires additional model dependencies. HybridChunker respects document structure and avoids splitting tables mid-row. Optimization by eval results (S8-02) if table extraction quality proves insufficient.

**Rejected:** `TableFormerMode.ACCURATE` — performance cost without proven need.

### D5: Static test fixtures committed to repository

**Decision:** Create minimal static sample files for each format, commit to `tests/fixtures/`.

**Why:** Static fixtures are deterministic, fast, and do not require dev-only dependencies (reportlab, python-docx). They test parsing of real files, closer to production. Fixtures are created once (programmatically or by hand) and committed. CI tests need stability over flexibility.

**Rejected:** Programmatic generation in conftest — adds dev dependencies, slower test startup, harder to inspect visually.

### D6: Extension-only validation

**Decision:** Validate uploaded files by extension only (as currently implemented). No magic bytes / MIME-type content inspection.

**Why:** Admin API will be protected by API key (S7-01) — this is not a public upload surface. If a file is misnamed, Docling will fail during parsing and the worker will mark the task as `failed` with a descriptive error. Magic bytes validation is a nice-to-have optimization (faster error feedback) but not critical for v1. Security is ensured by auth + rate limiting, not format sniffing.

**Rejected:** Magic bytes validation — marginal benefit for authenticated-only endpoint.

### D7: Accept both `.html` and `.htm` extensions

**Decision:** Both `.html` and `.htm` map to `SourceType.HTML`.

**Why:** Both extensions are common in the wild. Cost of support is one line in the extension mapping. No reason to reject `.htm` files.

## Architecture

### Data Flow: File Upload (extended)

```
Owner → POST /api/admin/sources (file: .pdf/.docx/.html/.htm)
  → validate extension
  → save file to SeaweedFS
  → create source record in PG (status: pending)
  → enqueue ingestion task in Redis
  → 202 Accepted

Worker picks up task:
  → download file from SeaweedFS
  → DoclingParser.parse(content, source_type)
    → DocumentConverter (auto-detects format from allowed list)
    → HybridChunker → chunks with anchor metadata
  → create Document + DocumentVersion records in PG
  → create Chunk records in PG
  → Gemini Embedding 2 → vectors
  → upsert to Qdrant with snapshot_id
  → update source status, mark task complete
```

**Note:** Document and DocumentVersion records are created by the ingestion worker after successful parsing — not by the upload endpoint. This matches the existing lifecycle: the upload endpoint creates only the source record and enqueues the task. If parsing fails, no orphaned document records are left in the database.

### Components Modified

| Component | File | Change |
|-----------|------|--------|
| Extension mapping | `services/storage.py` | Add `.pdf`, `.docx`, `.html`, `.htm` to `ALLOWED_SOURCE_EXTENSIONS` and `determine_source_type()` |
| DoclingParser | `services/docling_parser.py` | Multi-format `DocumentConverter`, per-format input handling in `parse_and_chunk()` |
| Upload endpoint | `api/admin.py` | No logic change — accepts new extensions automatically via storage validation |
| Config | `core/config.py` | `upload_max_file_size_mb` default 50 → 100 |
| Dependencies | `pyproject.toml` | No change in the current locked environment; apply-time verification confirms whether Docling PDF extras are already satisfied before adding anything |

### Components NOT Modified

- **Ingestion worker** (`workers/tasks/ingestion.py`) — already format-agnostic, calls `parser.parse_and_chunk(content, filename, source_type)` and processes returned chunks uniformly.
- **Embedding service** — receives chunk text, format-independent.
- **Qdrant indexing** — receives vectors + payload, format-independent.
- **Snapshot manager** — format-independent.
- **Chat/retrieval** — format-independent.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `upload_max_file_size_mb` | 100 (was 50) | Max file size for all uploads |

No new configuration settings. Existing settings are sufficient.

## Test Plan

### Unit Tests

- **DoclingParser** (`tests/unit/services/test_docling_parser.py`):
  - PDF → chunks with `anchor_page` populated
  - PDF with table → table content present in chunk text as Markdown table
  - DOCX → chunks with `anchor_chapter` extracted from heading styles
  - HTML → chunks with `anchor_chapter` extracted from `<h1>`–`<h6>`
  - Corrupt PDF / malformed DOCX / broken HTML → parser raises exception (worker marks task as FAILED)

- **Source validation** (`tests/unit/test_source_validation.py`):
  - `.pdf`, `.docx`, `.html`, `.htm` → accepted, correct SourceType
  - `.PDF`, `.Docx` → case-insensitive acceptance
  - `.xlsx`, `.pptx`, `.xml` → rejected

### Integration Tests

- **File upload** (`tests/integration/test_source_upload.py`):
  - Upload PDF → 202, source created, task enqueued
  - Upload DOCX → 202, source created, task enqueued
  - Upload HTML → 202, source created, task enqueued
  - Upload .htm → 202, SourceType.HTML

### Test Fixtures

| File | Content | Purpose |
|------|---------|---------|
| `sample.pdf` | 2 pages, headings, table, paragraphs | Verify page numbers, table extraction, heading anchors |
| `sample.docx` | H1/H2 headings, paragraphs, bulleted list | Verify heading-based anchors |
| `sample.html` | `<h1>`–`<h3>`, `<p>`, `<table>`, `<ul>` | Verify HTML structure parsing |

## Out of Scope

- **URL fetch / `from-url` endpoint** — deferred to a separate story after S7-01 (admin auth). Reason: fetching arbitrary URLs without authentication creates an SSRF attack surface. Must be implemented with private/loopback address blocking, redirect restrictions, and scheme validation — after admin API is properly secured.
- OCR for scanned PDFs (future: format-specific Docling options)
- JavaScript rendering for HTML pages
- Recursive web crawling / sitemaps
- MHTML / web archive support
- Path A: Gemini native parsing (S3-04)
- New anchor metadata fields
- Per-format file size limits
- Magic bytes / MIME content validation
- TableFormerMode.ACCURATE

## Dependencies

- Docling 2.80+ with working PDF/DOCX/HTML parser support in the locked environment; no dependency change was required for the current implementation

> **Security note:** this story adds ingestion support for HTML/PDF/DOCX, not browser-facing raw file serving. Any future endpoint that serves uploaded HTML back to browsers MUST use a safe delivery strategy such as `Content-Disposition: attachment` or a segregated domain with restrictive headers.

## Review History

- **v1** (2026-03-22): Initial design included URL fetch endpoint (`POST /api/admin/sources/from-url`).
- **v2** (2026-03-22): URL fetch removed after review. Key findings: SSRF risk on unauthenticated admin API, scope creep beyond S3-01 story definition, data flow inconsistencies. URL fetch deferred to separate story post-S7-01. Data flow corrected to reflect that Document/DocumentVersion are created by worker, not upload endpoint. Duplicate size limit settings consolidated to single `upload_max_file_size_mb`.
