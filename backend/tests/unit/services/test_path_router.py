from __future__ import annotations

import base64
import io
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db.models.enums import ProcessingPath, SourceType
from app.services.path_router import FileMetadata, determine_path, inspect_file

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
MINIMAL_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+yF9kAAAAASUVORK5CYII="
)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        path_a_max_pdf_pages=6,
        path_a_max_audio_duration_sec=80,
        path_a_max_video_duration_sec=120,
    )


def _wav_bytes(duration_seconds: float) -> bytes:
    sample_rate = 8000
    frame_count = int(sample_rate * duration_seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("source_type", "metadata", "expected_path", "expected_rejected"),
    [
        (SourceType.IMAGE, FileMetadata(None, None, 1), ProcessingPath.PATH_A, False),
        (SourceType.PDF, FileMetadata(2, None, 1), ProcessingPath.PATH_A, False),
        (SourceType.PDF, FileMetadata(9, None, 1), ProcessingPath.PATH_B, False),
        (SourceType.PDF, FileMetadata(None, None, 1), ProcessingPath.PATH_B, False),
        (SourceType.AUDIO, FileMetadata(None, 60.0, 1), ProcessingPath.PATH_A, False),
        (SourceType.AUDIO, FileMetadata(None, None, 1), ProcessingPath.PATH_A, False),
        (SourceType.VIDEO, FileMetadata(None, 100.0, 1), ProcessingPath.PATH_A, False),
        (SourceType.MARKDOWN, FileMetadata(None, None, 1), ProcessingPath.PATH_B, False),
    ],
)
def test_determine_path_routes_supported_inputs(
    source_type: SourceType,
    metadata: FileMetadata,
    expected_path: ProcessingPath,
    expected_rejected: bool,
) -> None:
    decision = determine_path(source_type, metadata, _settings())

    assert decision.path is expected_path
    assert decision.rejected is expected_rejected


def test_determine_path_rejects_over_limit_media() -> None:
    audio_decision = determine_path(SourceType.AUDIO, FileMetadata(None, 81.0, 1), _settings())
    video_decision = determine_path(SourceType.VIDEO, FileMetadata(None, 121.0, 1), _settings())

    assert audio_decision.path is None
    assert audio_decision.rejected is True
    assert video_decision.path is None
    assert video_decision.rejected is True


def test_inspect_file_reads_pdf_page_count() -> None:
    file_bytes = (FIXTURES_DIR / "sample.pdf").read_bytes()

    metadata = inspect_file(file_bytes, SourceType.PDF)

    assert metadata.page_count == 2
    assert metadata.duration_seconds is None
    assert metadata.file_size_bytes == len(file_bytes)


def test_inspect_file_returns_none_for_corrupt_pdf() -> None:
    metadata = inspect_file(b"not-a-pdf", SourceType.PDF)

    assert metadata.page_count is None
    assert metadata.duration_seconds is None


def test_inspect_file_reads_wav_duration() -> None:
    file_bytes = _wav_bytes(1.0)

    metadata = inspect_file(file_bytes, SourceType.AUDIO)

    assert metadata.page_count is None
    assert metadata.duration_seconds == pytest.approx(1.0, abs=0.1)


def test_inspect_file_returns_none_for_image_metadata() -> None:
    metadata = inspect_file(MINIMAL_PNG_BYTES, SourceType.IMAGE)

    assert metadata.page_count is None
    assert metadata.duration_seconds is None


def test_inspect_file_returns_none_for_invalid_audio_metadata() -> None:
    metadata = inspect_file(b"not-audio", SourceType.AUDIO)

    assert metadata.duration_seconds is None
