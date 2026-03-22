# S3-01: More Formats (PDF, DOCX, HTML) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the ingestion pipeline to accept PDF, DOCX, and HTML files in addition to the existing Markdown and TXT support.

**Architecture:** The existing pipeline is format-agnostic by design. Changes are confined to two layers: (1) storage validation — allow new extensions, (2) DoclingParser — configure the `DocumentConverter` for multiple formats and handle per-format input streams. The ingestion worker, embedding service, Qdrant indexing, and all downstream components remain untouched.

**Tech Stack:** Docling 2.80+ (PDF/DOCX/HTML parsing), HybridChunker (structure-aware chunking), pytest (testing), uv (package management)

**Spec:** `docs/superpowers/specs/2026-03-22-s3-01-more-formats-design.md`

**Important:** All commands use `uv run` for reproducible environments. Dependencies are managed via `uv add` / `uv lock`. Do NOT use bare `pip install`. Commits are proposed — do NOT execute `git commit` without explicit user permission.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/app/services/storage.py` | Modify (lines 11-15) | Add new extensions and type mappings |
| `backend/app/services/docling_parser.py` | Modify (lines 37, 60-84) | Multi-format converter, per-format `_convert_document` |
| `backend/app/core/config.py` | Modify (line 46) | Raise `upload_max_file_size_mb` default to 100 |
| `backend/tests/fixtures/sample.pdf` | Create | 2-page PDF with headings, table, paragraphs |
| `backend/tests/fixtures/sample.docx` | Create | DOCX with H1/H2 headings, paragraphs, list |
| `backend/tests/fixtures/sample.html` | Create | HTML with `<h1>`–`<h3>`, `<p>`, `<table>`, `<ul>` |
| `backend/tests/unit/services/test_docling_parser.py` | Modify | Add PDF/DOCX/HTML parsing tests |
| `backend/tests/unit/test_source_validation.py` | Modify | Update extension/type validation tests |
| `backend/tests/integration/test_source_upload.py` | Modify | Add PDF/DOCX/HTML upload tests, worker smoke test |
| `backend/tests/conftest.py` | Modify (line 198) | Update `upload_max_file_size_mb` fixture default to 100 |
| `backend/pyproject.toml` | Modify (if needed) | Docling PDF extras |

---

### Task 0: Preflight

Before writing any code, the implementer MUST complete these steps. They are required by the repository workflow (`CLAUDE.md`, `AGENTS.md`).

- [ ] **Step 1: Read development standards**

Read `docs/development.md` in full. This is the binding implementation standard. All code produced in this plan must conform to it.

- [ ] **Step 2: Read the spec**

Read `docs/superpowers/specs/2026-03-22-s3-01-more-formats-design.md` in full to understand all design decisions and their rationale.

- [ ] **Step 3: Run find-skills discovery**

Use the `find-skills` skill to search for relevant skills matching the technologies in this task. Search queries: "Docling", "FastAPI", "pytest", "PDF parsing", "SQLAlchemy". Search priority sources listed in `CLAUDE.md`. Install any found skills into the project (not globally):

```bash
npx skills add <owner/repo@skill> -y
```

- [ ] **Step 4: Verify current dependency versions**

Check that installed versions of key dependencies meet or exceed minimums in `docs/spec.md`:

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run python -c "
import docling; print(f'docling: {docling.__version__}')
import fastapi; print(f'fastapi: {fastapi.__version__}')
import sqlalchemy; print(f'sqlalchemy: {sqlalchemy.__version__}')
import pydantic; print(f'pydantic: {pydantic.__version__}')
"
```

Cross-reference output against `docs/spec.md` tables. If any version is below the minimum, update before proceeding.

---

### Task 1: Add new extensions to storage validation

**Files:**
- Modify: `backend/app/services/storage.py:11-15`
- Test: `backend/tests/unit/test_source_validation.py`

- [ ] **Step 1: Update existing test to expect PDF accepted (red)**

In `backend/tests/unit/test_source_validation.py`, the test on line 42 currently asserts PDF is rejected. Change it and add new parametrized cases:

```python
@pytest.mark.parametrize(
    "filename",
    ["notes.md", "DOCUMENT.MD", "note.Txt", "report.pdf", "report.PDF", "doc.docx", "doc.DOCX", "page.html", "page.htm", "page.HTML"],
)
def test_validate_file_extension_accepts_supported_types_case_insensitively(
    filename: str,
) -> None:
    ext = validate_file_extension(filename)
    assert ext in {".md", ".txt", ".pdf", ".docx", ".html", ".htm"}
```

Replace the existing rejection test:

```python
@pytest.mark.parametrize("filename", ["notes.xlsx", "photo.png", "data.csv", "archive.zip"])
def test_validate_file_extension_rejects_unsupported_types(filename: str) -> None:
    with pytest.raises(ValueError, match="Unsupported file format"):
        validate_file_extension(filename)
```

Add type mapping tests:

```python
@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("notes.md", SourceType.MARKDOWN),
        ("notes.TXT", SourceType.TXT),
        ("report.pdf", SourceType.PDF),
        ("report.PDF", SourceType.PDF),
        ("doc.docx", SourceType.DOCX),
        ("page.html", SourceType.HTML),
        ("page.htm", SourceType.HTML),
        ("page.HTML", SourceType.HTML),
    ],
)
def test_determine_source_type_maps_extension(filename: str, expected: SourceType) -> None:
    assert determine_source_type(filename) is expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run python -m pytest tests/unit/test_source_validation.py -v`

Expected: FAIL — PDF/DOCX/HTML extensions rejected by current validation.

- [ ] **Step 3: Update storage.py to accept new extensions**

In `backend/app/services/storage.py`, replace lines 11-15:

```python
ALLOWED_SOURCE_EXTENSIONS = (".md", ".txt", ".pdf", ".docx", ".html", ".htm")
SOURCE_TYPE_BY_EXTENSION = {
    ".md": SourceType.MARKDOWN,
    ".txt": SourceType.TXT,
    ".pdf": SourceType.PDF,
    ".docx": SourceType.DOCX,
    ".html": SourceType.HTML,
    ".htm": SourceType.HTML,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run python -m pytest tests/unit/test_source_validation.py -v`

Expected: ALL PASS.

- [ ] **Step 5: Propose commit**

Proposed message:
```
feat(storage): accept PDF, DOCX, HTML, HTM file extensions (S3-01)
```

Files to stage: `backend/app/services/storage.py`, `backend/tests/unit/test_source_validation.py`

---

### Task 2: Create test fixtures for new formats

**Files:**
- Create: `backend/tests/fixtures/sample.pdf`
- Create: `backend/tests/fixtures/sample.docx`
- Create: `backend/tests/fixtures/sample.html`

These fixtures are small, deterministic files with known structure for parser tests. PDF and DOCX are binary formats that cannot be written by hand — the implementer generates them once using temporary scripts, commits the output files, and removes the scripts. The generation libraries (reportlab, python-docx) are NOT added to project dependencies — they are used in an ephemeral `uv run --with` invocation only.

- [ ] **Step 1: Create sample.html**

Write `backend/tests/fixtures/sample.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head><title>Sample Document</title></head>
<body>
<h1>Introduction</h1>
<p>This is the introduction paragraph for testing HTML parsing.</p>

<h2>Details</h2>
<p>This section contains more detailed information about the topic.</p>

<h3>Subsection</h3>
<p>A deeper level of detail within the document structure.</p>

<table>
  <thead>
    <tr><th>Name</th><th>Value</th></tr>
  </thead>
  <tbody>
    <tr><td>Alpha</td><td>100</td></tr>
    <tr><td>Beta</td><td>200</td></tr>
  </tbody>
</table>

<h2>Summary</h2>
<ul>
  <li>First point about the topic</li>
  <li>Second point about the topic</li>
  <li>Third point about the topic</li>
</ul>
</body>
</html>
```

- [ ] **Step 2: Generate sample.pdf**

Write a temporary script `backend/tests/fixtures/_gen_pdf.py`:

```python
"""One-time script to generate sample.pdf. Run once, commit the PDF, then delete this script."""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet
from pathlib import Path

output = Path(__file__).parent / "sample.pdf"
doc = SimpleDocTemplate(str(output), pagesize=A4)
styles = getSampleStyleSheet()

story = [
    Paragraph("Introduction", styles["Heading1"]),
    Paragraph("This is the introduction paragraph on page one for testing PDF parsing.", styles["Normal"]),
    Spacer(1, 12),
    Paragraph("Details", styles["Heading2"]),
    Paragraph("This section contains more detailed information about the topic.", styles["Normal"]),
    Spacer(1, 12),
    Table(
        [["Name", "Value"], ["Alpha", "100"], ["Beta", "200"]],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ]),
    ),
    PageBreak(),
    Paragraph("Summary", styles["Heading1"]),
    Paragraph("This is the summary on page two. It wraps up the document content.", styles["Normal"]),
]

doc.build(story)
print(f"Created {output}")
```

Run (ephemeral, does NOT modify project deps):
```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run --with reportlab python tests/fixtures/_gen_pdf.py
```

Then delete the script: `rm backend/tests/fixtures/_gen_pdf.py`

- [ ] **Step 3: Generate sample.docx**

Write a temporary script `backend/tests/fixtures/_gen_docx.py`:

```python
"""One-time script to generate sample.docx. Run once, commit the DOCX, then delete this script."""
from docx import Document
from pathlib import Path

output = Path(__file__).parent / "sample.docx"
doc = Document()

doc.add_heading("Introduction", level=1)
doc.add_paragraph("This is the introduction paragraph for testing DOCX parsing.")

doc.add_heading("Details", level=2)
doc.add_paragraph("This section contains more detailed information about the topic.")

table = doc.add_table(rows=3, cols=2)
table.style = "Table Grid"
table.rows[0].cells[0].text = "Name"
table.rows[0].cells[1].text = "Value"
table.rows[1].cells[0].text = "Alpha"
table.rows[1].cells[1].text = "100"
table.rows[2].cells[0].text = "Beta"
table.rows[2].cells[1].text = "200"

doc.add_heading("Summary", level=1)
doc.add_paragraph("This is the summary. It wraps up the document content.")
for item in ["First point about the topic", "Second point about the topic"]:
    doc.add_paragraph(item, style="List Bullet")

doc.save(str(output))
print(f"Created {output}")
```

Run (ephemeral, does NOT modify project deps):
```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run --with python-docx python tests/fixtures/_gen_docx.py
```

Then delete the script: `rm backend/tests/fixtures/_gen_docx.py`

- [ ] **Step 4: Verify fixtures exist and have reasonable sizes**

Run: `ls -la /Users/techmeat/www/projects/agentic-depot/proxymind/backend/tests/fixtures/sample.{pdf,docx,html}`

Expected: All three files exist. PDF ~1-5 KB, DOCX ~5-15 KB, HTML ~1 KB.

- [ ] **Step 5: Propose commit**

Proposed message:
```
test: add PDF, DOCX, HTML test fixtures (S3-01)
```

Files to stage: `backend/tests/fixtures/sample.pdf`, `backend/tests/fixtures/sample.docx`, `backend/tests/fixtures/sample.html`

---

### Task 3: Extend DoclingParser for multi-format support

**Files:**
- Modify: `backend/app/services/docling_parser.py:37, 60-84`
- Test: `backend/tests/unit/services/test_docling_parser.py`

- [ ] **Step 1: Write failing test for PDF parsing**

Add to `backend/tests/unit/services/test_docling_parser.py`:

```python
@pytest.mark.asyncio
async def test_parse_pdf_extracts_chunks_with_page_numbers() -> None:
    parser = DoclingParser(chunk_max_tokens=1024)

    chunks = await parser.parse_and_chunk(
        _fixture_bytes("sample.pdf"),
        "sample.pdf",
        SourceType.PDF,
    )

    assert chunks
    assert all(chunk.text_content for chunk in chunks)
    assert all(chunk.token_count > 0 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    # PDF should have page numbers in anchor metadata
    pages_found = [chunk.anchor_page for chunk in chunks if chunk.anchor_page is not None]
    assert len(pages_found) > 0, "PDF chunks should have anchor_page populated"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run python -m pytest tests/unit/services/test_docling_parser.py::test_parse_pdf_extracts_chunks_with_page_numbers -v`

Expected: FAIL — `ValueError: Unsupported source type for DoclingParser: pdf`

- [ ] **Step 3: Write failing test for DOCX parsing**

Add to `backend/tests/unit/services/test_docling_parser.py`:

```python
@pytest.mark.asyncio
async def test_parse_docx_extracts_chunks_with_headings() -> None:
    parser = DoclingParser(chunk_max_tokens=1024)

    chunks = await parser.parse_and_chunk(
        _fixture_bytes("sample.docx"),
        "sample.docx",
        SourceType.DOCX,
    )

    assert chunks
    assert all(chunk.text_content for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    # DOCX should have heading-based chapter anchors
    chapters_found = [chunk.anchor_chapter for chunk in chunks if chunk.anchor_chapter is not None]
    assert len(chapters_found) > 0, "DOCX chunks should have anchor_chapter from headings"
```

- [ ] **Step 4: Write failing test for HTML parsing**

Add to `backend/tests/unit/services/test_docling_parser.py`:

```python
@pytest.mark.asyncio
async def test_parse_html_extracts_chunks_with_headings() -> None:
    parser = DoclingParser(chunk_max_tokens=1024)

    chunks = await parser.parse_and_chunk(
        _fixture_bytes("sample.html"),
        "sample.html",
        SourceType.HTML,
    )

    assert chunks
    assert all(chunk.text_content for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    # HTML should have heading-based chapter anchors
    chapters_found = [chunk.anchor_chapter for chunk in chunks if chunk.anchor_chapter is not None]
    assert len(chapters_found) > 0, "HTML chunks should have anchor_chapter from <h1>-<h6>"
```

- [ ] **Step 5: Write failing test for PDF table content**

Add to `backend/tests/unit/services/test_docling_parser.py`:

```python
@pytest.mark.asyncio
async def test_parse_pdf_table_content_appears_in_chunks() -> None:
    parser = DoclingParser(chunk_max_tokens=1024)

    chunks = await parser.parse_and_chunk(
        _fixture_bytes("sample.pdf"),
        "sample.pdf",
        SourceType.PDF,
    )

    all_text = " ".join(chunk.text_content for chunk in chunks)
    # Table data from the fixture should be present in chunk text
    assert "Alpha" in all_text, "Table content should be extracted into chunk text"
    assert "Beta" in all_text, "Table content should be extracted into chunk text"
```

- [ ] **Step 6: Write failing test for unsupported type raises error**

Add to `backend/tests/unit/services/test_docling_parser.py`:

```python
@pytest.mark.asyncio
async def test_parse_unsupported_type_raises_value_error() -> None:
    parser = DoclingParser(chunk_max_tokens=1024)

    with pytest.raises(ValueError, match="Unsupported source type"):
        await parser.parse_and_chunk(b"fake content", "file.wav", SourceType.AUDIO)
```

- [ ] **Step 7: Write unit test for corrupt file raises exception**

The contract: corrupt/malformed files MUST raise an exception from the parser. We don't control which exception type Docling raises for invalid content, so this unit test uses a broad catch. The **real contract test** is the integration test in Task 6 (corrupt file → worker → task FAILED).

Add to `backend/tests/unit/services/test_docling_parser.py`:

```python
@pytest.mark.asyncio
async def test_parse_corrupt_pdf_raises_exception() -> None:
    """Docling raises on corrupt content. The exact exception type is uncontrolled
    (Docling internal). The worker-level contract (corrupt → task FAILED) is tested
    in the integration smoke test."""
    parser = DoclingParser(chunk_max_tokens=1024)

    with pytest.raises(Exception):
        await parser.parse_and_chunk(
            b"not-a-real-pdf-content",
            "corrupt.pdf",
            SourceType.PDF,
        )
```

- [ ] **Step 8: Run all new tests to confirm they fail**

Run: `cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run python -m pytest tests/unit/services/test_docling_parser.py -v -k "pdf or docx or html or unsupported_type or corrupt"`

Expected: PDF/DOCX/HTML tests FAIL with `ValueError: Unsupported source type`. The unsupported_type test may PASS already (existing behavior).

- [ ] **Step 9: Update DocumentConverter to accept multiple formats**

In `backend/app/services/docling_parser.py`, line 37, change:

```python
self._converter = converter or DocumentConverter(allowed_formats=[InputFormat.MD])
```

to:

```python
self._converter = converter or DocumentConverter(
    allowed_formats=[
        InputFormat.MD,
        InputFormat.PDF,
        InputFormat.DOCX,
        InputFormat.HTML,
    ]
)
```

- [ ] **Step 10: Extend _convert_document for new formats**

In `backend/app/services/docling_parser.py`, add module-level helpers after the imports (before the `ChunkData` class):

```python
_SOURCE_TYPE_TO_INPUT_FORMAT = {
    SourceType.MARKDOWN: InputFormat.MD,
    SourceType.PDF: InputFormat.PDF,
    SourceType.DOCX: InputFormat.DOCX,
    SourceType.HTML: InputFormat.HTML,
}

_INPUT_FORMAT_SUFFIX = {
    InputFormat.MD: ".md",
    InputFormat.PDF: ".pdf",
    InputFormat.DOCX: ".docx",
    InputFormat.HTML: ".html",
}
```

Then replace the `_convert_document` method (lines 60-84):

```python
def _convert_document(
    self,
    content: bytes,
    filename: str,
    source_type: SourceType,
) -> DoclingDocument | None:
    input_format = _SOURCE_TYPE_TO_INPUT_FORMAT.get(source_type)

    if input_format is InputFormat.MD:
        stream = DocumentStream(
            name=self._normalize_stream_name(filename, input_format),
            stream=BytesIO(content),
        )
        return self._converter.convert(stream).document

    if source_type is SourceType.TXT:
        text = content.decode("utf-8", errors="replace")
        if not text.strip():
            return None
        normalized_name = f"{Path(filename).stem or 'document'}.md"
        return self._converter.convert_string(
            text,
            format=InputFormat.MD,
            name=normalized_name,
        ).document

    if input_format in {InputFormat.PDF, InputFormat.DOCX, InputFormat.HTML}:
        stream = DocumentStream(
            name=self._normalize_stream_name(filename, input_format),
            stream=BytesIO(content),
        )
        return self._converter.convert(stream).document

    raise ValueError(f"Unsupported source type for DoclingParser: {source_type.value}")
```

Docling auto-detects the format from the filename extension when `allowed_formats` includes the format. The mapping keeps format routing explicit, while `_normalize_stream_name()` ensures aliases like `.htm` are normalized to a suffix Docling accepts for HTML streams.

- [ ] **Step 11: If Docling needs PDF extras, install them**

If tests fail with import errors or missing PDF backend:

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv add 'docling[pdf]'
```

This updates `pyproject.toml` and `uv.lock` atomically. Then re-run tests.

- [ ] **Step 12: Run all parser tests**

Run: `cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run python -m pytest tests/unit/services/test_docling_parser.py -v`

Expected: ALL PASS — including existing MD/TXT tests (no regression) and new PDF/DOCX/HTML tests.

- [ ] **Step 13: Propose commit**

Proposed message:
```
feat(parser): extend DoclingParser for PDF, DOCX, HTML formats (S3-01)
```

Files to stage: `backend/app/services/docling_parser.py`, `backend/tests/unit/services/test_docling_parser.py`
Also include `backend/pyproject.toml` and `uv.lock` if extras were added.

---

### Task 4: Raise upload size limit and align test fixture

**Files:**
- Modify: `backend/app/core/config.py:46`
- Modify: `backend/tests/conftest.py:198`

- [ ] **Step 1: Change default upload limit**

In `backend/app/core/config.py`, line 46, change:

```python
upload_max_file_size_mb: int = Field(default=50, ge=1)
```

to:

```python
upload_max_file_size_mb: int = Field(default=100, ge=1)
```

- [ ] **Step 2: Align test fixture default**

In `backend/tests/conftest.py`, line 198, change:

```python
upload_max_file_size_mb=50,
```

to:

```python
upload_max_file_size_mb=100,
```

This keeps the test fixture aligned with the production default.

- [ ] **Step 3: Run existing upload size test to verify it still works**

Run: `cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run python -m pytest tests/integration/test_source_upload.py::test_upload_endpoint_rejects_oversized_file -v`

Expected: PASS — the test sets its own limit (1 MB), not the default.

- [ ] **Step 4: Propose commit**

Proposed message:
```
feat(config): raise upload_max_file_size_mb default to 100 (S3-01)
```

Files to stage: `backend/app/core/config.py`, `backend/tests/conftest.py`

---

### Task 5: Update integration tests for new format uploads

**Files:**
- Modify: `backend/tests/integration/test_source_upload.py`

- [ ] **Step 1: Update parametrized upload test to include new formats**

In `backend/tests/integration/test_source_upload.py`, modify the parametrize on line 44-46 of `test_upload_endpoint_accepts_markdown_and_txt` to include PDF, DOCX, HTML:

```python
@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
@pytest.mark.parametrize(
    ("filename", "expected_type"),
    [
        ("doc.md", SourceType.MARKDOWN),
        ("notes.TXT", SourceType.TXT),
        ("report.pdf", SourceType.PDF),
        ("document.docx", SourceType.DOCX),
        ("page.html", SourceType.HTML),
        ("page.htm", SourceType.HTML),
    ],
)
async def test_upload_endpoint_accepts_supported_formats(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
    mock_storage_service: SimpleNamespace,
    filename: str,
    expected_type: SourceType,
) -> None:
    response = await api_client.post(
        "/api/admin/sources",
        data={"metadata": '{"title":"My document"}'},
        files={"file": (filename, b"hello world", "application/octet-stream")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"

    sources, tasks = await _load_source_and_task(session_factory)
    assert len(sources) == 1
    assert len(tasks) == 1
    assert sources[0].source_type is expected_type
```

- [ ] **Step 2: Update the rejection test — PDF should no longer be rejected**

In `backend/tests/integration/test_source_upload.py`, update `test_upload_endpoint_rejects_unsupported_extension` (line 147) to use a truly unsupported extension:

```python
@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_upload_endpoint_rejects_unsupported_extension(api_client) -> None:
    response = await api_client.post(
        "/api/admin/sources",
        data={"metadata": '{"title":"Bad document"}'},
        files={"file": ("data.xlsx", b"fake-data", "application/octet-stream")},
    )

    assert response.status_code == 422
    assert "Allowed extensions" in response.json()["detail"]
```

- [ ] **Step 3: Run integration tests**

Run: `cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run python -m pytest tests/integration/test_source_upload.py -v`

Expected: ALL PASS.

- [ ] **Step 4: Propose commit**

Proposed message:
```
test(upload): extend integration tests for PDF, DOCX, HTML uploads (S3-01)
```

Files to stage: `backend/tests/integration/test_source_upload.py`

---

### Task 6: Add worker smoke test with real parser for HTML

**Files:**
- Modify: `backend/tests/integration/test_source_upload.py` (or `backend/tests/integration/test_ingestion_worker.py`)

This addresses the gap where existing worker integration tests mock `parse_and_chunk`. We add one smoke test that runs `process_ingestion` with a real `DoclingParser` and a real HTML fixture to verify the full path: storage → parser → DB records.

- [ ] **Step 1: Write worker smoke test with real HTML parsing**

Add to `backend/tests/integration/test_source_upload.py` (it already imports `process_ingestion` and has the round-trip test pattern):

```python
@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_worker_parses_real_html_file_end_to_end(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Smoke test: upload HTML → worker with real DoclingParser → chunks in DB."""
    from pathlib import Path
    from app.services.docling_parser import DoclingParser
    from app.services.snapshot import SnapshotService

    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "sample.html"
    html_bytes = fixture_path.read_bytes()

    # Upload an HTML file
    upload_response = await api_client.post(
        "/api/admin/sources",
        data={"metadata": '{"title":"HTML smoke test"}'},
        files={"file": ("sample.html", html_bytes, "text/html")},
    )
    assert upload_response.status_code == 202
    task_id = upload_response.json()["task_id"]

    # Run ingestion with a REAL parser but mocked embedding/qdrant
    real_parser = DoclingParser(chunk_max_tokens=1024)

    await process_ingestion(
        {
            "session_factory": session_factory,
            "settings": SimpleNamespace(bm25_language="english"),
            "storage_service": SimpleNamespace(download=AsyncMock(return_value=html_bytes)),
            "docling_parser": real_parser,
            "embedding_service": SimpleNamespace(
                model="gemini-embedding-2-preview",
                dimensions=3,
                embed_texts=AsyncMock(
                    side_effect=lambda texts, **kw: [[0.1, 0.2, 0.3]] * len(texts)
                ),
            ),
            "qdrant_service": SimpleNamespace(
                upsert_chunks=AsyncMock(),
                delete_chunks=AsyncMock(),
            ),
            "snapshot_service": SnapshotService(),
        },
        task_id,
    )

    # Verify task completed and chunks were created
    task_response = await api_client.get(f"/api/admin/tasks/{task_id}")
    assert task_response.status_code == 200
    task_body = task_response.json()
    assert task_body["status"] == "complete"
    assert task_body["progress"] == 100
    assert task_body["result_metadata"]["chunk_count"] > 0
```

- [ ] **Step 2: Write integration test for corrupt file → worker marks FAILED**

This is the **primary contract test** for corrupt files. The unit test (Task 3 Step 7) only verifies the parser raises; this test verifies the full contract: corrupt file → worker → task/source FAILED.

Add to `backend/tests/integration/test_source_upload.py`:

```python
@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_worker_marks_task_failed_on_corrupt_file(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Contract test: corrupt file → parser raises → worker marks task FAILED."""
    from app.services.docling_parser import DoclingParser
    from app.services.snapshot import SnapshotService

    corrupt_pdf = b"not-a-real-pdf-content"

    upload_response = await api_client.post(
        "/api/admin/sources",
        data={"metadata": '{"title":"Corrupt PDF test"}'},
        files={"file": ("corrupt.pdf", corrupt_pdf, "application/pdf")},
    )
    assert upload_response.status_code == 202
    task_id = upload_response.json()["task_id"]
    source_id = upload_response.json()["source_id"]

    real_parser = DoclingParser(chunk_max_tokens=1024)

    await process_ingestion(
        {
            "session_factory": session_factory,
            "settings": SimpleNamespace(bm25_language="english"),
            "storage_service": SimpleNamespace(download=AsyncMock(return_value=corrupt_pdf)),
            "docling_parser": real_parser,
            "embedding_service": SimpleNamespace(
                model="gemini-embedding-2-preview",
                dimensions=3,
                embed_texts=AsyncMock(return_value=[]),
            ),
            "qdrant_service": SimpleNamespace(
                upsert_chunks=AsyncMock(),
                delete_chunks=AsyncMock(),
            ),
            "snapshot_service": SnapshotService(),
        },
        task_id,
    )

    # Task and source should be FAILED
    task_response = await api_client.get(f"/api/admin/tasks/{task_id}")
    assert task_response.status_code == 200
    assert task_response.json()["status"] == "failed"

    async with session_factory() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        assert source.status is SourceStatus.FAILED
```

- [ ] **Step 3: Run both smoke tests**

Run: `cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run python -m pytest tests/integration/test_source_upload.py -v -k "real_html or corrupt"`

Expected: Both PASS — HTML smoke test creates chunks; corrupt file test marks task FAILED.

- [ ] **Step 4: Propose commit**

Proposed message:
```
test(worker): add smoke tests — real parser for HTML and corrupt file contract (S3-01)
```

Files to stage: `backend/tests/integration/test_source_upload.py`

---

### Task 7: Full test suite verification and post-apply checks

- [ ] **Step 1: Run the complete test suite**

Run: `cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run python -m pytest tests/ -v --tb=short`

Expected: ALL PASS — no regressions from existing MD/TXT functionality.

- [ ] **Step 2: Run linter**

Run: `cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run ruff check app/ tests/`

Expected: No errors.

- [ ] **Step 3: If any failures, fix and re-run**

Fix issues found in Step 1 or 2. Common issues:
- Import errors from missing Docling extras → `uv add 'docling[pdf]'`
- Docling API differences → check Docling docs for `DocumentStream` constructor
- Anchor metadata not populated → adjust `_extract_anchor_page` if Docling uses different provenance structure for PDF

- [ ] **Step 4: Verify dependency versions against spec**

Check that all installed dependency versions meet or exceed `docs/spec.md` minimums:

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run python -c "
import docling; print(f'docling: {docling.__version__}')
import fastapi; print(f'fastapi: {fastapi.__version__}')
import sqlalchemy; print(f'sqlalchemy: {sqlalchemy.__version__}')
import pydantic; print(f'pydantic: {pydantic.__version__}')
"
```

Cross-reference output against `docs/spec.md` tables. If any version is below the minimum, update via `uv add 'package>=minimum_version'`.

- [ ] **Step 5: Re-read docs/development.md and self-review**

Re-read `docs/development.md` and verify the implementation against its checklist:
- No mocks outside `tests/`
- No fallbacks to stubs or dead code
- All stubs reference a specific story
- Secrets outside of code and git
- Tests for meaningful behavior

Explicitly confirm both the pre-code read (Task 0) and this post-code self-review were completed.

- [ ] **Step 6: Propose final commit if any fixes were needed**

Proposed message:
```
fix(s3-01): address test suite issues
```

---

## Verification Checklist

After all tasks are complete:

- [ ] `uv run python -m pytest tests/` — all tests pass
- [ ] Upload PDF via API → 202, task created, source type is `pdf`
- [ ] Upload DOCX via API → 202, task created, source type is `docx`
- [ ] Upload HTML via API → 202, task created, source type is `html`
- [ ] Upload .htm via API → 202, source type is `html`
- [ ] Upload .xlsx → 422, rejected
- [ ] DoclingParser produces chunks with `anchor_page` from PDF
- [ ] DoclingParser produces chunks with `anchor_chapter` from DOCX headings
- [ ] DoclingParser produces chunks with `anchor_chapter` from HTML `<h1>`–`<h6>`
- [ ] PDF table content appears in chunk text
- [ ] Corrupt PDF raises exception (not silent empty result)
- [ ] Worker smoke test passes with real DoclingParser + HTML fixture
- [ ] Existing MD/TXT parsing still works (no regression)
- [ ] `uv run ruff check app/ tests/` passes
- [ ] All dependency versions ≥ `docs/spec.md` minimums
- [ ] Post-apply self-review against `docs/development.md` completed

## Review History

- **v1** (2026-03-22): Initial plan with `pip install`, `git commit`, and code bug in `_SOURCE_TYPE_TO_INPUT_FORMAT`.
- **v2** (2026-03-22): Fixed all 6 review findings: (1) `pip install` → `uv run` / `uv add` everywhere; (2) `git commit` → "Propose commit" per repo policy; (3) fixed `self._SOURCE_TYPE_TO_INPUT_FORMAT` → module-level `_SOURCE_TYPE_TO_INPUT_FORMAT`; (4) fixture generation uses `uv run --with` (ephemeral, no project deps added); (5) added Task 6 — worker smoke test with real DoclingParser + HTML fixture; (6) aligned conftest fixture default with config default (50 → 100).
- **v3** (2026-03-22): Fixed 3 review findings: (1) added Task 0: Preflight (read development.md, find-skills, verify versions); (2) corrupt file contract fixed — parser MUST raise, no ambiguous "error or empty" — updated spec and plan; (3) fixed spec API drift `parse()` → `parse_and_chunk()`; (4) added post-apply self-review step and version verification in Task 7.
- **v4** (2026-03-22): Fixed 3 review findings: (1) corrupt file test — kept broad unit test with docstring explaining Docling's uncontrolled exception types, added integration test as primary contract test (corrupt → worker → FAILED); (2) replaced `_SOURCE_TYPE_TO_INPUT_FORMAT` mapping with simpler `_BINARY_DOCUMENT_TYPES` frozenset — Docling auto-detects format from filename; (3) aligned preflight version check command with text (now prints all key dependencies).
- **v5** (2026-03-22): Post-implementation follow-up after review: kept a generalized `_SOURCE_TYPE_TO_INPUT_FORMAT` + suffix normalization helper instead of `_BINARY_DOCUMENT_TYPES`, because the implementation needs one place to normalize stream filenames for Docling and explicitly support `.htm` alias → `.html`; added parser-level `.htm` coverage and clarified why corrupt PDF unit test catches broad exceptions.
