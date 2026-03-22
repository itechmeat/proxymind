from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db.models.enums import SourceType
from app.services.docling_parser import DoclingParser

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


@pytest.mark.asyncio
async def test_parse_markdown_extracts_chunk_metadata() -> None:
    parser = DoclingParser(chunk_max_tokens=128)

    chunks = await parser.parse_and_chunk(
        _fixture_bytes("sample.md"),
        "sample.md",
        SourceType.MARKDOWN,
    )

    assert chunks
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.text_content for chunk in chunks)
    assert all(chunk.token_count > 0 for chunk in chunks)
    assert chunks[0].anchor_chapter == "ProxyMind"
    assert chunks[0].anchor_section in {"Mission", "Retrieval", None}


@pytest.mark.asyncio
async def test_parse_txt_file_returns_chunks() -> None:
    parser = DoclingParser(chunk_max_tokens=128)

    chunks = await parser.parse_and_chunk(
        _fixture_bytes("sample.txt"),
        "sample.txt",
        SourceType.TXT,
    )

    assert len(chunks) == 1
    assert "Plain text files" in chunks[0].text_content


@pytest.mark.asyncio
async def test_empty_content_returns_no_chunks() -> None:
    parser = DoclingParser(chunk_max_tokens=128)

    chunks = await parser.parse_and_chunk(b"   \n\t", "empty.md", SourceType.MARKDOWN)

    assert chunks == []


@pytest.mark.asyncio
async def test_single_paragraph_document_produces_one_chunk() -> None:
    parser = DoclingParser(chunk_max_tokens=128)

    chunks = await parser.parse_and_chunk(
        _fixture_bytes("sample_small.md"),
        "sample_small.md",
        SourceType.MARKDOWN,
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0


def test_chunk_indices_stay_sequential_when_empty_chunks_are_skipped() -> None:
    parser = DoclingParser(chunk_max_tokens=128)

    class FakeChunker:
        tokenizer = SimpleNamespace(count_tokens=lambda text: len(text.split()))

        @staticmethod
        def contextualize(chunk: SimpleNamespace) -> str:
            return chunk.text

        @staticmethod
        def chunk(document: object) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(
                    text="First",
                    meta=SimpleNamespace(headings=["H1"], doc_items=[]),
                ),
                SimpleNamespace(
                    text="   ",
                    meta=SimpleNamespace(headings=["H1"], doc_items=[]),
                ),
                SimpleNamespace(
                    text="Second",
                    meta=SimpleNamespace(headings=["H1"], doc_items=[]),
                ),
            ]

    parser._chunker = FakeChunker()  # type: ignore[assignment]

    chunks = parser._chunk_document(document=object())

    assert [chunk.chunk_index for chunk in chunks] == [0, 1]


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
    pages_found = [chunk.anchor_page for chunk in chunks if chunk.anchor_page is not None]
    assert pages_found


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
    chapters_found = [chunk.anchor_chapter for chunk in chunks if chunk.anchor_chapter is not None]
    assert chapters_found


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
    chapters_found = [chunk.anchor_chapter for chunk in chunks if chunk.anchor_chapter is not None]
    assert chapters_found


@pytest.mark.asyncio
async def test_parse_htm_alias_extracts_chunks_with_headings() -> None:
    parser = DoclingParser(chunk_max_tokens=1024)

    chunks = await parser.parse_and_chunk(
        _fixture_bytes("sample.html"),
        "sample.htm",
        SourceType.HTML,
    )

    assert chunks
    assert all(chunk.text_content for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    chapters_found = [chunk.anchor_chapter for chunk in chunks if chunk.anchor_chapter is not None]
    assert chapters_found


@pytest.mark.asyncio
async def test_parse_pdf_table_content_appears_in_chunks() -> None:
    parser = DoclingParser(chunk_max_tokens=1024)

    chunks = await parser.parse_and_chunk(
        _fixture_bytes("sample.pdf"),
        "sample.pdf",
        SourceType.PDF,
    )

    all_text = " ".join(chunk.text_content for chunk in chunks)
    assert "Alpha" in all_text
    assert "Beta" in all_text


@pytest.mark.asyncio
async def test_parse_unsupported_type_raises_value_error() -> None:
    parser = DoclingParser(chunk_max_tokens=1024)

    with pytest.raises(ValueError, match="Unsupported source type"):
        await parser.parse_and_chunk(b"fake content", "file.wav", SourceType.AUDIO)


@pytest.mark.asyncio
async def test_parse_corrupt_pdf_raises_exception() -> None:
    parser = DoclingParser(chunk_max_tokens=1024)

    # Docling may raise different low-level parser exceptions here depending
    # on the PDF backend; the worker integration test is the primary contract.
    with pytest.raises(Exception):
        await parser.parse_and_chunk(
            b"not-a-real-pdf-content",
            "corrupt.pdf",
            SourceType.PDF,
        )
