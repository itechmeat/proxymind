# multi-format-parsing (delta)

**Story:** S4-06 — Lightweight Knowledge Processing Migration
**Status:** MODIFIED capability (includes MODIFIED, ADDED, and REMOVED requirements)
**Test coverage requirement:** All stable behavior introduced or modified by this change MUST be covered by CI tests before archive.

---

## MODIFIED Requirements

### Requirement: Multi-format DocumentConverter configuration

**[Modified by S4-06]** The `LightweightParser` (renamed from `DoclingParser`) SHALL support `SourceType.MD`, `SourceType.TXT`, `SourceType.PDF`, `SourceType.DOCX`, and `SourceType.HTML` formats. The parser SHALL route to the correct internal parsing method based on `source_type`. A single `LightweightParser` instance SHALL be used for all formats. The existing lightweight parsing implementations (pypdf for PDF, xml.etree/zipfile for DOCX, html.parser for HTML, plain text for MD/TXT) are unchanged — only the class name and module path change.

**[Modified by S4-06]** All references to `DoclingParser` class name SHALL be renamed to `LightweightParser`. The file SHALL be renamed from `docling_parser.py` to `lightweight_parser.py`. All import paths and test files SHALL be updated accordingly.

> **Previous state:** The class was named `DoclingParser` at `app/services/docling_parser.py`. Despite the name, the implementation was already a lightweight parser that did NOT import or use Docling. S4-06 aligns the naming with the actual implementation.

#### Scenario: LightweightParser accepts all supported formats

- **WHEN** `LightweightParser` is instantiated
- **THEN** it SHALL support `SourceType.MD`, `SourceType.TXT`, `SourceType.PDF`, `SourceType.DOCX`, and `SourceType.HTML`

#### Scenario: Format routing by source_type

- **WHEN** a PDF file is passed to `parse_and_chunk()` with `source_type=SourceType.PDF`
- **THEN** the parser SHALL route to the PDF parsing method (pypdf) based on the `source_type` parameter

#### Scenario: All existing tests pass after rename

- **WHEN** the rename from `DoclingParser` to `LightweightParser` is complete
- **THEN** all existing parsing tests SHALL pass without logic changes
- **AND** only import paths and class names SHALL differ

---

### Requirement: PDF parsing with page numbers

**[Modified by S4-06]** The `LightweightParser` (renamed from `DoclingParser`) SHALL parse PDF files via pypdf. The parser SHALL extract `anchor_page` from pypdf page indices for each chunk (1-based integer). The parser SHALL extract `anchor_chapter` and `anchor_section` from heading hierarchy when detected in the PDF text structure.

> **Previous state:** Referenced Docling `DocumentStream` and provenance metadata. The actual implementation already used pypdf. S4-06 aligns the spec with reality.

#### Scenario: PDF file produces chunks with page numbers

- **WHEN** `parse_and_chunk()` is called with bytes of a multi-page PDF containing headings and paragraphs
- **THEN** the result SHALL be a non-empty list of `ChunkData` instances
- **AND** chunks SHALL have `anchor_page` set to the page number (1-based integer) from which the text originates

#### Scenario: PDF with headings extracts chapter and section anchors

- **WHEN** `parse_and_chunk()` is called with a PDF containing headings
- **THEN** chunks under top-level headings SHALL have `anchor_chapter` populated
- **AND** chunks under sub-headings SHALL have `anchor_section` populated

#### Scenario: PDF source type mapping

- **WHEN** `parse_and_chunk()` is called with `source_type=SourceType.PDF`
- **THEN** the parser SHALL process the file as a PDF document

---

### Requirement: DOCX parsing with headings

**[Modified by S4-06]** The `LightweightParser` (renamed from `DoclingParser`) SHALL parse DOCX files. The parser SHALL extract `anchor_chapter` from Heading 1 styles and `anchor_section` from Heading 2+ styles in the DOCX structure. DOCX files SHALL NOT produce `anchor_page` values (set to None).

> **Previous state:** Referenced Docling `DocumentStream`. S4-06 aligns naming.

#### Scenario: DOCX file produces chunks with heading anchors

- **WHEN** `parse_and_chunk()` is called with bytes of a DOCX file containing H1 and H2 heading styles
- **THEN** the result SHALL be a non-empty list of `ChunkData` instances
- **AND** chunks under H1 headings SHALL have `anchor_chapter` set to the heading text
- **AND** chunks under H2 headings SHALL have `anchor_section` set to the sub-heading text

#### Scenario: DOCX chunks have no page anchors

- **WHEN** `parse_and_chunk()` is called with a DOCX file
- **THEN** all `ChunkData` instances SHALL have `anchor_page` set to None

---

### Requirement: HTML parsing with headings

**[Modified by S4-06]** The `LightweightParser` (renamed from `DoclingParser`) SHALL parse HTML files. The parser SHALL extract `anchor_chapter` from `<h1>` elements and `anchor_section` from `<h2>`-`<h6>` elements. HTML files SHALL NOT produce `anchor_page` values (set to None).

> **Previous state:** Referenced Docling `DocumentStream`. S4-06 aligns naming.

#### Scenario: HTML file produces chunks with heading anchors

- **WHEN** `parse_and_chunk()` is called with bytes of an HTML file containing `<h1>`, `<h2>`, and `<p>` elements
- **THEN** the result SHALL be a non-empty list of `ChunkData` instances
- **AND** chunks under `<h1>` elements SHALL have `anchor_chapter` set to the heading text
- **AND** chunks under `<h2>` elements SHALL have `anchor_section` set to the sub-heading text

#### Scenario: HTML chunks have no page anchors

- **WHEN** `parse_and_chunk()` is called with an HTML file
- **THEN** all `ChunkData` instances SHALL have `anchor_page` set to None

#### Scenario: HTML with structural elements parses correctly

- **WHEN** `parse_and_chunk()` is called with HTML containing `<table>`, `<ul>`, and `<p>` elements
- **THEN** the result SHALL contain `ChunkData` instances with the structural content preserved in `text_content`

---

### Requirement: Corrupt and malformed file handling

**[Modified by S4-06]** The `LightweightParser` (renamed from `DoclingParser`) SHALL raise an exception when parsing a corrupt or malformed file fails. The exception SHALL propagate to the caller without retry (parsing failures are deterministic). The parser SHALL NOT silently return an empty list for corrupt files -- an exception is required to distinguish corrupt input from legitimately empty documents.

> **Previous state:** Referenced Docling `DocumentConverter`. S4-06 aligns naming with actual lightweight parsing implementation.

#### Scenario: Corrupt PDF raises exception

- **WHEN** `parse_and_chunk()` is called with bytes that are not a valid PDF (e.g., truncated or random bytes with `.pdf` extension)
- **THEN** the parser SHALL raise an exception

#### Scenario: Malformed DOCX raises exception

- **WHEN** `parse_and_chunk()` is called with bytes that are not a valid DOCX archive
- **THEN** the parser SHALL raise an exception

#### Scenario: Broken HTML follows tolerant parser behavior

- **WHEN** `parse_and_chunk()` is called with severely malformed HTML (e.g., unclosed tags, invalid encoding)
- **THEN** the parser SHALL return a non-empty list if at least one non-whitespace chunk can be extracted
- **AND** callers that require successful ingestion SHALL treat an empty result as a parsing failure

#### Scenario: Exception is not retried

- **WHEN** `LightweightParser` raises an exception due to corrupt input
- **THEN** the calling code SHALL NOT retry the parse operation (deterministic failure)

---

### Requirement: Per-format input handling in parse_and_chunk

**[Modified by S4-06]** The `LightweightParser` (renamed from `DoclingParser`) SHALL handle PDF, DOCX, HTML, MD, and TXT source types. The method SHALL raise `ValueError` for any unsupported `SourceType`.

> **Previous state:** Referenced Docling `DocumentStream` with `BytesIO`. S4-06 aligns naming.

#### Scenario: Unsupported source type raises ValueError

- **WHEN** `parse_and_chunk()` is called with a `SourceType` not in (MARKDOWN, TXT, PDF, DOCX, HTML)
- **THEN** the parser SHALL raise a `ValueError` with a descriptive message

#### Scenario: All supported formats are handled

- **WHEN** `parse_and_chunk()` is called with `source_type` of PDF, DOCX, HTML, MARKDOWN, or TXT
- **THEN** the parser SHALL invoke the appropriate format-specific parsing logic

---

### Requirement: HybridChunker configuration

**[Modified by S4-06]** Chunking SHALL be configured with `max_tokens` sourced from the `chunk_max_tokens` setting (default 1024). Chunks SHALL NOT exceed the configured `max_tokens` limit. Consecutive small sections under the same heading SHALL be merged into a single chunk when they fit within the token limit. Chunking logic SHALL be provided by the shared `TextChunker` class (extracted from the former `DoclingParser._chunk_blocks`), which both `LightweightParser` and `DocumentAIParser` use.

> **Previous state:** Referenced Docling `HybridChunker`. The actual implementation already used a custom `_chunk_blocks` method, not Docling's chunker. S4-06 extracts it as a standalone `TextChunker`.

#### Scenario: No chunk exceeds the configured max_tokens

- **WHEN** a document is chunked with `chunk_max_tokens` set to 1024
- **THEN** every `ChunkData` in the result SHALL have `token_count` less than or equal to 1024

#### Scenario: Chunk max_tokens is configurable

- **WHEN** `chunk_max_tokens` is changed from 1024 to 512 in Settings
- **THEN** chunking SHALL use 512 as the maximum token limit

---

## ADDED Requirements

### Requirement: DocumentProcessor Protocol

**[Added by S4-06]** The system SHALL define a `DocumentProcessor` Protocol at `app/services/document_processing.py` with a single method:

```
async def parse_and_chunk(
    self, content: bytes, filename: str, source_type: SourceType
) -> list[ChunkData]
```

Both `LightweightParser` and `DocumentAIParser` SHALL implement this Protocol via structural subtyping (no explicit inheritance required). The Protocol provides the provider-agnostic contract for document parsing and chunking. The router selects the processor; handlers use the interface.

#### Scenario: LightweightParser satisfies DocumentProcessor Protocol

- **WHEN** `LightweightParser` is instantiated
- **THEN** it SHALL be assignable to a variable typed as `DocumentProcessor`

#### Scenario: DocumentAIParser satisfies DocumentProcessor Protocol

- **WHEN** `DocumentAIParser` is instantiated with valid configuration
- **THEN** it SHALL be assignable to a variable typed as `DocumentProcessor`

#### Scenario: Both implementations return identical ChunkData contract

- **WHEN** `LightweightParser` and `DocumentAIParser` each process a document
- **THEN** both SHALL return `list[ChunkData]` with identical field structure

---

### Requirement: TextChunker as shared component

**[Added by S4-06]** The system SHALL provide a `TextChunker` class at `app/services/document_processing.py` (extracted from the former `DoclingParser._chunk_blocks` private method). The `TextChunker` SHALL accept a list of `ParsedBlock` instances and return a list of `ChunkData` instances. Both `LightweightParser` and `DocumentAIParser` SHALL use `TextChunker` for chunking, ensuring consistent chunking behavior across all processing paths.

The `TextChunker` SHALL:
- Split oversized blocks that exceed `chunk_max_tokens`
- Merge consecutive small blocks under the same heading when they fit within the token limit
- Assign sequential zero-based `chunk_index` values
- Preserve anchor metadata (`anchor_page`, headings) from the first block in a merged chunk
- Skip blocks with whitespace-only text
- Return an empty list for empty input

#### Scenario: Single block within token budget

- **WHEN** `TextChunker` receives one block within the token limit
- **THEN** it SHALL return one `ChunkData` with the block's text, anchors, and `chunk_index=0`

#### Scenario: Oversized block is split

- **WHEN** `TextChunker` receives a block exceeding `chunk_max_tokens`
- **THEN** it SHALL return multiple `ChunkData` instances, each within the token limit
- **AND** all chunks SHALL preserve the block's anchor metadata

#### Scenario: Small blocks are merged

- **WHEN** `TextChunker` receives multiple small blocks under the same heading
- **AND** their combined token count is within the limit
- **THEN** they SHALL be merged into a single `ChunkData`

#### Scenario: Whitespace-only blocks are skipped

- **WHEN** `TextChunker` receives a block with only whitespace
- **THEN** that block SHALL be excluded from the result

#### Scenario: Empty input returns empty output

- **WHEN** `TextChunker` receives an empty list
- **THEN** it SHALL return an empty list

---

## REMOVED Requirements

### REMOVED: DoclingParser service for document parsing and chunking

**Reason:** The class `DoclingParser` is renamed to `LightweightParser` as part of S4-06. The class never actually used Docling -- the name was a historical artifact. All behavior is preserved under the new name.

**Migration:** All references to `DoclingParser` SHALL be replaced with `LightweightParser`. All references to `docling_parser.py` SHALL be replaced with `lightweight_parser.py`. No behavior change -- only naming alignment.

---

### REMOVED: _chunk_external_document dead code

**Reason:** The `_chunk_external_document()` method was never called. No external chunker was ever passed to the parser. This was a dead extension point that added confusion.

**Migration:** Remove the method. No callers exist. No behavior change.

---

### REMOVED: chunker parameter from parser __init__

**Reason:** The `chunker` parameter in the parser's `__init__()` was never used by any caller. It was a dead extension point.

**Migration:** Remove the parameter. No callers pass it. No behavior change.

---

### REMOVED: _extract_anchor_page dead code

**Reason:** The `_extract_anchor_page()` method was dead code -- no longer called after the lightweight parsing migration.

**Migration:** Remove the method. No callers exist. No behavior change.

---

### REMOVED: All Docling-specific naming

**Reason:** The codebase has no Docling dependency (`pyproject.toml` does not include Docling). All class names, file names, and references that still use "Docling" are misleading historical artifacts.

**Migration:** Rename all Docling references to their lightweight equivalents:

| Before | After |
|--------|-------|
| `DoclingParser` class | `LightweightParser` class |
| `docling_parser.py` file | `lightweight_parser.py` file |
| `test_docling_parser.py` | `test_lightweight_parser.py` |
| `PipelineServices.docling_parser` field | `PipelineServices.document_processor` field |
| `ctx["docling_parser"]` worker context key | `ctx["document_processor"]` worker context key |
