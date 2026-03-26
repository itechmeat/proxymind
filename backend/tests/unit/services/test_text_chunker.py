from __future__ import annotations

from app.services.document_processing import ParsedBlock, TextChunker


def test_chunker_keeps_single_block_within_budget() -> None:
    chunker = TextChunker(chunk_max_tokens=20)

    chunks = chunker.chunk_blocks(
        [ParsedBlock(text="one two three", headings=("Intro",), anchor_page=2)]
    )

    assert len(chunks) == 1
    assert chunks[0].text_content == "one two three"
    assert chunks[0].anchor_page == 2
    assert chunks[0].anchor_chapter == "Intro"


def test_chunker_splits_oversized_block() -> None:
    chunker = TextChunker(chunk_max_tokens=3)

    chunks = chunker.chunk_blocks(
        [ParsedBlock(text="alpha beta gamma delta epsilon zeta", headings=(), anchor_page=1)]
    )

    assert len(chunks) > 1
    assert all(chunk.token_count <= 3 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_chunker_merges_small_blocks() -> None:
    chunker = TextChunker(chunk_max_tokens=20)

    chunks = chunker.chunk_blocks(
        [
            ParsedBlock(text="alpha beta", headings=("Intro",), anchor_page=1),
            ParsedBlock(text="gamma delta", headings=("Intro",), anchor_page=1),
        ]
    )

    assert len(chunks) == 1
    assert chunks[0].text_content == "alpha beta gamma delta"


def test_chunker_skips_empty_text_and_empty_input() -> None:
    chunker = TextChunker(chunk_max_tokens=20)

    assert chunker.chunk_blocks([]) == []
    assert chunker.chunk_blocks([ParsedBlock(text="   ", headings=(), anchor_page=None)]) == []


def test_chunker_preserves_first_block_anchor_metadata() -> None:
    chunker = TextChunker(chunk_max_tokens=20)

    chunks = chunker.chunk_blocks(
        [
            ParsedBlock(text="alpha", headings=("Chapter 1", "Section A"), anchor_page=3),
            ParsedBlock(text="beta", headings=("Chapter 1", "Section B"), anchor_page=4),
        ]
    )

    assert len(chunks) == 1
    assert chunks[0].anchor_page == 3
    assert chunks[0].anchor_chapter == "Chapter 1"
    assert chunks[0].anchor_section == "Section A"
