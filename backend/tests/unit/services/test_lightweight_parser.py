from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import app.services.lightweight_parser as lightweight_parser
from app.db.models.enums import SourceType
from app.services.document_processing import ParsedBlock
from app.services.lightweight_parser import LightweightParser

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


@pytest.mark.asyncio
async def test_parse_markdown_extracts_chunk_metadata() -> None:
    parser = LightweightParser(chunk_max_tokens=128)

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
    parser = LightweightParser(chunk_max_tokens=128)

    chunks = await parser.parse_and_chunk(
        _fixture_bytes("sample.txt"),
        "sample.txt",
        SourceType.TXT,
    )

    assert len(chunks) == 1
    assert "Plain text files" in chunks[0].text_content


@pytest.mark.asyncio
async def test_empty_content_returns_no_chunks() -> None:
    parser = LightweightParser(chunk_max_tokens=128)

    chunks = await parser.parse_and_chunk(b"   \n\t", "empty.md", SourceType.MARKDOWN)

    assert chunks == []


@pytest.mark.asyncio
async def test_single_paragraph_document_produces_one_chunk() -> None:
    parser = LightweightParser(chunk_max_tokens=128)

    chunks = await parser.parse_and_chunk(
        _fixture_bytes("sample_small.md"),
        "sample_small.md",
        SourceType.MARKDOWN,
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0


@pytest.mark.asyncio
async def test_parse_pdf_extracts_chunks_with_page_numbers() -> None:
    parser = LightweightParser(chunk_max_tokens=1024)

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
    parser = LightweightParser(chunk_max_tokens=1024)

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
    parser = LightweightParser(chunk_max_tokens=1024)

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
    parser = LightweightParser(chunk_max_tokens=1024)

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
    parser = LightweightParser(chunk_max_tokens=1024)

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
    parser = LightweightParser(chunk_max_tokens=1024)

    with pytest.raises(ValueError, match="Unsupported source type"):
        await parser.parse_and_chunk(b"fake content", "file.wav", SourceType.AUDIO)


@pytest.mark.asyncio
async def test_parse_corrupt_pdf_raises_exception() -> None:
    parser = LightweightParser(chunk_max_tokens=1024)

    with pytest.raises(Exception):
        await parser.parse_and_chunk(
            b"not-a-real-pdf-content",
            "corrupt.pdf",
            SourceType.PDF,
        )


def test_chunk_blocks_split_oversized_block_to_respect_budget() -> None:
    parser = LightweightParser(chunk_max_tokens=10)

    chunks = parser._chunker.chunk_blocks(
        [
            ParsedBlock(
                text="word " * 40,
                headings=("Heading",),
                anchor_page=3,
            )
        ]
    )

    assert len(chunks) > 1
    assert all(chunk.token_count <= 10 for chunk in chunks)
    assert all(chunk.anchor_page == 3 for chunk in chunks)
    assert all(chunk.anchor_chapter == "Heading" for chunk in chunks)


def test_parse_docx_rejects_oversized_document_xml(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeZipFile:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self) -> FakeZipFile:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        @staticmethod
        def getinfo(_name: str) -> SimpleNamespace:
            return SimpleNamespace(
                file_size=lightweight_parser._MAX_DOCX_XML_BYTES + 1,
                compress_size=1024,
            )

        @staticmethod
        def read(_info: object) -> bytes:
            raise AssertionError("read should not be reached for oversized document.xml")

    monkeypatch.setattr(lightweight_parser, "ZipFile", FakeZipFile)

    with pytest.raises(ValueError, match="too large"):
        LightweightParser._parse_docx(b"fake-docx")