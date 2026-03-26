from __future__ import annotations

from types import SimpleNamespace

from app.db.models.enums import ProcessingPath, SourceType
from app.services.path_router import FileMetadata, determine_path


def _settings(*, document_ai_enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(
        path_a_max_pdf_pages=6,
        path_a_max_audio_duration_sec=80,
        path_a_max_video_duration_sec=120,
        document_ai_enabled=document_ai_enabled,
    )


def test_external_hint_routes_pdf_to_path_c_when_enabled() -> None:
    decision = determine_path(
        SourceType.PDF,
        FileMetadata(page_count=20, duration_seconds=None, file_size_bytes=1),
        _settings(document_ai_enabled=True),
        processing_hint="external",
    )

    assert decision.path is ProcessingPath.PATH_C
    assert decision.rejected is False


def test_external_hint_falls_back_to_path_b_when_disabled() -> None:
    decision = determine_path(
        SourceType.PDF,
        FileMetadata(page_count=20, duration_seconds=None, file_size_bytes=1),
        _settings(document_ai_enabled=False),
        processing_hint="external",
    )

    assert decision.path is ProcessingPath.PATH_B
    assert decision.rejected is False
    assert "Document AI is not configured" in decision.reason


def test_external_hint_short_pdf_still_falls_back_to_path_b_when_disabled() -> None:
    decision = determine_path(
        SourceType.PDF,
        FileMetadata(page_count=2, duration_seconds=None, file_size_bytes=1),
        _settings(document_ai_enabled=False),
        processing_hint="external",
    )

    assert decision.path is ProcessingPath.PATH_B
    assert decision.rejected is False
    assert "Document AI is not configured" in decision.reason


def test_external_hint_is_ignored_for_text_native_formats() -> None:
    decision = determine_path(
        SourceType.DOCX,
        FileMetadata(page_count=None, duration_seconds=None, file_size_bytes=1),
        _settings(document_ai_enabled=True),
        processing_hint="external",
    )

    assert decision.path is ProcessingPath.PATH_B
    assert decision.rejected is False


def test_auto_hint_preserves_existing_routing() -> None:
    decision = determine_path(
        SourceType.PDF,
        FileMetadata(page_count=2, duration_seconds=None, file_size_bytes=1),
        _settings(document_ai_enabled=True),
        processing_hint="auto",
    )

    assert decision.path is ProcessingPath.PATH_A
