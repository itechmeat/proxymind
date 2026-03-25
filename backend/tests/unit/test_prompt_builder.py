from __future__ import annotations

import uuid

from app.services.citation import SourceInfo
from app.services.prompt import NO_CONTEXT_REFUSAL, format_chunk_header
from app.services.qdrant import RetrievedChunk


def _chunk(text: str, *, source_id: uuid.UUID | None = None, score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=source_id or uuid.uuid4(),
        text_content=text,
        score=score,
        anchor_metadata={
            "anchor_page": 1,
            "anchor_chapter": "Chapter",
            "anchor_section": "Section",
            "anchor_timecode": None,
        },
    )


def _chunk_with_anchor(
    text: str,
    *,
    source_id: uuid.UUID | None = None,
    anchor_page: int | None = None,
    anchor_chapter: str | None = None,
    anchor_section: str | None = None,
    anchor_timecode: str | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=source_id or uuid.uuid4(),
        text_content=text,
        score=0.9,
        anchor_metadata={
            "anchor_page": anchor_page,
            "anchor_chapter": anchor_chapter,
            "anchor_section": anchor_section,
            "anchor_timecode": anchor_timecode,
        },
    )


def _source_info(
    source_id: uuid.UUID,
    *,
    title: str = "Test Source",
    public_url: str | None = None,
    source_type: str = "pdf",
) -> SourceInfo:
    return SourceInfo(
        id=source_id,
        title=title,
        public_url=public_url,
        source_type=source_type,
    )


def test_no_context_refusal_constant_exists() -> None:
    assert isinstance(NO_CONTEXT_REFUSAL, str)
    assert len(NO_CONTEXT_REFUSAL) > 0


def test_chunk_format_with_source_map() -> None:
    source_id = uuid.uuid4()
    header = format_chunk_header(
        1,
        _chunk(
            "Context body",
            source_id=source_id,
            score=0.9876,
        ),
        {
            source_id: _source_info(source_id, title="Clean Architecture"),
        },
    )
    assert "[source:1]" in header
    assert 'title: "Clean Architecture"' in header
    assert "score=" not in header
    assert "0.9876" not in header


def test_chunk_format_includes_anchor_metadata_when_available() -> None:
    source_id = uuid.uuid4()
    header = format_chunk_header(
        1,
        _chunk_with_anchor(
            "Context body",
            source_id=source_id,
            anchor_page=7,
            anchor_chapter="Chapter 5",
            anchor_section="Interfaces",
        ),
        {
            source_id: _source_info(source_id, title="Clean Architecture"),
        },
    )
    assert 'chapter: "Chapter 5"' in header
    assert 'section: "Interfaces"' in header
    assert "page: 7" in header
