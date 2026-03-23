from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

from pypdf import PdfReader
from tinytag import TinyTag

from app.db.models.enums import ProcessingPath, SourceType


class PathRouterSettings(Protocol):
    path_a_max_pdf_pages: int
    path_a_max_audio_duration_sec: int
    path_a_max_video_duration_sec: int


@dataclass(slots=True, frozen=True)
class FileMetadata:
    page_count: int | None
    duration_seconds: float | None
    file_size_bytes: int


@dataclass(slots=True, frozen=True)
class PathDecision:
    path: ProcessingPath | None
    reason: str
    rejected: bool


def inspect_file(file_bytes: bytes, source_type: SourceType) -> FileMetadata:
    page_count: int | None = None
    duration_seconds: float | None = None

    if source_type is SourceType.PDF:
        try:
            page_count = len(PdfReader(BytesIO(file_bytes)).pages)
        except Exception:
            page_count = None
    elif source_type in {SourceType.AUDIO, SourceType.VIDEO}:
        try:
            tag = TinyTag.get(file_obj=BytesIO(file_bytes))
            duration_seconds = float(tag.duration) if tag.duration is not None else None
        except Exception:
            duration_seconds = None

    return FileMetadata(
        page_count=page_count,
        duration_seconds=duration_seconds,
        file_size_bytes=len(file_bytes),
    )


def determine_path(
    source_type: SourceType,
    file_metadata: FileMetadata,
    settings: PathRouterSettings,
) -> PathDecision:
    if source_type is SourceType.IMAGE:
        return PathDecision(
            path=ProcessingPath.PATH_A,
            reason="Image sources always use Path A",
            rejected=False,
        )
    if source_type is SourceType.PDF:
        if file_metadata.page_count is None:
            return PathDecision(
                path=ProcessingPath.PATH_B,
                reason="PDF page count could not be determined; falling back to Path B",
                rejected=False,
            )
        if file_metadata.page_count <= settings.path_a_max_pdf_pages:
            return PathDecision(
                path=ProcessingPath.PATH_A,
                reason="PDF page count is within the Path A limit",
                rejected=False,
            )
        return PathDecision(
            path=ProcessingPath.PATH_B,
            reason="PDF exceeds the Path A page limit",
            rejected=False,
        )
    if source_type is SourceType.AUDIO:
        if file_metadata.duration_seconds is None:
            return PathDecision(
                path=ProcessingPath.PATH_A,
                reason=(
                    "Audio duration could not be determined; assuming Path A and relying "
                    "on the text threshold as the safety net"
                ),
                rejected=False,
            )
        if file_metadata.duration_seconds <= settings.path_a_max_audio_duration_sec:
            return PathDecision(
                path=ProcessingPath.PATH_A,
                reason="Audio duration is within the Path A limit",
                rejected=False,
            )
        return PathDecision(
            path=None,
            reason="Audio exceeds the Path A duration limit and Path B is unavailable",
            rejected=True,
        )
    if source_type is SourceType.VIDEO:
        if file_metadata.duration_seconds is None:
            return PathDecision(
                path=ProcessingPath.PATH_A,
                reason=(
                    "Video duration could not be determined; assuming Path A and relying "
                    "on the text threshold as the safety net"
                ),
                rejected=False,
            )
        if file_metadata.duration_seconds <= settings.path_a_max_video_duration_sec:
            return PathDecision(
                path=ProcessingPath.PATH_A,
                reason="Video duration is within the Path A limit",
                rejected=False,
            )
        return PathDecision(
            path=None,
            reason="Video exceeds the Path A duration limit and Path B is unavailable",
            rejected=True,
        )

    return PathDecision(
        path=ProcessingPath.PATH_B,
        reason="Text-native formats always use Path B",
        rejected=False,
    )
