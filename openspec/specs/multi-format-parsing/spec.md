## ADDED Requirements

### Requirement: Multi-format DocumentConverter configuration

The `DoclingParser` SHALL configure `DocumentConverter` with `allowed_formats` including `InputFormat.MD`, `InputFormat.PDF`, `InputFormat.DOCX`, and `InputFormat.HTML`. Docling SHALL auto-detect the document format from the allowed list and apply the correct parser. A single `DocumentConverter` instance SHALL be used for all formats — no per-format converter factory.

#### Scenario: DocumentConverter accepts all supported formats

- **WHEN** `DoclingParser` is instantiated
- **THEN** the underlying `DocumentConverter` SHALL be configured with `InputFormat.MD`, `InputFormat.PDF`, `InputFormat.DOCX`, and `InputFormat.HTML` in `allowed_formats`

#### Scenario: Format auto-detection by Docling

- **WHEN** a PDF file is passed to the converter configured with all four formats
- **THEN** Docling SHALL auto-detect the format and parse it as PDF without explicit format selection by the caller

---

### Requirement: PDF parsing with page numbers

The `DoclingParser` SHALL parse PDF files via `DocumentConverter` using `DocumentStream` with the source bytes. The parser SHALL extract `anchor_page` from Docling provenance metadata for each chunk. The parser SHALL extract `anchor_chapter` and `anchor_section` from heading hierarchy when present in the PDF structure.

#### Scenario: PDF file produces chunks with page numbers

- **WHEN** `parse_and_chunk()` is called with bytes of a multi-page PDF containing headings and paragraphs
- **THEN** the result SHALL be a non-empty list of `ChunkData` instances
- **AND** chunks originating from pages with provenance data SHALL have `anchor_page` set to the first provenance page number associated with that chunk (1-based integer)

#### Scenario: PDF with headings extracts chapter and section anchors

- **WHEN** `parse_and_chunk()` is called with a PDF containing H1 and H2 headings
- **THEN** chunks under those headings SHALL have `anchor_chapter` populated from the top-level heading
- **AND** chunks under sub-headings SHALL have `anchor_section` populated

#### Scenario: PDF source type mapping

- **WHEN** `parse_and_chunk()` is called with `source_type=SourceType.PDF`
- **THEN** the parser SHALL process the file as a PDF document via `DocumentStream`

---

### Requirement: PDF table extraction

The `DoclingParser` SHALL use Docling's default table extraction for PDF documents. Tables SHALL be extracted as Markdown-formatted text within the chunk body. `TableFormerMode.ACCURATE` SHALL NOT be enabled — the default table parser is sufficient.

#### Scenario: PDF with table includes table content in chunk text

- **WHEN** `parse_and_chunk()` is called with a PDF containing a data table
- **THEN** at least one `ChunkData` in the result SHALL contain the table content rendered as Markdown table syntax (pipe-delimited rows)

#### Scenario: Table is not split across chunks

- **WHEN** a table fits within the `chunk_max_tokens` limit
- **THEN** the table content SHALL appear in a single `ChunkData` instance, not split across multiple chunks

#### Scenario: Oversized table follows HybridChunker output

- **WHEN** extracted table content exceeds the `chunk_max_tokens` limit
- **THEN** the parser SHALL preserve Docling `HybridChunker` output without table-specific post-processing
- **AND** the result MAY contain multiple `ChunkData` instances for the same table
- **AND** the parser SHALL NOT raise solely because a table exceeds `chunk_max_tokens`

---

### Requirement: DOCX parsing with headings

The `DoclingParser` SHALL parse DOCX files via `DocumentConverter` using `DocumentStream` with the source bytes. The parser SHALL extract `anchor_chapter` from Heading 1 styles and `anchor_section` from Heading 2+ styles in the DOCX structure. DOCX files SHALL NOT produce `anchor_page` values (set to None).

#### Scenario: DOCX file produces chunks with heading anchors

- **WHEN** `parse_and_chunk()` is called with bytes of a DOCX file containing H1 and H2 heading styles
- **THEN** the result SHALL be a non-empty list of `ChunkData` instances
- **AND** chunks under H1 headings SHALL have `anchor_chapter` set to the heading text
- **AND** chunks under H2 headings SHALL have `anchor_section` set to the sub-heading text

#### Scenario: DOCX chunks have no page anchors

- **WHEN** `parse_and_chunk()` is called with a DOCX file
- **THEN** all `ChunkData` instances SHALL have `anchor_page` set to None

#### Scenario: DOCX source type mapping

- **WHEN** `parse_and_chunk()` is called with `source_type=SourceType.DOCX`
- **THEN** the parser SHALL process the file as a DOCX document via `DocumentStream`

---

### Requirement: HTML parsing with headings

The `DoclingParser` SHALL parse HTML files via `DocumentConverter` using `DocumentStream` with the source bytes. The parser SHALL extract `anchor_chapter` from `<h1>` elements and `anchor_section` from `<h2>`-`<h6>` elements. HTML files SHALL NOT produce `anchor_page` values (set to None).

#### Scenario: HTML file produces chunks with heading anchors

- **WHEN** `parse_and_chunk()` is called with bytes of an HTML file containing `<h1>`, `<h2>`, and `<p>` elements
- **THEN** the result SHALL be a non-empty list of `ChunkData` instances
- **AND** chunks under `<h1>` elements SHALL have `anchor_chapter` set to the heading text
- **AND** chunks under `<h2>` elements SHALL have `anchor_section` set to the sub-heading text

#### Scenario: HTML chunks have no page anchors

- **WHEN** `parse_and_chunk()` is called with an HTML file
- **THEN** all `ChunkData` instances SHALL have `anchor_page` set to None

#### Scenario: HTML source type mapping

- **WHEN** `parse_and_chunk()` is called with `source_type=SourceType.HTML`
- **THEN** the parser SHALL process the file as an HTML document via `DocumentStream`

#### Scenario: HTML with structural elements parses correctly

- **WHEN** `parse_and_chunk()` is called with HTML containing `<table>`, `<ul>`, and `<p>` elements
- **THEN** the result SHALL contain `ChunkData` instances with the structural content preserved in `text_content`

---

### Requirement: Corrupt and malformed file handling

The `DoclingParser` SHALL raise an exception when Docling fails to parse a corrupt or malformed file. The exception SHALL propagate to the caller without retry (parsing failures are deterministic). The parser SHALL NOT silently return an empty list for corrupt files — an exception is required to distinguish corrupt input from legitimately empty documents.

#### Scenario: Corrupt PDF raises exception

- **WHEN** `parse_and_chunk()` is called with bytes that are not a valid PDF (e.g., truncated or random bytes with `.pdf` extension)
- **THEN** the parser SHALL raise an exception

#### Scenario: Malformed DOCX raises exception

- **WHEN** `parse_and_chunk()` is called with bytes that are not a valid DOCX archive
- **THEN** the parser SHALL raise an exception

#### Scenario: Broken HTML follows tolerant parser behavior

- **WHEN** `parse_and_chunk()` is called with severely malformed HTML (e.g., unclosed tags, invalid encoding)
- **THEN** the parser SHALL return a non-empty list if Docling extracts at least one non-whitespace chunk from the document
- **AND** the parser MAY raise an exception or return an empty list if Docling cannot extract any non-whitespace content
- **AND** callers that require successful ingestion SHALL treat an empty result as a parsing failure

#### Scenario: Exception is not retried

- **WHEN** `DoclingParser` raises an exception due to corrupt input
- **THEN** the calling code SHALL NOT retry the parse operation (deterministic failure)

---

### Requirement: Per-format input handling in parse_and_chunk

The `_convert_document` method SHALL handle PDF, DOCX, and HTML source types in addition to existing MD and TXT types. PDF, DOCX, and HTML SHALL use `DocumentStream` with `BytesIO` wrapping the raw content bytes. The method SHALL raise `ValueError` for any unsupported `SourceType`.

#### Scenario: Unsupported source type raises ValueError

- **WHEN** `parse_and_chunk()` is called with a `SourceType` not in (MARKDOWN, TXT, PDF, DOCX, HTML)
- **THEN** the parser SHALL raise a `ValueError` with a descriptive message

#### Scenario: All new formats use DocumentStream

- **WHEN** `parse_and_chunk()` is called with `source_type` of PDF, DOCX, or HTML
- **THEN** the parser SHALL construct a `DocumentStream` from the raw bytes and pass it to `DocumentConverter.convert()`
