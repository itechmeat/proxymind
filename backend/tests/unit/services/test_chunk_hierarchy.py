from __future__ import annotations

from app.services.chunk_hierarchy import ChunkHierarchyBuilder
from app.services.document_processing import ChunkData


def _chunk(
    text: str,
    chunk_index: int,
    chapter: str | None,
    section: str | None,
    *,
    token_count: int | None = None,
) -> ChunkData:
    return ChunkData(
        text_content=text,
        token_count=token_count or len(text.split()),
        chunk_index=chunk_index,
        anchor_page=None,
        anchor_chapter=chapter,
        anchor_section=section,
    )


def test_qualifies_long_form_without_heading_structure_when_large_enough() -> None:
    builder = ChunkHierarchyBuilder(
        min_document_tokens=100,
        min_flat_chunks=3,
        parent_target_tokens=200,
        parent_max_tokens=350,
    )
    chunks = [_chunk("x " * 60, index, None, None, token_count=60) for index in range(3)]

    decision = builder.qualify(chunks)

    assert decision.qualifies is True
    assert decision.reason == "long_form_fallback"
    assert decision.has_structure is False


def test_build_returns_empty_hierarchy_when_document_does_not_qualify() -> None:
    builder = ChunkHierarchyBuilder(
        min_document_tokens=100,
        min_flat_chunks=3,
        parent_target_tokens=200,
        parent_max_tokens=350,
    )
    chunks = [_chunk("x " * 20, index, None, None, token_count=20) for index in range(2)]

    hierarchy = builder.build(chunks)

    assert hierarchy.decision.qualifies is False
    assert hierarchy.parents == []
    assert hierarchy.children == []


def test_build_prefers_structure_boundaries_when_present() -> None:
    builder = ChunkHierarchyBuilder(
        min_document_tokens=100,
        min_flat_chunks=3,
        parent_target_tokens=200,
        parent_max_tokens=350,
    )
    chunks = [
        _chunk("a " * 60, 0, "Chapter 1", "Section A", token_count=60),
        _chunk("b " * 60, 1, "Chapter 1", "Section A", token_count=60),
        _chunk("c " * 60, 2, "Chapter 2", "Section B", token_count=60),
    ]

    hierarchy = builder.build(chunks)

    assert len(hierarchy.parents) == 2
    assert [child.parent_index for child in hierarchy.children] == [0, 0, 1]
    assert hierarchy.parents[0].heading_path == ("Chapter 1", "Section A")


def test_build_uses_bounded_fallback_grouping_when_structure_missing() -> None:
    builder = ChunkHierarchyBuilder(
        min_document_tokens=100,
        min_flat_chunks=3,
        parent_target_tokens=120,
        parent_max_tokens=150,
    )
    chunks = [_chunk("x " * 80, index, None, None, token_count=80) for index in range(4)]

    hierarchy = builder.build(chunks)

    assert len(hierarchy.parents) >= 2
    assert all(parent.token_count <= 150 for parent in hierarchy.parents)
    assert [child.chunk_index for child in hierarchy.children] == [0, 1, 2, 3]


def test_build_splits_oversized_structural_group_deterministically() -> None:
    builder = ChunkHierarchyBuilder(
        min_document_tokens=100,
        min_flat_chunks=3,
        parent_target_tokens=100,
        parent_max_tokens=150,
    )
    chunks = [
        _chunk("a " * 60, 0, "Chapter 1", "Section A", token_count=60),
        _chunk("b " * 60, 1, "Chapter 1", "Section A", token_count=60),
        _chunk("c " * 60, 2, "Chapter 1", "Section A", token_count=60),
    ]

    hierarchy = builder.build(chunks)

    assert len(hierarchy.parents) == 2
    assert [child.parent_index for child in hierarchy.children] == [0, 0, 1]
