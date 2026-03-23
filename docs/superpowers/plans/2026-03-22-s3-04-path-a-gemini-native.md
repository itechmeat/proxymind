# S3-04: Path A (Gemini Native) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable multimodal source ingestion (short PDFs, images, audio, video) via Gemini native pipeline — text extraction via Gemini LLM, multimodal embeddings via Gemini Embedding 2, single-chunk indexing in Qdrant.

**Architecture:** New `PathRouter` decides Path A vs Path B based on format/size/duration. Path A handler calls `GeminiContentService` for text extraction, checks token threshold, then `EmbeddingService.embed_file()` for multimodal embedding. Shared `gemini_file_transfer` helper handles inline vs Files API. Existing ingestion orchestrator is refactored into thin dispatcher + separate handler modules per path.

**Tech Stack:** google-genai, pypdf, tinytag, tenacity, qdrant-client, pytest, HuggingFaceTokenizer

**Spec:** `docs/superpowers/specs/2026-03-22-s3-04-path-a-gemini-native-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `backend/pyproject.toml` | Add pypdf, tinytag dependencies |
| `backend/app/core/config.py` | Path A configuration settings |
| `backend/app/services/storage.py` | Extend allowed extensions + MIME type mapping |
| `backend/app/services/gemini_file_transfer.py` | Shared helper: inline vs Files API |
| `backend/app/services/gemini_content.py` | GeminiContentService: text extraction from multimodal files |
| `backend/app/services/embedding.py` | Add `embed_file()` method |
| `backend/app/services/path_router.py` | PathRouter: inspect_file + determine_path |
| `backend/app/workers/tasks/handlers/__init__.py` | Package init |
| `backend/app/workers/tasks/handlers/path_b.py` | Extracted existing Path B logic |
| `backend/app/workers/tasks/handlers/path_a.py` | New Path A handler |
| `backend/app/workers/tasks/ingestion.py` | Refactored to thin orchestrator |
| `backend/app/workers/main.py` | Initialize new services in worker context |
| `backend/tests/unit/services/test_path_router.py` | PathRouter unit tests |
| `backend/tests/unit/services/test_gemini_file_transfer.py` | File transfer helper tests |
| `backend/tests/unit/services/test_gemini_content.py` | GeminiContentService tests |
| `backend/tests/unit/services/test_embedding_file.py` | embed_file() tests |
| `backend/tests/unit/workers/test_path_a_handler.py` | Path A handler tests |
| `backend/tests/integration/test_path_a_ingestion.py` | Path A worker-level integration tests |

---

### Task 1: Add dependencies (pypdf, tinytag)

**Files:**
- Modify: `backend/pyproject.toml:6-23`

- [ ] **Step 1: Add pypdf and tinytag to dependencies**

In `backend/pyproject.toml`, add to the `dependencies` list:

```toml
  "pypdf>=5.0.0",
  "tinytag>=2.0.0",
```

- [ ] **Step 2: Lock and verify imports**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv lock && uv run python -c "from pypdf import PdfReader; from tinytag import TinyTag; print('OK')"
```

Expected: `OK`, no import errors.

- [ ] **Step 3: Propose commit**

Proposed message: `build: add pypdf and tinytag for Path A file inspection`
Files: `backend/pyproject.toml`, `backend/uv.lock`

---

### Task 2: Add Path A configuration settings

**Files:**
- Modify: `backend/app/core/config.py:28-46`
- Test: `backend/tests/unit/test_config.py`

- [ ] **Step 1: Write failing test for new settings**

Add to `backend/tests/unit/test_config.py`:

```python
def test_path_a_settings_defaults():
    """Path A settings have correct defaults."""
    from app.core.config import Settings

    s = Settings(**_base_settings())
    assert s.path_a_text_threshold_pdf == 2000
    assert s.path_a_text_threshold_media == 500
    assert s.path_a_max_pdf_pages == 6
    assert s.path_a_max_audio_duration_sec == 80
    assert s.path_a_max_video_duration_sec == 120
    assert s.gemini_content_model == "gemini-2.5-flash"
    assert s.gemini_file_upload_threshold_bytes == 10_485_760
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/test_config.py::test_path_a_settings_defaults -v
```

Expected: FAIL — `Settings` has no field `path_a_text_threshold_pdf`.

- [ ] **Step 3: Add settings to config.py**

In `backend/app/core/config.py`, add after line 41 (`min_dense_similarity`):

```python
    # Path A (Gemini native) settings
    path_a_text_threshold_pdf: int = Field(default=2000, ge=1)
    path_a_text_threshold_media: int = Field(default=500, ge=1)
    path_a_max_pdf_pages: int = Field(default=6, ge=1)
    path_a_max_audio_duration_sec: int = Field(default=80, ge=1)
    path_a_max_video_duration_sec: int = Field(default=120, ge=1)
    gemini_content_model: str = Field(default="gemini-2.5-flash", min_length=1)
    gemini_file_upload_threshold_bytes: int = Field(default=10_485_760, ge=1)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/test_config.py -v
```

Expected: all config tests PASS.

- [ ] **Step 5: Propose commit**

Proposed message: `feat(config): add Path A settings for Gemini native ingestion (S3-04)`
Files: `backend/app/core/config.py`, `backend/tests/unit/test_config.py`

---

### Task 3: Extend allowed file extensions and MIME types

**Files:**
- Modify: `backend/app/services/storage.py:11-19`
- Test: `backend/tests/unit/services/test_storage.py`

- [ ] **Step 1: Write failing test for new extensions**

Add to `backend/tests/unit/services/test_storage.py`:

```python
import pytest
from app.services.storage import validate_file_extension, determine_source_type, MIME_TYPE_BY_EXTENSION
from app.db.models.enums import SourceType


@pytest.mark.parametrize(
    "filename, expected_type",
    [
        ("photo.png", SourceType.IMAGE),
        ("photo.jpeg", SourceType.IMAGE),
        ("photo.jpg", SourceType.IMAGE),
        ("podcast.mp3", SourceType.AUDIO),
        ("recording.wav", SourceType.AUDIO),
        ("clip.mp4", SourceType.VIDEO),
    ],
)
def test_determine_source_type_media(filename, expected_type):
    assert determine_source_type(filename) == expected_type


@pytest.mark.parametrize(
    "ext, expected_mime",
    [
        (".png", "image/png"),
        (".jpeg", "image/jpeg"),
        (".jpg", "image/jpeg"),
        (".mp3", "audio/mpeg"),
        (".wav", "audio/wav"),
        (".mp4", "video/mp4"),
        (".pdf", "application/pdf"),
    ],
)
def test_mime_type_mapping(ext, expected_mime):
    assert MIME_TYPE_BY_EXTENSION[ext] == expected_mime
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_storage.py::test_determine_source_type_media -v
```

Expected: FAIL — `.png` not in ALLOWED_SOURCE_EXTENSIONS.

- [ ] **Step 3: Extend storage.py**

In `backend/app/services/storage.py`, update the constants:

```python
ALLOWED_SOURCE_EXTENSIONS = (
    ".md", ".txt", ".pdf", ".docx", ".html", ".htm",
    ".png", ".jpeg", ".jpg", ".mp3", ".wav", ".mp4",
)
SOURCE_TYPE_BY_EXTENSION = {
    ".md": SourceType.MARKDOWN,
    ".txt": SourceType.TXT,
    ".pdf": SourceType.PDF,
    ".docx": SourceType.DOCX,
    ".html": SourceType.HTML,
    ".htm": SourceType.HTML,
    ".png": SourceType.IMAGE,
    ".jpeg": SourceType.IMAGE,
    ".jpg": SourceType.IMAGE,
    ".mp3": SourceType.AUDIO,
    ".wav": SourceType.AUDIO,
    ".mp4": SourceType.VIDEO,
}
MIME_TYPE_BY_EXTENSION = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".html": "text/html",
    ".htm": "text/html",
    ".png": "image/png",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".mp4": "video/mp4",
}
```

- [ ] **Step 4: Run all storage tests**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_storage.py -v
```

Expected: all PASS.

- [ ] **Step 5: Propose commit**

Proposed message: `feat(storage): add multimodal file extensions and MIME type mapping (S3-04)`
Files: `backend/app/services/storage.py`, `backend/tests/unit/services/test_storage.py`

---

### Task 4: Implement PathRouter — inspect_file + determine_path

**Files:**
- Create: `backend/app/services/path_router.py`
- Test: `backend/tests/unit/services/test_path_router.py`

- [ ] **Step 1: Write failing tests for determine_path (pure function)**

Create `backend/tests/unit/services/test_path_router.py`:

```python
from __future__ import annotations

import pytest

from app.db.models.enums import ProcessingPath, SourceType
from app.services.path_router import FileMetadata, determine_path


@pytest.mark.parametrize(
    "source_type, metadata, expected_path",
    [
        # Always Path B
        (SourceType.MARKDOWN, FileMetadata(file_size_bytes=100), ProcessingPath.PATH_B),
        (SourceType.TXT, FileMetadata(file_size_bytes=100), ProcessingPath.PATH_B),
        (SourceType.DOCX, FileMetadata(file_size_bytes=100), ProcessingPath.PATH_B),
        (SourceType.HTML, FileMetadata(file_size_bytes=100), ProcessingPath.PATH_B),
        # IMAGE — always Path A
        (SourceType.IMAGE, FileMetadata(file_size_bytes=5_000_000), ProcessingPath.PATH_A),
        # PDF — under page limit
        (SourceType.PDF, FileMetadata(file_size_bytes=1_000, page_count=3), ProcessingPath.PATH_A),
        (SourceType.PDF, FileMetadata(file_size_bytes=1_000, page_count=6), ProcessingPath.PATH_A),
        # PDF — over page limit
        (SourceType.PDF, FileMetadata(file_size_bytes=1_000, page_count=7), ProcessingPath.PATH_B),
        # PDF — page_count unknown → Path B (conservative)
        (SourceType.PDF, FileMetadata(file_size_bytes=1_000, page_count=None), ProcessingPath.PATH_B),
        # AUDIO — under duration limit
        (SourceType.AUDIO, FileMetadata(file_size_bytes=1_000, duration_seconds=60.0), ProcessingPath.PATH_A),
        (SourceType.AUDIO, FileMetadata(file_size_bytes=1_000, duration_seconds=80.0), ProcessingPath.PATH_A),
        # AUDIO — over duration limit → REJECTED (Path B not available)
        # (SourceType.AUDIO, 81.0) tested separately below — returns rejected=True
        # AUDIO — duration unknown → Path A (threshold check catches oversize)
        (SourceType.AUDIO, FileMetadata(file_size_bytes=1_000, duration_seconds=None), ProcessingPath.PATH_A),
        # VIDEO — under duration limit
        (SourceType.VIDEO, FileMetadata(file_size_bytes=1_000, duration_seconds=100.0), ProcessingPath.PATH_A),
        (SourceType.VIDEO, FileMetadata(file_size_bytes=1_000, duration_seconds=120.0), ProcessingPath.PATH_A),
        # VIDEO — over duration limit → REJECTED (tested separately below)
        # VIDEO — duration unknown → Path A
        (SourceType.VIDEO, FileMetadata(file_size_bytes=1_000, duration_seconds=None), ProcessingPath.PATH_A),
    ],
)
def test_determine_path(source_type, metadata, expected_path):
    decision = determine_path(source_type, metadata)
    assert decision.path == expected_path


def test_determine_path_audio_over_limit_rejected():
    """Audio over 80s is rejected (Path B not available)."""
    metadata = FileMetadata(file_size_bytes=1_000, duration_seconds=81.0)
    decision = determine_path(SourceType.AUDIO, metadata)
    assert decision.rejected is True
    assert decision.path is None
    assert "Path B not available" in decision.reason


def test_determine_path_video_over_limit_rejected():
    """Video over 120s is rejected (Path B not available)."""
    metadata = FileMetadata(file_size_bytes=1_000, duration_seconds=121.0)
    decision = determine_path(SourceType.VIDEO, metadata)
    assert decision.rejected is True
    assert decision.path is None


def test_determine_path_custom_thresholds():
    """Custom page/duration thresholds override defaults."""
    metadata = FileMetadata(file_size_bytes=1_000, page_count=4)
    decision = determine_path(SourceType.PDF, metadata, max_pdf_pages=3)
    assert decision.path == ProcessingPath.PATH_B
    assert "pages" in decision.reason.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_path_router.py -v
```

Expected: FAIL — `path_router` module does not exist.

- [ ] **Step 3: Implement PathRouter**

Create `backend/app/services/path_router.py`:

```python
from __future__ import annotations

import io
from dataclasses import dataclass, field

import structlog

from app.db.models.enums import ProcessingPath, SourceType

logger = structlog.get_logger(__name__)

_PATH_B_ONLY_TYPES = frozenset({
    SourceType.MARKDOWN,
    SourceType.TXT,
    SourceType.DOCX,
    SourceType.HTML,
})


@dataclass(frozen=True, slots=True)
class FileMetadata:
    file_size_bytes: int
    page_count: int | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class PathDecision:
    path: ProcessingPath | None  # None when rejected
    reason: str
    metadata: FileMetadata = field(default_factory=lambda: FileMetadata(file_size_bytes=0))
    rejected: bool = False  # True = file cannot be processed by any available path


def inspect_file(file_bytes: bytes, source_type: SourceType) -> FileMetadata:
    """Inspect file to extract metadata for path routing."""
    page_count: int | None = None
    duration_seconds: float | None = None

    if source_type == SourceType.PDF:
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(file_bytes))
            page_count = len(reader.pages)
        except Exception:
            logger.warning("path_router.pdf_page_count_failed", exc_info=True)

    elif source_type in (SourceType.AUDIO, SourceType.VIDEO):
        try:
            from tinytag import TinyTag
            tag = TinyTag.get(file_obj=io.BytesIO(file_bytes))
            if tag.duration is not None:
                duration_seconds = tag.duration
        except Exception:
            logger.warning("path_router.duration_read_failed", exc_info=True)

    return FileMetadata(
        file_size_bytes=len(file_bytes),
        page_count=page_count,
        duration_seconds=duration_seconds,
    )


def determine_path(
    source_type: SourceType,
    metadata: FileMetadata,
    *,
    max_pdf_pages: int = 6,
    max_audio_duration_sec: int = 80,
    max_video_duration_sec: int = 120,
) -> PathDecision:
    """Pure routing function: decide Path A or Path B based on source type and metadata."""
    if source_type in _PATH_B_ONLY_TYPES:
        return PathDecision(
            path=ProcessingPath.PATH_B,
            reason=f"{source_type.value} always uses Path B (Docling)",
            metadata=metadata,
        )

    if source_type == SourceType.IMAGE:
        return PathDecision(
            path=ProcessingPath.PATH_A,
            reason="Image always uses Path A (Gemini native)",
            metadata=metadata,
        )

    if source_type == SourceType.PDF:
        if metadata.page_count is None:
            return PathDecision(
                path=ProcessingPath.PATH_B,
                reason="PDF page count unknown; defaulting to Path B",
                metadata=metadata,
            )
        if metadata.page_count <= max_pdf_pages:
            return PathDecision(
                path=ProcessingPath.PATH_A,
                reason=f"PDF has {metadata.page_count} pages (<= {max_pdf_pages})",
                metadata=metadata,
            )
        return PathDecision(
            path=ProcessingPath.PATH_B,
            reason=f"PDF has {metadata.page_count} pages (> {max_pdf_pages})",
            metadata=metadata,
        )

    if source_type == SourceType.AUDIO:
        if metadata.duration_seconds is not None and metadata.duration_seconds > max_audio_duration_sec:
            return PathDecision(
                path=None,
                reason=f"Audio {metadata.duration_seconds:.1f}s exceeds {max_audio_duration_sec}s limit; "
                       f"Path B not available for audio (Docling audio support pending)",
                metadata=metadata,
                rejected=True,
            )
        if metadata.duration_seconds is None:
            # Cannot verify duration — proceed with Path A, threshold check is the safety net
            logger.warning("path_router.audio_duration_unknown", file_size=metadata.file_size_bytes)
        return PathDecision(
            path=ProcessingPath.PATH_A,
            reason=f"Audio within limit (duration={'unknown' if metadata.duration_seconds is None else f'{metadata.duration_seconds:.1f}s'})",
            metadata=metadata,
        )

    if source_type == SourceType.VIDEO:
        if metadata.duration_seconds is not None and metadata.duration_seconds > max_video_duration_sec:
            return PathDecision(
                path=None,
                reason=f"Video {metadata.duration_seconds:.1f}s exceeds {max_video_duration_sec}s limit; "
                       f"Path B not available for video (Docling video support pending)",
                metadata=metadata,
                rejected=True,
            )
        if metadata.duration_seconds is None:
            logger.warning("path_router.video_duration_unknown", file_size=metadata.file_size_bytes)
        return PathDecision(
            path=ProcessingPath.PATH_A,
            reason=f"Video within limit (duration={'unknown' if metadata.duration_seconds is None else f'{metadata.duration_seconds:.1f}s'})",
            metadata=metadata,
        )

    return PathDecision(
        path=ProcessingPath.PATH_B,
        reason=f"Unknown source type {source_type.value}; defaulting to Path B",
        metadata=metadata,
    )
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_path_router.py -v
```

Expected: all PASS.

- [ ] **Step 5: Write inspect_file tests**

Add to `backend/tests/unit/services/test_path_router.py`:

```python
from app.services.path_router import inspect_file


def test_inspect_file_pdf(tmp_path):
    """inspect_file extracts page count from a real PDF."""
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=612, height=792)
    pdf_bytes = io.BytesIO()
    writer.write(pdf_bytes)
    pdf_bytes = pdf_bytes.getvalue()

    meta = inspect_file(pdf_bytes, SourceType.PDF)
    assert meta.page_count == 3
    assert meta.file_size_bytes == len(pdf_bytes)


def test_inspect_file_corrupt_pdf():
    """inspect_file returns None page_count for corrupt PDF."""
    meta = inspect_file(b"not a pdf", SourceType.PDF)
    assert meta.page_count is None


def test_inspect_file_image():
    """inspect_file for image returns no page_count or duration."""
    meta = inspect_file(b"\x89PNG\r\n", SourceType.IMAGE)
    assert meta.page_count is None
    assert meta.duration_seconds is None
    assert meta.file_size_bytes == 6
```

Add `import io` at the top of the test file if not already present.

- [ ] **Step 6: Run all path_router tests**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_path_router.py -v
```

Expected: all PASS.

- [ ] **Step 7: Propose commit**

Proposed message: `feat(ingestion): add PathRouter for Path A/B routing with file inspection (S3-04)`
Files: `backend/app/services/path_router.py`, `backend/tests/unit/services/test_path_router.py`

---

### Task 5: Implement gemini_file_transfer helper

**Files:**
- Create: `backend/app/services/gemini_file_transfer.py`
- Test: `backend/tests/unit/services/test_gemini_file_transfer.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/services/test_gemini_file_transfer.py`:

```python
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.gemini_file_transfer import prepare_file_part


def test_inline_for_small_file():
    """Files under threshold use inline data."""
    client = MagicMock()
    small_data = b"x" * 100
    prepared = prepare_file_part(client, small_data, "image/png", threshold_bytes=1000)
    client.files.upload.assert_not_called()
    assert prepared.part is not None
    assert prepared.uploaded_file_name is None


def test_files_api_for_large_file():
    """Files at or above threshold use Files API."""
    mock_file = SimpleNamespace(uri="https://files.example.com/abc", name="files/abc")
    client = MagicMock()
    client.files.upload.return_value = mock_file
    large_data = b"x" * 2000
    prepared = prepare_file_part(client, large_data, "video/mp4", threshold_bytes=1000)
    client.files.upload.assert_called_once()
    assert prepared.part is not None
    assert prepared.uploaded_file_name == "files/abc"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_gemini_file_transfer.py -v
```

Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement gemini_file_transfer.py**

Create `backend/app/services/gemini_file_transfer.py`:

```python
from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Any

import structlog
from google.genai import types

logger = structlog.get_logger(__name__)

_FILE_POLL_INTERVAL_SEC = 2
_FILE_POLL_MAX_ATTEMPTS = 60  # 2 min max wait


@dataclass(frozen=True, slots=True)
class PreparedFilePart:
    """A Gemini API Part with optional uploaded file name for cleanup."""
    part: types.Part
    uploaded_file_name: str | None = None


def prepare_file_part(
    client: Any,
    file_bytes: bytes,
    mime_type: str,
    *,
    threshold_bytes: int = 10_485_760,
) -> PreparedFilePart:
    """Prepare a Gemini API Part from file bytes.

    Uses inline data for files below threshold, Files API for larger files.
    Returns PreparedFilePart with the Part and optional file name for cleanup.
    """
    if len(file_bytes) < threshold_bytes:
        return PreparedFilePart(
            part=types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
        )

    uploaded_file = client.files.upload(
        file=io.BytesIO(file_bytes),
        config=types.UploadFileConfig(mime_type=mime_type),
    )
    # Poll until file is ACTIVE (required for video, recommended for all large files)
    uploaded_file = _wait_until_active(client, uploaded_file.name)
    return PreparedFilePart(
        part=types.Part(file_data=types.FileData(file_uri=uploaded_file.uri, mime_type=mime_type)),
        uploaded_file_name=uploaded_file.name,
    )


def _wait_until_active(client: Any, file_name: str) -> Any:
    """Poll Files API until file reaches ACTIVE state (required for video processing)."""
    for attempt in range(_FILE_POLL_MAX_ATTEMPTS):
        file_info = client.files.get(name=file_name)
        state = getattr(file_info, "state", None)
        if state is None or str(state) == "ACTIVE":
            return file_info
        if str(state) == "FAILED":
            raise RuntimeError(f"Uploaded file {file_name} failed processing")
        logger.debug(
            "gemini.file_upload.polling",
            file_name=file_name,
            state=str(state),
            attempt=attempt + 1,
        )
        time.sleep(_FILE_POLL_INTERVAL_SEC)
    raise TimeoutError(f"Uploaded file {file_name} did not become ACTIVE within timeout")


def cleanup_uploaded_file(client: Any, file_name: str | None) -> None:
    """Delete a file uploaded via Files API. No-op if file_name is None."""
    if file_name is None:
        return
    try:
        client.files.delete(name=file_name)
    except Exception:
        pass  # Best-effort cleanup; files auto-expire after 48h
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_gemini_file_transfer.py -v
```

Expected: all PASS.

- [ ] **Step 5: Propose commit**

Proposed message: `feat(gemini): add file transfer helper for inline vs Files API routing (S3-04)`
Files: `backend/app/services/gemini_file_transfer.py`, `backend/tests/unit/services/test_gemini_file_transfer.py`

---

### Task 6: Implement GeminiContentService

**Files:**
- Create: `backend/app/services/gemini_content.py`
- Test: `backend/tests/unit/services/test_gemini_content.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/services/test_gemini_content.py`:

```python
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from app.db.models.enums import SourceType
from app.services.gemini_content import GeminiContentService, EXTRACTION_PROMPTS


def test_extraction_prompts_exist_for_all_path_a_types():
    """Prompts exist for all Path A source types."""
    for st in (SourceType.PDF, SourceType.IMAGE, SourceType.AUDIO, SourceType.VIDEO):
        assert st in EXTRACTION_PROMPTS, f"Missing prompt for {st.value}"


def test_extraction_prompts_are_language_neutral():
    """Prompts should not hardcode a specific language."""
    for st, prompt in EXTRACTION_PROMPTS.items():
        assert "in english" not in prompt.lower(), f"Prompt for {st.value} hardcodes English"


@pytest.mark.asyncio
async def test_extract_text_content_inline():
    """Small files use inline data path."""
    mock_response = SimpleNamespace(text="Extracted text from image")
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    service = GeminiContentService(
        client=mock_client,
        model="gemini-2.5-flash",
        file_upload_threshold_bytes=10_000_000,
    )
    result = await service.extract_text_content(
        file_bytes=b"fake image data",
        mime_type="image/png",
        source_type=SourceType.IMAGE,
    )
    assert result == "Extracted text from image"
    mock_client.models.generate_content.assert_called_once()


@pytest.mark.asyncio
async def test_extract_text_content_selects_correct_prompt():
    """Each source type gets its specific prompt."""
    mock_response = SimpleNamespace(text="transcribed audio")
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    service = GeminiContentService(
        client=mock_client,
        model="gemini-2.5-flash",
        file_upload_threshold_bytes=10_000_000,
    )
    await service.extract_text_content(
        file_bytes=b"fake audio",
        mime_type="audio/mpeg",
        source_type=SourceType.AUDIO,
    )
    call_args = mock_client.models.generate_content.call_args
    contents = call_args.kwargs.get("contents") or call_args[1].get("contents") or call_args[0][1] if len(call_args[0]) > 1 else None
    # Verify the prompt for AUDIO was included
    assert mock_client.models.generate_content.called
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_gemini_content.py -v
```

Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement GeminiContentService**

Create `backend/app/services/gemini_content.py`:

```python
from __future__ import annotations

import asyncio
import threading
from typing import Any

import structlog
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.db.models.enums import SourceType
from app.services.gemini_file_transfer import cleanup_uploaded_file, prepare_file_part

logger = structlog.get_logger(__name__)

EXTRACTION_PROMPTS: dict[SourceType, str] = {
    SourceType.PDF: (
        "Extract all text content from this PDF document. "
        "Preserve the document structure including headings, paragraphs, lists, and tables. "
        "Preserve the original language of the document. "
        "Return only the extracted text, no commentary."
    ),
    SourceType.IMAGE: (
        "Describe this image in detail. Include all visible text, objects, people, scenes, "
        "colors, and spatial relationships. Preserve any text in its original language. "
        "Return only the description, no commentary."
    ),
    SourceType.AUDIO: (
        "Transcribe this audio recording completely and accurately. "
        "Preserve the original language. Include speaker changes if distinguishable. "
        "Return only the transcription, no commentary."
    ),
    SourceType.VIDEO: (
        "Transcribe all speech in this video completely and accurately. "
        "Also describe key visual content, scenes, and on-screen text. "
        "Preserve the original language. "
        "Return the transcription and visual descriptions, no commentary."
    ),
}


def _is_retryable_content_error(error: BaseException) -> bool:
    return isinstance(error, genai_errors.ServerError) or (
        isinstance(error, genai_errors.ClientError) and error.code == 429
    )


class GeminiContentService:
    def __init__(
        self,
        *,
        model: str,
        file_upload_threshold_bytes: int = 10_485_760,
        api_key: str | None = None,
        client: genai.Client | None = None,
    ) -> None:
        self._model = model
        self._file_upload_threshold_bytes = file_upload_threshold_bytes
        self._api_key = api_key
        self._client = client
        self._client_lock = threading.Lock()

    async def extract_text_content(
        self,
        file_bytes: bytes,
        mime_type: str,
        source_type: SourceType,
    ) -> str:
        """Extract text content from a multimodal file via Gemini LLM."""
        prompt = EXTRACTION_PROMPTS.get(source_type)
        if prompt is None:
            raise ValueError(f"No extraction prompt for source type: {source_type.value}")

        client = self._get_client()
        prepared = prepare_file_part(
            client, file_bytes, mime_type,
            threshold_bytes=self._file_upload_threshold_bytes,
        )

        try:
            response = await asyncio.to_thread(
                self._generate_content, client, prepared.part, prompt,
            )
            return response.text
        finally:
            cleanup_uploaded_file(client, prepared.uploaded_file_name)

    @retry(
        retry=retry_if_exception(_is_retryable_content_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _generate_content(
        self,
        client: genai.Client,
        file_part: types.Part,
        prompt: str,
    ) -> Any:
        return client.models.generate_content(
            model=self._model,
            contents=[file_part, prompt],
        )

    def _get_client(self) -> genai.Client:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    if not self._api_key:
                        raise ValueError("GEMINI_API_KEY is required for content extraction")
                    self._client = genai.Client(api_key=self._api_key)
        return self._client
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_gemini_content.py -v
```

Expected: all PASS.

- [ ] **Step 5: Propose commit**

Proposed message: `feat(gemini): add GeminiContentService for multimodal text extraction (S3-04)`
Files: `backend/app/services/gemini_content.py`, `backend/tests/unit/services/test_gemini_content.py`

---

### Task 7: Add embed_file() to EmbeddingService

**Files:**
- Modify: `backend/app/services/embedding.py`
- Test: `backend/tests/unit/services/test_embedding_file.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/services/test_embedding_file.py`:

```python
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_embed_file_returns_vector():
    """embed_file returns a vector of correct dimensions."""
    from app.services.embedding import EmbeddingService

    mock_embedding = SimpleNamespace(values=[0.1] * 3072)
    mock_response = SimpleNamespace(embeddings=[mock_embedding])
    mock_client = MagicMock()
    mock_client.models.embed_content.return_value = mock_response

    service = EmbeddingService(
        model="gemini-embedding-2-preview",
        dimensions=3072,
        batch_size=100,
        client=mock_client,
    )
    vector = await service.embed_file(
        file_bytes=b"fake image data",
        mime_type="image/png",
    )
    assert len(vector) == 3072
    mock_client.models.embed_content.assert_called_once()


@pytest.mark.asyncio
async def test_embed_file_uses_retrieval_document_task_type():
    """embed_file defaults to RETRIEVAL_DOCUMENT task type."""
    from app.services.embedding import EmbeddingService

    mock_embedding = SimpleNamespace(values=[0.1] * 3072)
    mock_response = SimpleNamespace(embeddings=[mock_embedding])
    mock_client = MagicMock()
    mock_client.models.embed_content.return_value = mock_response

    service = EmbeddingService(
        model="gemini-embedding-2-preview",
        dimensions=3072,
        batch_size=100,
        client=mock_client,
    )
    await service.embed_file(b"data", "image/png")
    call_kwargs = mock_client.models.embed_content.call_args
    config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
    assert config.task_type == "RETRIEVAL_DOCUMENT"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_embedding_file.py -v
```

Expected: FAIL — `EmbeddingService` has no `embed_file` method.

- [ ] **Step 3: Add embed_file to EmbeddingService**

In `backend/app/services/embedding.py`, add the import at the top:

```python
from app.services.gemini_file_transfer import prepare_file_part, cleanup_uploaded_file
```

Add the new method after `embed_texts()`, before `_embed_batch()`:

```python
    async def embed_file(
        self,
        file_bytes: bytes,
        mime_type: str,
        *,
        task_type: str = "RETRIEVAL_DOCUMENT",
        file_upload_threshold_bytes: int = 10_485_760,
    ) -> list[float]:
        """Generate embedding from a file (multimodal) via Gemini Embedding 2."""
        client = self._get_client()
        prepared = prepare_file_part(
            client, file_bytes, mime_type,
            threshold_bytes=file_upload_threshold_bytes,
        )

        try:
            response = await asyncio.to_thread(
                self._embed_file_sync, client, prepared.part, task_type,
            )
            if len(response.embeddings) != 1:
                raise ValueError("Embedding API returned unexpected number of vectors for file")
            values = list(response.embeddings[0].values)
            if len(values) != self._dimensions:
                raise ValueError(
                    f"Embedding API returned vector with unexpected dimensionality: "
                    f"expected {self._dimensions}, got {len(values)}"
                )
            return values
        finally:
            cleanup_uploaded_file(client, prepared.uploaded_file_name)

    @retry(
        retry=retry_if_exception(_is_retryable_embedding_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _embed_file_sync(
        self,
        client: genai.Client,
        file_part: types.Part,
        task_type: str,
    ) -> types.EmbedContentResponse:
        config = types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=self._dimensions,
        )
        return client.models.embed_content(
            model=self._model,
            contents=[file_part],
            config=config,
        )
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_embedding_file.py tests/unit/services/test_embedding.py -v
```

Expected: all PASS (new tests + existing embedding tests).

- [ ] **Step 5: Propose commit**

Proposed message: `feat(embedding): add embed_file() for multimodal file embedding (S3-04)`
Files: `backend/app/services/embedding.py`, `backend/tests/unit/services/test_embedding_file.py`

---

### Task 8: Extract Path B handler from ingestion.py

**Files:**
- Create: `backend/app/workers/tasks/handlers/__init__.py`
- Create: `backend/app/workers/tasks/handlers/path_b.py`
- Modify: `backend/app/workers/tasks/ingestion.py`

This is a **pure refactoring task** — extract existing Path B logic into a separate handler module. No behavioral changes.

**Important:**
- Snapshot management (`get_or_create_draft`, `ensure_draft_or_rebind`) stays in the orchestrator — it is shared logic for both Path A and Path B. The handler receives the already-bound `snapshot` as a parameter.
- The existing `_mark_persisted_records_failed` in `ingestion.py` must be renamed to `mark_persisted_records_failed` (drop leading underscore) and made importable — both handlers use it for cleanup on partial failure. Same for `_cleanup_qdrant_chunks` if needed.

- [ ] **Step 1: Create handlers package**

Create `backend/app/workers/tasks/handlers/__init__.py` (empty file).

- [ ] **Step 2: Extract Path B handler**

Create `backend/app/workers/tasks/handlers/path_b.py` — move the Docling parse → chunk → embed → upsert logic from `_run_ingestion_pipeline` into a standalone function:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from app.db.models import Chunk, Document, DocumentVersion, EmbeddingProfile
from app.db.models.enums import (
    ChunkStatus,
    DocumentStatus,
    DocumentVersionStatus,
    ProcessingPath,
    TaskType,
)
from app.services.qdrant import QdrantChunkPoint
from app.workers.tasks.ingestion import mark_persisted_records_failed

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.models import BackgroundTask, KnowledgeSnapshot, Source
    from app.workers.tasks.ingestion import PipelineServices


@dataclass(frozen=True, slots=True)
class PathBResult:
    """Result of Path B handler — data needed by orchestrator for finalization."""
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_ids: list[uuid.UUID]
    chunk_count: int
    token_count_total: int
    processing_path: ProcessingPath = ProcessingPath.PATH_B
    pipeline_version: str = "s2-02-path-b"


async def handle_path_b(
    *,
    session: AsyncSession,
    task: BackgroundTask,
    source: Source,
    snapshot: KnowledgeSnapshot,
    file_bytes: bytes,
    services: PipelineServices,
) -> PathBResult:
    """Process a source file via Docling (Path B): parse, chunk, embed, upsert.

    Cleanup contract: handler tracks persisted IDs and cleans up Qdrant + DB
    on partial failure (same pattern as current _run_ingestion_pipeline).
    """
    chunk_data = await services.docling_parser.parse_and_chunk(
        file_bytes,
        _source_filename(source),
        source.source_type,
    )
    if not chunk_data:
        raise ValueError("Parsed document produced no chunks")
    task.progress = 40
    await session.commit()

    document = Document(
        id=uuid.uuid7(),
        owner_id=source.owner_id,
        agent_id=source.agent_id,
        source_id=source.id,
        title=source.title,
        status=DocumentStatus.PROCESSING,
    )
    document_version = DocumentVersion(
        id=uuid.uuid7(),
        document_id=document.id,
        version_number=1,
        file_path=source.file_path,
        processing_path=ProcessingPath.PATH_B,
        status=DocumentVersionStatus.PROCESSING,
    )
    session.add_all([document, document_version])

    chunk_rows = [
        Chunk(
            id=uuid.uuid7(),
            owner_id=source.owner_id,
            agent_id=source.agent_id,
            knowledge_base_id=source.knowledge_base_id,
            document_version_id=document_version.id,
            snapshot_id=snapshot.id,
            source_id=source.id,
            chunk_index=chunk.chunk_index,
            text_content=chunk.text_content,
            token_count=chunk.token_count,
            anchor_page=chunk.anchor_page,
            anchor_chapter=chunk.anchor_chapter,
            anchor_section=chunk.anchor_section,
            anchor_timecode=chunk.anchor_timecode,
            status=ChunkStatus.PENDING,
        )
        for chunk in chunk_data
    ]
    session.add_all(chunk_rows)
    task.progress = 50
    await session.commit()

    vectors = await services.embedding_service.embed_texts(
        [chunk.text_content for chunk in chunk_data],
        task_type="RETRIEVAL_DOCUMENT",
        title=source.title,
    )
    task.progress = 85
    await session.commit()

    qdrant_points = [
        QdrantChunkPoint(
            chunk_id=row.id,
            vector=vector,
            snapshot_id=snapshot.id,
            source_id=source.id,
            document_version_id=document_version.id,
            agent_id=source.agent_id,
            knowledge_base_id=source.knowledge_base_id,
            text_content=row.text_content,
            chunk_index=row.chunk_index,
            token_count=row.token_count,
            anchor_page=row.anchor_page,
            anchor_chapter=row.anchor_chapter,
            anchor_section=row.anchor_section,
            anchor_timecode=row.anchor_timecode,
            source_type=source.source_type,
            language=source.language or services.default_language,
            status=ChunkStatus.INDEXED,
        )
        for row, vector in zip(chunk_rows, vectors, strict=True)
    ]
    # Qdrant upsert is the risky step — cleanup on failure.
    qdrant_write_may_have_happened = False
    chunk_ids = [r.id for r in chunk_rows]
    try:
        qdrant_write_may_have_happened = True
        await services.qdrant_service.upsert_chunks(qdrant_points)
        task.progress = 95
        await session.commit()
    except Exception:
        await session.rollback()
        if qdrant_write_may_have_happened:
            try:
                await services.qdrant_service.delete_chunks(chunk_ids)
            except Exception:
                logger.exception("worker.path_b.qdrant_cleanup_failed", chunk_count=len(chunk_ids))
        await mark_persisted_records_failed(
            session, source_id=source.id, document_id=document.id,
            document_version_id=document_version.id, chunk_ids=chunk_ids,
        )
        raise

    return PathBResult(
        document_id=document.id,
        document_version_id=document_version.id,
        chunk_ids=chunk_ids,
        chunk_count=len(chunk_rows),
        token_count_total=sum(chunk.token_count for chunk in chunk_data),
    )


def _source_filename(source: Source) -> str:
    return source.file_path.rsplit("/", maxsplit=1)[-1]
```

- [ ] **Step 3: Refactor ingestion.py to use Path B handler**

Refactor `_run_ingestion_pipeline` in `backend/app/workers/tasks/ingestion.py` to call `handle_path_b()` instead of containing the inline logic. The orchestrator should:
1. Download file (existing)
2. Get/create snapshot (existing)
3. Call `handle_path_b()` (replacing inline logic)
4. Call `_finalize_pipeline_success()` using `PathBResult` data

This is a mechanical refactoring — the behavior must remain identical.

- [ ] **Step 4: Run ALL existing tests to verify no regressions**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest -v
```

Expected: all existing tests PASS with identical behavior.

- [ ] **Step 5: Propose commit**

Proposed message: `refactor(ingestion): extract Path B handler into separate module (S3-04)`
Files: `backend/app/workers/tasks/handlers/__init__.py`, `backend/app/workers/tasks/handlers/path_b.py`, `backend/app/workers/tasks/ingestion.py`

---

### Task 9: Extend QdrantChunkPoint with Path A metadata + Implement Path A handler

**Files:**
- Modify: `backend/app/services/qdrant.py:40-58` — add `page_count: int | None = None` and `duration_seconds: float | None = None` to `QdrantChunkPoint`; add them to the inline payload dict in `upsert_chunks()` (only when non-None)
- Create: `backend/app/workers/tasks/handlers/path_a.py`
- Test: `backend/tests/unit/workers/test_path_a_handler.py`

**Note:** `page_count` and `duration_seconds` are extra optional fields on `QdrantChunkPoint`. They are written into the Qdrant payload dict inline (same pattern as existing fields at `qdrant.py:135-165` — there is no `_to_payload()` method; payload is assembled inline in `upsert_chunks`). Include them in payload only when non-None. They are NOT indexed (no payload index needed). Reader-side exposure (RetrievedChunk, API schemas) is deferred to S4-03 (citation builder) — storing in payload now is cheap and prevents re-indexing later.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/workers/test_path_a_handler.py`:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.enums import ProcessingPath, SourceType


@dataclass
class FakeSource:
    id: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
    owner_id: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000002")
    agent_id: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000003")
    knowledge_base_id: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000004")
    source_type: SourceType = SourceType.IMAGE
    title: str = "test.png"
    file_path: str = "agent/source/test.png"
    language: str | None = None


def test_path_a_result_has_expected_fields():
    """PathAResult contains all fields needed for finalization."""
    from app.workers.tasks.handlers.path_a import PathAResult
    result = PathAResult(
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        chunk_ids=[uuid.uuid4()],
        chunk_count=1,
        token_count_total=100,
    )
    assert result.processing_path == ProcessingPath.PATH_A
    assert result.pipeline_version == "s3-04-path-a"
    assert result.fallback_to_path_b is False


```

**Additional tests** (the implementer MUST write full mock implementations, not stubs):

Follow patterns from `tests/unit/services/test_qdrant.py` and `tests/unit/test_chat_service.py`.

1. `test_path_a_happy_path_image` — mock GeminiContentService returning 100 tokens of text, EmbeddingService returning 3072-dim vector, QdrantService upsert succeeding. Assert: result is PathAResult with chunk_count=1, processing_path=PATH_A, pipeline_version="s3-04-path-a". Assert: all three services were called.

2. `test_path_a_threshold_fallback_pdf` — mock GeminiContentService returning 3000 tokens for a PDF source. Assert: result is PathAFallback with fallback_to_path_b=True. Assert: embed_file was NOT called.

3. `test_path_a_threshold_exceeded_audio_raises` — mock GeminiContentService returning 600 tokens for an AUDIO source. Assert: raises ValueError with "Path B fallback is not available".

4. `test_path_a_gemini_failure_propagates` — mock GeminiContentService raising RuntimeError. Assert: error propagates unchanged.

5. `test_path_a_qdrant_failure_triggers_cleanup` — mock QdrantService.upsert_chunks raising. Assert: qdrant_service.delete_chunks called, DB records marked FAILED via `mark_persisted_records_failed`.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/workers/test_path_a_handler.py -v
```

Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement Path A handler**

Create `backend/app/workers/tasks/handlers/path_a.py`:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from app.db.models import Chunk, Document, DocumentVersion
from app.db.models.enums import (
    ChunkStatus,
    DocumentStatus,
    DocumentVersionStatus,
    ProcessingPath,
    SourceType,
)
from app.services.path_router import FileMetadata
from app.services.qdrant import QdrantChunkPoint
from app.services.storage import MIME_TYPE_BY_EXTENSION
from app.workers.tasks.ingestion import mark_persisted_records_failed

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.models import BackgroundTask, KnowledgeSnapshot, Source
    from app.services.embedding import EmbeddingService
    from app.services.gemini_content import GeminiContentService
    from app.services.qdrant import QdrantService

@dataclass(frozen=True, slots=True)
class PathAResult:
    """Result of Path A handler — data needed by orchestrator for finalization."""
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_ids: list[uuid.UUID]
    chunk_count: int
    token_count_total: int
    processing_path: ProcessingPath = ProcessingPath.PATH_A
    pipeline_version: str = "s3-04-path-a"
    fallback_to_path_b: bool = False


@dataclass(frozen=True, slots=True)
class PathAFallback:
    """Signals that Path A text_content exceeded threshold — orchestrator should use Path B."""
    reason: str
    fallback_to_path_b: bool = True


async def handle_path_a(
    *,
    session: AsyncSession,
    task: BackgroundTask,
    source: Source,
    snapshot: KnowledgeSnapshot,
    file_bytes: bytes,
    file_metadata: FileMetadata,
    gemini_content_service: GeminiContentService,
    embedding_service: EmbeddingService,
    qdrant_service: QdrantService,
    tokenizer: Any,  # HuggingFaceTokenizer, initialized once in worker context
    default_language: str,
    text_threshold: int,
    file_upload_threshold_bytes: int = 10_485_760,
) -> PathAResult | PathAFallback:
    """Process a source file via Gemini native (Path A).

    Returns PathAResult on success, or PathAFallback if text_content exceeds threshold.

    Cleanup contract: this handler tracks persisted IDs internally and cleans up
    Qdrant + marks DB records as FAILED if an exception occurs after partial commits.
    The orchestrator does NOT need to handle cleanup for Path A — the handler owns it.
    This follows the same pattern as the current monolithic _run_ingestion_pipeline.
    """
    ext = "." + source.file_path.rsplit(".", maxsplit=1)[-1].lower()
    mime_type = MIME_TYPE_BY_EXTENSION.get(ext, "application/octet-stream")

    # Step 1: Extract text_content via Gemini LLM
    text_content = await gemini_content_service.extract_text_content(
        file_bytes=file_bytes,
        mime_type=mime_type,
        source_type=source.source_type,
    )
    task.progress = 40
    await session.commit()

    # Step 2: Check token threshold (tokenizer passed from worker context, not created per-file)
    token_count = tokenizer.count_tokens(text_content)

    if token_count > text_threshold:
        if source.source_type in (SourceType.AUDIO, SourceType.VIDEO):
            raise ValueError(
                f"Path A text_content ({token_count} tokens) exceeds threshold "
                f"({text_threshold}) for {source.source_type.value}, "
                f"and Path B fallback is not available for this format"
            )
        logger.info(
            "worker.path_a.threshold_exceeded",
            source_id=str(source.id),
            token_count=token_count,
            threshold=text_threshold,
            source_type=source.source_type.value,
        )
        return PathAFallback(
            reason=f"text_content {token_count} tokens > threshold {text_threshold}",
        )

    # Step 3: Generate multimodal embedding from file
    dense_vector = await embedding_service.embed_file(
        file_bytes=file_bytes,
        mime_type=mime_type,
        task_type="RETRIEVAL_DOCUMENT",
        file_upload_threshold_bytes=file_upload_threshold_bytes,
    )
    task.progress = 70
    await session.commit()

    # Step 4: Create DB records (use file_metadata passed from orchestrator — no redundant inspect)
    document = Document(
        id=uuid.uuid7(),
        owner_id=source.owner_id,
        agent_id=source.agent_id,
        source_id=source.id,
        title=source.title,
        status=DocumentStatus.PROCESSING,
    )
    document_version = DocumentVersion(
        id=uuid.uuid7(),
        document_id=document.id,
        version_number=1,
        file_path=source.file_path,
        processing_path=ProcessingPath.PATH_A,
        status=DocumentVersionStatus.PROCESSING,
    )
    session.add_all([document, document_version])

    anchor_page = 1 if source.source_type == SourceType.PDF else None
    anchor_timecode = None
    if source.source_type in (SourceType.AUDIO, SourceType.VIDEO) and file_metadata.duration_seconds is not None:
        minutes = int(file_metadata.duration_seconds // 60)
        seconds = int(file_metadata.duration_seconds % 60)
        anchor_timecode = f"0:00-{minutes}:{seconds:02d}"

    chunk = Chunk(
        id=uuid.uuid7(),
        owner_id=source.owner_id,
        agent_id=source.agent_id,
        knowledge_base_id=source.knowledge_base_id,
        document_version_id=document_version.id,
        snapshot_id=snapshot.id,
        source_id=source.id,
        chunk_index=0,
        text_content=text_content,
        token_count=token_count,
        anchor_page=anchor_page,
        anchor_chapter=None,
        anchor_section=None,
        anchor_timecode=anchor_timecode,
        status=ChunkStatus.PENDING,
    )
    session.add(chunk)
    task.progress = 80
    await session.commit()

    # Step 5: Upsert to Qdrant (dense + BM25 sparse from text_content)
    # From this point, chunk is persisted in PG. If Qdrant upsert fails,
    # we must clean up. Handler owns cleanup (not orchestrator).
    qdrant_write_may_have_happened = False
    try:
        qdrant_point = QdrantChunkPoint(
            chunk_id=chunk.id,
            vector=dense_vector,
            snapshot_id=snapshot.id,
            source_id=source.id,
            document_version_id=document_version.id,
            agent_id=source.agent_id,
            knowledge_base_id=source.knowledge_base_id,
            text_content=text_content,
            chunk_index=0,
            token_count=token_count,
            anchor_page=anchor_page,
            anchor_chapter=None,
            anchor_section=None,
            anchor_timecode=anchor_timecode,
            source_type=source.source_type,
            language=source.language or default_language,
            status=ChunkStatus.INDEXED,
            page_count=file_metadata.page_count,
            duration_seconds=file_metadata.duration_seconds,
        )
        qdrant_write_may_have_happened = True
        await qdrant_service.upsert_chunks([qdrant_point])
        task.progress = 95
        await session.commit()
    except Exception:
        await session.rollback()
        if qdrant_write_may_have_happened:
            try:
                await qdrant_service.delete_chunks([chunk.id])
            except Exception:
                logger.exception("worker.path_a.qdrant_cleanup_failed", chunk_id=str(chunk.id))
        await mark_persisted_records_failed(
            session, source_id=source.id, document_id=document.id,
            document_version_id=document_version.id, chunk_ids=[chunk.id],
        )
        raise

    return PathAResult(
        document_id=document.id,
        document_version_id=document_version.id,
        chunk_ids=[chunk.id],
        chunk_count=1,
        token_count_total=token_count,
    )
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/workers/test_path_a_handler.py -v
```

Expected: all PASS.

- [ ] **Step 5: Propose commit**

Proposed message: `feat(ingestion): add Path A handler for Gemini native multimodal ingestion (S3-04)`
Files: `backend/app/workers/tasks/handlers/path_a.py`, `backend/tests/unit/workers/test_path_a_handler.py`

---

### Task 10: Wire PathRouter + Path A into orchestrator

**Files:**
- Modify: `backend/app/workers/tasks/ingestion.py`
- Modify: `backend/app/workers/main.py`

- [ ] **Step 1: Update PipelineServices to include new services**

In `backend/app/workers/tasks/ingestion.py`, extend the `PipelineServices` dataclass and `_load_pipeline_services`:

Add to `PipelineServices`:
```python
    gemini_content_service: GeminiContentService | None
    tokenizer: Any  # HuggingFaceTokenizer, for Path A token counting
    path_a_text_threshold_pdf: int
    path_a_text_threshold_media: int
    path_a_max_pdf_pages: int
    path_a_max_audio_duration_sec: int
    path_a_max_video_duration_sec: int
    gemini_file_upload_threshold_bytes: int
```

Update `_load_pipeline_services` to read these from `ctx["settings"]`, `ctx["gemini_content_service"]`, and `ctx["tokenizer"]`. Add fail-fast validation (same pattern as existing services):

```python
gemini_content_service = ctx.get("gemini_content_service")
if gemini_content_service is not None and not hasattr(gemini_content_service, "extract_text_content"):
    raise RuntimeError("Worker context contains an invalid Gemini content service")

tokenizer = ctx.get("tokenizer")
if tokenizer is not None and not hasattr(tokenizer, "count_tokens"):
    raise RuntimeError("Worker context contains an invalid tokenizer")
```

Note: `gemini_content_service` and `tokenizer` are allowed to be `None` — Path B does not need them. Validation fires only if present but invalid.

- [ ] **Step 2: Update orchestrator to use PathRouter**

In `_run_ingestion_pipeline`, after downloading the file, add:

```python
from app.services.path_router import inspect_file, determine_path
from app.workers.tasks.handlers.path_a import handle_path_a, PathAFallback
from app.workers.tasks.handlers.path_b import handle_path_b

file_meta = inspect_file(file_bytes, source.source_type)
path_decision = determine_path(
    source.source_type, file_meta,
    max_pdf_pages=services.path_a_max_pdf_pages,
    max_audio_duration_sec=services.path_a_max_audio_duration_sec,
    max_video_duration_sec=services.path_a_max_video_duration_sec,
)
if path_decision.rejected:
    raise ValueError(f"Source cannot be processed: {path_decision.reason}")

logger.info(
    "worker.ingestion.path_decided",
    path=path_decision.path.value,
    reason=path_decision.reason,
)
```

Then dispatch:
- If `path_decision.path == ProcessingPath.PATH_A`: call `handle_path_a()`. If result is `PathAFallback`, call `handle_path_b()`.
- If `path_decision.path == ProcessingPath.PATH_B`: call `handle_path_b()`.
- Use handler result (PathAResult or PathBResult) to call `_finalize_pipeline_success()` with `result.processing_path` and `result.pipeline_version`.

- [ ] **Step 3: Update worker startup to initialize GeminiContentService**

In `backend/app/workers/main.py`, add in `on_startup`:

```python
from app.services.gemini_content import GeminiContentService

gemini_content_service = GeminiContentService(
    model=settings.gemini_content_model,
    file_upload_threshold_bytes=settings.gemini_file_upload_threshold_bytes,
    api_key=settings.gemini_api_key,
)
ctx["gemini_content_service"] = gemini_content_service
```

Also initialize the tokenizer once (reuse the same model as DoclingParser):

```python
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
ctx["tokenizer"] = HuggingFaceTokenizer.from_pretrained(
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    max_tokens=settings.chunk_max_tokens,
)
```

This avoids creating the tokenizer per-file in the Path A handler. Uses `count_tokens(text) → int` method.

- [ ] **Step 4: Update _finalize_pipeline_success to accept processing_path and pipeline_version parameters**

Change the hardcoded `ProcessingPath.PATH_B` in `_finalize_pipeline_success` to use a `processing_path` parameter from the handler result. Also parameterize `pipeline_version` in the `EmbeddingProfile` creation (currently hardcoded as `"s2-02-path-b"`). Pass `"s3-04-path-a"` from Path A handler and `"s2-02-path-b"` from Path B handler.

- [ ] **Step 5: Run ALL tests**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest -v
```

Expected: all tests PASS.

- [ ] **Step 6: Propose commit**

Proposed message: `feat(ingestion): wire PathRouter + Path A into orchestrator with fallback (S3-04)`
Files: `backend/app/workers/tasks/ingestion.py`, `backend/app/workers/main.py`

---

### Task 11: Worker-level integration test for Path A

**Files:**
- Create: `backend/tests/integration/test_path_a_ingestion.py`

This test follows the pattern of `backend/tests/integration/test_ingestion_worker.py` — real PostgreSQL + real Qdrant, only Gemini API mocked (fixed text_content + embedding vector).

- [ ] **Step 1: Write worker-level integration test**

Create `backend/tests/integration/test_path_a_ingestion.py`:

The test should:
1. Use the existing conftest fixtures for test database and Qdrant (follow `test_ingestion_worker.py` patterns)
2. Create a Source record with `source_type=IMAGE` and upload a small PNG to SeaweedFS (or mock storage download)
3. Mock `GeminiContentService.extract_text_content` → return fixed short text (under 500 tokens)
4. Mock `EmbeddingService.embed_file` → return fixed 3072-dim vector
5. Call `process_ingestion` (the full orchestrator)
6. Assert:
   - Source status is READY
   - BackgroundTask status is COMPLETE with `processing_path: "path_a"` in result_metadata
   - Exactly 1 Chunk record in PG with `text_content` matching the mock, `anchor_page=None`
   - DocumentVersion has `processing_path=PATH_A`
   - EmbeddingProfile has `pipeline_version="s3-04-path-a"`
   - Qdrant hybrid search with the same vector finds the chunk
   - Qdrant payload does NOT contain `page_count` key (omitted when None per design) and has correct `source_type`

**The implementer MUST write full integration tests** (not stubs) following `tests/integration/test_ingestion_worker.py` as the template. Three concrete e2e scenarios:

1. **Image happy path**: Create Source(source_type=IMAGE), mock Gemini → "A photo of a cat" + 3072-dim vector. Run process_ingestion. Assert: Source READY, Task COMPLETE with `processing_path: "path_a"`, 1 Chunk in PG, DocumentVersion PATH_A, EmbeddingProfile `pipeline_version="s3-04-path-a"`, Qdrant hybrid_search finds the chunk.

2. **PDF threshold fallback**: Create Source(source_type=PDF, 3 pages), mock Gemini → text with >2000 tokens, mock Docling → 5 chunks. Run process_ingestion. Assert: PathRouter initially picks Path A, threshold triggers fallback, result uses Path B (multiple chunks, pipeline_version="s2-02-path-b").

3. **Audio/video rejection**: Create Source(source_type=AUDIO) with duration > 80s via mock. Run process_ingestion. Assert: Task FAILED with descriptive error about Path B unavailability.

- [ ] **Step 2: Add a threshold-fallback integration test**

Same setup but with PDF source type (3 pages), mock Gemini to return text > 2000 tokens. Assert that PathRouter picks Path A, then threshold triggers fallback to Path B (Docling processes the PDF instead).

- [ ] **Step 3: Run integration tests**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/integration/test_path_a_ingestion.py -v
```

Expected: PASS.

- [ ] **Step 4: Propose commit**

Proposed message: `test(integration): add worker-level Path A ingestion tests (S3-04)`
Files: `backend/tests/integration/test_path_a_ingestion.py`

---

### Task 12: Sync canonical docs with Path A audio/video reality

**Files:**
- Modify: `docs/spec.md:90-100`
- Modify: `docs/rag.md:84-99`

The canonical docs (spec.md, rag.md) state that "audio > 80 sec → Path B (Docling)" but Docling does not currently support audio or video. This creates a contradiction. The design spec (D7 caveat) resolves this, but the canonical docs must be synced.

- [ ] **Step 1: Update docs/rag.md Path A/B section**

Add a note clarifying that Path B for audio/video is not yet available. Audio/video files exceeding Path A limits are currently rejected (task FAILED). Docling audio support (`asr` extra) will enable Path B for audio in a future story.

- [ ] **Step 2: Update docs/spec.md ingestion pipeline section**

Add the same clarification to the ingestion pipeline description.

- [ ] **Step 3: Propose commit**

Proposed message: `docs: clarify audio/video Path B availability in spec.md and rag.md (S3-04)`
Files: `docs/spec.md`, `docs/rag.md`

---

### Task 13: Run full CI suite and final verification

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run linter**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run ruff check app/ tests/
```

Expected: no errors.

- [ ] **Step 3: Verify no regressions in existing tests**

Specifically check:
- `tests/integration/test_ingestion_worker.py` — existing Path B still works
- `tests/integration/test_qdrant_roundtrip.py` — existing hybrid search still works
- `tests/unit/services/test_storage.py` — existing extension validation still works

- [ ] **Step 4: Propose final commit if any loose ends**

Proposed message: `chore: finalize S3-04 Path A Gemini native ingestion`
